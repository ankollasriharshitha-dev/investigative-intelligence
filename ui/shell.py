"""Streamlit presentation shell for PS 26190:
Secure Digital Document Management System for Legal and Investigation Documents,
with PS 26189 Advanced Investigation Intelligence layer.
"""

from io import BytesIO
from pathlib import Path
import json

import pandas as pd
import streamlit as st

from graph.analytics import GraphAnalytics
from graph.presentation import filter_graph, network_figure
from services.data_management import DatasetStorageError
from services.document_management import CLASSIFICATIONS, DOCUMENT_TYPES, STATUSES
from services.investigation import InvestigationService
from services.security import ALL_ROLES, AuthorizationError, User, _totp


MODULES = (
    "Dashboard",
    "Cases",
    "Documents",
    "Search",
    "Audit Trail",
    "Integrity Verification",
    "Users & Permissions",
    "Advanced Investigation Intelligence",
)


def render_application(service: InvestigationService) -> None:
    st.set_page_config(
        page_title="Secure Investigation & Legal Document Management System",
        page_icon="🛡️",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _apply_styles()

    user = _authenticated_user(service)
    if not user:
        _render_login(service)
        return

    source, validation = service.active_source(), service.validate_active_dataset()

    # Sidebar Header
    st.sidebar.markdown(
        """
        <div style="display:flex; align-items:center; gap:10px; margin-bottom:12px;">
            <div class="brand-mark">🛡️</div>
            <div>
                <div style="font-size:0.95rem; font-weight:700; color:#42b9c6; letter-spacing:0.04em;">SECURE DMS</div>
                <div style="font-size:0.68rem; color:#8b9aaa; letter-spacing:0.08em;">LEGAL & INVESTIGATION</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.sidebar.caption("SIH PS 26190 · Core Document Management Platform")

    page = st.sidebar.radio("Navigation", MODULES, label_visibility="collapsed")

    st.sidebar.divider()

    # User Profile & Session Info
    st.sidebar.caption("ACTIVE USER SESSION")
    st.sidebar.markdown(
        f"""
        <div class="user-badge">
            <div style="font-weight:600; font-size:0.85rem; color:#e6edf3;">👤 {user.username}</div>
            <div style="font-size:0.75rem; color:#42b9c6; font-weight:500;">{user.role}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.sidebar.button("🚪 Logout", use_container_width=True):
        if service.audit:
            service.audit.record(user.username, "LOGOUT", "session", "Success")
        for key in ("authenticated_user", "pending_user", "selected_doc_id", "selected_case_id"):
            st.session_state.pop(key, None)
        st.rerun()

    st.sidebar.divider()
    st.sidebar.caption("SYSTEM STATUS")
    if validation.valid:
        st.sidebar.success("Security & Data Validated")
    else:
        st.sidebar.warning("Attention Required")
    st.sidebar.caption("PS 26189 Intelligence Layer: Active")

    pages = {
        "Dashboard": _dashboard,
        "Cases": _cases,
        "Documents": _documents,
        "Search": _search,
        "Audit Trail": _audit,
        "Integrity Verification": _integrity,
        "Users & Permissions": _users_and_permissions,
        "Advanced Investigation Intelligence": _advanced_intelligence,
    }

    try:
        pages[page](service, user)
    except AuthorizationError as error:
        st.error(f"Access Denied: {error}")
    except (DatasetStorageError, ValueError, KeyError, IndexError) as error:
        st.error("Operation could not be completed.")
        st.caption(f"Technical detail: {error}")


def _authenticated_user(service: InvestigationService) -> User | None:
    username = st.session_state.get("authenticated_user")
    return service.security.get_user(username) if username and service.security else None


def _render_login(service: InvestigationService) -> None:
    st.markdown(
        """
        <div class="login-shell">
            <div style="font-size:2.6rem; margin-bottom:0.5rem;">🛡️</div>
            <h1 style="margin:0 0 0.25rem; font-size:1.8rem; color:#e6edf3;">Secure Digital Document Management System</h1>
            <p style="color:#8b9aaa; font-size:0.95rem; margin:0 0 1.5rem;">Legal & Investigation Document Assurance Platform · SIH PS 26190</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Demo Quick Login Selector for Judges & Evaluators
    with st.container(border=True):
        st.markdown("### 🚀 Fast Demo Access (Evaluation Mode)")
        st.caption("Select a predefined role to test authentication, permissions, and RBAC boundaries instantly:")
        demo_cols = st.columns([3, 1])
        demo_role = demo_cols[0].selectbox(
            "Select Evaluation Identity",
            [
                ("demo_investigator", "Investigating Officer (Case intake, document upload, intelligence)"),
                ("demo_legal", "Legal Officer (Document vetting, court filings, approvals)"),
                ("demo_reviewer", "Reviewer (Document review, approval / rejection workflow)"),
                ("demo_auditor", "Auditor (Read-only access, full audit trail & integrity verification)"),
                ("demo_admin", "Administrator (Full administrative access & security control)"),
                ("demo_forensic", "Forensic Officer (Forensic document ingestion & hashing)"),
            ],
            format_func=lambda x: f"{x[0]} — {x[1]}",
        )
        if demo_cols[1].button("Sign In Instantly", type="primary", use_container_width=True):
            st.session_state["authenticated_user"] = demo_role[0]
            if service.audit:
                service.audit.record(demo_role[0], "LOGIN", "session", "Success", {"mode": "demo_quick_login"})
            st.rerun()

    st.markdown("<div style='text-align:center; color:#5b6e82; margin:1rem 0;'>— OR SIGN IN WITH CREDENTIALS —</div>", unsafe_allow_html=True)

    pending = st.session_state.get("pending_user")
    if not pending:
        with st.form("login-form"):
            username = st.text_input("Username", value="demo_investigator")
            password = st.text_input("Password", type="password", value="DemoPass!2026")
            submitted = st.form_submit_button("Authenticate", type="primary", use_container_width=True)

        if submitted:
            user = service.security.verify_password(username, password) if service.security else None
            if user:
                st.session_state["pending_user"] = user.username
                st.rerun()
            st.error("Invalid username or password.")
        return

    user = service.security.get_user(pending)
    if not user:
        st.session_state.pop("pending_user", None)
        st.rerun()

    if not user.mfa_enrolled:
        _render_mfa_enrollment(service, user)
        return

    st.subheader("MFA Verification")
    st.caption("Enter the six-digit TOTP code from your authenticator application:")
    with st.form("mfa-form"):
        code = st.text_input("6-digit TOTP code", max_chars=6)
        verify = st.form_submit_button("Verify & Sign In", type="primary", use_container_width=True)
    if verify:
        if service.security.verify_totp(user, code):
            st.session_state["authenticated_user"] = user.username
            st.session_state.pop("pending_user", None)
            st.rerun()
        st.error("The MFA code is invalid or expired.")

    # Helpful hint for local testing
    with st.expander("🔑 Current Demo TOTP Code (Local Testing Helper)"):
        st.code(_totp(user.totp_secret), language="text")

    if st.button("← Back to login"):
        st.session_state.pop("pending_user", None)
        st.rerun()


def _render_mfa_enrollment(service: InvestigationService, user: User) -> None:
    user = service.security.begin_totp_enrollment(user.username)
    st.subheader("MFA Security Enrollment")
    st.write("Scan this QR code with Google Authenticator or Microsoft Authenticator:")
    uri = service.security.provisioning_uri(user)
    try:
        import qrcode
        image = qrcode.make(uri)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        st.image(buffer.getvalue(), width=200, caption="Authenticator Setup")
    except ImportError:
        pass
    st.code(user.totp_secret, language="text")
    st.caption("Secret Key (Time-based TOTP · 6 digits · 30s)")

    with st.form("mfa-enroll-form"):
        code = st.text_input("Enter code from app to confirm", max_chars=6)
        verify = st.form_submit_button("Complete Enrollment", type="primary", use_container_width=True)
    if verify:
        if service.security.complete_totp_enrollment(user, code):
            st.session_state["authenticated_user"] = user.username
            st.session_state.pop("pending_user", None)
            st.rerun()
        st.error("Invalid code.")


def _header(eyebrow: str, title: str, caption: str) -> None:
    st.markdown(f"<div class='eyebrow'>{eyebrow}</div>", unsafe_allow_html=True)
    st.title(title)
    st.caption(caption)


# =====================================================================
# 1. DASHBOARD (PS 26190 Core)
# =====================================================================
def _dashboard(service: InvestigationService, user: User) -> None:
    _header(
        "OPERATIONAL OVERVIEW",
        "Secure Document Management Dashboard",
        "Central assurance portal for legal filings, police reports, forensic documents, and audit compliance.",
    )

    cases = service.cases.cases() if service.cases else []
    docs = service.documents.documents() if service.documents else []
    doc_stats = service.document_statistics()
    audit_events = service.audit.events() if service.audit else []

    # PS 26190 Metric Cards Row
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("TOTAL CASES", len(cases))
    m2.metric("TOTAL DOCUMENTS", doc_stats["total_documents"])
    m3.metric("PENDING REVIEW", doc_stats["pending_review"])
    m4.metric("INTEGRITY VERIFIED", f"{doc_stats['verified_documents']} / {doc_stats['total_documents']}")
    m5.metric("INTEGRITY ALERTS", doc_stats["integrity_alerts"])
    m6.metric("AUDIT EVENTS", len(audit_events))

    # Action Shortcuts
    st.markdown(
        """
        <div class="action-bar">
            <strong>QUICK ACTIONS:</strong> &nbsp;
            <span>Navigate to <em>Cases</em> to create or review investigations, <em>Documents</em> to upload files, <em>Search</em> to query filings, or <em>Integrity Verification</em> to inspect cryptographic hashes.</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_left, col_right = st.columns([1.2, 1])

    with col_left:
        st.subheader("Recent Legal & Investigation Documents")
        if docs:
            recent_docs = docs[-6:][::-1]
            rows = []
            for d in recent_docs:
                rows.append({
                    "Doc ID": d.get("document_id"),
                    "Title / File": d.get("title") or d.get("filename"),
                    "Type": d.get("document_type"),
                    "Case": d.get("case_id"),
                    "Ver": f"v{d.get('current_version', 1)}",
                    "Status": d.get("status"),
                    "Integrity": d.get("integrity_status"),
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("No documents uploaded yet. Upload a document from the Documents section.")

        st.subheader("Active Investigation Cases")
        if cases:
            recent_cases = cases[-4:][::-1]
            case_rows = []
            for c in recent_cases:
                cid = c.get("case_id")
                c_docs = [d for d in docs if d.get("case_id") == cid]
                case_rows.append({
                    "Case ID": cid,
                    "Title": c.get("title"),
                    "Department": c.get("department", "General"),
                    "Lead Officer": c.get("investigating_officer", c.get("created_by")),
                    "Status": c.get("status"),
                    "Docs": len(c_docs),
                })
            st.dataframe(pd.DataFrame(case_rows), use_container_width=True, hide_index=True)
        else:
            st.info("No cases registered yet.")

    with col_right:
        st.subheader("Security & Audit Stream")
        if audit_events:
            recent_audit = audit_events[-6:][::-1]
            audit_rows = []
            for a in recent_audit:
                audit_rows.append({
                    "Time": a.get("timestamp", "")[-8:],
                    "User": a.get("user"),
                    "Action": a.get("action", "").replace("_", " "),
                    "Resource": a.get("resource"),
                    "Status": a.get("status"),
                })
            st.dataframe(pd.DataFrame(audit_rows), use_container_width=True, hide_index=True)
        else:
            st.info("Audit log is empty.")

        # Advanced Intelligence Layer Banner
        st.markdown(
            """
            <div class="intel-card">
                <div style="font-size:0.75rem; color:#42b9c6; font-weight:700; letter-spacing:0.1em; margin-bottom:4px;">
                    PS 26189 · ADVANCED INVESTIGATION INTELLIGENCE LAYER
                </div>
                <h4 style="margin:0 0 6px 0; color:#e6edf3;">Criminal Network Analytics & Lead Engine</h4>
                <p style="font-size:0.84rem; color:#8b9aaa; margin-bottom:10px;">
                    Authorized investigation documents feed graph analytics, entity extraction (persons, phones, vehicles, accounts), and cross-case leads.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        net_stats = service.network_statistics()
        ic1, ic2, ic3 = st.columns(3)
        ic1.metric("NETWORK NODES", net_stats["nodes"])
        ic2.metric("CONNECTIONS", net_stats["relationships"])
        ic3.metric("INVESTIGATIVE LEADS", net_stats["leads"])


# =====================================================================
# 2. CASE MANAGEMENT (PS 26190 Central Container)
# =====================================================================
def _cases(service: InvestigationService, user: User) -> None:
    _header(
        "CASE CONTAINER",
        "Case Management",
        "Centralized investigation files grouping documents, evidence, access permissions, audit history, and intelligence.",
    )

    cases = service.cases.cases() if service.cases else []

    # New Case Intake Expander
    with st.expander("➕ Register New Investigation Case", expanded=len(cases) == 0):
        with st.form("new-case-form"):
            c1, c2 = st.columns(2)
            new_id = c1.text_input("Case ID *", placeholder="CASE-2026-0089")
            new_title = c2.text_input("Case Title *", placeholder="Financial Fraud & Token Siphoning Inquiry")
            new_desc = st.text_area("Scope & Narrative Description", placeholder="Outline scope, incident dates, and key legal provisions.")
            c3, c4, c5 = st.columns(3)
            new_dept = c3.selectbox("Department / Division", (
                "Economic Offences Wing",
                "Cyber Crime Cell",
                "CID Special Crime",
                "Narcotics Control Bureau",
                "Anti-Corruption Bureau",
                "General Investigation",
            ))
            new_officer = c4.text_input("Lead Investigating Officer", value=user.username)
            new_priority = c5.selectbox("Priority", ("High", "Critical", "Medium", "Low"))
            new_date = st.date_input("Date Opened")
            submitted = st.form_submit_button("Create Case Record", type="primary")

        if submitted:
            try:
                service.create_case(
                    case_id=new_id,
                    title=new_title,
                    description=new_desc,
                    date=str(new_date),
                    priority=new_priority,
                    user=user,
                    department=new_dept,
                    investigating_officer=new_officer,
                )
                st.success(f"Investigation Case {new_id} registered successfully.")
                st.rerun()
            except Exception as e:
                st.error(str(e))

    if not cases:
        st.info("No cases registered yet.")
        return

    # Select Active Case
    case_ids = [c["case_id"] for c in cases]
    selected_cid = st.selectbox("Open Case File", case_ids, index=0)
    current_case = service.cases.get_case(selected_cid) or next(c for c in cases if c["case_id"] == selected_cid)

    # Case Header Info Card
    with st.container(border=True):
        ch1, ch2, ch3, ch4 = st.columns(4)
        ch1.markdown(f"**Case ID:** `{current_case['case_id']}`")
        ch2.markdown(f"**Department:** {current_case.get('department', 'General')}")
        ch3.markdown(f"**Officer:** {current_case.get('investigating_officer', current_case.get('created_by'))}")
        ch4.markdown(f"**Status:** `{current_case.get('status', 'Open')}`")
        st.markdown(f"### {current_case['title']}")
        if current_case.get("description"):
            st.caption(current_case["description"])

    # Tabs inside Case Container
    tab_docs, tab_audit, tab_rbac, tab_integ, tab_vers, tab_intel = st.tabs([
        "📄 Documents",
        "📜 Audit History",
        "👥 Access & Permissions",
        "🛡️ Integrity Status",
        "🔄 Version History",
        "🧠 Advanced Intelligence",
    ])

    case_docs = service.documents.for_case(selected_cid) if service.documents else []

    with tab_docs:
        st.subheader(f"Documents Attached to {selected_cid}")
        if case_docs:
            d_rows = []
            for d in case_docs:
                d_rows.append({
                    "Document ID": d["document_id"],
                    "Title": d.get("title") or d["filename"],
                    "Type": d.get("document_type"),
                    "Version": f"v{d.get('current_version', 1)}",
                    "Status": d.get("status"),
                    "Classification": d.get("classification"),
                    "Integrity": d.get("integrity_status"),
                    "Uploaded By": d.get("uploaded_by"),
                    "Date": d.get("uploaded_at")[:10],
                })
            st.dataframe(pd.DataFrame(d_rows), use_container_width=True, hide_index=True)
        else:
            st.info("No documents attached to this case yet.")

        # Quick Upload to this Case
        with st.expander("➕ Upload Document to this Case"):
            _render_upload_form(service, user, preselected_case=selected_cid)

    with tab_audit:
        st.subheader(f"Audit Trail for Case {selected_cid}")
        all_audit = service.audit.events() if service.audit else []
        case_audit = [a for a in all_audit if selected_cid in str(a.get("resource", "")) or selected_cid in str(a.get("metadata", {}))]
        if case_audit:
            a_rows = []
            for a in case_audit[::-1]:
                a_rows.append({
                    "Timestamp": a.get("timestamp"),
                    "User": a.get("user"),
                    "Action": a.get("action", "").replace("_", " "),
                    "Resource": a.get("resource"),
                    "Status": a.get("status"),
                    "Details": json.dumps(a.get("metadata", {})),
                })
            st.dataframe(pd.DataFrame(a_rows), use_container_width=True, hide_index=True)
        else:
            st.info("No audit events recorded for this case.")

    with tab_rbac:
        st.subheader("Case Access & Personnel Permissions")
        st.write(f"**Lead Investigator:** {current_case.get('investigating_officer', current_case.get('created_by'))}")
        st.write(f"**Assigned Personnel:** {', '.join(current_case.get('assigned_users', [user.username]))}")
        st.write(f"**Access Level:** Role-based restriction active. Officers in {current_case.get('department', 'General')} and authorized roles have access.")

    with tab_integ:
        st.subheader("Case Evidence & Document Integrity Verification")
        if case_docs:
            verified_count = sum(1 for d in case_docs if d.get("integrity_status") == "VERIFIED")
            st.metric("INTEGRITY STATUS", f"{verified_count} / {len(case_docs)} Documents Cryptographically Verified")
            if st.button("Verify All Case Documents", type="primary"):
                for d in case_docs:
                    service.verify_document_integrity(d["document_id"], user)
                st.success("Completed SHA-256 integrity verification across all case documents.")
                st.rerun()
        else:
            st.info("No documents to verify.")

    with tab_vers:
        st.subheader("Version History of Case Documents")
        all_vers = []
        for d in case_docs:
            for v in d.get("versions", []):
                all_vers.append({
                    "Document ID": d["document_id"],
                    "Document Title": d.get("title") or d["filename"],
                    "Version": f"v{v['version_number']}",
                    "SHA-256": v["sha256"][:16] + "...",
                    "Uploaded By": v["uploaded_by"],
                    "Timestamp": v["timestamp"][:19],
                    "Change Summary": v.get("change_summary", "Initial upload"),
                })
        if all_vers:
            st.dataframe(pd.DataFrame(all_vers), use_container_width=True, hide_index=True)
        else:
            st.info("No version history recorded.")

    with tab_intel:
        st.subheader(f"Criminal Network Intelligence for {selected_cid}")
        graph = service.build_active_graph()
        if selected_cid in graph:
            neighbors = list(graph.neighbors(selected_cid))
            st.write(f"**Entities linked to this case:** {len(neighbors)}")
            st.write(", ".join(neighbors[:20]))
        else:
            st.info("No entities linked in graph yet. Upload an investigation report to extract entities.")


# =====================================================================
# 3. DOCUMENT MANAGEMENT (Major New Core Module)
# =====================================================================
def _documents(service: InvestigationService, user: User) -> None:
    _header(
        "CORE REPOSITORY",
        "Document Management",
        "Secure storage, classification, metadata indexing, version control, and approval workflows for legal & investigation files.",
    )

    docs = service.documents.documents() if service.documents else []
    cases = service.cases.cases() if service.cases else []

    # Upload Expander
    with st.expander("📄 Upload New Legal / Investigation Document", expanded=len(docs) == 0):
        _render_upload_form(service, user)

    st.divider()

    # Filter Bar
    f1, f2, f3, f4 = st.columns(4)
    case_filter = f1.selectbox("Filter by Case", ["All Cases"] + [c["case_id"] for c in cases])
    type_filter = f2.selectbox("Filter by Document Type", ["All Types"] + list(DOCUMENT_TYPES))
    status_filter = f3.selectbox("Filter by Status", ["All Statuses"] + list(STATUSES))
    class_filter = f4.selectbox("Filter by Classification", ["All Classifications"] + list(CLASSIFICATIONS))

    filtered_docs = service.search_documents(
        case_id=case_filter,
        document_type=type_filter,
        status=status_filter,
        classification=class_filter,
    )

    st.subheader(f"Document Archive ({len(filtered_docs)} files)")
    if filtered_docs:
        table_rows = []
        for d in filtered_docs:
            table_rows.append({
                "Document ID": d["document_id"],
                "Title": d.get("title") or d["filename"],
                "Document Type": d.get("document_type"),
                "Case ID": d.get("case_id"),
                "Version": f"v{d.get('current_version', 1)}",
                "Status": d.get("status"),
                "Classification": d.get("classification"),
                "SHA-256 Digest": d.get("sha256", "")[:12] + "...",
                "Integrity": d.get("integrity_status"),
                "Uploaded By": d.get("uploaded_by"),
                "Date": d.get("uploaded_at", "")[:10],
            })
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

        # Document Workspace Inspector
        st.markdown("### Document Workspace & Inspector")
        selected_id = st.selectbox("Inspect Document", [d["document_id"] for d in filtered_docs], key="inspect-doc-select")
        doc = service.documents.get_document(selected_id)
        if doc:
            _render_document_workspace(service, user, doc)
    else:
        st.info("No documents match the current filters.")


def _render_upload_form(service: InvestigationService, user: User, preselected_case: str | None = None) -> None:
    cases = service.cases.cases() if service.cases else []
    if not cases:
        st.warning("Please create at least one Case in the Cases module before uploading documents.")
        return

    case_ids = [c["case_id"] for c in cases]
    idx = case_ids.index(preselected_case) if preselected_case in case_ids else 0

    with st.form(f"upload-doc-form-{preselected_case or 'main'}"):
        col1, col2 = st.columns(2)
        target_case = col1.selectbox("Attach to Case *", case_ids, index=idx)
        doc_type = col2.selectbox("Document Type *", DOCUMENT_TYPES)

        col3, col4 = st.columns(2)
        doc_title = col3.text_input("Document Title / Reference *", placeholder="e.g. First Information Report 42/2026")
        doc_dept = col4.text_input("Department / Legal Authority", value="Cyber & Economic Crime Division")

        col5, col6 = st.columns(2)
        doc_class = col5.selectbox("Access Classification", CLASSIFICATIONS, index=0)
        doc_status = col6.selectbox("Initial Status", ("Submitted", "Draft", "Under Review"))

        doc_desc = st.text_area("Document Abstract / Description", placeholder="Summary of evidentiary value or legal purpose.")
        uploaded_file = st.file_uploader(
            "Select Document File (PDF, DOCX, TXT, JPG, PNG)",
            type=["pdf", "docx", "txt", "jpg", "jpeg", "png"],
            key=f"file-upload-{preselected_case or 'main'}",
        )

        can_upload = service.security.has_permission(user, "document:upload") if service.security else True
        if not can_upload:
            st.warning(f"Role '{user.role}' is not authorized to upload new documents.")

        submitted = st.form_submit_button(
            "Upload & Compute Cryptographic Signature",
            type="primary",
            disabled=not can_upload,
        )

    if submitted:
        if not uploaded_file:
            st.error("Please select a file to upload.")
            return
        content = uploaded_file.getvalue()
        try:
            doc = service.upload_document(
                case_id=target_case,
                filename=uploaded_file.name,
                content=content,
                user=user,
                document_type=doc_type,
                title=doc_title,
                department=doc_dept,
                classification=doc_class,
                description=doc_desc,
                status=doc_status,
            )
            st.success(f"Document {doc['document_id']} successfully uploaded and sealed with SHA-256 hash.")
            st.rerun()
        except Exception as e:
            st.error(str(e))


def _render_document_workspace(service: InvestigationService, user: User, doc: dict) -> None:
    doc_id = doc["document_id"]
    current_ver = doc.get("current_version", 1)

    # Document Header Card
    with st.container(border=True):
        dh1, dh2, dh3, dh4 = st.columns(4)
        dh1.markdown(f"**Document ID:** `{doc_id}`")
        dh2.markdown(f"**Case:** `{doc.get('case_id')}`")
        dh3.markdown(f"**Type:** {doc.get('document_type')}")
        dh4.markdown(f"**Version:** `v{current_ver}`")

        dh5, dh6, dh7, dh8 = st.columns(4)
        dh5.markdown(f"**Classification:** `{doc.get('classification')}`")
        dh6.markdown(f"**Status:** `{doc.get('status')}`")
        dh7.markdown(f"**Uploaded By:** {doc.get('uploaded_by')}")
        dh8.markdown(f"**Integrity:** `{doc.get('integrity_status')}`")

        st.markdown(f"**SHA-256 Signature:** `{doc.get('sha256')}`")
        st.markdown(f"**Ledger Block:** `{doc.get('block_id', 'Unrecorded')}`")

        # Action Buttons
        btn_cols = st.columns(4)
        if btn_cols[0].button("🛡️ Verify Integrity", key=f"verify-{doc_id}", type="primary"):
            report = service.verify_document_integrity(doc_id, user)
            if report["verified"]:
                st.success("INTEGRITY VERIFIED: File matches immutable SHA-256 cryptographic signature.")
            else:
                st.error("INTEGRITY VIOLATION DETECTED: File content on disk does not match stored hash!")
            st.rerun()

        # Download Button
        storage_path = Path(doc.get("storage_path", ""))
        if storage_path.exists():
            file_bytes = storage_path.read_bytes()
            btn_cols[1].download_button(
                "⬇️ Download File",
                data=file_bytes,
                file_name=doc.get("filename", "document.bin"),
                mime=doc.get("mime_type", "application/octet-stream"),
                key=f"dl-{doc_id}",
            )
            if service.audit:
                service.audit.record(user.username, "DOCUMENT_DOWNLOAD", doc_id, "Success")

    # Document Sub-Tabs
    t_prev, t_ver, t_rev, t_share, t_audit = st.tabs([
        "👁️ Preview & Content",
        "🔄 Version Control",
        "⚖️ Review & Approval",
        "🤝 Collaboration & Sharing",
        "📜 Document Audit Trail",
    ])

    with t_prev:
        st.subheader("Document Content Preview")
        if doc.get("description"):
            st.markdown(f"**Abstract:** {doc['description']}")
        text = doc.get("extracted_text", "").strip()
        if text:
            st.text_area("Extracted Document Text", text, height=300)
        else:
            st.info("No extracted text available for this file type.")

    with t_ver:
        st.subheader(f"Version History for {doc_id}")
        versions = doc.get("versions", [])
        if versions:
            v_rows = []
            for v in versions:
                v_rows.append({
                    "Version": f"v{v['version_number']}",
                    "Filename": v["filename"],
                    "SHA-256": v["sha256"][:16] + "...",
                    "Uploaded By": v["uploaded_by"],
                    "Timestamp": v["timestamp"][:19],
                    "Change Summary": v.get("change_summary", ""),
                    "Status": v.get("status", ""),
                    "Ledger Block": v.get("block_id", ""),
                })
            st.dataframe(pd.DataFrame(v_rows), use_container_width=True, hide_index=True)

        st.markdown("#### Upload New Version")
        with st.form(f"new-ver-form-{doc_id}"):
            v_summary = st.text_input("Summary of Changes *", placeholder="Added witness cross-examination section.")
            v_file = st.file_uploader("Select Updated Document File", type=["pdf", "docx", "txt", "jpg", "jpeg", "png"], key=f"ver-file-{doc_id}")
            v_submit = st.form_submit_button("Upload New Version", type="primary")

        if v_submit:
            if not v_file:
                st.error("Please select a file.")
            elif not v_summary.strip():
                st.error("Change summary is required.")
            else:
                try:
                    updated = service.upload_document_version(
                        document_id=doc_id,
                        filename=v_file.name,
                        content=v_file.getvalue(),
                        user=user,
                        change_summary=v_summary,
                    )
                    st.success(f"Version {updated['current_version']} successfully uploaded.")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

    with t_rev:
        st.subheader("Document Review & Approval Workflow")
        st.write(f"**Current Status:** `{doc.get('status')}`")
        st.markdown("Workflow State: **Draft** ➔ **Submitted** ➔ **Under Review** ➔ **Approved / Rejected** ➔ **Final**")

        can_approve = service.security.has_permission(user, "document:approve") if service.security else True

        c_stat, c_notes = st.columns([1, 2])
        new_stat = c_stat.selectbox("Transition Status to", STATUSES, index=STATUSES.index(doc.get("status", "Submitted")) if doc.get("status") in STATUSES else 1)
        notes = c_notes.text_input("Reviewer Notes / Legal Opinion", placeholder="Approved for filing before Magistrate Court.")

        if st.button("Update Status", type="primary", disabled=not can_approve):
            try:
                service.update_document_status(doc_id, new_stat, user, notes=notes)
                st.success(f"Status updated to '{new_stat}'.")
                st.rerun()
            except Exception as e:
                st.error(str(e))

        st.markdown("#### Approval & Transition History")
        history = doc.get("approval_history", [])
        if history:
            h_rows = []
            for h in history[::-1]:
                h_rows.append({
                    "Status": h.get("status"),
                    "By": h.get("by"),
                    "Role": h.get("role"),
                    "Timestamp": h.get("timestamp", "")[:19],
                    "Notes": h.get("notes"),
                })
            st.dataframe(pd.DataFrame(h_rows), use_container_width=True, hide_index=True)

    with t_share:
        st.subheader("Document Collaboration & Access Delegation")
        shared = doc.get("shared_with", [])
        if shared:
            st.write("**Delegated Permissions:**")
            st.dataframe(pd.DataFrame(shared), use_container_width=True, hide_index=True)
        else:
            st.info("No custom sharing delegations. Role-based default policies apply.")

        with st.form(f"share-form-{doc_id}"):
            s_target = st.selectbox("Share with Role / User", ["Legal Officer", "Reviewer", "Auditor", "Investigating Officer", "demo_legal", "demo_reviewer", "demo_auditor"])
            s_perm = st.selectbox("Permission Level", ("View Only", "View + Download", "View + Edit", "Full Access"))
            s_notes = st.text_input("Authorization Reference / Notes", placeholder="Authorized for bail hearing review.")
            s_submit = st.form_submit_button("Grant Permission", type="primary")

        if s_submit:
            try:
                service.share_document(doc_id, s_target, s_perm, user, s_notes)
                st.success(f"Permission '{s_perm}' granted to '{s_target}'.")
                st.rerun()
            except Exception as e:
                st.error(str(e))

    with t_audit:
        st.subheader(f"Audit Trail for Document {doc_id}")
        all_audit = service.audit.events() if service.audit else []
        doc_audit = [a for a in all_audit if a.get("resource") == doc_id or doc_id in str(a.get("metadata", {}))]
        if doc_audit:
            d_rows = []
            for a in doc_audit[::-1]:
                d_rows.append({
                    "Timestamp": a.get("timestamp"),
                    "User": a.get("user"),
                    "Action": a.get("action", "").replace("_", " "),
                    "Status": a.get("status"),
                    "Metadata": json.dumps(a.get("metadata", {})),
                })
            st.dataframe(pd.DataFrame(d_rows), use_container_width=True, hide_index=True)
        else:
            st.info("No audit events for this document yet.")


# =====================================================================
# 4. SEARCH & RETRIEVAL (PS 26190 Dedicated Search)
# =====================================================================
def _search(service: InvestigationService, user: User) -> None:
    _header(
        "DISCOVERY & RETRIEVAL",
        "Document Search",
        "Full-text keyword querying across document contents, metadata, legal classifications, and case identifiers.",
    )

    cases = service.cases.cases() if service.cases else []

    # Search Bar & Facets
    query = st.text_input("🔍 Search Query", placeholder="Enter keywords, entity names, phone numbers, vehicle numbers, or legal terms...")

    c1, c2, c3, c4 = st.columns(4)
    sel_case = c1.selectbox("Case", ["All Cases"] + [c["case_id"] for c in cases])
    sel_type = c2.selectbox("Document Type", ["All Types"] + list(DOCUMENT_TYPES))
    sel_status = c3.selectbox("Status", ["All Statuses"] + list(STATUSES))
    sel_class = c4.selectbox("Classification", ["All Classifications"] + list(CLASSIFICATIONS))

    results = service.search_documents(
        query=query,
        case_id=sel_case,
        document_type=sel_type,
        status=sel_status,
        classification=sel_class,
    )

    st.subheader(f"Search Results ({len(results)} matches)")
    if results:
        for r in results:
            with st.container(border=True):
                rc1, rc2 = st.columns([3, 1])
                rc1.markdown(f"### {r.get('title') or r.get('filename')} (`{r.get('document_id')}`)")
                rc1.markdown(f"**Case:** `{r.get('case_id')}` &nbsp; | &nbsp; **Type:** `{r.get('document_type')}` &nbsp; | &nbsp; **Version:** `v{r.get('current_version', 1)}` &nbsp; | &nbsp; **Status:** `{r.get('status')}`")
                if r.get("description"):
                    rc1.caption(r["description"])

                integ_color = "#10b981" if r.get("integrity_status") == "VERIFIED" else "#ef4444"
                rc2.markdown(
                    f"""
                    <div style="text-align:right;">
                        <span style="background:{integ_color}22; color:{integ_color}; border:1px solid {integ_color}; padding:4px 8px; border-radius:4px; font-size:0.75rem; font-weight:700;">
                            {r.get('integrity_status')}
                        </span>
                        <div style="color:#8b9aaa; font-size:0.72rem; margin-top:6px;">By {r.get('uploaded_by')}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                # Snippet match preview
                text = r.get("extracted_text", "")
                if query and query.lower() in text.lower():
                    idx = text.lower().find(query.lower())
                    start = max(0, idx - 50)
                    end = min(len(text), idx + 100)
                    st.markdown(f"> *...{text[start:end]}...*")
    else:
        st.info("No matching documents found.")


# =====================================================================
# 5. AUDIT TRAIL (PS 26190 Major Feature)
# =====================================================================
def _audit(service: InvestigationService, user: User) -> None:
    _header(
        "COMPLIANCE & GOVERNANCE",
        "Tamper-Evident Audit Trail",
        "Complete append-only audit trail tracking every document intake, access, version update, permission modification, and verification event.",
    )

    service.require_permission(user, "audit:view")

    events = service.audit.events() if service.audit else []
    if not events:
        st.info("No audit events recorded yet.")
        return

    # Filter Controls
    users = ["All Users"] + sorted(list({e.get("user") for e in events if e.get("user")}))
    actions = ["All Actions"] + sorted(list({e.get("action") for e in events if e.get("action")}))
    statuses = ["All Statuses"] + sorted(list({e.get("status") for e in events if e.get("status")}))

    f1, f2, f3 = st.columns(3)
    sel_u = f1.selectbox("Filter by User", users)
    sel_a = f2.selectbox("Filter by Action", actions)
    sel_s = f3.selectbox("Filter by Status", statuses)

    filtered = []
    for e in events:
        if sel_u != "All Users" and e.get("user") != sel_u:
            continue
        if sel_a != "All Actions" and e.get("action") != sel_a:
            continue
        if sel_s != "All Statuses" and e.get("status") != sel_s:
            continue
        filtered.append(e)

    st.subheader(f"Audit Log Events ({len(filtered)} records)")

    # Export Button
    st.download_button(
        "⬇️ Export Audit Log (JSON)",
        data=json.dumps(filtered, indent=2),
        file_name="audit_trail_export.json",
        mime="application/json",
    )

    t_rows = []
    for e in filtered[::-1]:
        t_rows.append({
            "Timestamp (UTC)": e.get("timestamp"),
            "User": e.get("user"),
            "Action": e.get("action", "").replace("_", " "),
            "Resource / Target": e.get("resource"),
            "Status": e.get("status"),
            "Metadata": json.dumps(e.get("metadata", {})),
        })
    st.dataframe(pd.DataFrame(t_rows), use_container_width=True, hide_index=True)


# =====================================================================
# 6. INTEGRITY VERIFICATION & LEDGER (PS 26190 Core)
# =====================================================================
def _integrity(service: InvestigationService, user: User) -> None:
    _header(
        "CRYPTOGRAPHIC ASSURANCE",
        "Document Integrity Verification & Immutable Ledger",
        "SHA-256 hash comparison and tamper-evident cryptographic ledger guaranteeing evidentiary authenticity.",
    )

    docs = service.documents.documents() if service.documents else []

    # Section A: Document Integrity Check
    st.subheader("1. Real-Time Document Hash Verification")
    if docs:
        doc_ids = [d["document_id"] for d in docs]
        chk_id = st.selectbox("Select Document for Integrity Verification", doc_ids, key="chk-integ-id")
        selected_doc = service.documents.get_document(chk_id)

        if selected_doc:
            c_left, c_right = st.columns(2)
            c_left.markdown(f"**Registered SHA-256 (Database):**\n`{selected_doc.get('sha256')}`")

            target_path = Path(selected_doc.get("storage_path", ""))
            disk_hash = hashlib.sha256(target_path.read_bytes()).hexdigest() if target_path.exists() else "File not found"
            c_right.markdown(f"**Computed SHA-256 (Disk File):**\n`{disk_hash}`")

            # Verification Button
            if st.button("Run Verification Check", type="primary", key="run-verify-btn"):
                report = service.verify_document_integrity(chk_id, user)
                if report["verified"]:
                    st.success("✅ INTEGRITY VERIFIED: Current file hash perfectly matches the cryptographic record.")
                else:
                    st.error("🚨 INTEGRITY VIOLATION DETECTED: Disk content does not match stored cryptographic hash!")

            # Live Demonstration Tamper Simulation Tool
            st.divider()
            st.markdown("#### 🧪 Evaluator Demonstration: Live Tamper Detection Simulation")
            st.caption("Demonstrate tamper detection live: simulate unauthorized modification on disk and verify that the system flags it instantly.")

            t_col1, t_col2 = st.columns(2)
            if t_col1.button("⚠️ Simulate Unauthorized File Modification", key="sim-tamper-btn"):
                service.simulate_document_tampering(chk_id, user)
                st.warning("Simulated modification applied to file on disk. Click 'Run Verification Check' above to see the tamper alert.")
                st.rerun()

            if t_col2.button("✅ Restore Original Clean File", key="restore-clean-btn"):
                service.restore_document_tampering(chk_id, user)
                st.success("Clean original file restored from backup. Integrity re-verified.")
                st.rerun()

    # Section B: Tamper-Evident Cryptographic Ledger
    st.divider()
    st.subheader("2. Tamper-Evident Cryptographic Ledger")
    st.caption("Each document action forms a chained block with cryptographic link to the previous hash:")

    ledger = service.documents.ledger() if service.documents else []
    if ledger:
        if st.button("🔗 Verify Entire Ledger Chain Integrity", type="primary"):
            res = service.documents.verify_ledger(user.username)
            if res["valid"]:
                st.success(f"✅ {res['status']}: All {res['blocks']} blocks cryptographically verified.")
            else:
                st.error(f"🚨 {res['status']}")

        l_rows = []
        for b in ledger[::-1]:
            l_rows.append({
                "Block ID": b.get("block_id"),
                "Action": b.get("action", "").replace("_", " "),
                "Resource": b.get("resource_id"),
                "Version": f"v{b.get('version', 1)}",
                "SHA-256": b.get("sha256", "")[:12] + "...",
                "User": b.get("user"),
                "Timestamp": b.get("timestamp", "")[:19],
                "Previous Block Hash": b.get("previous_hash", "")[:12] + "...",
                "Block Hash": b.get("current_hash", "")[:12] + "...",
            })
        st.dataframe(pd.DataFrame(l_rows), use_container_width=True, hide_index=True)
    else:
        st.info("No ledger blocks recorded yet.")


# =====================================================================
# 7. USERS & PERMISSIONS (RBAC)
# =====================================================================
def _users_and_permissions(service: InvestigationService, user: User) -> None:
    _header(
        "ACCESS GOVERNANCE",
        "Users & Role-Based Access Control",
        "Role permissions matrix, active credentials, and live role switching for demonstration and evaluation.",
    )

    # Active User Profile
    with st.container(border=True):
        st.markdown(f"### Current Authenticated Identity: `{user.username}`")
        st.markdown(f"**Assigned Role:** `{user.role}` &nbsp; | &nbsp; **MFA Status:** `{'Enrolled' if user.mfa_enrolled else 'Pending'}`")

    # Fast Role Switcher
    st.subheader("Live Role Switcher (SIH Evaluation & Demonstration)")
    st.caption("Switch active role instantly to test RBAC authorization enforcement:")

    all_users = service.security.all_users() if service.security else []
    u_choices = [(u.username, u.role) for u in all_users]

    switch_col, btn_col = st.columns([3, 1])
    target_username = switch_col.selectbox(
        "Select User Identity",
        u_choices,
        format_func=lambda x: f"{x[0]} ({x[1]})",
        key="switch-user-select",
    )

    if btn_col.button("Switch Active Role", type="primary", use_container_width=True):
        st.session_state["authenticated_user"] = target_username[0]
        if service.audit:
            service.audit.record(target_username[0], "LOGIN", "session", "Success", {"mode": "demo_role_switch"})
        st.rerun()

    st.divider()

    # Permissions Matrix
    st.subheader("Role Permissions Matrix")
    matrix = [
        {"Role": "Administrator", "Case Create/Edit": "✅", "Document Upload": "✅", "Document Download": "✅", "Review/Approve": "✅", "Audit Trail": "✅", "Integrity Verify": "✅", "User Admin": "✅"},
        {"Role": "Investigating Officer", "Case Create/Edit": "✅", "Document Upload": "✅", "Document Download": "✅", "Review/Approve": "❌", "Audit Trail": "❌", "Integrity Verify": "✅", "User Admin": "❌"},
        {"Role": "Legal Officer", "Case Create/Edit": "❌", "Document Upload": "❌", "Document Download": "✅", "Review/Approve": "✅", "Audit Trail": "❌", "Integrity Verify": "✅", "User Admin": "❌"},
        {"Role": "Reviewer", "Case Create/Edit": "❌", "Document Upload": "❌", "Document Download": "✅", "Review/Approve": "✅", "Audit Trail": "❌", "Integrity Verify": "✅", "User Admin": "❌"},
        {"Role": "Auditor", "Case Create/Edit": "❌", "Document Upload": "❌", "Document Download": "✅", "Review/Approve": "❌", "Audit Trail": "✅", "Integrity Verify": "✅", "User Admin": "❌"},
        {"Role": "Forensic Officer", "Case Create/Edit": "❌", "Document Upload": "✅", "Document Download": "✅", "Review/Approve": "❌", "Audit Trail": "❌", "Integrity Verify": "✅", "User Admin": "❌"},
    ]
    st.dataframe(pd.DataFrame(matrix), use_container_width=True, hide_index=True)


# =====================================================================
# 8. ADVANCED INVESTIGATION INTELLIGENCE (Preserved PS 26189 Layer)
# =====================================================================
def _advanced_intelligence(service: InvestigationService, user: User) -> None:
    _header(
        "PS 26189 INTEGRATION LAYER",
        "Advanced Investigation Intelligence",
        "AI-powered criminal network analytics, entity extraction, relationship mapping, and explainable investigative leads.",
    )

    st.markdown(
        """
        <div class="intel-card" style="margin-bottom:1.5rem;">
            <div style="font-size:0.75rem; color:#42b9c6; font-weight:700; letter-spacing:0.1em; margin-bottom:4px;">
                DOCUMENT-DRIVEN INTELLIGENCE
            </div>
            <p style="margin:0; font-size:0.88rem; color:#c7d2dc;">
                This module analyzes structured facts extracted from authorized legal and investigation documents in the secure repository,
                constructing relationship networks and generating explainable leads to accelerate complex investigations.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    t_graph, t_entities, t_analytics, t_cross, t_leads = st.tabs([
        "🌐 Investigation Network Graph",
        "🔍 Entity Explorer",
        "📊 Network Analysis & Centrality",
        "🔗 Cross-Case Intelligence",
        "💡 Investigative Leads Queue",
    ])

    with t_graph:
        _render_network_graph(service)

    with t_entities:
        _render_entity_explorer(service)

    with t_analytics:
        _render_network_analytics(service)

    with t_cross:
        _render_cross_case(service)

    with t_leads:
        _render_leads_queue(service)


def _render_network_graph(service: InvestigationService) -> None:
    graph = service.build_active_graph()
    if not graph.nodes:
        st.info("No network data available.")
        return

    cols = st.columns(4)
    cases = ["All cases"] + sorted(n for n, d in graph.nodes(data=True) if d.get("entity_type") == "CASE")
    types = ["All entity types"] + sorted({d.get("entity_type", "UNKNOWN") for _, d in graph.nodes(data=True)})
    relationships = ["All relationship types"] + sorted({x for _, _, d in graph.edges(data=True) for x in d.get("relationship_types", [])})

    case = cols[0].selectbox("Select case", cases, key="graph-case")
    entity_type = cols[1].selectbox("Entity type", types, key="graph-type")
    relation = cols[2].selectbox("View connections", relationships, key="graph-rel")
    degree = cols[3].slider("Minimum connections", 0, max((graph.degree(n) for n in graph), default=0), 0, key="graph-deg")

    filtered = filter_graph(graph, case, entity_type, relation, degree)
    st.caption(f"Showing {filtered.number_of_nodes()} nodes and {filtered.number_of_edges()} relationships")
    st.plotly_chart(network_figure(filtered), use_container_width=True, key="investigation-network-chart")

    nodes = sorted(filtered.nodes) or sorted(graph.nodes)
    selected = st.selectbox("Search / Inspect Entity", nodes, format_func=lambda node: f"{node} · {graph.nodes[node].get('label', node)}", key="graph-inspect-node")
    hops = st.selectbox("Show Neighborhood", ("1-hop", "2-hop"), key="graph-hops")
    related = sorted(graph.neighbors(selected))

    with st.container(border=True):
        st.subheader(f"Entity Details: {selected}")
        node_data = graph.nodes[selected]
        st.write(f"**Entity Type:** {node_data.get('entity_type', 'Unknown')}")
        st.write(f"**Label:** {node_data.get('label', selected)}")
        evidence_types = sorted({x for _, _, edge in graph.edges(selected, data=True) for x in edge.get("relationship_types", [])})
        st.write(f"**Relationship Types:** {', '.join(evidence_types) or 'None'}")
        st.write(f"**Connected Neighbors ({len(related)}):** {', '.join(related[:15]) or 'None'}")
        st.caption(f"{len(GraphAnalytics(graph).hop_connections(selected, int(hops[0])))} displayed {hops} paths. Requires investigator verification.")


def _render_entity_explorer(service: InvestigationService) -> None:
    st.subheader("Entities Extracted from Documents & Cases")
    graph = service.build_active_graph()

    entity_records = []
    for node, data in graph.nodes(data=True):
        etype = data.get("entity_type", "UNKNOWN")
        if etype in {"CASE", "DOCUMENT", "EVIDENCE"}:
            continue
        entity_records.append({
            "Entity ID": node,
            "Type": etype,
            "Label": data.get("label", node),
            "Connections": graph.degree(node),
        })

    if entity_records:
        st.dataframe(pd.DataFrame(entity_records), use_container_width=True, hide_index=True)
    else:
        st.info("No extracted entities found.")


def _render_network_analytics(service: InvestigationService) -> None:
    st.subheader("Network Significance & Key Individuals")
    analytics = service.investigative_analytics()
    centrality_rows = analytics.centrality()

    if centrality_rows:
        st.dataframe(pd.DataFrame(centrality_rows[:15]), use_container_width=True, hide_index=True)
    else:
        st.info("No analytics data available.")

    st.subheader("Network Clusters & Communities")
    clusters = analytics.clusters()
    if clusters:
        st.dataframe(pd.DataFrame(clusters), use_container_width=True, hide_index=True)


def _render_cross_case(service: InvestigationService) -> None:
    st.subheader("Cross-Case Entity Associations")
    st.caption("Entities observed across multiple independent case files:")
    rows = service.graph_analytics().cross_case_entities()
    graph = service.build_active_graph()

    if rows:
        for idx, item in enumerate(rows, 1):
            entity = item["entity_id"]
            data = graph.nodes.get(entity, {})
            cases = item.get("cases", [])
            with st.container(border=True):
                st.markdown(f"**Cross-Case Link #{idx}**")
                st.write(f"**Entity:** `{data.get('label', entity)}` ({entity}) &nbsp; | &nbsp; **Type:** {data.get('entity_type', 'Entity').title()}")
                st.write(f"**Cases Involved:** {' ↔ '.join(cases)}")
                st.warning("Requires Investigator Corroboration")
    else:
        st.info("No cross-case entity overlaps detected.")


def _render_leads_queue(service: InvestigationService) -> None:
    st.subheader("Prioritized Investigative Leads")
    st.caption("Explainable AI signals derived from network metrics and document facts:")
    leads = service.investigative_analytics().leads()

    if leads:
        for lead in leads:
            with st.container(border=True):
                l1, l2 = st.columns([3, 1])
                l1.markdown(f"**Lead {lead.lead_id} · {lead.lead_type.replace('_', ' ')}**")
                l1.write(f"**Cases:** {', '.join(lead.cases) or 'General'} &nbsp; | &nbsp; **Entities:** {', '.join(lead.entities)}")
                l1.write(f"**Rationale:** {lead.reason}")
                l1.caption(f"Evidence Basis: {lead.evidence}")

                priority_color = "#ef4444" if lead.priority == "High" else "#f59e0b" if lead.priority == "Medium" else "#10b981"
                l2.markdown(
                    f"""
                    <div style="text-align:right;">
                        <span style="background:{priority_color}22; color:{priority_color}; border:1px solid {priority_color}; padding:4px 8px; border-radius:4px; font-size:0.75rem; font-weight:700;">
                            {lead.priority.upper()} PRIORITY
                        </span>
                        <div style="font-size:0.72rem; color:#8b9aaa; margin-top:6px;">Status: Requires Verification</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
    else:
        st.info("No active leads generated.")


# =====================================================================
# STYLES
# =====================================================================
def _apply_styles() -> None:
    st.markdown(
        """
        <style>
        .stApp { background: #070d13; color: #e6edf3; }
        [data-testid="stSidebar"] { background: #0b141e; border-right: 1px solid #1a2a38; }
        [data-testid="stSidebarContent"] { padding-top: 1.2rem; }
        [data-testid="stMetric"] { background: #0f1c29; border: 1px solid #1c2e40; padding: 0.8rem 1rem; border-radius: 6px; }
        [data-testid="stMetricLabel"] { color: #8b9aaa; letter-spacing: 0.08em; font-size: 0.68rem; font-weight: 600; }
        [data-testid="stMetricValue"] { color: #42b9c6; font-size: 1.6rem; font-weight: 700; }
        [data-testid="stDataFrame"] { border: 1px solid #1c2e40; border-radius: 6px; }
        h1, h2, h3 { letter-spacing: 0.01em; font-weight: 700; color: #f0f6fc; }
        h1 { font-size: 1.95rem; }
        .eyebrow { color: #42b9c6; font-size: 0.72rem; font-weight: 700; letter-spacing: 0.16em; margin-bottom: 0.35rem; }
        .brand-mark { color: #42b9c6; border: 1px solid #285060; border-radius: 6px; display: inline-flex; align-items: center; justify-content: center; width: 2.2rem; height: 2.2rem; font-size: 1.2rem; background: #0f1c29; }
        .user-badge { background: #0f1c29; border: 1px solid #1c2e40; padding: 0.6rem 0.8rem; border-radius: 6px; margin-bottom: 0.8rem; }
        .action-bar { background: #0f1c29; border-left: 3px solid #42b9c6; padding: 0.75rem 1rem; color: #c7d2dc; margin: 1rem 0 1.2rem; font-size: 0.85rem; border-radius: 0 4px 4px 0; }
        .intel-card { background: linear-gradient(135deg, #0d1e2c 0%, #091520 100%); border: 1px solid #1e3a4e; border-radius: 8px; padding: 1rem 1.2rem; margin-top: 1rem; }
        .login-shell { text-align: center; max-width: 600px; margin: 2rem auto 1rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )
