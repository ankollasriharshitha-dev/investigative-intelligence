"""Application service boundary for investigation workflows."""

from domain.models import DataSourceInfo, DatasetSnapshot, ValidationResult
from graph.analytics import GraphAnalytics
from graph.investigative import InvestigativeAnalytics
from graph.provider import GraphProvider, NetworkXGraphProvider
from providers.base import DataProvider
from services.data_management import DataManagementService, DatasetStorageError
from services.document_ingestion import DocumentIngestionService, ExtractedDocument
from services.audit import AuditService
from services.case_management import CaseManagementService
from services.evidence import EvidenceService
from services.entity_intelligence import normalize
from services.security import AuthenticationService, User


class InvestigationService:
    def __init__(self, provider: DataProvider, settings=None, graph_provider: GraphProvider | None = None) -> None:
        self.provider = provider
        self._settings = settings
        self._data_management = DataManagementService(settings) if settings else None
        self._graph_provider = graph_provider or NetworkXGraphProvider()
        runtime = settings.runtime_data_dir if settings and settings.runtime_data_dir else None
        self.audit = AuditService(runtime / "audit.json") if runtime else None
        self.security = AuthenticationService(runtime / "users.json", self.audit) if runtime and self.audit else None
        self.cases = CaseManagementService(runtime / "cases.json", self.audit) if runtime and self.audit else None
        self.evidence = EvidenceService(runtime / "evidence", self.audit) if runtime and self.audit else None

    @property
    def data_management(self) -> DataManagementService | None:
        return self._data_management

    def refresh_active_provider(self) -> None:
        if self._settings is None:
            raise RuntimeError("Source refresh requires application settings")
        from services.provider_factory import build_current_provider
        self.provider = build_current_provider(self._settings)

    def active_source(self) -> DataSourceInfo:
        return self.provider.get_source_info()

    def validate_active_dataset(self) -> ValidationResult:
        return self.provider.validate()

    def load_active_dataset(self) -> DatasetSnapshot:
        return self.provider.load_snapshot()

    def build_active_graph(self):
        """Build from a fresh active snapshot so providers can change without stale state."""
        graph = self._graph_provider.build(self.load_active_dataset())
        if self.evidence and self.cases:
            for case in self.cases.cases():
                graph.add_node(case["case_id"], entity_type="CASE", label=case["title"], **case)
            for record in self.evidence.records():
                evidence_id = record["evidence_id"]
                graph.add_node(evidence_id, entity_type="EVIDENCE", label=record["filename"], **record)
                if record["case_id"] in graph:
                    graph.add_edge(evidence_id, record["case_id"], relationship_type="APPEARS_IN", relationship_types=["APPEARS_IN"])
            for entity in self.cases.entity_records():
                node_id = f"{entity['type'].upper()}:{entity['normalized']}"
                graph.add_node(node_id, entity_type=entity["type"].upper(), label=entity["value"], normalized=entity["normalized"])
                if entity["case_id"] in graph:
                    graph.add_edge(node_id, entity["case_id"], relationship_type="APPEARS_IN", relationship_types=["APPEARS_IN"])
                if entity["evidence_id"] in graph:
                    graph.add_edge(node_id, entity["evidence_id"], relationship_type="EXTRACTED_FROM", relationship_types=["EXTRACTED_FROM"])
                for existing_id, existing in graph.nodes(data=True):
                    if existing_id == node_id or existing.get("entity_type") != entity["type"].upper():
                        continue
                    if normalize(str(existing.get("label", "")), entity["type"]) == entity["normalized"]:
                        graph.add_edge(node_id, existing_id, relationship_type="NORMALIZED_MATCH", relationship_types=["NORMALIZED_MATCH"])
        return graph

    def graph_analytics(self) -> GraphAnalytics:
        return GraphAnalytics(self.build_active_graph())

    def investigative_analytics(self) -> InvestigativeAnalytics:
        snapshot = self.load_active_dataset()
        return InvestigativeAnalytics(snapshot, self.build_active_graph())

    def import_dataset(self, files: dict[str, bytes], operation: str = "replace"):
        if self._data_management is None:
            raise RuntimeError("Dataset import requires application settings")
        report = self._data_management.import_dataset(files, operation)
        if report.validation.valid:
            self.refresh_active_provider()
        return report

    def activate_uploaded_dataset(self) -> bool:
        if self._data_management is None:
            raise RuntimeError("Source activation requires application settings")
        activated = self._data_management.activate_uploaded()
        if activated:
            self.refresh_active_provider()
        return activated

    def activate_synthetic_dataset(self) -> None:
        if self._data_management is None:
            raise RuntimeError("Source activation requires application settings")
        self._data_management.activate_synthetic()
        self.refresh_active_provider()

    def clear_uploaded_dataset(self) -> None:
        if self._data_management is None:
            raise RuntimeError("Dataset clearing requires application settings")
        self._data_management.clear_uploaded()
        self.refresh_active_provider()

    def extract_document(self, filename: str, content: bytes) -> ExtractedDocument:
        return DocumentIngestionService().extract(filename, content)

    def approve_document(self, extraction: ExtractedDocument, operation: str = "append"):
        if self._data_management is None:
            raise RuntimeError("Document approval requires application settings")
        files = DocumentIngestionService().package_files(extraction)
        report = self.import_dataset(files, operation)
        return report

    def dashboard_statistics(self) -> dict[str, int]:
        """Return counts from the active snapshot for presentation layers."""
        snapshot = self.load_active_dataset()
        return {
            "cases": len(snapshot.documents.get("cases", [])) + (len(self.cases.cases()) if self.cases else 0),
            "persons": len(snapshot.tables.get("persons", [])),
            "phones": len(snapshot.tables.get("phones", [])),
            "vehicles": len(snapshot.tables.get("vehicles", [])),
            "locations": len(snapshot.tables.get("locations", [])),
            "organizations": len(snapshot.tables.get("organizations", [])),
            "accounts": len(snapshot.tables.get("accounts", [])),
            "relationships": sum(
                len(snapshot.tables.get(table_name, []))
                for table_name in ("calls", "messages", "transactions", "events")
            ),
        }

    def require_permission(self, user: User | None, permission: str) -> None:
        if not self.security:
            return
        self.security.require(user, permission)

    def create_case(self, case_id: str, title: str, description: str, date: str, priority: str, user: User) -> dict:
        self.require_permission(user, "case:create")
        if not self.cases: raise RuntimeError("Local case persistence is unavailable.")
        return self.cases.create(case_id, title, description, date, priority, user.username)

    def upload_evidence(self, case_id: str, filename: str, content: bytes, user: User) -> dict:
        self.require_permission(user, "evidence:upload")
        if not self.evidence or not self.cases: raise RuntimeError("Local evidence persistence is unavailable.")
        evidence = self.evidence.upload(case_id, filename, content, user.username)
        entities = self.cases.evidence_entities(evidence)
        evidence["detected_entities"] = entities
        matches = self.cases.matches(case_id, entities, self._synthetic_entity_records())
        evidence["potential_matches"] = matches
        self.evidence.update_analysis(evidence["evidence_id"], entities, matches)
        self.audit.record(user.username, "ENTITY_ANALYSIS", evidence["evidence_id"], "Success", {"entities": len(entities), "matches": len(matches)})
        return evidence

    def verify_evidence(self, evidence_id: str, user: User) -> dict:
        self.require_permission(user, "evidence:verify")
        if not self.evidence: raise RuntimeError("Local evidence persistence is unavailable.")
        return self.evidence.verify(evidence_id, user.username)

    def verify_ledger(self, user: User) -> dict:
        self.require_permission(user, "evidence:verify")
        if not self.evidence: raise RuntimeError("Local evidence persistence is unavailable.")
        return self.evidence.verify_ledger(user.username)

    def _synthetic_entity_records(self) -> list[dict]:
        snapshot = self.load_active_dataset(); result = []
        specs = {"persons": ("Person", "name", "case_ids"), "phones": ("Phone", "phone_number", "case_id"), "vehicles": ("Vehicle", "registration_number", "case_id"), "locations": ("Location", "label", None), "organizations": ("Organization", "name", "case_ids"), "accounts": ("Account", "account_label", "case_id")}
        for table, (kind, label, case_column) in specs.items():
            for row in snapshot.tables.get(table, []).to_dict(orient="records"):
                raw_cases = str(row.get(case_column, "")) if case_column else ""
                for case_id in raw_cases.split("|") if raw_cases else []:
                    value = str(row.get(label, "")); result.append({"case_id": case_id.strip(), "type": kind, "normalized": normalize(value, kind), "evidence_id": "Synthetic dataset"})
        return result

    def network_statistics(self) -> dict[str, int]:
        investigative = self.investigative_analytics()
        graph = investigative.graph
        analytics = investigative.graph_analytics
        return {
            "nodes": graph.number_of_nodes(),
            "relationships": graph.number_of_edges(),
            "components": len(analytics.connected_components()),
            "cross_case_entities": len(analytics.cross_case_entities()),
            "potential_bridges": sum(1 for row in analytics.centrality() if row["betweenness"] >= 0.05),
            "clusters": len(investigative.clusters()),
            "leads": len(investigative.leads()),
        }
