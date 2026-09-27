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
from services.document_management import DocumentManagementService
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
        self.documents = DocumentManagementService(runtime / "documents", self.audit, self.evidence) if runtime and self.audit else None

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
            if self.documents:
                for doc in self.documents.documents():
                    doc_id = doc["document_id"]
                    if doc_id not in graph:
                        graph.add_node(doc_id, entity_type="DOCUMENT", label=doc.get("title") or doc["filename"], **doc)
                        if doc.get("case_id") in graph:
                            graph.add_edge(doc_id, doc["case_id"], relationship_type="ATTACHED_TO", relationship_types=["ATTACHED_TO"])
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

    def create_case(
        self,
        case_id: str,
        title: str,
        description: str,
        date: str,
        priority: str,
        user: User,
        department: str = "General Investigation Division",
        investigating_officer: str = "",
        assigned_users: list[str] | None = None,
    ) -> dict:
        self.require_permission(user, "case:create")
        if not self.cases: raise RuntimeError("Local case persistence is unavailable.")
        return self.cases.create(
            case_id,
            title,
            description,
            date,
            priority,
            user.username,
            department=department,
            investigating_officer=investigating_officer,
            assigned_users=assigned_users,
        )

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
        if self.documents:
            self.documents._sync_legacy_evidence()
        return evidence

    def upload_document(
        self,
        case_id: str,
        filename: str,
        content: bytes,
        user: User,
        document_type: str = "Investigation Record",
        title: str = "",
        department: str = "General Investigation",
        classification: str = "Restricted",
        description: str = "",
        status: str = "Submitted",
    ) -> dict:
        self.require_permission(user, "document:upload")
        if not self.documents: raise RuntimeError("Document storage service is unavailable.")
        doc = self.documents.upload_document(
            case_id=case_id,
            filename=filename,
            content=content,
            user=user.username,
            document_type=document_type,
            title=title,
            department=department,
            classification=classification,
            description=description,
            status=status,
        )
        if self.cases:
            entities = self.cases.evidence_entities({
                "extracted_text": doc.get("extracted_text", ""),
                "entities": doc.get("entities", {}),
                "evidence_id": doc["document_id"],
                "case_id": case_id,
            })
            doc["detected_entities"] = entities
            matches = self.cases.matches(case_id, entities, self._synthetic_entity_records())
            doc["potential_matches"] = matches
        return doc

    def upload_document_version(
        self,
        document_id: str,
        filename: str,
        content: bytes,
        user: User,
        change_summary: str = "",
    ) -> dict:
        self.require_permission(user, "document:edit")
        if not self.documents: raise RuntimeError("Document storage service is unavailable.")
        return self.documents.upload_version(document_id, filename, content, user.username, change_summary)

    def verify_document_integrity(self, document_id: str, user: User, version_number: int | None = None) -> dict:
        self.require_permission(user, "integrity:verify")
        if not self.documents: raise RuntimeError("Document storage service is unavailable.")
        return self.documents.verify_integrity(document_id, user.username, version_number)

    def update_document_status(self, document_id: str, new_status: str, user: User, notes: str = "") -> dict:
        self.require_permission(user, "document:review")
        if not self.documents: raise RuntimeError("Document storage service is unavailable.")
        return self.documents.update_status(document_id, new_status, user.username, role=user.role, notes=notes)

    def share_document(self, document_id: str, target: str, permission: str, user: User, notes: str = "") -> dict:
        self.require_permission(user, "document:share")
        if not self.documents: raise RuntimeError("Document storage service is unavailable.")
        return self.documents.share_document(document_id, target, permission, user.username, notes)

    def search_documents(self, **kwargs) -> list[dict]:
        if not self.documents: return []
        return self.documents.search_documents(**kwargs)

    def document_statistics(self) -> dict[str, int]:
        docs = self.documents.documents() if self.documents else []
        verified = sum(1 for d in docs if d.get("integrity_status") == "VERIFIED")
        mismatch = sum(1 for d in docs if d.get("integrity_status") == "INTEGRITY MISMATCH")
        pending_review = sum(1 for d in docs if d.get("status") in {"Draft", "Submitted", "Under Review"})
        return {
            "total_documents": len(docs),
            "verified_documents": verified,
            "integrity_alerts": mismatch,
            "pending_review": pending_review,
        }

    def simulate_document_tampering(self, document_id: str, user: User) -> dict:
        self.require_permission(user, "integrity:verify")
        if not self.documents: raise RuntimeError("Document storage service is unavailable.")
        return self.documents.simulate_tampering(document_id, user.username)

    def restore_document_tampering(self, document_id: str, user: User) -> dict:
        self.require_permission(user, "integrity:verify")
        if not self.documents: raise RuntimeError("Document storage service is unavailable.")
        return self.documents.restore_tampering(document_id, user.username)

    def verify_evidence(self, evidence_id: str, user: User) -> dict:
        self.require_permission(user, "evidence:verify")
        if not self.evidence: raise RuntimeError("Local evidence persistence is unavailable.")
        res = self.evidence.verify(evidence_id, user.username)
        if self.documents and self.documents.get_document(evidence_id):
            self.documents.verify_integrity(evidence_id, user.username)
        return res

    def verify_ledger(self, user: User) -> dict:
        self.require_permission(user, "evidence:verify")
        if not self.evidence: raise RuntimeError("Local evidence persistence is unavailable.")
        if self.documents:
            self.documents.verify_ledger(user.username)
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
