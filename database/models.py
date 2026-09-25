"""SQLAlchemy ORM models for canonical entities, relationships, users, and audit records."""

from typing import Any
from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, JSON, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Canonical Investigation Entities and Relationships
# ---------------------------------------------------------------------------

class CaseModel(Base):
    __tablename__ = "cases"

    case_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    opened_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    priority: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="Open")
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[str | None] = mapped_column(String(64), nullable=True)


class PersonModel(Base):
    __tablename__ = "persons"

    person_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(128), nullable=False)
    case_ids: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_case: Mapped[str | None] = mapped_column(String(64), nullable=True)


class PhoneModel(Base):
    __tablename__ = "phones"

    phone_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    phone_number: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    owner_person_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("persons.person_id", ondelete="SET NULL"), nullable=True, index=True
    )
    case_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_case: Mapped[str | None] = mapped_column(String(64), nullable=True)


class LocationModel(Base):
    __tablename__ = "locations"

    location_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_case: Mapped[str | None] = mapped_column(String(64), nullable=True)


class VehicleModel(Base):
    __tablename__ = "vehicles"

    vehicle_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    registration_number: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    owner_person_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("persons.person_id", ondelete="SET NULL"), nullable=True, index=True
    )
    case_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_case: Mapped[str | None] = mapped_column(String(64), nullable=True)


class OrganizationModel(Base):
    __tablename__ = "organizations"

    organization_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(128), nullable=True)
    case_ids: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_case: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AccountModel(Base):
    __tablename__ = "accounts"

    account_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_label: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_person_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("persons.person_id", ondelete="SET NULL"), nullable=True, index=True
    )
    organization_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("organizations.organization_id", ondelete="SET NULL"), nullable=True, index=True
    )
    case_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_case: Mapped[str | None] = mapped_column(String(64), nullable=True)


class CallModel(Base):
    __tablename__ = "calls"

    call_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    caller_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("phones.phone_id", ondelete="SET NULL"), nullable=True, index=True
    )
    receiver_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("phones.phone_id", ondelete="SET NULL"), nullable=True, index=True
    )
    timestamp: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    case_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_case: Mapped[str | None] = mapped_column(String(64), nullable=True)


class MessageModel(Base):
    __tablename__ = "messages"

    message_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sender_phone_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("phones.phone_id", ondelete="SET NULL"), nullable=True, index=True
    )
    receiver_phone_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("phones.phone_id", ondelete="SET NULL"), nullable=True, index=True
    )
    timestamp: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    case_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_case: Mapped[str | None] = mapped_column(String(64), nullable=True)


class TransactionModel(Base):
    __tablename__ = "transactions"

    transaction_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    from_account: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("accounts.account_id", ondelete="SET NULL"), nullable=True, index=True
    )
    to_account: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("accounts.account_id", ondelete="SET NULL"), nullable=True, index=True
    )
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    timestamp: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    case_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_case: Mapped[str | None] = mapped_column(String(64), nullable=True)


class EventModel(Base):
    __tablename__ = "events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    person_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("persons.person_id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    location_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("locations.location_id", ondelete="SET NULL"), nullable=True, index=True
    )
    vehicle_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("vehicles.vehicle_id", ondelete="SET NULL"), nullable=True, index=True
    )
    organization_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("organizations.organization_id", ondelete="SET NULL"), nullable=True, index=True
    )
    timestamp: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    case_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_case: Mapped[str | None] = mapped_column(String(64), nullable=True)


# ---------------------------------------------------------------------------
# Authentication, RBAC, Evidence, Ledger, and Audit Models
# ---------------------------------------------------------------------------

class UserModel(Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(128), primary_key=True)
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    totp_secret: Mapped[str] = mapped_column(String(128), nullable=False)
    mfa_enrolled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class EvidenceModel(Base):
    __tablename__ = "evidence"

    evidence_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(32), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_at: Mapped[str] = mapped_column(String(64), nullable=False)
    uploader: Mapped[str] = mapped_column(String(128), nullable=False)
    processing_status: Mapped[str] = mapped_column(String(64), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    ocr_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    entities: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    relationships: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    block_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detected_entities: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    potential_matches: Mapped[Any | None] = mapped_column(JSON, nullable=True)


class EvidenceLedgerModel(Base):
    __tablename__ = "evidence_ledger"

    block_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[str] = mapped_column(String(64), nullable=False)
    user: Mapped[str] = mapped_column(String(128), nullable=False)
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    current_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class CaseEntityModel(Base):
    __tablename__ = "case_entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    evidence_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized: Mapped[str] = mapped_column(String(255), nullable=False, index=True)


class CaseMatchModel(Base):
    __tablename__ = "case_matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_case: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_case: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    confidence: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AuditEventModel(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[Any | None] = mapped_column(JSON, nullable=True)


class DatasetMetadataModel(Base):
    __tablename__ = "dataset_metadata"

    dataset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(64), nullable=False)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="active")
    validation_status: Mapped[str] = mapped_column(String(64), nullable=False, default="Validated")


class IngestionHistoryModel(Base):
    __tablename__ = "ingestion_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ingestion_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    dataset: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[str] = mapped_column(String(64), nullable=False)
    records_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
