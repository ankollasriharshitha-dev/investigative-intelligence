"""Professional Streamlit interface for active-source investigation analysis."""

from io import BytesIO

import pandas as pd
import streamlit as st

from graph.analytics import GraphAnalytics
from graph.presentation import TYPE_COLORS, filter_graph, network_figure, path_relationships
from services.data_management import DatasetStorageError
from services.investigation import InvestigationService


MODULES = (
    "Overview",
    "Cases",
    "Investigation Network",
    "Entity Explorer",
    "Network Analysis",
    "Investigative Leads",
    "Data Management",
    "System Information",
)


def render_application(service: InvestigationService) -> None:
    st.set_page_config(page_title="Investigative Intelligence", page_icon="II", layout="wide")
    _apply_brand_styles()
    source = service.active_source()
    validation = service.validate_active_dataset()
    st.sidebar.markdown("<div class='brand-mark'>II</div>", unsafe_allow_html=True)
    st.sidebar.markdown("# INVESTIGATIVE\n# INTELLIGENCE")
    st.sidebar.caption("Criminal Network Analysis Platform")
    st.sidebar.caption("SIH 2026 • PS 26189")
    selected_module = st.sidebar.radio("Workspace", MODULES, label_visibility="collapsed")
    st.sidebar.divider()
    st.sidebar.caption("ACTIVE DATA SOURCE")
    st.sidebar.info("Synthetic Demo Dataset")
    st.sidebar.caption(f"Provider: {source.source_type.value}")
    st.sidebar.caption("DATA VALIDATION")
    st.sidebar.success("Validated") if validation.valid else st.sidebar.error("Failed")
    if not validation.valid:
        st.error("The active data source failed validation. Analysis is unavailable.")
        for error in validation.errors:
            st.write(f"- {error}")
        return
    if selected_module == "Overview":
        _render_dashboard(service)
    elif selected_module == "Investigation Network":
        _render_network(service)
    elif selected_module == "Network Analysis":
        _render_rankings(service)
    elif selected_module == "Investigative Leads":
        _render_leads(service)
    elif selected_module == "Entity Explorer":
        _render_entity_explorer(service)
    elif selected_module == "About / System Information":
        _render_about(service)
    elif selected_module == "Data Management":
        _render_data_management(service)
    else:
        _render_case_management(service)


def _render_dashboard(service: InvestigationService) -> None:
    st.markdown("<div class='eyebrow'>OPERATIONS OVERVIEW</div>", unsafe_allow_html=True)
    st.title("Investigative Intelligence")
    st.caption("Criminal Network Analysis Platform")
    stats = service.dashboard_statistics()
    network = service.network_statistics()
    investigative = service.investigative_analytics()
    st.markdown(
        "<div class='source-strip'><span><b>ACTIVE DATA SOURCE</b><br>Synthetic Demo Dataset</span>"
        "<span><b>DATA VALIDATION</b><br><span class='status-good'>Validated</span></span>"
        "<span><b>REFERENCE</b><br>SIH 2026 • PS 26189</span></div>",
        unsafe_allow_html=True,
    )
    metric_groups = (("CASES", "cases"), ("PERSONS", "persons"), ("PHONES", "phones"), ("VEHICLES", "vehicles"),
                     ("LOCATIONS", "locations"), ("ORGANIZATIONS", "organizations"), ("ACCOUNTS", "accounts"),
                     ("RELATIONSHIPS / EVENTS", "relationships"))
    for start in range(0, len(metric_groups), 4):
        columns = st.columns(4)
        for column, (label, key) in zip(columns, metric_groups[start:start + 4]):
            column.metric(label, stats[key])
    st.subheader("Network intelligence")
    columns = st.columns(4)
    columns[0].metric("TOTAL NODES", network["nodes"])
    columns[1].metric("GRAPH RELATIONSHIPS", network["relationships"])
    columns[2].metric("CONNECTED COMPONENTS", network["components"])
    columns[3].metric("CROSS-CASE ASSOCIATIONS", network["cross_case_entities"])
    columns = st.columns(3)
    columns[0].metric("NETWORK CLUSTERS", network["clusters"])
    columns[1].metric("POTENTIAL BRIDGE ENTITIES", network["potential_bridges"])
    columns[2].metric("INVESTIGATIVE LEADS", network["leads"])
    st.subheader("Network intelligence overview")
    overview = pd.DataFrame(investigative.centrality()).head(5)
    st.dataframe(overview[["entity_id", "entity_type", "degree", "betweenness", "pagerank", "network_significance", "cases"]], width="stretch", hide_index=True)
    st.subheader("Recent intelligence signals")
    signals = pd.DataFrame([{"lead_id": lead.lead_id, "type": lead.lead_type, "entity": ", ".join(lead.entities), "priority": lead.priority, "reason": lead.reason} for lead in investigative.leads()[:5]])
    st.dataframe(signals, width="stretch", hide_index=True)
    st.subheader("Active cases")
    cases = pd.DataFrame(service.load_active_dataset().documents["cases"])
    st.dataframe(cases, width="stretch", hide_index=True, height=180)


def _render_network(service: InvestigationService) -> None:
    st.title("Investigation Network")
    st.caption("Explore potential connections and network significance in the active dataset")
    graph = service.build_active_graph()
    analytics = GraphAnalytics(graph)
    with st.expander("Network filters", expanded=True):
        columns = st.columns(4)
        cases = ["All cases"] + sorted(node for node, data in graph.nodes(data=True) if data.get("entity_type") == "CASE")
        types = ["All entity types"] + sorted({data.get("entity_type") for _, data in graph.nodes(data=True)})
        edge_types = ["All relationship types"] + sorted({item for _, _, data in graph.edges(data=True) for item in data.get("relationship_types", [])})
        selected_case = columns[0].selectbox("Case", cases)
        selected_type = columns[1].selectbox("Entity type", types)
        selected_relationship = columns[2].selectbox("Relationship type", edge_types)
        minimum_degree = columns[3].slider("Minimum degree", 0, max((graph.degree(node) for node in graph), default=0), 0)
        if columns[0].button("Reset filters", type="secondary"):
            st.rerun()
    filtered = filter_graph(graph, selected_case, selected_type, selected_relationship, minimum_degree)
    legend = "  ".join(f"<span class='legend-dot' style='background:{color}'></span>{entity_type}" for entity_type, color in TYPE_COLORS.items())
    st.markdown(f"<div class='network-meta'><span>SHOWING <b>{filtered.number_of_nodes()}</b> NODES / <b>{filtered.number_of_edges()}</b> RELATIONSHIPS</span><span>{legend}</span></div>", unsafe_allow_html=True)
    selection_event = st.plotly_chart(
        network_figure(filtered), width="stretch", key="investigation-network",
        on_select="rerun", selection_mode=["points"],
    )
    _render_node_inspection(graph, analytics, _selected_node(selection_event))
    _render_path_tools(graph, analytics)
    _render_cross_case(analytics)


def _render_node_inspection(graph, analytics: GraphAnalytics, selected_node: str | None = None) -> None:
    st.subheader("Entity inspection")
    nodes = sorted(graph.nodes)
    selected_index = nodes.index(selected_node) if selected_node in nodes else 0
    selected = st.selectbox("Select an entity", nodes, index=selected_index, format_func=lambda node: f"{node} · {graph.nodes[node].get('label', node)}")
    data = graph.nodes[selected]
    columns = st.columns(4)
    columns[0].metric("Entity type", data.get("entity_type", "UNKNOWN"))
    columns[1].metric("Connections", graph.degree(selected))
    columns[2].metric("Case associations", len([n for n in graph.neighbors(selected) if graph.nodes[n].get("entity_type") == "CASE"]))
    columns[3].metric("Network significance", "Review" if graph.degree(selected) >= 3 else "Contextual")
    st.write({"entity_id": selected, "label": data.get("label", selected), "relationship_types": sorted({item for _, _, edge in graph.edges(selected, data=True) for item in edge.get("relationship_types", [])}), "immediate_connections": sorted(graph.neighbors(selected))})


def _selected_node(selection_event: object) -> str | None:
    """Read Plotly customdata without coupling the UI to Streamlit event internals."""
    try:
        points = selection_event.selection.points
        return str(points[0]["customdata"]) if points else None
    except (AttributeError, IndexError, KeyError, TypeError):
        return None


def _render_path_tools(graph, analytics: GraphAnalytics) -> None:
    st.subheader("Connection analysis")
    nodes = sorted(graph.nodes)
    columns = st.columns(4)
    source = columns[0].selectbox("Entity A", nodes, key="path-source")
    target = columns[1].selectbox("Entity B", nodes, index=min(1, len(nodes) - 1), key="path-target")
    hop_source = columns[2].selectbox("Hop source", nodes, key="hop-source")
    hop_count = columns[3].selectbox("Hop depth", (2, 3))
    path = analytics.shortest_path(source, target)
    if path:
        st.success("Potential connection found: " + " → ".join(path))
        st.caption(" → ".join(path_relationships(graph, path)))
    else:
        st.warning("No connection found in the active dataset.")
    paths = analytics.hop_connections(hop_source, hop_count)
    st.write(f"{len(paths)} actual {hop_count}-hop connection(s) from {hop_source}")
    for path in paths[:10]:
        st.write(" → ".join(path) + "  |  " + " → ".join(path_relationships(graph, path)))


def _render_cross_case(analytics: GraphAnalytics) -> None:
    st.subheader("Potential cross-case associations")
    rows = analytics.cross_case_entities()
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True) if rows else st.info("No cross-case association found in the active dataset.")


def _render_rankings(service: InvestigationService) -> None:
    st.markdown("<div class='eyebrow'>ANALYTICS WORKSPACE</div>", unsafe_allow_html=True)
    st.title("Network Analysis")
    st.caption("Key entities ranked by transparent graph metrics")
    analytics = service.investigative_analytics()
    rows = analytics.centrality()
    frame = pd.DataFrame(rows)
    frame.insert(0, "Rank", range(1, len(frame) + 1))
    frame["network_significance_label"] = frame.apply(lambda row: "Potential Bridge Entity" if row["betweenness"] >= 0.05 else "Network Significance", axis=1)
    st.dataframe(frame[["Rank", "entity_id", "label", "entity_type", "degree", "degree_centrality", "betweenness", "pagerank", "network_significance", "cases", "network_significance_label"]].head(25), width="stretch", hide_index=True)
    selected = st.selectbox("Inspect ranked entity", frame["entity_id"].tolist(), format_func=lambda item: f"{item} · {frame.loc[frame.entity_id == item, 'label'].iloc[0]}")
    _render_entity_evidence(service.build_active_graph(), analytics, selected)


def _render_leads(service: InvestigationService) -> None:
    st.markdown("<div class='eyebrow'>REVIEW QUEUE</div>", unsafe_allow_html=True)
    st.title("Investigative Leads")
    st.caption("Explainable signals for investigator review")
    leads = service.investigative_analytics().leads()
    lead_types = ["All types"] + sorted({lead.lead_type for lead in leads})
    priorities = ["All priorities"] + ["High", "Medium", "Low"]
    columns = st.columns(3)
    selected_type = columns[0].selectbox("Lead type", lead_types)
    selected_priority = columns[1].selectbox("Priority", priorities)
    selected_status = columns[2].selectbox("Status", ["All statuses", "Requires Verification"])
    leads = [lead for lead in leads if (selected_type == "All types" or lead.lead_type == selected_type) and (selected_priority == "All priorities" or lead.priority == selected_priority) and (selected_status == "All statuses" or lead.status == selected_status)]
    if not leads:
        st.info("No potential investigative leads were generated from the active graph.")
    for lead in leads:
        with st.container(border=True):
            st.markdown(f"**{lead.lead_id} · {lead.lead_type}**")
            st.write(f"Entity: {', '.join(lead.entities)} | Cases: {', '.join(lead.cases) or 'Not specified'} | Priority: {lead.priority}")
            st.write(f"Reason: {lead.reason} Evidence: {lead.evidence}")
            st.json(lead.metrics)
            st.caption(f"{lead.status}")


def _render_entity_explorer(service: InvestigationService) -> None:
    graph = service.build_active_graph()
    analytics = service.investigative_analytics()
    query = st.text_input("Search entity, label, or ID")
    candidates = sorted(node for node, data in graph.nodes(data=True) if not query or query.lower() in f"{node} {data.get('label', '')}".lower())
    if not candidates:
        st.warning("No entity matches the active dataset search.")
        return
    selected = st.selectbox("Entity", candidates, format_func=lambda node: f"{node} · {graph.nodes[node].get('label', node)}")
    _render_entity_evidence(graph, analytics, selected)


def _render_entity_evidence(graph, analytics, selected: str) -> None:
    data = graph.nodes[selected]
    row = next(item for item in analytics.centrality() if item["entity_id"] == selected)
    st.subheader("Entity intelligence")
    columns = st.columns(5)
    columns[0].metric("Entity type", data.get("entity_type", "UNKNOWN"))
    columns[1].metric("Degree", row["degree"])
    columns[2].metric("Betweenness", f"{row['betweenness']:.3f}")
    columns[3].metric("PageRank", f"{row['pagerank']:.3f}")
    columns[4].metric("Network significance", f"{row['network_significance']:.2f}")
    st.write({"entity_id": selected, "label": data.get("label", selected), "cases": row["cases"], "metadata": data})
    st.write({"direct_connections": sorted(graph.neighbors(selected)), "relationship_types": sorted({relationship for _, _, edge in graph.edges(selected, data=True) for relationship in edge.get("relationship_types", [])})})
    paths_two = analytics.graph_analytics.hop_connections(selected, 2)
    paths_three = analytics.graph_analytics.hop_connections(selected, 3)
    columns = st.columns(2)
    columns[0].write({"2-hop_connections": [" -> ".join(path) for path in paths_two[:10]]})
    columns[1].write({"3-hop_connections": [" -> ".join(path) for path in paths_three[:10]]})
    relevant_leads = [lead for lead in analytics.leads() if selected in lead.entities]
    if relevant_leads:
        st.caption("Potential investigative signals")
        for lead in relevant_leads:
            st.info(f"{lead.lead_type}: {lead.reason} {lead.evidence} ({lead.status})")


def _render_case_management(service: InvestigationService) -> None:
    st.markdown("<div class='eyebrow'>CASE REGISTER</div>", unsafe_allow_html=True)
    st.title("Cases")
    st.caption("Structured investigation records from the active source")
    snapshot = service.load_active_dataset()
    graph = service.build_active_graph()
    analytics = service.investigative_analytics()
    case_rows = []
    for case in snapshot.documents["cases"]:
        case_id = case["case_id"]
        members = [node for node in graph.neighbors(case_id)] if case_id in graph else []
        relationships = sum(1 for node in members for neighbor in graph.neighbors(node) if neighbor != case_id) // 2
        case_rows.append({**case, "entity_count": len(members), "relationship_count": relationships})
    cases = pd.DataFrame(case_rows)
    st.dataframe(cases, width="stretch", hide_index=True)
    selected = st.selectbox("Open case record", cases["case_id"].tolist())
    record = next(case for case in case_rows if case["case_id"] == selected)
    members = sorted(graph.neighbors(selected))
    leads = [lead for lead in analytics.leads() if selected in lead.cases]
    st.subheader(f"{record['case_id']} · {record['title']}")
    columns = st.columns(4)
    columns[0].metric("Status", record["status"])
    columns[1].metric("Priority", record["priority"])
    columns[2].metric("Entities", record["entity_count"])
    columns[3].metric("Relationships", record["relationship_count"])
    with st.expander("Associated entities", expanded=True):
        st.write(", ".join(members) if members else "No associated entities in the active dataset.")
    with st.expander("Case intelligence", expanded=True):
        st.write(f"{len(leads)} potential investigative signal(s) require verification.")
        if leads:
            st.dataframe(pd.DataFrame([{"lead_id": lead.lead_id, "type": lead.lead_type, "priority": lead.priority, "reason": lead.reason} for lead in leads]), width="stretch", hide_index=True)


def _render_about(service: InvestigationService) -> None:
    st.markdown("<div class='eyebrow'>PLATFORM FOUNDATION</div>", unsafe_allow_html=True)
    st.title("System Information")
    st.caption("INVESTIGATIVE INTELLIGENCE · Criminal Network Analysis Platform")
    st.write("This is investigative decision-support software. Analytics identify potential connections and network significance; they do not determine guilt.")
    source = service.active_source()
    columns = st.columns(3)
    columns[0].metric("Active provider", source.name)
    columns[1].metric("Source type", source.source_type.value)
    columns[2].metric("Production backend", "Future phase")
    st.subheader("Current architecture")
    st.code("Frontend\n  ↓\nInvestigation Services\n  ↓\nData Provider\n  ↓\nSynthetic Dataset\n  ↓\nGraph Analytics", language="text")
    st.write("Current: synthetic or uploaded file-backed data, provider/service contracts, a NetworkX graph, and transparent rule-based analytics.")
    st.write("Future: persistent databases, graph databases, backend APIs, stronger AI/ML services, daily ingestion, authentication, authorization, and formal audit logging. Those production capabilities are not claimed by this MVP.")


def _render_data_management(service: InvestigationService) -> None:
    st.markdown("<div class='eyebrow'>SOURCE CONTROL</div>", unsafe_allow_html=True)
    st.title("Data Management")
    st.caption("Visible, controlled data-source foundation")
    manager = service.data_management
    if manager is None:
        st.error("DATA SOURCE ERROR: source management is unavailable in this application context.")
        return
    active_label = "Uploaded Investigation Dataset" if manager.active_source_type() == "uploaded" else "Synthetic Demo Dataset"
    active_location = "data/uploads/current/" if active_label.startswith("Uploaded") else "data/synthetic/"
    metadata = manager.source_metadata()
    dataset_metadata = manager.dataset_metadata()
    st.markdown(f"<div class='source-card'><div class='eyebrow'>ACTIVE DATA SOURCE</div><h3>{active_label}</h3><p>{metadata['status']} · {active_location}</p></div>", unsafe_allow_html=True)
    source_options = ["Synthetic Demo Dataset"] + (["Uploaded Investigation Dataset"] if manager.uploaded_exists() else [])
    selected_source = st.radio("Switch active source", source_options, index=source_options.index(active_label), horizontal=True)
    if selected_source != active_label:
        if selected_source == "Uploaded Investigation Dataset":
            service.activate_uploaded_dataset()
        else:
            service.activate_synthetic_dataset()
        st.rerun()
    st.subheader("Current dataset")
    columns = st.columns(4)
    snapshot = service.load_active_dataset()
    validation = service.validate_active_dataset()
    file_count = len(validation.checked_files)
    record_count = len(snapshot.documents.get("cases", [])) + sum(len(frame) for frame in snapshot.tables.values())
    columns[0].metric("Files", file_count)
    columns[1].metric("Records", record_count)
    columns[2].metric("Dataset version", dataset_metadata.version)
    columns[3].metric("Validation", dataset_metadata.validation_status)
    if metadata.get("imported_at"):
        st.caption(f"Last updated: {metadata['imported_at']}")

    st.subheader("Upload investigation data")
    st.caption("Upload a complete structured package using the existing internal schema. CSV and JSON are supported.")
    uploaded_files = st.file_uploader("Choose CSV/JSON files", type=["csv", "json"], accept_multiple_files=True, key="investigation-upload")
    if uploaded_files:
        file_bytes = {file.name: file.getvalue() for file in uploaded_files}
        upload_signature = tuple(sorted((name, len(content)) for name, content in file_bytes.items()))
        if st.session_state.get("upload_signature") != upload_signature:
            st.session_state.pop("upload_validation", None)
            st.session_state.pop("last_import_report", None)
            st.session_state["upload_signature"] = upload_signature
        preview_columns = st.columns(min(3, len(file_bytes)))
        for index, (filename, content) in enumerate(file_bytes.items()):
            with preview_columns[index % len(preview_columns)]:
                try:
                    preview = pd.read_json(BytesIO(content)) if filename.endswith(".json") else pd.read_csv(BytesIO(content), nrows=3)
                    st.caption(f"{filename} · {len(preview)} preview rows")
                    st.dataframe(preview, width="stretch", hide_index=True, height=150)
                except (ValueError, UnicodeDecodeError, pd.errors.ParserError) as error:
                    st.error(f"{filename}: unable to preview ({error})")
        operation = st.selectbox("Import operation", ("replace", "append", "update"), format_func=lambda value: value.title())
        if operation in {"append", "update"}:
            st.info("Development / Demo Data Update · this local workflow simulates a daily ingestion package.")
        action_columns = st.columns(2)
        if action_columns[0].button("Validate Dataset", type="secondary"):
            result, _ = manager.validate_files(file_bytes)
            st.session_state["upload_validation"] = result
        validation_report = st.session_state.get("upload_validation")
        if validation_report:
            if validation_report.valid:
                st.success("DATASET VALIDATION PASSED · schema, IDs, timestamps, and references are valid")
            else:
                st.error("DATASET VALIDATION FAILED")
                for error in validation_report.errors:
                    st.write(f"- {error}")
            if action_columns[1].button("Import Dataset", disabled=not validation_report.valid):
                try:
                    report = service.import_dataset(file_bytes, operation)
                except DatasetStorageError:
                    st.error("Unable to replace or update the uploaded dataset because a file is currently in use. Close any application using the dataset and try again.")
                else:
                    st.session_state["last_import_report"] = report
                    st.rerun()
    report = st.session_state.get("last_import_report")
    if report:
        st.success(f"{report.operation.title()} staged: {report.records_received} records received, {report.records_added} added, {report.records_updated} updated, {report.duplicates_skipped} duplicates skipped.")
        if manager.pending_path.exists():
            if st.button("Activate Uploaded Dataset", type="primary"):
                service.activate_uploaded_dataset()
                st.session_state.pop("last_import_report", None)
                st.session_state.pop("upload_validation", None)
                st.rerun()

    st.subheader("Upload investigation documents")
    st.caption("Extract structured investigation information from supported documents.")
    st.info("Document ingestion is intended for synthetic/anonymized development data in this prototype. Production deployment requires access control, encryption, audit logging, retention policies, and privacy safeguards.")
    document_files = st.file_uploader("Choose PDF, DOCX, or TXT", type=["pdf", "docx", "txt"], accept_multiple_files=False, key="investigation-document-upload")
    if document_files:
        document_content = document_files.getvalue()
        document_signature = (document_files.name, len(document_content))
        if st.session_state.get("document_signature") != document_signature:
            st.session_state["document_signature"] = document_signature
            st.session_state["document_extraction"] = service.extract_document(document_files.name, document_content)
        extraction = st.session_state.get("document_extraction")
        if extraction:
            st.markdown(f"**Document:** {extraction.filename}  \n**Type:** {extraction.document_type}  \n**Extraction status:** {'Text extracted' if extraction.text.strip() else 'No text extracted'}")
            with st.expander("Extracted text preview", expanded=True):
                st.text(extraction.text[:4000] if extraction.text else "No extractable text was found.")
            entity_rows = [{"type": table.rstrip("s").upper(), "id": row.get(next((key for key in row if key.endswith("_id")), "id")), "label": row.get("name") or row.get("label") or row.get("account_label") or row.get("phone_number") or row.get("registration_number") or ""} for table, rows in extraction.entities.items() if table != "cases" for row in rows]
            st.write("Detected entities")
            st.dataframe(pd.DataFrame(entity_rows), width="stretch", hide_index=True) if entity_rows else st.info("No explicit supported entities detected.")
            st.write("Detected relationships")
            st.dataframe(pd.DataFrame(extraction.relationships), width="stretch", hide_index=True) if extraction.relationships else st.info("No explicit supported relationships detected.")
            if extraction.warnings:
                st.warning("\n".join(extraction.warnings))
            if extraction.validation.valid:
                st.success("Extraction validation passed for review.")
            else:
                st.error("Extracted information requires correction before approval.")
                for error in extraction.validation.errors:
                    st.write(f"- {error}")
            review_columns = st.columns(2)
            if review_columns[0].button("Approve & Add to Investigation Dataset", disabled=not extraction.validation.valid, type="primary"):
                document_report = service.approve_document(extraction, "append")
                st.session_state["document_report"] = document_report
                st.session_state.pop("document_extraction", None)
                st.success("Document-derived records were added to the staged uploaded dataset. Activate the uploaded source separately after review.")
            if review_columns[1].button("Discard", type="secondary"):
                st.session_state.pop("document_extraction", None)
                st.session_state.pop("document_signature", None)
                st.rerun()
            document_report = st.session_state.get("document_report")
            if document_report:
                st.caption(f"Document ingestion {document_report.ingestion_id or 'completed'} · version {document_report.dataset_version or 'pending'} · {document_report.records_added} records added")
    if manager.uploaded_exists():
        st.subheader("Uploaded dataset controls")
        st.caption("The uploaded package is stored separately and can be activated without changing the synthetic demo source.")
        if st.button("Clear Uploaded Data", type="secondary"):
            st.session_state["confirm_clear_upload"] = True
        if st.session_state.get("confirm_clear_upload"):
            st.warning("This removes only data/uploads/current. The synthetic dataset will remain intact.")
            confirm_columns = st.columns(2)
            if confirm_columns[0].button("Confirm Clear", type="primary"):
                try:
                    service.clear_uploaded_dataset()
                except DatasetStorageError:
                    st.error("Unable to clear the uploaded dataset because a file is currently in use. Close any application using the dataset and try again.")
                else:
                    st.session_state.pop("confirm_clear_upload", None)
                    st.rerun()
            if confirm_columns[1].button("Cancel"):
                st.session_state.pop("confirm_clear_upload", None)
                st.rerun()
    history = manager.history()
    if history:
        st.subheader("Recent ingestion activity")
        st.dataframe(pd.DataFrame(history[-10:]), width="stretch", hide_index=True)


def _apply_brand_styles() -> None:
    st.markdown("""<style>
    .stApp { background: #0a1016; color: #e6edf3; }
    [data-testid="stSidebar"] { background: #0d161e; border-right: 1px solid #263645; }
    [data-testid="stSidebarContent"] { padding-top: 2rem; }
    [data-testid="stMetric"] { background: #121d27; border: 1px solid #263645; padding: .9rem 1rem; border-radius: 3px; }
    [data-testid="stMetricLabel"] { color: #8b9aaa; letter-spacing: .08em; font-size: .7rem; }
    [data-testid="stMetricValue"] { color: #e6edf3; }
    [data-testid="stDataFrame"] { border: 1px solid #263645; }
    h1, h2, h3 { letter-spacing: .01em; font-weight: 600; }
    h1 { font-size: 2.2rem; }
    h2 { margin-top: 2rem; }
    .eyebrow { color: #42b9c6; font-size: .7rem; font-weight: 700; letter-spacing: .16em; margin-bottom: .4rem; }
    .brand-mark { color: #42b9c6; border: 1px solid #2f7480; display: inline-flex; align-items: center; justify-content: center; width: 2.2rem; height: 2.2rem; font-weight: 700; letter-spacing: .05em; margin-bottom: .6rem; }
    .source-strip { display: flex; gap: 2rem; background: #121d27; border: 1px solid #263645; border-left: 3px solid #42b9c6; padding: .9rem 1.1rem; margin: 1.2rem 0 1.4rem; color: #aebac5; font-size: .8rem; }
    .source-strip span { flex: 1; }
    .source-strip b { color: #748696; font-size: .65rem; letter-spacing: .12em; }
    .status-good { color: #79b68a; }
    .network-meta { display: flex; justify-content: space-between; gap: 1rem; flex-wrap: wrap; color: #8b9aaa; font-size: .72rem; letter-spacing: .08em; margin: .5rem 0 .8rem; }
    .legend-dot { display: inline-block; width: .55rem; height: .55rem; border-radius: 50%; margin: 0 .25rem 0 .6rem; }
    .source-card { background: #121d27; border: 1px solid #2f7480; border-left: 3px solid #42b9c6; padding: 1.1rem 1.25rem; margin: 1rem 0 1.5rem; }
    .source-card h3 { margin: .2rem 0; }
    .source-card p { color: #8b9aaa; margin: 0; }
    [data-testid="stSidebar"] .stRadio label { padding: .35rem 0; }
    @media (max-width: 700px) { .source-strip { display: block; } .source-strip span { display: block; margin-bottom: .65rem; } h1 { font-size: 1.8rem; } }
    </style>""", unsafe_allow_html=True)