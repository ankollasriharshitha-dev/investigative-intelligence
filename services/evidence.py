"""Local evidence storage, processing, hashing, and tamper-evident ledger."""

import hashlib
import json
import mimetypes
import zipfile
from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.audit import AuditService
from services.document_ingestion import DocumentIngestionService


SUPPORTED = {".pdf", ".docx", ".txt", ".jpg", ".jpeg", ".png"}
MAX_BYTES = 20 * 1024 * 1024


class EvidenceService:
    def __init__(self, root: Path, audit: AuditService) -> None:
        self.root, self.audit = root, audit
        self.files, self.records_path, self.ledger_path = root / "files", root / "evidence.json", root / "ledger.json"

    def upload(self, case_id: str, filename: str, content: bytes, user: str) -> dict[str, Any]:
        self._validate(filename, content)
        evidence_id = f"EVD-{len(self.records()) + 1:04d}"
        target = self.files / f"{evidence_id}{Path(filename).suffix.lower()}"
        self.files.mkdir(parents=True, exist_ok=True); target.write_bytes(content)
        sha256 = hashlib.sha256(content).hexdigest()
        suffix = Path(filename).suffix.lower()
        result = DocumentIngestionService().extract(filename, content) if suffix in {".pdf", ".docx", ".txt"} else self._image_result(filename, content)
        ocr_used = suffix in {".jpg", ".jpeg", ".png"} and not any("unavailable" in warning.lower() or "failed" in warning.lower() for warning in result.warnings)
        if suffix == ".pdf" and not result.text.strip():
            result, ocr_used = self._ocr_pdf(filename, content, result)
        failed = any("failed" in warning.lower() for warning in result.warnings)
        record = {"evidence_id": evidence_id, "case_id": case_id, "filename": Path(filename).name, "file_type": suffix.lstrip(".").upper(), "mime_type": mimetypes.guess_type(filename)[0] or "application/octet-stream", "file_size": len(content), "uploaded_at": _now(), "uploader": user, "processing_status": "Processing failed" if failed else ("Processed" if result.text else "Processing requires review"), "sha256": sha256, "path": str(target), "ocr_used": ocr_used, "extracted_text": result.text, "warnings": list(result.warnings), "entities": result.entities, "relationships": result.relationships}
        records = self.records(); records.append(record); self._write_json(self.records_path, records)
        block = self._append_block(record)
        record["block_id"] = block["block_id"]; self._write_json(self.records_path, records)
        self.audit.record(user, "EVIDENCE_UPLOAD", evidence_id, "Success", {"case_id": case_id, "sha256": sha256})
        self.audit.record(user, "EVIDENCE_PROCESSING", evidence_id, "Success" if result.text else "Review", {"ocr_used": record["ocr_used"]})
        return record

    def records(self) -> list[dict[str, Any]]:
        return self._read_json(self.records_path)

    def for_case(self, case_id: str) -> list[dict[str, Any]]:
        return [record for record in self.records() if record["case_id"] == case_id]

    def update_analysis(self, evidence_id: str, entities: list[dict[str, Any]], matches: list[dict[str, Any]]) -> None:
        records = self.records()
        record = next((x for x in records if x["evidence_id"] == evidence_id), None)
        if record:
            record["detected_entities"] = entities; record["potential_matches"] = matches
            self._write_json(self.records_path, records)

    def verify(self, evidence_id: str, user: str) -> dict[str, Any]:
        record = next((x for x in self.records() if x["evidence_id"] == evidence_id), None)
        if not record: raise ValueError("Evidence record was not found.")
        path = Path(record["path"]); current = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""
        status = "VERIFIED" if current and current == record["sha256"] else "INTEGRITY MISMATCH"
        self.audit.record(user, "EVIDENCE_VERIFICATION", evidence_id, status)
        return {**record, "current_sha256": current, "integrity_status": status}

    def ledger(self) -> list[dict[str, Any]]: return self._read_json(self.ledger_path)

    def verify_ledger(self, user: str) -> dict[str, Any]:
        previous = "0" * 64
        valid = True
        for block in self.ledger():
            payload = {key: block[key] for key in ("block_id", "evidence_id", "sha256", "timestamp", "user", "previous_hash")}
            if block.get("previous_hash") != previous or block.get("current_hash") != _block_hash(payload): valid = False; break
            previous = block["current_hash"]
        status = "LEDGER VALID" if valid else "LEDGER TAMPERED"
        self.audit.record(user, "LEDGER_VERIFICATION", "ledger", status)
        return {"status": status, "blocks": len(self.ledger())}

    def _append_block(self, record: dict[str, Any]) -> dict[str, Any]:
        chain = self.ledger(); previous = chain[-1]["current_hash"] if chain else "0" * 64
        block = {"block_id": f"BLOCK-{len(chain) + 1:04d}", "evidence_id": record["evidence_id"], "sha256": record["sha256"], "timestamp": record["uploaded_at"], "user": record["uploader"], "previous_hash": previous}
        block["current_hash"] = _block_hash(block); chain.append(block); self._write_json(self.ledger_path, chain)
        return block

    @staticmethod
    def _validate(filename: str, content: bytes) -> None:
        suffix = Path(filename).suffix.lower()
        if not filename or suffix not in SUPPORTED: raise ValueError("Unsupported file type. Use PDF, DOCX, TXT, JPG, or PNG.")
        if not content: raise ValueError("The uploaded file is empty.")
        if len(content) > MAX_BYTES: raise ValueError("The uploaded file exceeds the 20 MB prototype limit.")
        if suffix == ".pdf" and not content.startswith(b"%PDF"):
            raise ValueError("The PDF file is corrupt or does not contain PDF content.")
        if suffix == ".docx":
            try:
                with zipfile.ZipFile(BytesIO(content)) as archive:
                    if "word/document.xml" not in archive.namelist(): raise ValueError
            except (ValueError, zipfile.BadZipFile):
                raise ValueError("The DOCX file is corrupt or unreadable.") from None
        if suffix == ".txt":
            try: content.decode("utf-8")
            except UnicodeDecodeError: raise ValueError("The TXT file is not UTF-8 readable.") from None

    def _image_result(self, filename: str, content: bytes):
        """Use local pytesseract when installed; never pretend OCR ran if it is unavailable."""
        from services.document_ingestion import ExtractedDocument
        try:
            import pytesseract
            from PIL import Image
            from io import BytesIO
            text = pytesseract.image_to_string(Image.open(BytesIO(content)))
            return ExtractedDocument(filename, Path(filename).suffix[1:].upper(), text, warnings=() if text.strip() else ("OCR returned no readable text.",))
        except ImportError:
            return ExtractedDocument(filename, Path(filename).suffix[1:].upper(), "", warnings=("OCR is unavailable locally. Install optional OCR dependencies and Tesseract to process images.",))
        except Exception as error:
            return ExtractedDocument(filename, Path(filename).suffix[1:].upper(), "", warnings=(f"OCR processing failed: {error}",))

    def _ocr_pdf(self, filename: str, content: bytes, fallback):
        """Render scanned PDF pages locally before Tesseract OCR when optional tools exist."""
        from services.document_ingestion import ExtractedDocument
        try:
            import fitz
            import pytesseract
            from PIL import Image
            from io import BytesIO
            document = fitz.open(stream=content, filetype="pdf")
            text = "\n".join(pytesseract.image_to_string(Image.open(BytesIO(page.get_pixmap(dpi=180).tobytes("png")))) for page in document)
            warnings = () if text.strip() else ("OCR was used but returned no readable text.",)
            return ExtractedDocument(filename, "PDF", text, warnings=warnings), True
        except ImportError:
            return fallback, False
        except Exception as error:
            return ExtractedDocument(filename, "PDF", "", warnings=(f"OCR processing failed: {error}",)), False

    @staticmethod
    def _read_json(path: Path) -> list[dict[str, Any]]:
        if not path.exists(): return []
        try:
            data = json.loads(path.read_text(encoding="utf-8")); return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError): return []

    @staticmethod
    def _write_json(path: Path, data: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _block_hash(block: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(block, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _now() -> str: return datetime.now(timezone.utc).isoformat(timespec="seconds")
