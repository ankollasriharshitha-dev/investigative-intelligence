"""Application service boundary for investigation workflows."""

from domain.models import DataSourceInfo, DatasetSnapshot, ValidationResult
from graph.analytics import GraphAnalytics
from graph.investigative import InvestigativeAnalytics
from graph.provider import GraphProvider, NetworkXGraphProvider
from providers.base import DataProvider
from services.data_management import DataManagementService, DatasetStorageError
from services.document_ingestion import DocumentIngestionService, ExtractedDocument


class InvestigationService:
    def __init__(self, provider: DataProvider, settings=None, graph_provider: GraphProvider | None = None) -> None:
        self.provider = provider
        self._settings = settings
        self._data_management = DataManagementService(settings) if settings else None
        self._graph_provider = graph_provider or NetworkXGraphProvider()

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
        return self._graph_provider.build(self.load_active_dataset())

    def graph_analytics(self) -> GraphAnalytics:
        return GraphAnalytics(self.build_active_graph())

    def investigative_analytics(self) -> InvestigativeAnalytics:
        snapshot = self.load_active_dataset()
        return InvestigativeAnalytics(snapshot, self._graph_provider.build(snapshot))

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
            "cases": len(snapshot.documents.get("cases", [])),
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
