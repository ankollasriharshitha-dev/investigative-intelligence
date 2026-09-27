"""PS 26190: Secure Digital Document Management Service for Legal and Investigation Documents.

Provides secure document storage, cryptographic SHA-256 integrity verification,
multi-version document control, RBAC collaboration, approval workflows,
tamper-evident immutable ledger, and multi-faceted search.
"""

import hashlib
import json
import mimetypes
import shutil
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

from services.audit import AuditService
from services.document_ingestion import DocumentIngestionService


DOCUMENT_TYPES = (
    "FIR / Police Report",
    "Investigation Record",
    "Witness Statement",
    "Charge Sheet",
    "Court Filing",
    "Evidence Record",
    "Forensic Report",
    "Legal Notice",
    "Judgment",
    "General Legal Document",
)

CLASSIFICATIONS = (
    "Confidential",
    "Restricted",
    "Law Enforcement Only",
    "Public",
)

STATUSES = (
    "Draft",
    "Submitted",
    "Under Review",
    "Approved",
    "Rejected",
    "Final",
    "Archived",
)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".jpg", ".jpeg", ".png"}
MAX_FILE_BYTES = 25 * 1024 * 1024


class DocumentManagementService:
    """Core PS-26190 Document Management Service."""

    def __init__(self, root: Path, audit: AuditService, legacy_evidence_service=None) -> None:
        self.root = root
        self.audit = audit
        self.legacy_evidence = legacy_evidence_service
        self.files_dir = root / "files"
        self.versions_dir = root / "versions"
        self.backups_dir = root / "backups"
        self.records_path = root / "documents.json"
        self.ledger_path = root / "ledger.json"

        self.files_dir.mkdir(parents=True, exist_ok=True)
        self.versions_dir.mkdir(parents=True, exist_ok=True)
        self.backups_dir.mkdir(parents=True, exist_ok=True)

        self._sync_legacy_evidence()

    def documents(self) -> list[dict[str, Any]]:
        return self._read_json(self.records_path)

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        for doc in self.documents():
            if doc.get("document_id") == document_id:
                return doc
        return None

    def for_case(self, case_id: str) -> list[dict[str, Any]]:
        return [doc for doc in self.documents() if doc.get("case_id") == case_id]

    def upload_document(
        self,
        case_id: str,
        filename: str,
        content: bytes,
        user: str,
        document_type: str = "Investigation Record",
        title: str = "",
        department: str = "General Investigation",
        classification: str = "Restricted",
        description: str = "",
        status: str = "Submitted",
    ) -> dict[str, Any]:
        self._validate_file(filename, content)
        sha256 = hashlib.sha256(content).hexdigest()
        now_str = _now()
        suffix = Path(filename).suffix.lower()

        docs = self.documents()
        doc_number = len(docs) + 1
        document_id = f"DOC-{doc_number:04d}"

        # Current file target
        target = self.files_dir / f"{document_id}{suffix}"
        target.write_bytes(content)

        # Version 1 file target
        v1_target = self.versions_dir / f"{document_id}_v1{suffix}"
        v1_target.write_bytes(content)

        # Text and entity extraction
        result = (
            DocumentIngestionService().extract(filename, content)
            if suffix in {".pdf", ".docx", ".txt"}
            else self._image_result(filename, content)
        )
        ocr_used = suffix in {".jpg", ".jpeg", ".png"} and bool(result.text.strip())
        if suffix == ".pdf" and not result.text.strip():
            result, ocr_used = self._ocr_pdf(filename, content, result)

        doc_title = title.strip() or Path(filename).stem.replace("_", " ").title()

        v1_record = {
            "version_number": 1,
            "filename": Path(filename).name,
            "storage_path": str(v1_target),
            "sha256": sha256,
            "uploaded_by": user,
            "timestamp": now_str,
            "change_summary": "Initial document upload and intake",
            "file_size": len(content),
            "status": status,
        }

        record = {
            "document_id": document_id,
            "case_id": case_id,
            "filename": Path(filename).name,
            "title": doc_title,
            "description": description.strip(),
            "document_type": document_type if document_type in DOCUMENT_TYPES else "Investigation Record",
            "department": department.strip() or "General Investigation",
            "classification": classification if classification in CLASSIFICATIONS else "Restricted",
            "current_version": 1,
            "status": status if status in STATUSES else "Submitted",
            "uploaded_by": user,
            "uploaded_at": now_str,
            "last_modified": now_str,
            "sha256": sha256,
            "integrity_status": "VERIFIED",
            "storage_path": str(target),
            "file_size": len(content),
            "file_type": suffix.lstrip(".").upper(),
            "mime_type": mimetypes.guess_type(filename)[0] or "application/octet-stream",
            "extracted_text": result.text,
            "ocr_used": ocr_used,
            "warnings": list(result.warnings),
            "entities": result.entities,
            "relationships": result.relationships,
            "shared_with": [],
            "approval_history": [
                {
                    "status": status,
                    "by": user,
                    "role": "Uploader",
                    "timestamp": now_str,
                    "notes": "Initial document ingestion",
                }
            ],
            "versions": [v1_record],
        }

        # Tamper-evident ledger
        block = self._append_ledger_block(document_id, sha256, now_str, user, action="DOCUMENT_UPLOAD", version=1)
        record["block_id"] = block["block_id"]
        v1_record["block_id"] = block["block_id"]

        docs.append(record)
        self._write_json(self.records_path, docs)

        self.audit.record(
            user,
            "DOCUMENT_UPLOAD",
            document_id,
            "Success",
            {
                "case_id": case_id,
                "document_type": document_type,
                "title": doc_title,
                "version": 1,
                "sha256": sha256,
                "block_id": block["block_id"],
            },
        )

        return record

    def upload_version(
        self,
        document_id: str,
        filename: str,
        content: bytes,
        user: str,
        change_summary: str = "",
    ) -> dict[str, Any]:
        self._validate_file(filename, content)
        docs = self.documents()
        doc = next((d for d in docs if d["document_id"] == document_id), None)
        if not doc:
            raise ValueError(f"Document {document_id} was not found.")

        new_version_num = doc.get("current_version", 1) + 1
        now_str = _now()
        sha256 = hashlib.sha256(content).hexdigest()
        suffix = Path(filename).suffix.lower()

        # Save new version file in versions directory
        version_target = self.versions_dir / f"{document_id}_v{new_version_num}{suffix}"
        version_target.write_bytes(content)

        # Update active file target
        active_target = Path(doc["storage_path"])
        active_target.write_bytes(content)

        # Extract text from updated version
        result = (
            DocumentIngestionService().extract(filename, content)
            if suffix in {".pdf", ".docx", ".txt"}
            else self._image_result(filename, content)
        )

        block = self._append_ledger_block(
            document_id,
            sha256,
            now_str,
            user,
            action="NEW_VERSION",
            version=new_version_num,
        )

        version_entry = {
            "version_number": new_version_num,
            "filename": Path(filename).name,
            "storage_path": str(version_target),
            "sha256": sha256,
            "uploaded_by": user,
            "timestamp": now_str,
            "change_summary": change_summary.strip() or f"Version {new_version_num} update",
            "file_size": len(content),
            "status": doc.get("status", "Under Review"),
            "block_id": block["block_id"],
        }

        doc["current_version"] = new_version_num
        doc["sha256"] = sha256
        doc["file_size"] = len(content)
        doc["last_modified"] = now_str
        doc["integrity_status"] = "VERIFIED"
        doc["block_id"] = block["block_id"]
        doc["extracted_text"] = result.text or doc.get("extracted_text", "")
        doc.setdefault("versions", []).append(version_entry)

        self._write_json(self.records_path, docs)

        self.audit.record(
            user,
            "DOCUMENT_VERSION_UPLOAD",
            document_id,
            "Success",
            {
                "new_version": new_version_num,
                "change_summary": version_entry["change_summary"],
                "sha256": sha256,
                "block_id": block["block_id"],
            },
        )

        return doc

    def verify_integrity(self, document_id: str, user: str, version_number: int | None = None) -> dict[str, Any]:
        doc = self.get_document(document_id)
        if not doc:
            raise ValueError(f"Document {document_id} was not found.")

        if version_number and version_number != doc.get("current_version"):
            # Verify specific historical version
            ver = next((v for v in doc.get("versions", []) if v["version_number"] == version_number), None)
            if not ver:
                raise ValueError(f"Version {version_number} of {document_id} was not found.")
            target_path = Path(ver["storage_path"])
            expected = ver["sha256"]
        else:
            target_path = Path(doc["storage_path"])
            expected = doc["sha256"]
            version_number = doc.get("current_version", 1)

        current = hashlib.sha256(target_path.read_bytes()).hexdigest() if target_path.exists() else ""
        is_verified = bool(current and current.lower() == expected.lower())
        status = "VERIFIED" if is_verified else "INTEGRITY MISMATCH"

        # Update in metadata
        docs = self.documents()
        for d in docs:
            if d["document_id"] == document_id:
                d["integrity_status"] = status
                break
        self._write_json(self.records_path, docs)

        audit_status = "Success" if is_verified else "Integrity Violation"
        self.audit.record(
            user,
            "INTEGRITY_VERIFICATION",
            document_id,
            audit_status,
            {
                "version": version_number,
                "expected_sha256": expected,
                "current_sha256": current,
                "result": status,
            },
        )

        return {
            "document_id": document_id,
            "version": version_number,
            "expected_sha256": expected,
            "current_sha256": current,
            "integrity_status": status,
            "verified": is_verified,
            "verified_by": user,
            "verified_at": _now(),
        }

    def update_status(self, document_id: str, new_status: str, user: str, role: str = "", notes: str = "") -> dict[str, Any]:
        if new_status not in STATUSES:
            raise ValueError(f"Invalid status: {new_status}. Allowed: {', '.join(STATUSES)}")
        docs = self.documents()
        doc = next((d for d in docs if d["document_id"] == document_id), None)
        if not doc:
            raise ValueError(f"Document {document_id} was not found.")

        old_status = doc.get("status", "Draft")
        now_str = _now()
        doc["status"] = new_status
        doc["last_modified"] = now_str
        doc.setdefault("approval_history", []).append({
            "status": new_status,
            "old_status": old_status,
            "by": user,
            "role": role,
            "timestamp": now_str,
            "notes": notes.strip(),
        })

        self._write_json(self.records_path, docs)

        action_name = (
            "DOCUMENT_APPROVAL" if new_status == "Approved"
            else "DOCUMENT_REJECTION" if new_status == "Rejected"
            else "DOCUMENT_STATUS_CHANGE"
        )
        self.audit.record(
            user,
            action_name,
            document_id,
            "Success",
            {"from": old_status, "to": new_status, "notes": notes},
        )

        return doc

    def share_document(self, document_id: str, target: str, permission: str, user: str, notes: str = "") -> dict[str, Any]:
        docs = self.documents()
        doc = next((d for d in docs if d["document_id"] == document_id), None)
        if not doc:
            raise ValueError(f"Document {document_id} was not found.")

        share_entry = {
            "target": target.strip(),
            "permission": permission,
            "granted_by": user,
            "granted_at": _now(),
            "notes": notes.strip(),
        }
        doc.setdefault("shared_with", []).append(share_entry)
        self._write_json(self.records_path, docs)

        self.audit.record(
            user,
            "DOCUMENT_SHARE",
            document_id,
            "Success",
            {"target": target, "permission": permission, "notes": notes},
        )

        return doc

    def search_documents(
        self,
        query: str = "",
        case_id: str = "",
        document_type: str = "",
        status: str = "",
        classification: str = "",
        uploader: str = "",
        department: str = "",
    ) -> list[dict[str, Any]]:
        results = []
        q = query.strip().lower()

        for doc in self.documents():
            if case_id and case_id != "All Cases" and doc.get("case_id") != case_id:
                continue
            if document_type and document_type != "All Types" and doc.get("document_type") != document_type:
                continue
            if status and status != "All Statuses" and doc.get("status") != status:
                continue
            if classification and classification != "All Classifications" and doc.get("classification") != classification:
                continue
            if uploader and uploader != "All Users" and doc.get("uploaded_by") != uploader:
                continue
            if department and department != "All Departments" and doc.get("department") != department:
                continue

            if q:
                searchable = " ".join([
                    doc.get("document_id", ""),
                    doc.get("title", ""),
                    doc.get("filename", ""),
                    doc.get("description", ""),
                    doc.get("department", ""),
                    doc.get("case_id", ""),
                    doc.get("extracted_text", ""),
                ]).lower()
                if q not in searchable:
                    continue

            results.append(doc)

        return results

    def ledger(self) -> list[dict[str, Any]]:
        return self._read_json(self.ledger_path)

    def verify_ledger(self, user: str) -> dict[str, Any]:
        chain = self.ledger()
        previous = "0" * 64
        valid = True
        tampered_block = None

        for block in chain:
            payload = {
                key: block[key]
                for key in ("block_id", "resource_id", "action", "version", "sha256", "timestamp", "user", "previous_hash")
                if key in block
            }
            if block.get("previous_hash") != previous or block.get("current_hash") != _block_hash(payload):
                valid = False
                tampered_block = block.get("block_id")
                break
            previous = block["current_hash"]

        status = "LEDGER VALID" if valid else f"LEDGER TAMPERED (at {tampered_block})"
        self.audit.record(user, "LEDGER_VERIFICATION", "tamper_evident_ledger", "Valid" if valid else "Tampered")
        return {"status": status, "valid": valid, "blocks": len(chain), "tampered_block": tampered_block}

    def simulate_tampering(self, document_id: str, user: str) -> dict[str, Any]:
        """Utility for demonstrations: modifies one byte on disk to show tamper detection."""
        doc = self.get_document(document_id)
        if not doc:
            raise ValueError(f"Document {document_id} was not found.")

        target = Path(doc["storage_path"])
        if not target.exists():
            raise FileNotFoundError(f"File {target} not found on disk.")

        # Backup clean file if not already backed up
        backup = self.backups_dir / f"{document_id}_clean_backup{target.suffix}"
        if not backup.exists():
            shutil.copy2(target, backup)

        # Alter bytes
        original_bytes = target.read_bytes()
        tampered_bytes = original_bytes + b"\n# UNAUTHORIZED TAMPERED CONTENT [SIMULATION] #"
        target.write_bytes(tampered_bytes)

        # Mark integrity mismatch
        self.audit.record(user, "INTEGRITY_TAMPER_SIMULATION", document_id, "Alert", {"note": "Simulated file tampering"})
        return self.verify_integrity(document_id, user)

    def restore_tampering(self, document_id: str, user: str) -> dict[str, Any]:
        """Restores the original clean file from backup after a tampering simulation."""
        doc = self.get_document(document_id)
        if not doc:
            raise ValueError(f"Document {document_id} was not found.")

        target = Path(doc["storage_path"])
        backup = self.backups_dir / f"{document_id}_clean_backup{target.suffix}"
        if backup.exists():
            shutil.copy2(backup, target)

        self.audit.record(user, "INTEGRITY_RESTORED", document_id, "Success", {"note": "Original file restored from secure backup"})
        return self.verify_integrity(document_id, user)

    def _append_ledger_block(
        self,
        resource_id: str,
        sha256: str,
        timestamp: str,
        user: str,
        action: str = "RECORD",
        version: int = 1,
    ) -> dict[str, Any]:
        chain = self.ledger()
        previous = chain[-1]["current_hash"] if chain else "0" * 64
        payload = {
            "block_id": f"BLOCK-{len(chain) + 1:04d}",
            "resource_id": resource_id,
            "action": action,
            "version": version,
            "sha256": sha256,
            "timestamp": timestamp,
            "user": user,
            "previous_hash": previous,
        }
        block = dict(payload)
        block["current_hash"] = _block_hash(payload)
        chain.append(block)
        self._write_json(self.ledger_path, chain)
        return block

    def _sync_legacy_evidence(self) -> None:
        """Seamlessly syncs existing legacy evidence records into documents.json."""
        if not self.legacy_evidence:
            return
        existing_docs = self.documents()
        existing_doc_ids = {d.get("document_id") for d in existing_docs}
        existing_hashes = {d.get("sha256") for d in existing_docs}

        legacy_records = self.legacy_evidence.records()
        modified = False

        for rec in legacy_records:
            if rec.get("sha256") in existing_hashes or rec.get("evidence_id") in existing_doc_ids:
                continue

            doc_id = rec.get("evidence_id", f"DOC-{len(existing_docs) + 1:04d}")
            suffix = Path(rec.get("filename", "")).suffix.lower()
            storage_path = rec.get("path", "")

            # If file exists at legacy path, copy or reference it
            target = self.files_dir / f"{doc_id}{suffix}"
            if Path(storage_path).exists() and not target.exists():
                try:
                    shutil.copy2(storage_path, target)
                    storage_path = str(target)
                except OSError:
                    pass

            v1_target = self.versions_dir / f"{doc_id}_v1{suffix}"
            if Path(storage_path).exists() and not v1_target.exists():
                try:
                    shutil.copy2(storage_path, v1_target)
                except OSError:
                    pass

            v1 = {
                "version_number": 1,
                "filename": rec.get("filename", "evidence.bin"),
                "storage_path": str(v1_target if v1_target.exists() else storage_path),
                "sha256": rec.get("sha256", ""),
                "uploaded_by": rec.get("uploader", "demo_investigator"),
                "timestamp": rec.get("uploaded_at", _now()),
                "change_summary": "Initial intake (Synchronized from evidence records)",
                "file_size": rec.get("file_size", 0),
                "status": "Approved",
            }

            doc_entry = {
                "document_id": doc_id,
                "case_id": rec.get("case_id", "CASE001"),
                "filename": rec.get("filename", "evidence.bin"),
                "title": Path(rec.get("filename", "evidence.bin")).stem.replace("_", " ").title(),
                "description": "Investigation evidence record imported to document management",
                "document_type": "Evidence Record",
                "department": "Forensics & Evidence Cell",
                "classification": "Restricted",
                "current_version": 1,
                "status": "Approved",
                "uploaded_by": rec.get("uploader", "demo_investigator"),
                "uploaded_at": rec.get("uploaded_at", _now()),
                "last_modified": rec.get("uploaded_at", _now()),
                "sha256": rec.get("sha256", ""),
                "integrity_status": "VERIFIED",
                "storage_path": storage_path,
                "file_size": rec.get("file_size", 0),
                "file_type": rec.get("file_type", "DOCX"),
                "mime_type": rec.get("mime_type", "application/octet-stream"),
                "extracted_text": rec.get("extracted_text", ""),
                "ocr_used": rec.get("ocr_used", False),
                "warnings": rec.get("warnings", []),
                "entities": rec.get("entities", {}),
                "relationships": rec.get("relationships", []),
                "shared_with": [],
                "approval_history": [
                    {
                        "status": "Approved",
                        "by": rec.get("uploader", "demo_investigator"),
                        "role": "Investigator",
                        "timestamp": rec.get("uploaded_at", _now()),
                        "notes": "Synchronized from case intake",
                    }
                ],
                "versions": [v1],
            }

            existing_docs.append(doc_entry)
            existing_doc_ids.add(doc_id)
            existing_hashes.add(rec.get("sha256"))
            modified = True

        if modified:
            self._write_json(self.records_path, existing_docs)

    @staticmethod
    def _validate_file(filename: str, content: bytes) -> None:
        suffix = Path(filename).suffix.lower()
        if not filename or suffix not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported file format '{suffix}'. Supported formats: PDF, DOCX, TXT, JPG, PNG.")
        if not content:
            raise ValueError("Uploaded file is empty.")
        if len(content) > MAX_FILE_BYTES:
            raise ValueError(f"Uploaded file exceeds maximum limit of {MAX_FILE_BYTES // (1024*1024)} MB.")
        if suffix == ".pdf" and not content.startswith(b"%PDF"):
            raise ValueError("Corrupt PDF file: missing standard PDF header.")
        if suffix == ".docx":
            try:
                with zipfile.ZipFile(BytesIO(content)) as archive:
                    if "word/document.xml" not in archive.namelist():
                        raise ValueError
            except (ValueError, zipfile.BadZipFile):
                raise ValueError("Corrupt DOCX file: unable to read XML document payload.") from None
        if suffix == ".txt":
            try:
                content.decode("utf-8")
            except UnicodeDecodeError:
                raise ValueError("Corrupt TXT file: text must be valid UTF-8.") from None

    @staticmethod
    def _image_result(filename: str, content: bytes):
        from services.document_ingestion import ExtractedDocument
        try:
            import pytesseract
            from PIL import Image
            text = pytesseract.image_to_string(Image.open(BytesIO(content)))
            return ExtractedDocument(
                filename,
                Path(filename).suffix[1:].upper(),
                text,
                warnings=() if text.strip() else ("OCR returned no readable text.",),
            )
        except ImportError:
            return ExtractedDocument(
                filename,
                Path(filename).suffix[1:].upper(),
                "",
                warnings=("OCR is unavailable in this environment.",),
            )
        except Exception as error:
            return ExtractedDocument(
                filename,
                Path(filename).suffix[1:].upper(),
                "",
                warnings=(f"OCR processing error: {error}",),
            )

    @staticmethod
    def _ocr_pdf(filename: str, content: bytes, fallback):
        from services.document_ingestion import ExtractedDocument
        try:
            import fitz
            import pytesseract
            from PIL import Image
            document = fitz.open(stream=content, filetype="pdf")
            text = "\n".join(
                pytesseract.image_to_string(Image.open(BytesIO(page.get_pixmap(dpi=180).tobytes("png"))))
                for page in document
            )
            warnings = () if text.strip() else ("OCR was attempted but returned no readable text.",)
            return ExtractedDocument(filename, "PDF", text, warnings=warnings), True
        except ImportError:
            return fallback, False
        except Exception as error:
            return ExtractedDocument(filename, "PDF", "", warnings=(f"PDF OCR failed: {error}",)), False

    @staticmethod
    def _read_json(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    @staticmethod
    def _write_json(path: Path, data: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _block_hash(block: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(block, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
