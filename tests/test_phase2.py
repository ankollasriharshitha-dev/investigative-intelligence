"""Phase-2 local prototype tests: no PostgreSQL or external service required."""

from pathlib import Path
import json

import pytest

from config.settings import Settings, get_settings
from providers.synthetic import SyntheticDataProvider
from services.investigation import InvestigationService
from services.security import AuthorizationError, User, _totp


def phase2_service(tmp_path) -> InvestigationService:
    settings = Settings(tmp_path, get_settings().synthetic_data_dir, tmp_path / "uploads", tmp_path / "runtime")
    return InvestigationService(SyntheticDataProvider(settings.synthetic_data_dir), settings)


def authenticate(service: InvestigationService) -> User:
    user = service.security.verify_password("demo_investigator", "DemoPass!2026")
    assert user is not None
    if not user.mfa_enrolled:
        assert service.security.complete_totp_enrollment(user, _totp(user.totp_secret))
        user = service.security.get_user(user.username)
    assert service.security.verify_totp(user, _totp(user.totp_secret))
    return user


def test_password_totp_and_permission_boundary(tmp_path) -> None:
    service = phase2_service(tmp_path)
    assert service.security.verify_password("demo_investigator", "wrong") is None
    user = service.security.verify_password("demo_investigator", "DemoPass!2026")
    assert user is not None and not user.mfa_enrolled
    assert user.password_hash != "DemoPass!2026"
    assert not service.security.verify_totp(user, _totp(user.totp_secret))
    assert not service.security.complete_totp_enrollment(user, "000000")
    assert service.security.complete_totp_enrollment(user, _totp(user.totp_secret))
    user = service.security.get_user("demo_investigator")
    assert not service.security.verify_totp(user, "000000")
    assert service.security.verify_totp(user, _totp(user.totp_secret))
    with pytest.raises(AuthorizationError):
        service.require_permission(user, "audit:view")


def test_case_evidence_hash_ledger_and_audit_end_to_end(tmp_path) -> None:
    service = phase2_service(tmp_path)
    user = authenticate(service)
    service.create_case("CASE900", "Synthetic uploaded review", "test", "2026-09-16", "High", user)
    evidence = service.upload_evidence("CASE900", "review.txt", b"Arun Vale contacted 9876543210 on 12 August 2026. Vehicle AP21AB1234 was observed near Vijayawada.", user)

    assert evidence["evidence_id"] == "EVD-0001"
    assert len(evidence["sha256"]) == 64
    assert {item["type"] for item in evidence["detected_entities"]} >= {"Person", "Phone", "Vehicle", "Date"}
    assert any(match["target_case"] in {"CASE001", "CASE002"} for match in evidence["potential_matches"])
    assert service.build_active_graph().nodes[evidence["evidence_id"]]["entity_type"] == "EVIDENCE"

    forensic = service.security.verify_password("demo_forensic", "DemoPass!2026")
    assert forensic and service.security.complete_totp_enrollment(forensic, _totp(forensic.totp_secret))
    forensic = service.security.get_user("demo_forensic")
    assert service.security.verify_totp(forensic, _totp(forensic.totp_secret))
    assert service.verify_evidence(evidence["evidence_id"], forensic)["integrity_status"] == "VERIFIED"
    assert service.verify_ledger(forensic)["status"] == "LEDGER VALID"
    actions = {event["action"] for event in service.audit.events()}
    assert {"LOGIN", "MFA_VERIFICATION", "CASE_CREATION", "EVIDENCE_UPLOAD", "ENTITY_ANALYSIS", "EVIDENCE_VERIFICATION", "LEDGER_VERIFICATION"} <= actions


def test_evidence_tampering_is_detected(tmp_path) -> None:
    service = phase2_service(tmp_path)
    user = authenticate(service)
    service.create_case("CASE901", "Integrity test", "", "2026-09-16", "Low", user)
    evidence = service.upload_evidence("CASE901", "note.txt", b"Synthetic evidence", user)
    Path(evidence["path"]).write_bytes(b"modified")
    forensic = service.security.get_user("demo_forensic")
    assert service.security.complete_totp_enrollment(forensic, _totp(forensic.totp_secret))
    assert service.verify_evidence(evidence["evidence_id"], forensic)["integrity_status"] == "INTEGRITY MISMATCH"


def test_ledger_tampering_is_detected(tmp_path) -> None:
    service = phase2_service(tmp_path)
    user = authenticate(service)
    service.create_case("CASE903", "Ledger test", "", "2026-09-16", "Low", user)
    service.upload_evidence("CASE903", "note.txt", b"Synthetic evidence", user)
    ledger_path = service.evidence.ledger_path
    blocks = json.loads(ledger_path.read_text(encoding="utf-8")); blocks[0]["sha256"] = "tampered"
    ledger_path.write_text(json.dumps(blocks), encoding="utf-8")
    forensic = service.security.get_user("demo_forensic")
    assert service.security.complete_totp_enrollment(forensic, _totp(forensic.totp_secret))
    assert service.verify_ledger(forensic)["status"] == "LEDGER TAMPERED"


def test_invalid_upload_is_rejected(tmp_path) -> None:
    service = phase2_service(tmp_path)
    user = authenticate(service)
    service.create_case("CASE902", "Upload validation", "", "2026-09-16", "Low", user)
    with pytest.raises(ValueError, match="Unsupported"):
        service.upload_evidence("CASE902", "malware.exe", b"x", user)
    with pytest.raises(ValueError, match="empty"):
        service.upload_evidence("CASE902", "empty.txt", b"", user)
