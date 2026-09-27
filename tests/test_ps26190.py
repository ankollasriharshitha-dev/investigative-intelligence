"""Comprehensive test suite for SIH PS 26190:
Secure Digital Document Management System for Legal and Investigation Documents.
"""

from pathlib import Path
import pytest

from config.settings import Settings, get_settings
from providers.synthetic import SyntheticDataProvider
from services.investigation import InvestigationService
from services.security import AuthorizationError, User, _totp


def create_test_service(tmp_path: Path) -> InvestigationService:
    settings = Settings(
        tmp_path,
        get_settings().synthetic_data_dir,
        tmp_path / "uploads",
        tmp_path / "runtime",
    )
    return InvestigationService(SyntheticDataProvider(settings.synthetic_data_dir), settings)


def authenticate_user(service: InvestigationService, username: str) -> User:
    user = service.security.verify_password(username, "DemoPass!2026")
    assert user is not None
    if not user.mfa_enrolled:
        assert service.security.complete_totp_enrollment(user, _totp(user.totp_secret))
        user = service.security.get_user(username)
    assert service.security.verify_totp(user, _totp(user.totp_secret))
    return user


def test_document_intake_with_metadata_and_integrity_hashing(tmp_path: Path) -> None:
    service = create_test_service(tmp_path)
    investigator = authenticate_user(service, "demo_investigator")

    # 1. Create a legal investigation case
    case = service.create_case(
        case_id="CR-2026-101",
        title="Securities & Financial Irregularities Inquiry",
        description="Investigation into unauthorized electronic transactions and fund diversions.",
        date="2026-09-20",
        priority="High",
        user=investigator,
        department="Economic Offences Wing",
        investigating_officer="Insp. Arun Vale",
    )
    assert case["case_id"] == "CR-2026-101"
    assert case["department"] == "Economic Offences Wing"

    # 2. Upload legal document (FIR / Police Report)
    fir_content = b"FIRST INFORMATION REPORT (Under Section 154 Cr.P.C.)\nPolice Station: Cyber Crime Cell\nComplainant: Axis Digital Banking Unit\nIncident: Unauthorized API token access."
    doc = service.upload_document(
        case_id="CR-2026-101",
        filename="FIR_0042_2026.txt",
        content=fir_content,
        user=investigator,
        document_type="FIR / Police Report",
        title="Initial First Information Report",
        department="Cyber Crime Cell",
        classification="Confidential",
        description="Formal FIR registered upon initial bank disclosure",
        status="Submitted",
    )

    assert doc["document_id"] == "DOC-0001"
    assert doc["case_id"] == "CR-2026-101"
    assert doc["document_type"] == "FIR / Police Report"
    assert doc["current_version"] == 1
    assert doc["classification"] == "Confidential"
    assert len(doc["sha256"]) == 64
    assert doc["integrity_status"] == "VERIFIED"
    assert len(doc["versions"]) == 1
    assert doc["versions"][0]["version_number"] == 1

    # 3. Verify integrity verification check returns VERIFIED
    verify_report = service.verify_document_integrity(doc["document_id"], investigator)
    assert verify_report["integrity_status"] == "VERIFIED"
    assert verify_report["verified"] is True
    assert verify_report["current_sha256"] == doc["sha256"]


def test_document_version_control(tmp_path: Path) -> None:
    service = create_test_service(tmp_path)
    investigator = authenticate_user(service, "demo_investigator")

    service.create_case("CASE-VER-01", "Forensic Device Examination", "Mobile device seizure", "2026-09-21", "Medium", investigator)

    # Version 1
    v1_bytes = b"Preliminary Witness Statement - Interview with Roommate. Statement recorded on 21 Sep 2026."
    doc = service.upload_document(
        case_id="CASE-VER-01",
        filename="Witness_Statement_01.txt",
        content=v1_bytes,
        user=investigator,
        document_type="Witness Statement",
        title="Witness Statement of Roommate",
    )
    v1_hash = doc["sha256"]
    assert doc["current_version"] == 1

    # Version 2
    v2_bytes = b"Supplementary Witness Statement - Corroborated with call records and parking receipts on 22 Sep 2026."
    updated = service.upload_document_version(
        document_id=doc["document_id"],
        filename="Witness_Statement_01_revised.txt",
        content=v2_bytes,
        user=investigator,
        change_summary="Added corroborating parking gate ticket timestamps",
    )

    assert updated["current_version"] == 2
    assert updated["sha256"] != v1_hash
    assert len(updated["versions"]) == 2
    assert updated["versions"][0]["version_number"] == 1
    assert updated["versions"][0]["sha256"] == v1_hash
    assert updated["versions"][1]["version_number"] == 2
    assert updated["versions"][1]["change_summary"] == "Added corroborating parking gate ticket timestamps"

    # Both versions are verifiable
    assert service.verify_document_integrity(doc["document_id"], investigator, version_number=1)["verified"] is True
    assert service.verify_document_integrity(doc["document_id"], investigator, version_number=2)["verified"] is True


def test_tamper_detection_and_ledger_validation(tmp_path: Path) -> None:
    service = create_test_service(tmp_path)
    investigator = authenticate_user(service, "demo_investigator")

    service.create_case("CASE-TMP-01", "Tamper Assurance Test", "Integrity testing", "2026-09-22", "High", investigator)
    doc = service.upload_document(
        case_id="CASE-TMP-01",
        filename="Charge_Sheet_Draft.txt",
        content=b"Draft Charge Sheet under IPC Sections 420 and 120B.",
        user=investigator,
        document_type="Charge Sheet",
    )

    # Initial verification passes
    initial = service.verify_document_integrity(doc["document_id"], investigator)
    assert initial["integrity_status"] == "VERIFIED"

    # Simulate unauthorized file tampering
    tampered_report = service.simulate_document_tampering(doc["document_id"], investigator)
    assert tampered_report["integrity_status"] == "INTEGRITY MISMATCH"
    assert tampered_report["verified"] is False
    assert tampered_report["current_sha256"] != doc["sha256"]

    # Restore from clean backup
    restored_report = service.restore_document_tampering(doc["document_id"], investigator)
    assert restored_report["integrity_status"] == "VERIFIED"
    assert restored_report["verified"] is True

    # Ledger verification
    ledger_report = service.documents.verify_ledger(investigator.username)
    assert ledger_report["valid"] is True
    assert "LEDGER VALID" in ledger_report["status"]


def test_search_and_retrieval(tmp_path: Path) -> None:
    service = create_test_service(tmp_path)
    investigator = authenticate_user(service, "demo_investigator")

    service.create_case("CASE-SRC-01", "Narcotics Seizure Operation", "Contraband recovery", "2026-09-23", "Critical", investigator)
    service.create_case("CASE-SRC-02", "Cyber Extortion Network", "Ransomware demands", "2026-09-23", "High", investigator)

    service.upload_document(
        case_id="CASE-SRC-01",
        filename="Forensic_Lab_Report_44.txt",
        content=b"Chemical analysis confirmed substance purity 92 percent. Spectrometry completed.",
        user=investigator,
        document_type="Forensic Report",
        title="Chemical Analysis Report",
    )
    service.upload_document(
        case_id="CASE-SRC-02",
        filename="Court_Bail_Opposition_Brief.txt",
        content=b"Petition opposing bail application of accused citing flight risk and digital evidence destruction.",
        user=investigator,
        document_type="Court Filing",
        title="Bail Opposition Brief",
    )

    # Search by keyword
    results_chem = service.search_documents(query="Spectrometry")
    assert len(results_chem) == 1
    assert results_chem[0]["document_type"] == "Forensic Report"

    # Search by document type
    results_court = service.search_documents(document_type="Court Filing")
    assert len(results_court) == 1
    assert results_court[0]["case_id"] == "CASE-SRC-02"

    # Search by case ID
    results_case1 = service.search_documents(case_id="CASE-SRC-01")
    assert len(results_case1) == 1


def test_rbac_boundaries_for_different_roles(tmp_path: Path) -> None:
    service = create_test_service(tmp_path)
    investigator = authenticate_user(service, "demo_investigator")
    auditor = authenticate_user(service, "demo_auditor")
    reviewer = authenticate_user(service, "demo_reviewer")

    # Investigator creates case and uploads document
    service.create_case("CASE-RBAC-01", "RBAC Boundary Test", "Testing role limits", "2026-09-24", "Low", investigator)
    doc = service.upload_document(
        case_id="CASE-RBAC-01",
        filename="Investigation_Record_01.txt",
        content=b"Interrogation notes of primary suspect.",
        user=investigator,
        document_type="Investigation Record",
        status="Submitted",
    )

    # Auditor is strictly read-only for uploads and edits
    with pytest.raises(AuthorizationError):
        service.upload_document("CASE-RBAC-01", "Audit_Note.txt", b"Test", auditor)

    with pytest.raises(AuthorizationError):
        service.upload_document_version(doc["document_id"], "Audit_Note_v2.txt", b"Test", auditor)

    # Auditor CAN verify integrity and view audit trail
    audit_events = service.audit.events()
    assert len(audit_events) > 0
    verify_res = service.verify_document_integrity(doc["document_id"], auditor)
    assert verify_res["verified"] is True

    # Reviewer approves document
    approved_doc = service.update_document_status(doc["document_id"], "Approved", reviewer, notes="Approved after legal vetting")
    assert approved_doc["status"] == "Approved"
    assert any(h["status"] == "Approved" and h["by"] == "demo_reviewer" for h in approved_doc["approval_history"])

    # Document sharing records collaboration event
    shared_doc = service.share_document(doc["document_id"], "demo_legal", "View + Download", investigator, "Shared for court briefing")
    assert any(s["target"] == "demo_legal" for s in shared_doc["shared_with"])

    # Verify audit trail recorded all these actions
    actions = {e["action"] for e in service.audit.events()}
    assert {
        "CASE_CREATION",
        "DOCUMENT_UPLOAD",
        "DOCUMENT_APPROVAL",
        "DOCUMENT_SHARE",
        "INTEGRITY_VERIFICATION",
    } <= actions
