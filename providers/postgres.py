"""PostgreSQL data provider implementing the canonical DataProvider contract."""

import logging
from typing import Any

import pandas as pd
from sqlalchemy import inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from database.connection import get_engine, get_session_factory, mask_database_url, session_scope
from database.models import (
    AccountModel,
    CallModel,
    CaseModel,
    EventModel,
    LocationModel,
    MessageModel,
    OrganizationModel,
    PersonModel,
    PhoneModel,
    TransactionModel,
    VehicleModel,
)
from domain.models import DatasetSnapshot, DataSourceInfo, DataSourceType, ValidationResult
from providers.base import DataProvider
from providers.synthetic import CSV_SCHEMAS

logger = logging.getLogger(__name__)

TABLE_MODEL_MAP = {
    "persons": PersonModel,
    "phones": PhoneModel,
    "calls": CallModel,
    "messages": MessageModel,
    "transactions": TransactionModel,
    "locations": LocationModel,
    "vehicles": VehicleModel,
    "organizations": OrganizationModel,
    "accounts": AccountModel,
    "events": EventModel,
}


class PostgresDataProvider(DataProvider):
    """PostgreSQL implementation exposing canonical snapshots for graph analytics and services."""

    def __init__(
        self,
        database_url_or_engine: str | Engine | None = None,
        source_name: str = "PostgreSQL Investigation Database",
    ) -> None:
        if isinstance(database_url_or_engine, Engine):
            self.engine = database_url_or_engine
        else:
            self.engine = get_engine(database_url_or_engine)

        self.session_factory = get_session_factory(self.engine)
        self._source = DataSourceInfo(
            source_type=DataSourceType.DATABASE,
            name=source_name,
            location=None,
        )

    def get_source_info(self) -> DataSourceInfo:
        return self._source

    def validate(self) -> ValidationResult:
        errors: list[str] = []
        checked: list[str] = ["cases"] + list(TABLE_MODEL_MAP.keys())

        try:
            inspector = inspect(self.engine)
            existing_tables = set(inspector.get_table_names())
            missing_tables = (set(TABLE_MODEL_MAP.keys()) | {"cases"}) - existing_tables
            if missing_tables:
                return ValidationResult(
                    valid=False,
                    checked_files=tuple(sorted(checked)),
                    errors=tuple(f"Missing required database table: {tbl}" for tbl in sorted(missing_tables)),
                )

            with session_scope(self.session_factory) as session:
                cases = session.scalars(select(CaseModel)).all()
                if not cases:
                    errors.append("cases table contains no records")
                case_ids = {c.case_id for c in cases if c.case_id}

                persons = session.scalars(select(PersonModel)).all()
                phones = session.scalars(select(PhoneModel)).all()
                locations = session.scalars(select(LocationModel)).all()
                vehicles = session.scalars(select(VehicleModel)).all()
                orgs = session.scalars(select(OrganizationModel)).all()
                accounts = session.scalars(select(AccountModel)).all()
                calls = session.scalars(select(CallModel)).all()
                messages = session.scalars(select(MessageModel)).all()
                transactions = session.scalars(select(TransactionModel)).all()
                events = session.scalars(select(EventModel)).all()

                person_ids = {p.person_id for p in persons if p.person_id}
                phone_ids = {ph.phone_id for ph in phones if ph.phone_id}
                location_ids = {loc.location_id for loc in locations if loc.location_id}
                vehicle_ids = {v.vehicle_id for v in vehicles if v.vehicle_id}
                org_ids = {o.organization_id for o in orgs if o.organization_id}
                account_ids = {acc.account_id for acc in accounts if acc.account_id}

                # Validate foreign reference integrity
                for p in persons:
                    if p.case_ids:
                        for cid in (item.strip() for item in p.case_ids.split("|") if item.strip()):
                            if cid not in case_ids:
                                errors.append(f"persons.case_ids references unknown case_id: {cid}")

                for o in orgs:
                    if o.case_ids:
                        for cid in (item.strip() for item in o.case_ids.split("|") if item.strip()):
                            if cid not in case_ids:
                                errors.append(f"organizations.case_ids references unknown case_id: {cid}")

                for ph in phones:
                    if ph.owner_person_id and ph.owner_person_id not in person_ids:
                        errors.append(f"phones.owner_person_id references unknown person_id: {ph.owner_person_id}")

                for c in calls:
                    if c.caller_id and c.caller_id not in phone_ids:
                        errors.append(f"calls.caller_id references unknown phone_id: {c.caller_id}")
                    if c.receiver_id and c.receiver_id not in phone_ids:
                        errors.append(f"calls.receiver_id references unknown phone_id: {c.receiver_id}")

                for m in messages:
                    if m.sender_phone_id and m.sender_phone_id not in phone_ids:
                        errors.append(f"messages.sender_phone_id references unknown phone_id: {m.sender_phone_id}")
                    if m.receiver_phone_id and m.receiver_phone_id not in phone_ids:
                        errors.append(f"messages.receiver_phone_id references unknown phone_id: {m.receiver_phone_id}")

                for t in transactions:
                    if t.from_account and t.from_account not in account_ids:
                        errors.append(f"transactions.from_account references unknown account_id: {t.from_account}")
                    if t.to_account and t.to_account not in account_ids:
                        errors.append(f"transactions.to_account references unknown account_id: {t.to_account}")

                for v in vehicles:
                    if v.owner_person_id and v.owner_person_id not in person_ids:
                        errors.append(f"vehicles.owner_person_id references unknown person_id: {v.owner_person_id}")

                for acc in accounts:
                    if acc.owner_person_id and acc.owner_person_id not in person_ids:
                        errors.append(f"accounts.owner_person_id references unknown person_id: {acc.owner_person_id}")
                    if acc.organization_id and acc.organization_id not in org_ids:
                        errors.append(f"accounts.organization_id references unknown organization_id: {acc.organization_id}")

                for ev in events:
                    if ev.person_id and ev.person_id not in person_ids:
                        errors.append(f"events.person_id references unknown person_id: {ev.person_id}")
                    if ev.location_id and ev.location_id not in location_ids:
                        errors.append(f"events.location_id references unknown location_id: {ev.location_id}")
                    if ev.vehicle_id and ev.vehicle_id not in vehicle_ids:
                        errors.append(f"events.vehicle_id references unknown vehicle_id: {ev.vehicle_id}")
                    if ev.organization_id and ev.organization_id not in org_ids:
                        errors.append(f"events.organization_id references unknown organization_id: {ev.organization_id}")

        except Exception as error:
            masked = mask_database_url(str(self.engine.url))
            errors.append(f"Database validation error on {masked}: {error}")

        return ValidationResult(
            valid=not errors,
            checked_files=tuple(sorted(checked)),
            errors=tuple(errors),
        )

    def load_snapshot(self) -> DatasetSnapshot:
        validation = self.validate()
        if not validation.valid:
            raise ValueError("PostgreSQL dataset validation failed: " + "; ".join(validation.errors))

        tables: dict[str, pd.DataFrame] = {}
        documents: dict[str, Any] = {}

        with session_scope(self.session_factory) as session:
            for table_name, model_cls in TABLE_MODEL_MAP.items():
                rows = session.scalars(select(model_cls)).all()
                data = [
                    {col.name: getattr(r, col.name) for col in model_cls.__table__.columns}
                    for r in rows
                ]
                schema_cols = CSV_SCHEMAS.get(f"{table_name}.csv", ())
                if data:
                    df = pd.DataFrame(data)
                    cols = [c for c in schema_cols if c in df.columns]
                    extra_cols = [c for c in df.columns if c not in schema_cols]
                    tables[table_name] = df[cols + extra_cols]
                else:
                    tables[table_name] = pd.DataFrame(columns=list(schema_cols))

            cases = session.scalars(select(CaseModel)).all()
            documents["cases"] = [
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
                for c in cases
            ]

        return DatasetSnapshot(tables=tables, documents=documents, source=self._source)
