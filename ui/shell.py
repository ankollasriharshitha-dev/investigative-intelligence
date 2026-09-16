"""Streamlit presentation shell for Investigative Intelligence."""

from io import BytesIO

import pandas as pd
import streamlit as st

from graph.analytics import GraphAnalytics
from graph.presentation import filter_graph, network_figure
from services.data_management import DatasetStorageError
from services.investigation import InvestigationService
from services.security import AuthorizationError, User

MODULES = ("Dashboard", "Cases", "New Investigation", "Evidence Upload", "Document Intelligence", "Cross-Case Intelligence", "Investigation Network", "Investigative Leads", "Evidence Integrity", "Audit Trail", "System Information")


def render_application(service: InvestigationService) -> None:
    st.set_page_config(page_title="Investigative Intelligence", page_icon="II", layout="wide")
    _apply_styles()
    user = _authenticated_user(service)
    if not user:
        _render_login(service)
        return
    source, validation = service.active_source(), service.validate_active_dataset()
    st.sidebar.markdown("<div class='brand-mark'>II</div>", unsafe_allow_html=True)
    st.sidebar.markdown("## INVESTIGATIVE INTELLIGENCE")
    st.sidebar.caption("Decision-support workspace · SIH 2026")
    page = st.sidebar.radio("Workspace", MODULES, label_visibility="collapsed")
    st.sidebar.divider()
    st.sidebar.caption("ACTIVE DATA SOURCE")
    st.sidebar.info("Uploaded investigation dataset" if source.source_type.value == "uploaded_investigation" else "Synthetic demo dataset")
    st.sidebar.caption(f"Provider: {source.source_type.value}")
    st.sidebar.caption(f"SIGNED IN: {user.username} · {user.role}")
    if st.sidebar.button("Logout", use_container_width=True):
        service.audit.record(user.username, "LOGOUT", "session", "Success")
        for key in ("authenticated_user", "pending_user"):
            st.session_state.pop(key, None)
        st.rerun()
    st.sidebar.success("Validated") if validation.valid else st.sidebar.error("Needs attention")
    if not validation.valid:
        st.error("The active data source could not be validated. Correct the dataset before continuing.")
        for error in validation.errors: st.write(f"- {error}")
        return
    pages = {"Dashboard": _dashboard, "Cases": _cases, "New Investigation": _new_case, "Evidence Upload": _evidence_upload, "Document Intelligence": _document_intelligence, "Cross-Case Intelligence": _cross_case, "Investigation Network": _network, "Investigative Leads": _leads, "Evidence Integrity": _integrity, "Audit Trail": _audit, "System Information": _system_information}
    try:
        pages[page](service, user)
    except AuthorizationError as error:
        st.error(str(error))
    except (DatasetStorageError, ValueError, KeyError, IndexError) as error:
        st.error("This view could not load the available investigation data. Check the dataset and try again.")
        st.caption(f"Technical detail: {error}")


def _authenticated_user(service: InvestigationService) -> User | None:
    username = st.session_state.get("authenticated_user")
    return service.security.get_user(username) if username and service.security else None


def _render_login(service: InvestigationService) -> None:
    st.markdown("<div class='login-shell'><div class='brand-mark'>II</div><h1>Investigative Intelligence</h1><p>Secure local prototype access</p></div>", unsafe_allow_html=True)
    pending = st.session_state.get("pending_user")
    if not pending:
        with st.form("login"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login", type="primary")
        if submitted:
            user = service.security.verify_password(username, password) if service.security else None
            if user:
                st.session_state["pending_user"] = user.username
                st.rerun()
            st.error("Invalid username or password.")
        st.caption("After password verification, first-time users enroll an authenticator app; enrolled users must enter a changing six-digit TOTP code.")
        return
    user = service.security.get_user(pending)
    if not user:
        st.session_state.pop("pending_user", None); st.rerun()
    if not user.mfa_enrolled:
        _render_mfa_enrollment(service, user)
        return
    st.subheader("MFA Verification")
    st.caption("Enter the six-digit code from your authenticator application. MFA is required before access is granted.")
    with st.form("mfa"):
        code = st.text_input("6-digit authenticator code", max_chars=6)
        verify = st.form_submit_button("Verify MFA", type="primary")
    if verify:
        if service.security.verify_totp(user, code):
            st.session_state["authenticated_user"] = user.username
            st.session_state.pop("pending_user", None)
            st.rerun()
        st.error("The MFA code is invalid or expired. Try the current code.")
    if st.button("Back to login"):
        st.session_state.pop("pending_user", None); st.rerun()


def _render_mfa_enrollment(service: InvestigationService, user: User) -> None:
    """First-factor users must complete real TOTP enrollment before a session is created."""
    user = service.security.begin_totp_enrollment(user.username)
    st.subheader("Set up authenticator MFA")
    st.write("Scan this QR code with Google Authenticator or Microsoft Authenticator. The app will generate a changing six-digit code every 30 seconds.")
    uri = service.security.provisioning_uri(user)
    try:
        import qrcode
        image = qrcode.make(uri)
        buffer = BytesIO(); image.save(buffer, format="PNG")
        st.image(buffer.getvalue(), width=220, caption="Investigative Intelligence · demo_investigator")
    except ImportError:
        st.warning("QR rendering is unavailable in this environment. Use the manual setup key below.")
    st.markdown("**Manual setup key**")
    st.code(user.totp_secret, language="text")
    st.caption("Authenticator type: Time-based (TOTP) · 6 digits · 30 seconds · SHA-1")
    with st.form("mfa-enrollment"):
        code = st.text_input("Enter the current 6-digit code from your authenticator app", max_chars=6)
        verify = st.form_submit_button("Verify and complete MFA setup", type="primary")
    if verify:
        if service.security.complete_totp_enrollment(user, code):
            st.session_state["authenticated_user"] = user.username
            st.session_state.pop("pending_user", None)
            st.rerun()
        st.error("The code is invalid or expired. Check the authenticator clock and try the current code.")
    if st.button("Back to login", key="enrollment-back"):
        st.session_state.pop("pending_user", None); st.rerun()


def _header(eyebrow: str, title: str, caption: str) -> None:
    st.markdown(f"<div class='eyebrow'>{eyebrow}</div>", unsafe_allow_html=True)
    st.title(title); st.caption(caption)


def _case_rows(service: InvestigationService) -> list[dict]:
    snapshot, graph = service.load_active_dataset(), service.build_active_graph()
    rows = []
    for case in snapshot.documents.get("cases", []):
        cid = case.get("case_id", "Unknown")
        members = list(graph.neighbors(cid)) if cid in graph else []
        rows.append({"Case ID": cid, "Case title": case.get("title", "Untitled case"), "Status": case.get("status", "Open"), "Date": case.get("opened_date", "Not recorded"), "Evidence files": graph.degree(cid) if cid in graph else 0, "Entities": len(members), "Potential connections": sum(graph.degree(node) for node in members) // 2 if members else 0, "Priority": case.get("priority", "Not recorded")})
    if service.cases and service.evidence:
        for case in service.cases.cases():
            cid = case["case_id"]
            rows.append({"Case ID": cid, "Case title": case["title"], "Status": case["status"], "Date": case["opened_date"], "Evidence files": len(service.evidence.for_case(cid)), "Entities": len([x for x in service.cases.entity_records() if x["case_id"] == cid]), "Potential connections": len(service.cases.matches_for_case(cid)), "Priority": case["priority"]})
    return rows


def _dashboard(service: InvestigationService, user: User) -> None:
    _header("OPERATIONS OVERVIEW", "Investigation Dashboard", "Active dataset overview. Demo data is labelled and is not live operational information.")
    stats, network, cases = service.dashboard_statistics(), service.network_statistics(), _case_rows(service)
    active = sum(str(row["Status"]).lower() in {"open", "active", "in progress"} for row in cases)
    metrics = (("Total cases", stats["cases"]), ("Active cases", active), ("Evidence files", stats["relationships"]), ("Entities", sum(stats[x] for x in ("persons", "phones", "vehicles", "locations", "organizations", "accounts"))), ("Potential connections", network["cross_case_entities"]), ("Investigative leads", network["leads"]))
    for start in range(0, len(metrics), 3):
        for col, (name, value) in zip(st.columns(3), metrics[start:start + 3]): col.metric(name.upper(), value)
    st.subheader("Investigation workflow")
    st.info("Cases → upload evidence → document review → cross-case review → network → leads → integrity → audit trail. All signals require investigator verification.")
    st.subheader("Active cases")
    st.dataframe(pd.DataFrame(cases), width="stretch", hide_index=True) if cases else st.info("No cases available.")
    leads = service.investigative_analytics().leads()
    st.subheader("Potential investigative leads")
    frame = pd.DataFrame([{"Lead ID": x.lead_id, "Cases": ", ".join(x.cases), "Entity": ", ".join(x.entities), "Reason": x.reason, "Status": "Requires Investigator Verification"} for x in leads[:5]])
    st.dataframe(frame, width="stretch", hide_index=True) if not frame.empty else st.info("No investigative leads available.")


def _cases(service: InvestigationService, user: User) -> None:
    _header("CASE REGISTER", "Cases", "Review structured case records from the active source.")
    rows = _case_rows(service)
    if not rows: st.info("No cases available."); return
    st.dataframe(pd.DataFrame(rows).drop(columns="Priority"), width="stretch", hide_index=True)
    selected = st.selectbox("Open case", [row["Case ID"] for row in rows])
    record = next(row for row in rows if row["Case ID"] == selected)
    st.subheader(f"{record['Case ID']} · {record['Case title']}")
    for col, key in zip(st.columns(4), ("Status", "Priority", "Entities", "Potential connections")): col.metric(key.upper(), record[key])
    graph = service.build_active_graph()
    with st.expander("Associated entities", expanded=True): st.write(", ".join(sorted(graph.neighbors(selected))) if selected in graph and graph.degree(selected) else "No associated entities in the active dataset.")
    st.caption("Use New Investigation to prepare a new case intake.")


def _new_case(service: InvestigationService, user: User) -> None:
    _header("CASE INTAKE", "New Investigation", "Create a locally persisted investigation record. It can be replaced by PostgreSQL persistence in a later round.")
    with st.form("new-investigation"):
        left, right = st.columns(2)
        case_id, title = left.text_input("Case ID", placeholder="CASE-041"), right.text_input("Case title", placeholder="Brief investigation title")
        description = st.text_area("Description", placeholder="Record the investigation context and scope.")
        opened_date = left.date_input("Date"); priority = right.selectbox("Priority/status", ("Medium", "High", "Low", "Critical"))
        st.markdown("### Evidence")
        files = st.file_uploader("Upload Case Evidence — PDF / DOCX / JPG / PNG", type=["pdf", "docx", "jpg", "jpeg", "png", "txt"], accept_multiple_files=True, key="new-case-evidence")
        submitted = st.form_submit_button("Create Investigation", type="primary")
    if submitted:
        if not case_id.strip() or not title.strip(): st.warning("Case ID and case title are required.")
        else:
            case = service.create_case(case_id, title, description, str(opened_date), priority, user)
            st.success(f"Investigation {case['case_id']} created.")
            if files: st.caption(f"{len(files)} evidence file(s) selected. Upload them from Evidence Upload to process and record them.")


def _evidence_upload(service: InvestigationService, user: User) -> None:
    _header("EVIDENCE INTAKE", "Evidence Upload", "Store, hash, process, and analyze local evidence records. OCR uses local optional tools when installed.")
    st.markdown("<div class='workflow'>1. Select file &nbsp; → &nbsp; 2. Upload &nbsp; → &nbsp; 3. Processing &nbsp; → &nbsp; 4. Analysis &nbsp; → &nbsp; 5. Results</div>", unsafe_allow_html=True)
    cases = _case_rows(service)
    selected_case = st.selectbox("Attach evidence to case", [row["Case ID"] for row in cases]) if cases else None
    uploaded = st.file_uploader("Select evidence file", type=["pdf", "docx", "txt", "jpg", "jpeg", "png"], key="evidence-upload")
    if uploaded:
        content = uploaded.getvalue()
        st.dataframe(pd.DataFrame([{"Filename": uploaded.name, "File type": uploaded.type or uploaded.name.rsplit(".", 1)[-1].upper(), "Size": f"{len(content)/1024:.1f} KB", "Upload status": "Selected", "Processing status": "Ready for review"}]), width="stretch", hide_index=True)
        if st.button("Upload and process evidence", type="primary", disabled=not selected_case):
            evidence = service.upload_evidence(selected_case, uploaded.name, content, user)
            st.session_state["processed_evidence"] = evidence
            st.success(f"Evidence {evidence['evidence_id']} was stored, hashed, and processed.")
            if evidence["warnings"]: st.warning(" ".join(evidence["warnings"]))
    else: st.info("No evidence uploaded yet.")
    _structured_upload(service)


def _document_intelligence(service: InvestigationService, user: User) -> None:
    _header("DOCUMENT REVIEW", "Document Intelligence", "Review available document-service output. Detected values remain subject to investigator verification.")
    evidence = st.session_state.get("processed_evidence")
    extraction = st.session_state.get("document_extraction")
    if evidence:
        st.dataframe(pd.DataFrame([{"Evidence ID": evidence["evidence_id"], "Filename": evidence["filename"], "Processing status": evidence["processing_status"], "OCR used": "Yes" if evidence["ocr_used"] else "No", "SHA-256": evidence["sha256"]}]), width="stretch", hide_index=True)
        extraction = type("EvidenceReview", (), {"entities": evidence.get("entities", {}), "filename": evidence["filename"], "document_type": evidence["file_type"], "warnings": tuple(evidence.get("warnings", [])), "text": evidence.get("extracted_text", ""), "validation": type("Validation", (), {"valid": True})()})()
    names = ("PERSONS", "PHONE NUMBERS", "VEHICLES", "LOCATIONS", "ORGANIZATIONS", "ACCOUNTS", "EMAILS", "DATES")
    counts, rows = {name: 0 for name in names}, []
    if evidence:
        rows = [{"Entity": x["value"], "Type": x["type"], "Source": evidence["filename"], "Status": "Detected — review required"} for x in evidence.get("detected_entities", [])]
        for row in rows:
            metric = row["Type"].upper() + ("S" if row["Type"].upper() not in {"PHONE", "EMAIL"} else "")
            if metric in counts: counts[metric] += 1
    elif extraction:
        mapping = {"persons": "PERSONS", "phones": "PHONE NUMBERS", "vehicles": "VEHICLES", "locations": "LOCATIONS", "organizations": "ORGANIZATIONS", "accounts": "ACCOUNTS"}
        for table, items in extraction.entities.items():
            if table in mapping: counts[mapping[table]] = len(items)
            for item in items:
                if table == "cases": continue
                first_id = next((key for key in item if key.endswith("_id")), "")
                label = item.get("name") or item.get("phone_number") or item.get("registration_number") or item.get("label") or item.get("account_label") or item.get(first_id, "")
                rows.append({"Entity": label, "Type": table.rstrip("s").title(), "Source": extraction.filename, "Status": "Detected — review required"})
        st.caption(f"Current review file: {extraction.filename} ({extraction.document_type})")
        if extraction.warnings: st.warning(" ".join(extraction.warnings))
    for start in range(0, len(names), 4):
        for col, name in zip(st.columns(4), names[start:start + 4]): col.metric(name, counts[name])
    st.subheader("Extracted Information")
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True) if rows else st.info("No entities detected. Upload a supported document to populate this review workspace.")
    if extraction and extraction.text:
        with st.expander("Text preview"): st.text(extraction.text[:4000])
    if extraction and not evidence:
        if extraction.validation.valid:
            st.success("Document-service output passed its current validation checks and is ready for investigator approval.")
            if st.button("Approve & add to staged investigation dataset", type="primary"):
                try:
                    report = service.approve_document(extraction, "append")
                except DatasetStorageError:
                    st.error("The document-derived dataset could not be written. Close applications using it and try again.")
                else:
                    st.session_state["document_report"] = report
                    st.success("Document-derived records were staged. Activate the uploaded dataset in Evidence Upload after review.")
        else:
            st.warning("Document-service output requires correction before it can be added to the staged dataset.")
        report = st.session_state.get("document_report")
        if report:
            st.caption(f"Staged document ingestion: {report.records_added} records added · version {report.dataset_version or 'pending'}")


def _cross_case(service: InvestigationService, user: User) -> None:
    _header("CONNECTION REVIEW", "Cross-Case Intelligence", "Potential connections are review signals, not findings of guilt or identity.")
    rows, graph = service.graph_analytics().cross_case_entities(), service.build_active_graph()
    actual_matches = service.cases.matches_for_case() if service.cases else []
    if actual_matches:
        for match in actual_matches:
            with st.container(border=True):
                st.markdown("**Potential Connection**")
                st.write(f"**Cases:** {match['source_case']} ↔ {match['target_case']}")
                st.write(f"**Matched entity:** {match['entity']}")
                st.write(f"**Type:** {match['entity_type']}")
                st.write(f"**Reason:** {match['reason']}")
                st.write(f"**Match strength:** {match['confidence']}")
                st.warning(match['status'])
    if not rows and not actual_matches: st.info("No potential cross-case connections found."); return
    for index, item in enumerate(rows, 1):
        entity, data, cases = item["entity_id"], graph.nodes.get(item["entity_id"], {}), item.get("cases", [])
        with st.container(border=True):
            st.markdown(f"**Potential Connection #{index}**")
            st.write(f"**Cases:** {' ↔ '.join(cases)}")
            st.write(f"**Matched entity:** {data.get('label', entity)} ({entity})")
            st.write(f"**Type:** Shared {data.get('entity_type', 'entity').title()}")
            st.write("**Reason:** The same entity appears in more than one active case.")
            st.warning("Requires Investigator Verification")


def _network(service: InvestigationService, user: User) -> None:
    _header("RELATIONSHIP EXPLORER", "Investigation Network", "Explore existing graph relationships. Connections are context for review and require investigator verification.")
    graph = service.build_active_graph()
    if not graph.nodes: st.info("No network data available."); return
    cols = st.columns(4)
    cases = ["All cases"] + sorted(n for n, d in graph.nodes(data=True) if d.get("entity_type") == "CASE")
    types = ["All entity types"] + sorted({d.get("entity_type", "UNKNOWN") for _, d in graph.nodes(data=True)})
    relationships = ["All relationship types"] + sorted({x for _, _, d in graph.edges(data=True) for x in d.get("relationship_types", [])})
    case, entity_type, relation = cols[0].selectbox("Select case", cases), cols[1].selectbox("Entity type", types), cols[2].selectbox("View connections", relationships)
    degree = cols[3].slider("Minimum connections", 0, max((graph.degree(n) for n in graph), default=0), 0)
    filtered = filter_graph(graph, case, entity_type, relation, degree)
    st.caption(f"Showing {filtered.number_of_nodes()} nodes and {filtered.number_of_edges()} relationships")
    st.plotly_chart(network_figure(filtered), width="stretch", key="investigation-network")
    nodes = sorted(filtered.nodes) or sorted(graph.nodes)
    selected = st.selectbox("Search / select entity", nodes, format_func=lambda node: f"{node} · {graph.nodes[node].get('label', node)}")
    hops = st.selectbox("Show relationships", ("1-hop", "2-hop"))
    related = sorted(graph.neighbors(selected))
    with st.container(border=True):
        st.subheader("Why is this connection shown?")
        evidence = sorted({x for _, _, edge in graph.edges(selected, data=True) for x in edge.get("relationship_types", [])})
        st.write(f"**Source:** {case if case != 'All cases' else 'Active dataset'}")
        st.write(f"**Relationship evidence:** {', '.join(evidence) or 'No relationship metadata available'}")
        st.write(f"**Connections:** {', '.join(related[:12]) or 'None'}")
        st.caption(f"{len(GraphAnalytics(graph).hop_connections(selected, int(hops[0])))} displayed {hops} path(s). Requires investigator verification.")


def _leads(service: InvestigationService, user: User) -> None:
    _header("REVIEW QUEUE", "Investigative Leads", "Potential leads summarize explainable signals. They are not conclusions or proof.")
    direct_matches = service.cases.matches_for_case() if service.cases else []
    for index, match in enumerate(direct_matches, 1):
        with st.container(border=True):
            st.markdown(f"**Potential Lead · MATCH-{index:03d}**")
            st.write(f"**Cases involved:** {match['source_case']} ↔ {match['target_case']}")
            st.write(f"**Entity involved:** {match['entity']} ({match['entity_type']})")
            st.write(f"**Reason:** {match['reason']}")
            st.write(f"**Evidence/source:** {match['evidence_id']}")
            st.write(f"**Confidence / match strength:** {match['confidence']}")
            st.warning(match['status'])
    leads = service.investigative_analytics().leads()
    if not leads: st.info("No investigative leads available."); return
    selected_type = st.selectbox("Lead type", ["All types"] + sorted({lead.lead_type for lead in leads}))
    for lead in leads:
        if selected_type != "All types" and lead.lead_type != selected_type: continue
        with st.container(border=True):
            st.markdown(f"**Potential Lead · {lead.lead_id}**")
            st.write(f"**Cases involved:** {' ↔ '.join(lead.cases) or 'Not specified'}")
            st.write(f"**Entity involved:** {', '.join(lead.entities)}")
            st.write(f"**Reason:** {lead.reason}")
            st.write(f"**Evidence/source:** {lead.evidence}")
            st.write(f"**Confidence / match strength:** {lead.metrics.get('network_significance') or lead.metrics.get('case_count') or 'Not available'}")
            st.warning("Requires Investigator Verification")


def _integrity(service: InvestigationService, user: User) -> None:
    _header("EVIDENCE ASSURANCE", "Evidence Integrity", "Local prototype tamper-evident ledger: evidence files remain local; only integrity metadata is chained.")
    records = service.evidence.records() if service.evidence else []
    if records:
        ledger = {block["evidence_id"]: block for block in service.evidence.ledger()}
        st.dataframe(pd.DataFrame([{"Evidence ID": x["evidence_id"], "Filename": x["filename"], "SHA-256": x["sha256"], "Ledger/Block ID": ledger.get(x["evidence_id"], {}).get("block_id", "Not recorded"), "Timestamp": x["uploaded_at"], "Previous Hash": ledger.get(x["evidence_id"], {}).get("previous_hash", ""), "Current Hash": ledger.get(x["evidence_id"], {}).get("current_hash", "")} for x in records]), width="stretch", hide_index=True)
        evidence_id = st.selectbox("Evidence to verify", [x["evidence_id"] for x in records])
        if st.button("Verify Evidence Integrity", type="primary"):
            result = service.verify_evidence(evidence_id, user)
            st.success(result["integrity_status"]) if result["integrity_status"] == "VERIFIED" else st.error(result["integrity_status"])
        if st.button("Verify Ledger"):
            result = service.verify_ledger(user)
            st.success(result["status"]) if result["status"] == "LEDGER VALID" else st.error(result["status"])
    else: st.info("No evidence integrity records are available yet.")


def _audit(service: InvestigationService, user: User) -> None:
    _header("ACTIVITY HISTORY", "Audit Trail", "Available ingestion activity; formal user and security auditing awaits backend integration.")
    service.require_permission(user, "audit:view")
    manager = service.data_management
    history = service.audit.events() if service.audit else (manager.history() if manager else [])
    if not history: st.info("No audit events available."); return
    rows = [{"Timestamp": x.get("timestamp", "Not recorded"), "User": x.get("user", "System / local workflow"), "Action": x.get("action", x.get("operation", "Dataset operation")).replace("_", " ").title(), "Case/Evidence": x.get("resource", x.get("dataset", "Investigation dataset")), "Status": x.get("status", "Unknown").title()} for x in history]
    st.dataframe(pd.DataFrame(rows).iloc[::-1], width="stretch", hide_index=True)


def _system_information(service: InvestigationService, user: User) -> None:
    _header("PLATFORM FOUNDATION", "System Information", "Current local Phase-2 prototype capabilities and security configuration.")
    source = service.active_source()
    for col, (name, value) in zip(st.columns(3), (("Active provider", source.name), ("Source type", source.source_type.value), ("Backend integration", "Local Phase 2"))): col.metric(name.upper(), value)
    st.info("This is investigative decision-support software. Potential connections and leads require investigator verification and do not determine guilt.")
    st.subheader("Current architecture")
    st.code("Streamlit frontend\n  ↓\nInvestigation services\n  ↓\nActive data provider\n  ↓\nSynthetic or uploaded dataset\n  ↓\nNetwork graph and explainable analytics", language="text")
    st.caption("Current: local persistence, MFA, audit logging, SHA-256 verification, graph integration, and a tamper-evident ledger. PostgreSQL is intentionally not connected.")


def _structured_upload(service: InvestigationService) -> None:
    """Preserves the existing CSV/JSON package workflow under Evidence Upload."""
    manager = service.data_management
    if manager is None: return
    with st.expander("Structured investigation dataset (existing workflow)"):
        st.caption("For the current CSV/JSON demo schema.")
        active_uploaded = manager.active_source_type() == "uploaded"
        choices = ["Synthetic demo dataset"] + (["Uploaded investigation dataset"] if manager.uploaded_exists() else [])
        selected_source = st.radio("Active source", choices, index=1 if active_uploaded and len(choices) > 1 else 0, horizontal=True)
        if selected_source == "Uploaded investigation dataset" and not active_uploaded:
            service.activate_uploaded_dataset(); st.rerun()
        if selected_source == "Synthetic demo dataset" and active_uploaded:
            service.activate_synthetic_dataset(); st.rerun()
        uploaded = st.file_uploader("Choose CSV/JSON package files", type=["csv", "json"], accept_multiple_files=True, key="structured-upload")
        if uploaded:
            files = {file.name: file.getvalue() for file in uploaded}
            st.dataframe(pd.DataFrame([{"Filename": name, "Size": f"{len(data)/1024:.1f} KB", "Status": "Selected"} for name, data in files.items()]), width="stretch", hide_index=True)
            operation = st.selectbox("Import operation", ("replace", "append", "update"), format_func=str.title)
            if st.button("Validate structured dataset"):
                st.session_state["structured_validation"] = manager.validate_files(files)[0]
            result = st.session_state.get("structured_validation")
            if result and not result.valid:
                st.error("Dataset validation failed.")
                for error in result.errors: st.write(f"- {error}")
            if result and result.valid:
                st.success("Dataset validation passed.")
                if st.button("Stage structured dataset", type="primary"):
                    try: st.session_state["structured_report"] = service.import_dataset(files, operation)
                    except DatasetStorageError: st.error("The dataset could not be written. Close applications using it and try again.")
        report = st.session_state.get("structured_report")
        if report:
            st.success(f"Dataset staged: {report.records_received} records received.")
            if manager.pending_path.exists() and st.button("Activate uploaded dataset"):
                service.activate_uploaded_dataset(); st.rerun()
        if manager.uploaded_exists() and st.button("Clear uploaded dataset", type="secondary"):
            st.session_state["confirm_clear_upload"] = True
        if st.session_state.get("confirm_clear_upload"):
            st.warning("This removes only the uploaded dataset. The synthetic demo dataset remains available.")
            confirm, cancel = st.columns(2)
            if confirm.button("Confirm clear", type="primary"):
                try:
                    service.clear_uploaded_dataset()
                except DatasetStorageError:
                    st.error("The uploaded dataset could not be cleared because a file is in use.")
                else:
                    st.session_state.pop("confirm_clear_upload", None)
                    st.success("Uploaded dataset cleared.")
                    st.rerun()
            if cancel.button("Cancel clear"):
                st.session_state.pop("confirm_clear_upload", None)
                st.rerun()


def _apply_styles() -> None:
    st.markdown("""<style>
    .stApp { background:#0a1016; color:#e6edf3; } [data-testid="stSidebar"] { background:#0d161e; border-right:1px solid #263645; }
    [data-testid="stSidebarContent"] { padding-top:1.5rem; } [data-testid="stMetric"] { background:#121d27; border:1px solid #263645; padding:.8rem 1rem; border-radius:4px; }
    [data-testid="stMetricLabel"] { color:#8b9aaa; letter-spacing:.07em; font-size:.68rem; } [data-testid="stDataFrame"] { border:1px solid #263645; border-radius:4px; }
    h1,h2,h3 { letter-spacing:.01em; font-weight:600; } h1 { font-size:2.05rem; } .eyebrow { color:#42b9c6; font-size:.7rem; font-weight:700; letter-spacing:.16em; margin-bottom:.35rem; }
    .brand-mark { color:#42b9c6; border:1px solid #2f7480; display:inline-flex; align-items:center; justify-content:center; width:2.2rem; height:2.2rem; font-weight:700; margin-bottom:.5rem; }
    .workflow { background:#121d27; border-left:3px solid #42b9c6; padding:.8rem 1rem; color:#c7d2dc; margin:.8rem 0 1rem; font-size:.85rem; }
    [data-testid="stSidebar"] .stRadio label { padding:.25rem 0; } @media(max-width:700px) { h1 { font-size:1.7rem; } }
    </style>""", unsafe_allow_html=True)
