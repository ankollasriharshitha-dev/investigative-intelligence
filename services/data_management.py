"""Validated upload, persistence, source switching, and dataset mutation workflows."""

import json
import logging
import os
import stat
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from config.settings import Settings
from domain.models import DatasetMetadata, ImportReport, IngestionRecord, ValidationResult
from providers.synthetic import CSV_SCHEMAS, JSON_SCHEMAS, UNIQUE_ID_COLUMNS
from providers.uploaded import UploadedDataProvider
from services.normalization import normalize_package


STATE_FILE = ".active_source.json"
PENDING_FILE = ".pending_import.json"
HISTORY_FILE = "upload_history.json"
METADATA_FILE = "dataset_metadata.json"
CURRENT_DIR = "current"
DELETE_RETRIES = 3
DELETE_RETRY_DELAY_SECONDS = 0.15

logger = logging.getLogger(__name__)


class DatasetStorageError(RuntimeError):
    """Raised when an uploaded dataset cannot be safely removed or replaced."""


class DataManagementService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.uploads_dir = settings.uploads_data_dir
        self.current_dir = self.uploads_dir / CURRENT_DIR
        self.state_path = self.uploads_dir / STATE_FILE
        self.history_path = self.uploads_dir / HISTORY_FILE
        self.metadata_path = self.uploads_dir / METADATA_FILE

    def active_source_type(self) -> str:
        state = self._read_state()
        if state.get("source") == "uploaded" and not self.uploaded_exists():
            self.activate_synthetic()
            return "synthetic"
        return state.get("source", "synthetic")

    def uploaded_exists(self) -> bool:
        return self.current_dir.exists() and UploadedDataProvider(self.current_dir).validate().valid

    def source_metadata(self) -> dict[str, object]:
        metadata = self.dataset_metadata()
        provider = UploadedDataProvider(self.current_dir) if metadata.source == "uploaded" else self._synthetic_provider()
        return {"source": "Uploaded Investigation Dataset" if metadata.source == "uploaded" else "Synthetic Demo Dataset", "status": metadata.status, "files": len(provider.validate().checked_files), "records": metadata.record_count, "imported_at": metadata.updated_at}

    def dataset_metadata(self) -> DatasetMetadata:
        if self.active_source_type() == "uploaded" and self.uploaded_exists() and self.metadata_path.exists():
            return DatasetMetadata(**json.loads(self.metadata_path.read_text(encoding="utf-8")))
        snapshot = self._synthetic_provider().load_snapshot()
        return DatasetMetadata("synthetic-demo", "synthetic", 0, "", "", _snapshot_record_count(snapshot), "Validated", "Validated")

    def ingestion_history(self) -> list[dict[str, object]]:
        return self.history()

    def validate_files(self, files: dict[str, bytes | BinaryIO]) -> tuple[ValidationResult, Path]:
        staging = self.uploads_dir / ".staging"
        if staging.exists():
            _remove_directory(staging)
        staging.mkdir(parents=True, exist_ok=True)
        errors: list[str] = []
        supported = set(CSV_SCHEMAS) | set(JSON_SCHEMAS)
        for filename, content in files.items():
            if Path(filename).name not in supported:
                errors.append(f"Unsupported file: {filename}")
                continue
            target = staging / Path(filename).name
            if hasattr(content, "read"):
                target.write_bytes(content.read())
            else:
                target.write_bytes(content)
        missing = supported - {path.name for path in staging.iterdir()}
        errors.extend(f"Missing required file: {filename}" for filename in sorted(missing))
        provider = UploadedDataProvider(staging)
        result = provider.validate()
        result = ValidationResult(
            valid=not errors and result.valid,
            checked_files=result.checked_files,
            errors=tuple(errors) + result.errors,
            warnings=result.warnings,
        )
        return result, staging

    def import_dataset(self, files: dict[str, bytes | BinaryIO], operation: str = "replace") -> ImportReport:
        validation, staging = self.validate_files(files)
        if not validation.valid:
            return ImportReport(operation, 0, 0, 0, 0, 0, validation)
        normalize_package(staging)
        normalized_validation = UploadedDataProvider(staging).validate()
        if not normalized_validation.valid:
            return ImportReport(operation, 0, 0, 0, 0, 0, normalized_validation)
        incoming = UploadedDataProvider(staging).load_snapshot()
        received = _snapshot_record_count(incoming)
        if operation == "replace" or not self.current_dir.exists():
            added, updated, skipped = received, 0, 0
            self._store_directory(staging)
        else:
            added, updated, skipped = self._merge_current(incoming, operation)
        imported_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        ingestion_id = f"ING-{uuid.uuid4().hex[:12].upper()}"
        previous_metadata = self._read_metadata()
        version = int(previous_metadata.get("version", 0)) + 1
        dataset_id = str(previous_metadata.get("dataset_id", f"upload-{uuid.uuid4().hex[:10]}"))
        self._write_metadata({"dataset_id": dataset_id, "source": "uploaded", "version": version, "created_at": previous_metadata.get("created_at", imported_at), "updated_at": imported_at, "record_count": _snapshot_record_count(UploadedDataProvider(self.current_dir).load_snapshot()), "status": "staged", "validation_status": "Validated"})
        self._write_pending({"ingestion_id": ingestion_id, "imported_at": imported_at, "operation": operation, "records": received, "version": version})
        self._append_history({"ingestion_id": ingestion_id, "dataset": dataset_id, "source": "uploaded", "timestamp": imported_at, "records_received": received, "records_added": added, "records_updated": updated, "records_rejected": 0, "operation": operation.upper(), "status": "staged", "version": version})
        return ImportReport(operation, received, added, updated, skipped, 0, validation, imported_at, ingestion_id, version)

    def activate_uploaded(self) -> bool:
        if not self.uploaded_exists():
            return False
        state = self._read_state()
        pending = self._read_pending()
        state.update({"source": "uploaded", "imported_at": pending.get("imported_at") or state.get("imported_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")})
        self._write_state(state)
        metadata = self._read_metadata()
        metadata["status"] = "active"
        metadata["updated_at"] = state["imported_at"]
        self._write_metadata(metadata)
        self._append_history({"ingestion_id": pending.get("ingestion_id", f"ING-{uuid.uuid4().hex[:12].upper()}"), "dataset": metadata.get("dataset_id", "uploaded"), "source": "uploaded", "timestamp": state["imported_at"], "records_received": pending.get("records", 0), "records_added": 0, "records_updated": 0, "records_rejected": 0, "operation": "ACTIVATE", "status": "active", "version": metadata.get("version", 0)})
        if self.pending_path.exists():
            _remove_file(self.pending_path)
        return True

    def activate_synthetic(self) -> None:
        self._write_state({"source": "synthetic"})

    def clear_uploaded(self) -> None:
        if self.current_dir.exists():
            _remove_directory(self.current_dir)
        if self.pending_path.exists():
            _remove_file(self.pending_path)
        self.activate_synthetic()
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._append_history({"ingestion_id": f"ING-{uuid.uuid4().hex[:12].upper()}", "dataset": "uploaded", "source": "uploaded", "timestamp": timestamp, "records_received": 0, "records_added": 0, "records_updated": 0, "records_rejected": 0, "operation": "CLEAR", "status": "cleared", "version": self._read_metadata().get("version", 0)})

    def history(self) -> list[dict[str, object]]:
        if not self.history_path.exists():
            return []
        return json.loads(self.history_path.read_text(encoding="utf-8"))

    def _merge_current(self, incoming, operation: str) -> tuple[int, int, int]:
        existing = UploadedDataProvider(self.current_dir).load_snapshot()
        added = updated = skipped = 0
        for filename, id_column in UNIQUE_ID_COLUMNS.items():
            name = Path(filename).stem
            current = existing.tables[name]
            new = incoming.tables[name]
            current_ids = set(current[id_column])
            incoming_ids = set(new[id_column])
            if operation == "append":
                skipped += len(current_ids & incoming_ids)
                result = pd.concat([current, new[~new[id_column].isin(current_ids)]], ignore_index=True)
                added += len(incoming_ids - current_ids)
            else:
                result = current.set_index(id_column)
                incoming_frame = new.set_index(id_column)
                common = current_ids & incoming_ids
                result.update(incoming_frame)
                result = pd.concat([result, incoming_frame.loc[list(incoming_ids - current_ids)]])
                updated += len(common)
                added += len(incoming_ids - current_ids)
                result = result.reset_index()
            result.to_csv(self.current_dir / filename, index=False)
        existing_cases = {case["case_id"]: case for case in existing.documents.get("cases", [])}
        incoming_cases = {case["case_id"]: case for case in incoming.documents.get("cases", [])}
        if operation == "append":
            existing_cases.update({case_id: case for case_id, case in incoming_cases.items() if case_id not in existing_cases})
        else:
            existing_cases.update(incoming_cases)
        (self.current_dir / "cases.json").write_text(json.dumps(list(existing_cases.values()), indent=2), encoding="utf-8")
        validation = UploadedDataProvider(self.current_dir).validate()
        if not validation.valid:
            raise ValueError("Merged uploaded dataset failed validation: " + "; ".join(validation.errors))
        return added, updated, skipped

    def _store_directory(self, staging: Path) -> None:
        if self.current_dir.exists():
            _remove_directory(self.current_dir)
        try:
            shutil.copytree(staging, self.current_dir)
        except OSError as error:
            raise DatasetStorageError(
                "Unable to replace the uploaded dataset because the target directory "
                "could not be written. Close applications using the dataset and try again."
            ) from error

    def _read_state(self) -> dict[str, object]:
        if not self.state_path.exists():
            return {"source": "synthetic"}
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def _read_metadata(self) -> dict[str, object]:
        if not self.metadata_path.exists():
            return {}
        return json.loads(self.metadata_path.read_text(encoding="utf-8"))

    def _write_metadata(self, metadata: dict[str, object]) -> None:
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    def _synthetic_provider(self):
        from providers.synthetic import SyntheticDataProvider
        return SyntheticDataProvider(self.settings.synthetic_data_dir)

    @property
    def pending_path(self) -> Path:
        return self.uploads_dir / PENDING_FILE

    def _read_pending(self) -> dict[str, object]:
        if not self.pending_path.exists():
            return {}
        return json.loads(self.pending_path.read_text(encoding="utf-8"))

    def _write_pending(self, state: dict[str, object]) -> None:
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.pending_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def _write_state(self, state: dict[str, object]) -> None:
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def _append_history(self, record: dict[str, object]) -> None:
        records = self.history()
        records.append(record)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.history_path.write_text(json.dumps(records, indent=2), encoding="utf-8")


def _snapshot_record_count(snapshot) -> int:
    return len(snapshot.documents.get("cases", [])) + sum(len(table) for table in snapshot.tables.values())


def _remove_directory(directory: Path) -> None:
    """Remove a dataset directory safely across Windows and synchronized folders."""
    if not directory.exists():
        return

    last_error: OSError | None = None
    for attempt in range(DELETE_RETRIES):
        try:
            shutil.rmtree(directory, onerror=_make_writable_and_retry)
            if not directory.exists():
                return
            last_error = PermissionError(f"Directory still exists after removal: {directory}")
        except OSError as error:
            last_error = error
            logger.warning("Uploaded dataset removal attempt %s failed for %s: %s", attempt + 1, directory, error)
        if attempt < DELETE_RETRIES - 1:
            time.sleep(DELETE_RETRY_DELAY_SECONDS * (attempt + 1))

    raise DatasetStorageError(
        "Unable to clear the uploaded dataset because a file is currently in use or "
        "the synchronized folder denied access. Close applications using the dataset and try again."
    ) from last_error


def _make_writable_and_retry(function, path, error_info) -> None:
    """Clear read-only attributes for one failed rmtree operation, then retry it."""
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        function(path)
    except OSError:
        raise error_info[1]


def _remove_file(file_path: Path) -> None:
    """Remove one state file while handling read-only Windows attributes."""
    if not file_path.exists():
        return
    last_error: OSError | None = None
    for attempt in range(DELETE_RETRIES):
        try:
            os.chmod(file_path, stat.S_IWRITE | stat.S_IREAD)
            file_path.unlink()
            return
        except OSError as error:
            last_error = error
            logger.warning("Uploaded state removal attempt %s failed for %s: %s", attempt + 1, file_path, error)
            if attempt < DELETE_RETRIES - 1:
                time.sleep(DELETE_RETRY_DELAY_SECONDS * (attempt + 1))
    raise DatasetStorageError(
        "Unable to clear uploaded dataset state because a file is currently in use. "
        "Close applications using the dataset and try again."
    ) from last_error