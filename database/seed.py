"""Seed PostgreSQL database with canonical synthetic datasets and initial authentication records."""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from config.settings import get_settings
from database.connection import get_engine, get_session_factory, mask_database_url, session_scope
from database.models import (
    AccountModel,
    AuditEventModel,
    Base,
    CallModel,
    CaseModel,
    DatasetMetadataModel,
    EventModel,
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
from database.schema import init_db
from providers.synthetic import SyntheticDataProvider
from services.security import _hash_password, _new_secret

logger = logging.getLogger(__name__)


def seed_database(
    engine: Engine | None = None,
    synthetic_data_dir: Path | None = None,
    database_url: str | None = None,
    force: bool = False,
) -> dict[str, int]:
    """Seed the database with canonical synthetic data in a single clean transaction."""
    settings = get_settings()
    data_dir = synthetic_data_dir or settings.synthetic_data_dir
    eng = engine or get_engine(database_url or settings.database_url)

    # 1. Initialize schema
    init_db(eng)

    # 2. Validate synthetic dataset
    validator = SyntheticDataProvider(data_dir)
    validation = validator.validate()
    if not validation.valid:
        raise ValueError(f"Synthetic dataset failed validation: {'; '.join(validation.errors)}")

    snapshot = validator.load_snapshot()
    session_factory = get_session_factory(eng)
    summary: dict[str, int] = {}

    with session_scope(session_factory) as session:
        # If force is requested, clear existing tables in reverse dependency order
        if force:
            logger.info("Force flag enabled. Clearing existing records before seeding.")
            _clear_tables(session)

        # 3. Seed Cases
        cases_data = snapshot.documents.get("cases", [])
        cases_added = 0
        for case in cases_data:
            existing = session.get(CaseModel, str(case["case_id"]))
            if not existing:
                session.add(CaseModel(
                    case_id=str(case["case_id"]),
                    title=str(case.get("title", case["case_id"])),
                    description=case.get("description", ""),
                    opened_date=str(case.get("opened_date", "")),
                    priority=str(case.get("priority", "Medium")),
                    status=str(case.get("status", "Open")),
                    created_by=case.get("created_by", "System Seed"),
                    created_at=case.get("created_at", datetime.now(timezone.utc).isoformat(timespec="seconds")),
                ))
                cases_added += 1
        summary["cases"] = len(cases_data)

        # 4. Seed Persons
        persons_frame = snapshot.tables.get("persons", pd.DataFrame())
        for row in persons_frame.to_dict(orient="records"):
            pid = str(row["person_id"])
            if not session.get(PersonModel, pid):
                session.add(PersonModel(
                    person_id=pid,
                    name=str(row["name"]),
                    role=str(row["role"]),
                    case_ids=str(row["case_ids"]) if pd.notna(row.get("case_ids")) else None,
                    source_type=str(row.get("source_type", "synthetic")),
                    source_file=str(row.get("source_file", "persons.csv")),
                    source_case=str(row.get("source_case", "")),
                ))
        summary["persons"] = len(persons_frame)

        # 5. Seed Locations
        locations_frame = snapshot.tables.get("locations", pd.DataFrame())
        for row in locations_frame.to_dict(orient="records"):
            lid = str(row["location_id"])
            if not session.get(LocationModel, lid):
                session.add(LocationModel(
                    location_id=lid,
                    label=str(row["label"]),
                    latitude=float(row["latitude"]) if pd.notna(row.get("latitude")) else None,
                    longitude=float(row["longitude"]) if pd.notna(row.get("longitude")) else None,
                    source_type=str(row.get("source_type", "synthetic")),
                    source_file=str(row.get("source_file", "locations.csv")),
                    source_case=str(row.get("source_case", "")),
                ))
        summary["locations"] = len(locations_frame)

        # 6. Seed Vehicles
        vehicles_frame = snapshot.tables.get("vehicles", pd.DataFrame())
        for row in vehicles_frame.to_dict(orient="records"):
            vid = str(row["vehicle_id"])
            if not session.get(VehicleModel, vid):
                session.add(VehicleModel(
                    vehicle_id=vid,
                    registration_number=str(row["registration_number"]),
                    owner_person_id=str(row["owner_person_id"]) if pd.notna(row.get("owner_person_id")) else None,
                    case_id=str(row["case_id"]) if pd.notna(row.get("case_id")) else None,
                    source_type=str(row.get("source_type", "synthetic")),
                    source_file=str(row.get("source_file", "vehicles.csv")),
                    source_case=str(row.get("source_case", "")),
                ))
        summary["vehicles"] = len(vehicles_frame)

        # 7. Seed Organizations
        orgs_frame = snapshot.tables.get("organizations", pd.DataFrame())
        for row in orgs_frame.to_dict(orient="records"):
            oid = str(row["organization_id"])
            if not session.get(OrganizationModel, oid):
                session.add(OrganizationModel(
                    organization_id=oid,
                    name=str(row["name"]),
                    sector=str(row["sector"]) if pd.notna(row.get("sector")) else None,
                    case_ids=str(row["case_ids"]) if pd.notna(row.get("case_ids")) else None,
                    source_type=str(row.get("source_type", "synthetic")),
                    source_file=str(row.get("source_file", "organizations.csv")),
                    source_case=str(row.get("source_case", "")),
                ))
        summary["organizations"] = len(orgs_frame)

        # 8. Seed Phones
        phones_frame = snapshot.tables.get("phones", pd.DataFrame())
        for row in phones_frame.to_dict(orient="records"):
            phid = str(row["phone_id"])
            if not session.get(PhoneModel, phid):
                session.add(PhoneModel(
                    phone_id=phid,
                    phone_number=str(row["phone_number"]),
                    owner_person_id=str(row["owner_person_id"]) if pd.notna(row.get("owner_person_id")) else None,
                    case_id=str(row["case_id"]) if pd.notna(row.get("case_id")) else None,
                    source_type=str(row.get("source_type", "synthetic")),
                    source_file=str(row.get("source_file", "phones.csv")),
                    source_case=str(row.get("source_case", "")),
                ))
        summary["phones"] = len(phones_frame)
        # Ensure parent records are written before dependent foreign-key inserts.
        session.flush()
        # 9. Seed Accounts
        accounts_frame = snapshot.tables.get("accounts", pd.DataFrame())
        for row in accounts_frame.to_dict(orient="records"):
            acc_id = str(row["account_id"])
            if not session.get(AccountModel, acc_id):
                session.add(AccountModel(
                    account_id=acc_id,
                    account_label=str(row["account_label"]),
                    owner_person_id=str(row["owner_person_id"]) if pd.notna(row.get("owner_person_id")) else None,
                    organization_id=str(row["organization_id"]) if pd.notna(row.get("organization_id")) else None,
                    case_id=str(row["case_id"]) if pd.notna(row.get("case_id")) else None,
                    source_type=str(row.get("source_type", "synthetic")),
                    source_file=str(row.get("source_file", "accounts.csv")),
                    source_case=str(row.get("source_case", "")),
                ))
        summary["accounts"] = len(accounts_frame)

        # 10. Seed Calls
        calls_frame = snapshot.tables.get("calls", pd.DataFrame())
        for row in calls_frame.to_dict(orient="records"):
            cid = str(row["call_id"])
            if not session.get(CallModel, cid):
                session.add(CallModel(
                    call_id=cid,
                    caller_id=str(row["caller_id"]) if pd.notna(row.get("caller_id")) else None,
                    receiver_id=str(row["receiver_id"]) if pd.notna(row.get("receiver_id")) else None,
                    timestamp=str(row["timestamp"]),
                    case_id=str(row["case_id"]) if pd.notna(row.get("case_id")) else None,
                    source=str(row["source"]) if pd.notna(row.get("source")) else None,
                    confidence=str(row["confidence"]) if pd.notna(row.get("confidence")) else None,
                    source_type=str(row.get("source_type", "synthetic")),
                    source_file=str(row.get("source_file", "calls.csv")),
                    source_case=str(row.get("source_case", "")),
                ))
        summary["calls"] = len(calls_frame)

        # 11. Seed Messages
        msgs_frame = snapshot.tables.get("messages", pd.DataFrame())
        for row in msgs_frame.to_dict(orient="records"):
            mid = str(row["message_id"])
            if not session.get(MessageModel, mid):
                session.add(MessageModel(
                    message_id=mid,
                    sender_phone_id=str(row["sender_phone_id"]) if pd.notna(row.get("sender_phone_id")) else None,
                    receiver_phone_id=str(row["receiver_phone_id"]) if pd.notna(row.get("receiver_phone_id")) else None,
                    timestamp=str(row["timestamp"]),
                    case_id=str(row["case_id"]) if pd.notna(row.get("case_id")) else None,
                    source=str(row["source"]) if pd.notna(row.get("source")) else None,
                    confidence=str(row["confidence"]) if pd.notna(row.get("confidence")) else None,
                    source_type=str(row.get("source_type", "synthetic")),
                    source_file=str(row.get("source_file", "messages.csv")),
                    source_case=str(row.get("source_case", "")),
                ))
        summary["messages"] = len(msgs_frame)

        # 12. Seed Transactions
        tx_frame = snapshot.tables.get("transactions", pd.DataFrame())
        for row in tx_frame.to_dict(orient="records"):
            tid = str(row["transaction_id"])
            if not session.get(TransactionModel, tid):
                session.add(TransactionModel(
                    transaction_id=tid,
                    from_account=str(row["from_account"]) if pd.notna(row.get("from_account")) else None,
                    to_account=str(row["to_account"]) if pd.notna(row.get("to_account")) else None,
                    amount=float(row["amount"]) if pd.notna(row.get("amount")) else None,
                    timestamp=str(row["timestamp"]),
                    case_id=str(row["case_id"]) if pd.notna(row.get("case_id")) else None,
                    source=str(row["source"]) if pd.notna(row.get("source")) else None,
                    confidence=str(row["confidence"]) if pd.notna(row.get("confidence")) else None,
                    source_type=str(row.get("source_type", "synthetic")),
                    source_file=str(row.get("source_file", "transactions.csv")),
                    source_case=str(row.get("source_case", "")),
                ))
        summary["transactions"] = len(tx_frame)

        # 13. Seed Events
        events_frame = snapshot.tables.get("events", pd.DataFrame())
        for row in events_frame.to_dict(orient="records"):
            eid = str(row["event_id"])
            if not session.get(EventModel, eid):
                session.add(EventModel(
                    event_id=eid,
                    person_id=str(row["person_id"]) if pd.notna(row.get("person_id")) else None,
                    event_type=str(row["event_type"]),
                    location_id=str(row["location_id"]) if pd.notna(row.get("location_id")) else None,
                    vehicle_id=str(row["vehicle_id"]) if pd.notna(row.get("vehicle_id")) else None,
                    organization_id=str(row["organization_id"]) if pd.notna(row.get("organization_id")) else None,
                    timestamp=str(row["timestamp"]),
                    case_id=str(row["case_id"]) if pd.notna(row.get("case_id")) else None,
                    source=str(row["source"]) if pd.notna(row.get("source")) else None,
                    confidence=str(row["confidence"]) if pd.notna(row.get("confidence")) else None,
                    source_type=str(row.get("source_type", "synthetic")),
                    source_file=str(row.get("source_file", "events.csv")),
                    source_case=str(row.get("source_case", "")),
                ))
        summary["events"] = len(events_frame)

        # 14. Seed Default Users
        demo_password = os.environ.get("II_DEMO_PASSWORD", "DemoPass!2026")
        default_users = [
            ("demo_investigator", "Investigator"),
            ("demo_forensic", "Forensic Officer"),
            ("demo_admin", "Administrator"),
        ]
        users_added = 0
        for username, role in default_users:
            if not session.get(UserModel, username):
                password_hash = _hash_password(demo_password)
                session.add(UserModel(
                    username=username,
                    role=role,
                    password_hash=password_hash,
                    totp_secret=_new_secret(),
                    mfa_enrolled=False,
                ))
                users_added += 1
        summary["users"] = len(default_users)

        # 15. Dataset Metadata & Ingestion History
        now_str = datetime.now(timezone.utc).isoformat(timespec="seconds")
        total_records = sum(summary[k] for k in summary if k not in {"users"})
        meta = session.get(DatasetMetadataModel, "synthetic-demo")
        if not meta:
            session.add(DatasetMetadataModel(
                dataset_id="synthetic-demo",
                source="synthetic",
                version=1,
                created_at=now_str,
                updated_at=now_str,
                record_count=total_records,
                status="active",
                validation_status="Validated",
            ))
        else:
            meta.record_count = total_records
            meta.updated_at = now_str

        session.add(AuditEventModel(
            timestamp=now_str,
            user="system",
            action="DATASET_SEED",
            resource="synthetic-demo",
            status="Success",
            metadata_json={"records": summary},
        ))

    logger.info("Successfully seeded PostgreSQL database with records: %s", summary)
    return summary


def _clear_tables(session: Session) -> None:
    """Clear tables in reverse dependency order."""
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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    force_flag = "--force" in sys.argv
    try:
        results = seed_database(force=force_flag)
        print("Database seeded successfully!")
        for entity, count in results.items():
            print(f"  {entity}: {count} records")
    except Exception as error:
        print(f"Seeding failed: {error}", file=sys.stderr)
        sys.exit(1)
