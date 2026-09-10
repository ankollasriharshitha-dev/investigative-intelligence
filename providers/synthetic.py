"""File-backed provider for the isolated synthetic demonstration dataset."""

import json
from pathlib import Path

import pandas as pd

from domain.models import DatasetSnapshot, DataSourceInfo, DataSourceType, ValidationResult
from providers.base import DataProvider


CSV_SCHEMAS = {
    "persons.csv": ("person_id", "name", "role", "case_ids"),
    "phones.csv": ("phone_id", "phone_number", "owner_person_id", "case_id"),
    "calls.csv": ("call_id", "caller_id", "receiver_id", "timestamp", "case_id", "source", "confidence"),
    "messages.csv": ("message_id", "sender_phone_id", "receiver_phone_id", "timestamp", "case_id", "source", "confidence"),
    "transactions.csv": ("transaction_id", "from_account", "to_account", "amount", "timestamp", "case_id", "source", "confidence"),
    "locations.csv": ("location_id", "label", "latitude", "longitude"),
    "vehicles.csv": ("vehicle_id", "registration_number", "owner_person_id", "case_id"),
    "organizations.csv": ("organization_id", "name", "sector", "case_ids"),
    "accounts.csv": ("account_id", "account_label", "owner_person_id", "organization_id", "case_id"),
    "events.csv": ("event_id", "person_id", "event_type", "location_id", "vehicle_id", "organization_id", "timestamp", "case_id", "source", "confidence"),
}
JSON_SCHEMAS = {"cases.json"}
UNIQUE_ID_COLUMNS = {
    "persons.csv": "person_id", "phones.csv": "phone_id", "calls.csv": "call_id",
    "messages.csv": "message_id", "transactions.csv": "transaction_id", "locations.csv": "location_id",
    "vehicles.csv": "vehicle_id", "organizations.csv": "organization_id", "accounts.csv": "account_id",
    "events.csv": "event_id",
}


class SyntheticDataProvider(DataProvider):
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self._source = DataSourceInfo(
            source_type=DataSourceType.SYNTHETIC,
            name="Synthetic Demo Data",
            location=data_dir,
        )

    def get_source_info(self) -> DataSourceInfo:
        return self._source

    def validate(self) -> ValidationResult:
        errors: list[str] = []
        checked_files: list[str] = []
        frames: dict[str, pd.DataFrame] = {}
        for filename, required_columns in CSV_SCHEMAS.items():
            path = self.data_dir / filename
            checked_files.append(filename)
            if not path.exists():
                errors.append(f"Missing required file: {filename}")
                continue
            try:
                frame = pd.read_csv(path)
            except (pd.errors.ParserError, UnicodeDecodeError) as error:
                errors.append(f"{filename} could not be parsed: {error}")
                continue
            frames[filename] = frame
            columns = tuple(frame.columns)
            missing = set(required_columns) - set(columns)
            if missing:
                errors.append(f"{filename} is missing columns: {sorted(missing)}")
                continue
            identifier = UNIQUE_ID_COLUMNS[filename]
            if frame[identifier].isna().any() or frame[identifier].astype(str).str.strip().eq("").any():
                errors.append(f"{filename}.{identifier} contains an empty value")
            if frame[identifier].duplicated().any():
                errors.append(f"{filename}.{identifier} contains duplicate IDs")
            for column in ("name", "role", "label", "source", "event_type"):
                if column in frame and frame[column].isna().any():
                    errors.append(f"{filename}.{column} contains an empty value")
        for filename in JSON_SCHEMAS:
            path = self.data_dir / filename
            checked_files.append(filename)
            if not path.exists():
                errors.append(f"Missing required file: {filename}")
                continue
            try:
                cases = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(cases, list):
                    errors.append(f"{filename} must contain a list of case records")
                elif not all(case.get("case_id") for case in cases):
                    errors.append(f"{filename}.case_id contains an empty value")
            except json.JSONDecodeError as error:
                errors.append(f"{filename} is not valid JSON: {error.msg}")
        if not errors:
            cases = json.loads((self.data_dir / "cases.json").read_text(encoding="utf-8"))
            case_ids = {case["case_id"] for case in cases}
            person_ids = set(frames["persons.csv"]["person_id"])
            phone_ids = set(frames["phones.csv"]["phone_id"])
            account_ids = set(frames["accounts.csv"]["account_id"])
            location_ids = set(frames["locations.csv"]["location_id"])
            vehicle_ids = set(frames["vehicles.csv"]["vehicle_id"])
            organization_ids = set(frames["organizations.csv"]["organization_id"])
            for filename in ("persons.csv", "organizations.csv"):
                for row_number, value in frames[filename]["case_ids"].items():
                    referenced_cases = {item.strip() for item in str(value).split("|") if item.strip()}
                    unknown_cases = referenced_cases - case_ids
                    if unknown_cases:
                        errors.append(
                            f"{filename}.case_ids at record {row_number + 2} references unknown IDs: "
                            f"{sorted(unknown_cases)}"
                        )
            for filename in ("calls.csv", "messages.csv", "transactions.csv", "events.csv"):
                frame = frames[filename]
                if pd.to_datetime(frame["timestamp"], errors="coerce").isna().any():
                    errors.append(f"{filename}.timestamp contains an invalid date")
                unknown_cases = set(frame["case_id"]) - case_ids
                if unknown_cases:
                    errors.append(f"{filename}.case_id references unknown IDs: {sorted(unknown_cases)}")
            checks = {
                "phones.csv": (("owner_person_id", person_ids),),
                "calls.csv": (("caller_id", phone_ids), ("receiver_id", phone_ids)),
                "messages.csv": (("sender_phone_id", phone_ids), ("receiver_phone_id", phone_ids)),
                "transactions.csv": (("from_account", account_ids), ("to_account", account_ids)),
                "vehicles.csv": (("owner_person_id", person_ids),),
                "accounts.csv": (("owner_person_id", person_ids), ("organization_id", organization_ids)),
                "events.csv": (("person_id", person_ids), ("location_id", location_ids), ("vehicle_id", vehicle_ids), ("organization_id", organization_ids)),
            }
            for filename, column_checks in checks.items():
                for column, valid_ids in column_checks:
                    values = set(frames[filename][column].dropna())
                    unknown_ids = values - valid_ids
                    if unknown_ids:
                        errors.append(f"{filename}.{column} references unknown IDs: {sorted(unknown_ids)}")
        return ValidationResult(
            valid=not errors,
            checked_files=tuple(sorted(checked_files)),
            errors=tuple(errors),
        )

    def load_snapshot(self) -> DatasetSnapshot:
        validation = self.validate()
        if not validation.valid:
            raise ValueError("Synthetic dataset validation failed: " + "; ".join(validation.errors))
        tables = {
            Path(filename).stem: pd.read_csv(self.data_dir / filename)
            for filename in CSV_SCHEMAS
        }
        documents = {
            Path(filename).stem: json.loads((self.data_dir / filename).read_text(encoding="utf-8"))
            for filename in JSON_SCHEMAS
        }
        return DatasetSnapshot(tables=tables, documents=documents, source=self._source)
