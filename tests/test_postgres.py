"""Comprehensive tests for PostgreSQL schema, provider, repositories, and graph analytics."""

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from config.settings import Settings, get_settings
from database.connection import mask_database_url, normalize_database_url, test_connection as check_db_connection
from database.models import Base, CaseModel, UserModel
from database.schema import get_table_counts, init_db
from database.seed import seed_database
from domain.models import DataSourceType
from graph.analytics import GraphAnalytics
from graph.builder import InvestigationGraphBuilder
from providers.postgres import PostgresDataProvider
from repositories.postgres import PostgresDatasetRepository
from services.investigation import InvestigationService
from services.security import AuthorizationError, _totp


@pytest.fixture
def db_engine(tmp_path):
    """Provide a clean in-memory SQLite database instance behaving with SQLAlchemy standard dialect."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    return engine


@pytest.fixture
def seeded_engine(db_engine):
    seed_database(engine=db_engine, synthetic_data_dir=get_settings().synthetic_data_dir)
    return db_engine


def test_url_masking_and_normalization():
    url = "postgresql://myuser:secret_pass@db.internal:5432/investigations"
    masked = mask_database_url(url)
    assert "secret_pass" not in masked
    assert "myuser:***@db.internal:5432" in masked

    normalized = normalize_database_url(url)
    assert normalized.startswith("postgresql+psycopg2://")


def test_db_connection_failure_handling():
    ok, msg = check_db_connection("postgresql+psycopg2://invalid:pass@127.0.0.1:59999/nonexistent")
    assert not ok
    assert "Could not connect to database" in msg
    assert "pass@" not in msg  # Ensure password is not exposed


def test_schema_creation_and_tables(db_engine):
    counts = get_table_counts(db_engine)
    expected_tables = {
        "cases", "persons", "phones", "calls", "messages",
        "transactions", "locations", "vehicles", "organizations",
        "accounts", "events", "users", "evidence", "evidence_ledger",
        "case_entities", "case_matches", "audit_events",
        "dataset_metadata", "ingestion_history"
    }
    assert expected_tables.issubset(counts.keys())
    assert all(count == 0 for count in counts.values())


def test_database_seed_populates_canonical_data(seeded_engine):
    counts = get_table_counts(seeded_engine)
    assert counts["cases"] == 3
    assert counts["persons"] == 18
    assert counts["phones"] == 10
    assert counts["vehicles"] == 6
    assert counts["locations"] == 6
    assert counts["organizations"] == 4
    assert counts["accounts"] == 10
    assert counts["calls"] == 16
    assert counts["messages"] == 10
    assert counts["transactions"] == 12
    assert counts["events"] == 22
    assert counts["users"] == 3


def test_postgres_data_provider_validation_and_snapshot(seeded_engine):
    provider = PostgresDataProvider(seeded_engine)
    info = provider.get_source_info()
    assert info.source_type is DataSourceType.DATABASE

    validation = provider.validate()
    assert validation.valid
    assert len(validation.errors) == 0

    snapshot = provider.load_snapshot()
    assert len(snapshot.documents["cases"]) == 3
    assert set(snapshot.tables.keys()) == {
        "accounts", "calls", "events", "locations", "messages",
        "organizations", "persons", "phones", "transactions", "vehicles"
    }
    assert len(snapshot.tables["persons"]) == 18
    assert len(snapshot.tables["calls"]) == 16


def test_postgres_snapshot_builds_exact_network_graph(seeded_engine):
    provider = PostgresDataProvider(seeded_engine)
    snapshot = provider.load_snapshot()
    builder = InvestigationGraphBuilder()
    graph = builder.build(snapshot)

    assert graph.number_of_nodes() == 57
    assert graph.number_of_edges() == 134
    assert graph.nodes["P001"]["entity_type"] == "PERSON"
    assert graph.nodes["CASE001"]["entity_type"] == "CASE"
    assert "CALLED" in graph["PH001"]["PH002"]["relationship_types"]


def test_postgres_graph_analytics(seeded_engine):
    provider = PostgresDataProvider(seeded_engine)
    snapshot = provider.load_snapshot()
    analytics = GraphAnalytics(InvestigationGraphBuilder().build(snapshot))

    centrality = analytics.centrality()
    assert len(centrality) == 57
    assert centrality[0]["degree"] >= centrality[-1]["degree"]
    assert analytics.shortest_path("P001", "P010") is not None
    assert len(analytics.connected_components()) == 2
    assert len(analytics.cross_case_entities()) == 9
    assert len(analytics.leads()) > 0


def test_postgres_investigation_service_workflow(seeded_engine, tmp_path):
    provider = PostgresDataProvider(seeded_engine)
    settings = Settings(
        project_root=tmp_path,
        synthetic_data_dir=get_settings().synthetic_data_dir,
        uploads_data_dir=tmp_path / "uploads",
        runtime_data_dir=tmp_path / "runtime",
        data_provider="postgres",
        database_url="sqlite://",
    )
    service = InvestigationService(provider, settings)

    stats = service.dashboard_statistics()
    assert stats["cases"] == 3
    assert stats["persons"] == 18
    assert stats["relationships"] == 60

    net_stats = service.network_statistics()
    assert net_stats["nodes"] == 57
    assert net_stats["relationships"] == 134

    # Test Auth against Database
    user = service.security.verify_password("demo_investigator", "DemoPass!2026")
    assert user is not None
    assert not user.mfa_enrolled
    assert service.security.complete_totp_enrollment(user, _totp(user.totp_secret))
    user = service.security.get_user("demo_investigator")
    assert user.mfa_enrolled
    assert service.security.verify_totp(user, _totp(user.totp_secret))

    # Test Case Creation
    created_case = service.create_case("CASE-PG01", "PostgreSQL Case", "DB integration test", "2026-09-20", "High", user)
    assert created_case["case_id"] == "CASE-PG01"
    assert any(c["case_id"] == "CASE-PG01" for c in service.cases.cases())

    # Test Evidence Upload & SHA-256 & Ledger in DB
    evidence = service.upload_evidence(
        "CASE-PG01",
        "evidence_note.txt",
        b"Suspect Arun Vale contacted 9876543210 regarding vehicle AP21AB1234 near Vijayawada.",
        user,
    )
    assert evidence["evidence_id"] == "EVD-0001"
    assert len(evidence["sha256"]) == 64
    assert evidence["block_id"] == "BLOCK-0001"

    # Test Verification and Ledger
    forensic = service.security.verify_password("demo_forensic", "DemoPass!2026")
    assert forensic and service.security.complete_totp_enrollment(forensic, _totp(forensic.totp_secret))
    forensic = service.security.get_user("demo_forensic")
    ver_ev = service.verify_evidence(evidence["evidence_id"], forensic)
    assert ver_ev["integrity_status"] == "VERIFIED"

    ver_ledger = service.verify_ledger(forensic)
    assert ver_ledger["status"] == "LEDGER VALID"

    # Test Audit Trail
    audit_events = service.audit.events()
    assert len(audit_events) >= 5
    actions = {e["action"] for e in audit_events}
    assert {"LOGIN", "MFA_VERIFICATION", "CASE_CREATION", "EVIDENCE_UPLOAD"}.issubset(actions)


def test_postgres_dataset_repository_upsert(seeded_engine):
    repo = PostgresDatasetRepository(seeded_engine)
    snapshot = repo.load_snapshot()
    initial_count = len(snapshot.tables["persons"])
    assert initial_count == 18

    # Modify snapshot and test append
    new_person = snapshot.tables["persons"].iloc[0:1].copy()
    new_person["person_id"] = "P999"
    new_person["name"] = "Database Test Person"
    snapshot.tables["persons"] = new_person

    added, updated, skipped = repo.upsert(snapshot, operation="append")
    assert added >= 1

    reloaded = repo.load_snapshot()
    assert len(reloaded.tables["persons"]) == 19
    assert any(p["person_id"] == "P999" for p in reloaded.tables["persons"].to_dict(orient="records"))


def test_postgres_evidence_tampering_detection(seeded_engine, tmp_path):
    provider = PostgresDataProvider(seeded_engine)
    settings = Settings(
        project_root=tmp_path,
        synthetic_data_dir=get_settings().synthetic_data_dir,
        uploads_data_dir=tmp_path / "uploads",
        runtime_data_dir=tmp_path / "runtime",
        data_provider="postgres",
        database_url="sqlite://",
    )
    service = InvestigationService(provider, settings)
    user = service.security.verify_password("demo_investigator", "DemoPass!2026")
    service.security.complete_totp_enrollment(user, _totp(user.totp_secret))
    user = service.security.get_user("demo_investigator")

    service.create_case("CASE-TMP01", "Tamper Test", "", "2026-09-20", "Low", user)
    evidence = service.upload_evidence("CASE-TMP01", "note.txt", b"Original content", user)

    # Modify file on disk
    Path(evidence["path"]).write_bytes(b"Modified content")

    forensic = service.security.verify_password("demo_forensic", "DemoPass!2026")
    service.security.complete_totp_enrollment(forensic, _totp(forensic.totp_secret))
    forensic = service.security.get_user("demo_forensic")

    ver = service.verify_evidence(evidence["evidence_id"], forensic)
    assert ver["integrity_status"] == "INTEGRITY MISMATCH"


def test_postgres_user_rbac_permissions(seeded_engine, tmp_path):
    provider = PostgresDataProvider(seeded_engine)
    settings = Settings(
        project_root=tmp_path,
        synthetic_data_dir=get_settings().synthetic_data_dir,
        uploads_data_dir=tmp_path / "uploads",
        runtime_data_dir=tmp_path / "runtime",
        data_provider="postgres",
        database_url="sqlite://",
    )
    service = InvestigationService(provider, settings)
    user = service.security.verify_password("demo_investigator", "DemoPass!2026")

    # Investigator has case:create but not audit:view
    service.require_permission(user, "case:create")
    with pytest.raises(AuthorizationError):
        service.require_permission(user, "audit:view")
