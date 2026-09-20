"""PostgreSQL repositories for dataset snapshot persistence, case management, evidence, audit, and auth."""

import hashlib
import json
import logging
import mimetypes
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from database.connection import get_engine, get_session_factory, session_scope
from database.models import (
    AccountModel,
    AuditEventModel,
    CallModel,
    CaseEntityModel,
    CaseMatchModel,
    CaseModel,
    DatasetMetadataModel,
    EventModel,
    EvidenceLedgerModel,
    EvidenceModel,
    IngestionHistoryModel,
    LocationModel,
    MessageModel,
    OrganizationModel,
    PersonModel,
    PhoneModel,
    TransactionModel,
    UserModel,
    VehicleModel,
)
from domain.models import DatasetSnapshot, ValidationResult
from providers.postgres import TABLE_MODEL_MAP, PostgresDataProvider
from providers.synthetic import UNIQUE_ID_COLUMNS
from repositories.base import DatasetRepository
from services.audit import AuditService
from services.document_ingestion import DocumentIngestionService
from services.entity_intelligence import extract_entities, normalize, potential_matches
from services.security import (
    AuthorizationError,
    PERMISSIONS,
    User,
    _hash_password,
    _new_secret,
    _totp,
    _verify_password,
)

logger = logging.getLogger(__name__)


class PostgresDatasetRepository(DatasetRepository):
    """PostgreSQL dataset persistence adapter supporting transactional snapshot upsert."""

    def __init__(self, database_url_or_engine: str | Engine | None = None) -> None:
        if isinstance(database_url_or_engine, Engine):
            self.engine = database_url_or_engine
        else:
            self.engine = get_engine(database_url_or_engine)
        self.session_factory = get_session_factory(self.engine)
        self.provider = PostgresDataProvider(self.engine)

    def validate(self) -> ValidationResult:
        return self.provider.validate()

    def load_snapshot(self) -> DatasetSnapshot:
        return self.provider.load_snapshot()

    def upsert(self, snapshot: DatasetSnapshot, operation: str = "replace") -> tuple[int, int, int]:
        """Apply snapshot into PostgreSQL tables in a single transaction."""
        added = updated = skipped = 0
        with session_scope(self.session_factory) as session:
            if operation == "replace":
                self._clear_all_data(session)

            # 1. Cases
            for case in snapshot.documents.get("cases", []):
                cid = str(case["case_id"])
                existing = session.get(CaseModel, cid)
                if not existing:
                    session.add(CaseModel(
                        case_id=cid,
                        title=str(case.get("title", cid)),
                        description=case.get("description", ""),
                        opened_date=str(case.get("opened_date", "")),
                        priority=str(case.get("priority", "Medium")),
                        status=str(case.get("status", "Open")),
                        created_by=case.get("created_by", "Import"),
                        created_at=case.get("created_at", _now()),
                    ))
                    added += 1
                elif operation == "update":
                    existing.title = str(case.get("title", existing.title))
                    existing.description = case.get("description", existing.description)
                    existing.opened_date = str(case.get("opened_date", existing.opened_date))
                    existing.priority = str(case.get("priority", existing.priority))
                    existing.status = str(case.get("status", existing.status))
                    updated += 1
                else:
                    skipped += 1

            # 2. Canonical Tables in foreign key order
            table_order = (
                "persons", "locations", "vehicles", "organizations",
                "phones", "accounts", "calls", "messages", "transactions", "events"
            )
            for table_name in table_order:
                df = snapshot.tables.get(table_name, pd.DataFrame())
                if df.empty:
                    continue
                model_cls = TABLE_MODEL_MAP[table_name]
                pk_col = UNIQUE_ID_COLUMNS[f"{table_name}.csv"]
                for row in df.to_dict(orient="records"):
                    pk_val = str(row[pk_col])
                    existing = session.get(model_cls, pk_val)
                    if not existing:
                        clean_row = {k: v for k, v in row.items() if hasattr(model_cls, k) and pd.notna(v)}
                        clean_row[pk_col] = pk_val
                        session.add(model_cls(**clean_row))
                        added += 1
                    elif operation == "update":
                        for k, v in row.items():
                            if hasattr(model_cls, k) and k != pk_col and pd.notna(v):
                                setattr(existing, k, v)
                        updated += 1
                    else:
                        skipped += 1

        return added, updated, skipped

    def _clear_all_data(self, session: Session) -> None:
        session.query(EventModel).delete()
        session.query(TransactionModel).delete()
        session.query(MessageModel).delete()
        session.query(CallModel).delete()
        session.query(AccountModel).delete()
        session.query(PhoneModel).delete()
        session.query(VehicleModel).delete()
        session.query(LocationModel).delete()
        session.query(OrganizationModel).delete()
        session.query(PersonModel).delete()
        session.query(CaseModel).delete()


class PostgresAuditService:
    """PostgreSQL-backed append-only audit event service."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def record(self, user: str, action: str, resource: str, status: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        event = {
            "timestamp": _now(),
            "user": user or "anonymous",
            "action": action,
            "resource": resource,
            "status": status,
            "metadata": metadata or {},
        }
        with session_scope(self.session_factory) as session:
            session.add(AuditEventModel(
                timestamp=event["timestamp"],
                user=event["user"],
                action=event["action"],
                resource=event["resource"],
                status=event["status"],
                metadata_json=event["metadata"],
            ))
        return event

    def events(self) -> list[dict[str, Any]]:
        with session_scope(self.session_factory) as session:
            records = session.scalars(select(AuditEventModel).order_by(AuditEventModel.id.asc())).all()
            return [
                {
                    "timestamp": r.timestamp,
                    "user": r.user,
                    "action": r.action,
                    "resource": r.resource,
                    "status": r.status,
                    "metadata": r.metadata_json or {},
                }
                for r in records
            ]


class PostgresAuthenticationService:
    """PostgreSQL-backed authentication and RBAC service."""

    def __init__(self, session_factory: sessionmaker[Session], audit: PostgresAuditService | AuditService) -> None:
        self.session_factory = session_factory
        self.audit = audit
        self._ensure_users()

    def verify_password(self, username: str, password: str) -> User | None:
        user = self.get_user(username)
        valid = bool(user and _verify_password(password, user.password_hash))
        self.audit.record(username, "LOGIN", "session", "Success" if valid else "Denied")
        return user if valid else None

    def verify_totp(self, user: User, code: str, window: int = 1) -> bool:
        import hmac
        valid = user.mfa_enrolled and any(
            hmac.compare_digest(_totp(user.totp_secret, offset), str(code).strip())
            for offset in range(-window, window + 1)
        )
        self.audit.record(user.username, "MFA_VERIFICATION", "session", "Success" if valid else "Denied")
        return valid

    def begin_totp_enrollment(self, username: str) -> User:
        with session_scope(self.session_factory) as session:
            user_model = session.get(UserModel, username)
            if not user_model:
                raise ValueError("Unknown user")
            if not user_model.totp_secret:
                user_model.totp_secret = _new_secret()
            return User(
                user_model.username,
                user_model.role,
                user_model.password_hash,
                user_model.totp_secret,
                bool(user_model.mfa_enrolled),
            )

    def complete_totp_enrollment(self, user: User, code: str, window: int = 1) -> bool:
        import hmac
        valid = any(
            hmac.compare_digest(_totp(user.totp_secret, offset), str(code).strip())
            for offset in range(-window, window + 1)
        )
        if valid:
            with session_scope(self.session_factory) as session:
                user_model = session.get(UserModel, user.username)
                if user_model:
                    user_model.mfa_enrolled = True
        self.audit.record(user.username, "MFA_ENROLLMENT", "session", "Success" if valid else "Denied")
        return valid

    @staticmethod
    def provisioning_uri(user: User, issuer: str = "Investigative Intelligence") -> str:
        from urllib.parse import quote
        label = quote(f"{issuer}:{user.username}")
        return f"otpauth://totp/{label}?secret={user.totp_secret}&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30"

    def get_user(self, username: str) -> User | None:
        with session_scope(self.session_factory) as session:
            user_model = session.get(UserModel, username)
            if user_model:
                return User(
                    user_model.username,
                    user_model.role,
                    user_model.password_hash,
                    user_model.totp_secret,
                    bool(user_model.mfa_enrolled),
                )
        return None

    def require(self, user: User | None, permission: str) -> None:
        if not user or user.role not in PERMISSIONS.get(permission, set()):
            self.audit.record(user.username if user else "anonymous", "PERMISSION_DENIED", permission, "Denied")
            raise AuthorizationError("You do not have permission for this operation.")

    def _ensure_users(self) -> None:
        with session_scope(self.session_factory) as session:
            count = session.query(UserModel).count()
            if count == 0:
                password_hash = _hash_password(os.environ.get("II_DEMO_PASSWORD", "DemoPass!2026"))
                default_users = [
                    UserModel(username="demo_investigator", role="Investigator", password_hash=password_hash, totp_secret=_new_secret(), mfa_enrolled=False),
                    UserModel(username="demo_forensic", role="Forensic Officer", password_hash=password_hash, totp_secret=_new_secret(), mfa_enrolled=False),
                    UserModel(username="demo_admin", role="Administrator", password_hash=password_hash, totp_secret=_new_secret(), mfa_enrolled=False),
                ]
                session.add_all(default_users)


class PostgresCaseManagementService:
    """PostgreSQL-backed case registration, entity matching, and intelligence store."""

    def __init__(self, session_factory: sessionmaker[Session], audit: PostgresAuditService | AuditService) -> None:
        self.session_factory = session_factory
        self.audit = audit

    def cases(self) -> list[dict[str, Any]]:
        with session_scope(self.session_factory) as session:
            records = session.scalars(select(CaseModel).order_by(CaseModel.created_at.desc())).all()
            return [
                {
                    "case_id": c.case_id,
                    "title": c.title,
                    "description": c.description or "",
                    "opened_date": c.opened_date or "",
                    "priority": c.priority or "Medium",
                    "status": c.status or "Open",
                    "created_by": c.created_by or "",
                    "created_at": c.created_at or "",
                }
                for c in records
            ]

    def create(self, case_id: str, title: str, description: str, date: str, priority: str, user: str) -> dict[str, Any]:
        if not case_id.strip() or not title.strip():
            raise ValueError("Case ID and title are required.")
        with session_scope(self.session_factory) as session:
            existing = session.get(CaseModel, case_id.strip())
            if existing:
                raise ValueError("A case with this ID already exists.")
            record = {
                "case_id": case_id.strip(),
                "title": title.strip(),
                "description": description.strip(),
                "opened_date": date,
                "priority": priority,
                "status": "Open",
                "created_by": user,
                "created_at": _now(),
            }
            session.add(CaseModel(**record))
        self.audit.record(user, "CASE_CREATION", record["case_id"], "Success")
        return record

    def update(self, case_id: str, changes: dict[str, Any], user: str) -> dict[str, Any]:
        with session_scope(self.session_factory) as session:
            case = session.get(CaseModel, case_id)
            if not case:
                raise ValueError("Case was not found.")
            for key in ("title", "description", "status", "priority"):
                if key in changes:
                    setattr(case, key, changes[key])
            record = {
                "case_id": case.case_id,
                "title": case.title,
                "description": case.description or "",
                "opened_date": case.opened_date or "",
                "priority": case.priority or "Medium",
                "status": case.status or "Open",
                "created_by": case.created_by or "",
                "created_at": case.created_at or "",
            }
        self.audit.record(user, "CASE_UPDATE", case_id, "Success")
        return record

    def evidence_entities(self, evidence: dict[str, Any]) -> list[dict[str, str]]:
        entities = extract_entities(evidence.get("extracted_text", ""), evidence.get("entities", {}))
        with session_scope(self.session_factory) as session:
            # Clear previous entities for this evidence
            session.query(CaseEntityModel).filter(CaseEntityModel.evidence_id == evidence["evidence_id"]).delete()
            for item in entities:
                session.add(CaseEntityModel(
                    case_id=evidence["case_id"],
                    evidence_id=evidence["evidence_id"],
                    type=item["type"],
                    value=item["value"],
                    normalized=item["normalized"],
                ))
        return entities

    def entity_records(self) -> list[dict[str, Any]]:
        with session_scope(self.session_factory) as session:
            rows = session.scalars(select(CaseEntityModel)).all()
            return [
                {
                    "case_id": r.case_id,
                    "evidence_id": r.evidence_id,
                    "type": r.type,
                    "value": r.value,
                    "normalized": r.normalized,
                }
                for r in rows
            ]

    def matches(self, case_id: str, entities: list[dict[str, str]], synthetic_entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        matches = potential_matches(case_id, entities, [*self.entity_records(), *synthetic_entities])
        with session_scope(self.session_factory) as session:
            session.query(CaseMatchModel).filter(CaseMatchModel.source_case == case_id).delete()
            for m in matches:
                session.add(CaseMatchModel(
                    source_case=m["source_case"],
                    target_case=m["target_case"],
                    entity=m["entity"],
                    entity_type=m["entity_type"],
                    reason=m["reason"],
                    confidence=m["confidence"],
                    status=m["status"],
                    evidence_id=m.get("evidence_id"),
                ))
        return matches

    def matches_for_case(self, case_id: str | None = None) -> list[dict[str, Any]]:
        with session_scope(self.session_factory) as session:
            query = select(CaseMatchModel)
            if case_id:
                query = query.filter(CaseMatchModel.source_case == case_id)
            rows = session.scalars(query).all()
            return [
                {
                    "source_case": r.source_case,
                    "target_case": r.target_case,
                    "entity": r.entity,
                    "entity_type": r.entity_type,
                    "reason": r.reason,
                    "confidence": r.confidence,
                    "status": r.status,
                    "evidence_id": r.evidence_id,
                }
                for r in rows
            ]


class PostgresEvidenceService:
    """PostgreSQL-backed evidence metadata, hash verification, and tamper-evident ledger."""

    SUPPORTED = {".pdf", ".docx", ".txt", ".jpg", ".jpeg", ".png"}
    MAX_BYTES = 20 * 1024 * 1024

    def __init__(self, root: Path, session_factory: sessionmaker[Session], audit: PostgresAuditService | AuditService) -> None:
        self.root = root
        self.files = root / "files"
        self.session_factory = session_factory
        self.audit = audit

    def upload(self, case_id: str, filename: str, content: bytes, user: str) -> dict[str, Any]:
        self._validate(filename, content)
        count = len(self.records())
        evidence_id = f"EVD-{count + 1:04d}"
        target = self.files / f"{evidence_id}{Path(filename).suffix.lower()}"
        self.files.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

        sha256 = hashlib.sha256(content).hexdigest()
        suffix = Path(filename).suffix.lower()
        result = DocumentIngestionService().extract(filename, content) if suffix in {".pdf", ".docx", ".txt"} else self._image_result(filename, content)
        ocr_used = suffix in {".jpg", ".jpeg", ".png"} and not any("unavailable" in w.lower() or "failed" in w.lower() for w in result.warnings)
        if suffix == ".pdf" and not result.text.strip():
            result, ocr_used = self._ocr_pdf(filename, content, result)
        failed = any("failed" in w.lower() for w in result.warnings)

        record = {
            "evidence_id": evidence_id,
            "case_id": case_id,
            "filename": Path(filename).name,
            "file_type": suffix.lstrip(".").upper(),
            "mime_type": mimetypes.guess_type(filename)[0] or "application/octet-stream",
            "file_size": len(content),
            "uploaded_at": _now(),
            "uploader": user,
            "processing_status": "Processing failed" if failed else ("Processed" if result.text else "Processing requires review"),
            "sha256": sha256,
            "path": str(target),
            "ocr_used": ocr_used,
            "extracted_text": result.text,
            "warnings": list(result.warnings),
            "entities": result.entities,
            "relationships": result.relationships,
            "detected_entities": [],
            "potential_matches": [],
        }

        block = self._append_block(record)
        record["block_id"] = block["block_id"]

        with session_scope(self.session_factory) as session:
            session.add(EvidenceModel(**record))

        self.audit.record(user, "EVIDENCE_UPLOAD", evidence_id, "Success", {"case_id": case_id, "sha256": sha256})
        self.audit.record(user, "EVIDENCE_PROCESSING", evidence_id, "Success" if result.text else "Review", {"ocr_used": record["ocr_used"]})
        return record

    def records(self) -> list[dict[str, Any]]:
        with session_scope(self.session_factory) as session:
            models = session.scalars(select(EvidenceModel).order_by(EvidenceModel.evidence_id.asc())).all()
            return [self._to_dict(m) for m in models]

    def for_case(self, case_id: str) -> list[dict[str, Any]]:
        with session_scope(self.session_factory) as session:
            models = session.scalars(select(EvidenceModel).filter(EvidenceModel.case_id == case_id)).all()
            return [self._to_dict(m) for m in models]

    def update_analysis(self, evidence_id: str, entities: list[dict[str, Any]], matches: list[dict[str, Any]]) -> None:
        with session_scope(self.session_factory) as session:
            model = session.get(EvidenceModel, evidence_id)
            if model:
                model.detected_entities = entities
                model.potential_matches = matches

    def verify(self, evidence_id: str, user: str) -> dict[str, Any]:
        with session_scope(self.session_factory) as session:
            model = session.get(EvidenceModel, evidence_id)
            if not model:
                raise ValueError("Evidence record was not found.")
            path = Path(model.path)
            current = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""
            status = "VERIFIED" if current and current == model.sha256 else "INTEGRITY MISMATCH"
            self.audit.record(user, "EVIDENCE_VERIFICATION", evidence_id, status)
            rec = self._to_dict(model)
            rec.update({"current_sha256": current, "integrity_status": status})
            return rec

    def ledger(self) -> list[dict[str, Any]]:
        with session_scope(self.session_factory) as session:
            blocks = session.scalars(select(EvidenceLedgerModel).order_by(EvidenceLedgerModel.block_id.asc())).all()
            return [
                {
                    "block_id": b.block_id,
                    "evidence_id": b.evidence_id,
                    "sha256": b.sha256,
                    "timestamp": b.timestamp,
                    "user": b.user,
                    "previous_hash": b.previous_hash,
                    "current_hash": b.current_hash,
                }
                for b in blocks
            ]

    def verify_ledger(self, user: str) -> dict[str, Any]:
        previous = "0" * 64
        valid = True
        ledger_blocks = self.ledger()
        for block in ledger_blocks:
            payload = {key: block[key] for key in ("block_id", "evidence_id", "sha256", "timestamp", "user", "previous_hash")}
            if block.get("previous_hash") != previous or block.get("current_hash") != _block_hash(payload):
                valid = False
                break
            previous = block["current_hash"]
        status = "LEDGER VALID" if valid else "LEDGER TAMPERED"
        self.audit.record(user, "LEDGER_VERIFICATION", "ledger", status)
        return {"status": status, "blocks": len(ledger_blocks)}

    def _append_block(self, record: dict[str, Any]) -> dict[str, Any]:
        with session_scope(self.session_factory) as session:
            chain = session.scalars(select(EvidenceLedgerModel).order_by(EvidenceLedgerModel.block_id.asc())).all()
            previous = chain[-1].current_hash if chain else "0" * 64
            block_id = f"BLOCK-{len(chain) + 1:04d}"
            block_dict = {
                "block_id": block_id,
                "evidence_id": record["evidence_id"],
                "sha256": record["sha256"],
                "timestamp": record["uploaded_at"],
                "user": record["uploader"],
                "previous_hash": previous,
            }
            block_dict["current_hash"] = _block_hash(block_dict)
            session.add(EvidenceLedgerModel(**block_dict))
            return block_dict

    def _to_dict(self, m: EvidenceModel) -> dict[str, Any]:
        return {
            "evidence_id": m.evidence_id,
            "case_id": m.case_id,
            "filename": m.filename,
            "file_type": m.file_type,
            "mime_type": m.mime_type,
            "file_size": m.file_size,
            "uploaded_at": m.uploaded_at,
            "uploader": m.uploader,
            "processing_status": m.processing_status,
            "sha256": m.sha256,
            "path": m.path,
            "ocr_used": m.ocr_used,
            "extracted_text": m.extracted_text,
            "warnings": m.warnings or [],
            "entities": m.entities or {},
            "relationships": m.relationships or [],
            "block_id": m.block_id,
            "detected_entities": m.detected_entities or [],
            "potential_matches": m.potential_matches or [],
        }

    @classmethod
    def _validate(cls, filename: str, content: bytes) -> None:
        from services.evidence import EvidenceService
        EvidenceService._validate(filename, content)

    @staticmethod
    def _image_result(filename: str, content: bytes):
        from services.evidence import EvidenceService
        return EvidenceService._image_result(None, filename, content)

    @staticmethod
    def _ocr_pdf(filename: str, content: bytes, fallback):
        from services.evidence import EvidenceService
        return EvidenceService._ocr_pdf(None, filename, content, fallback)


def _block_hash(block: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(block, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
