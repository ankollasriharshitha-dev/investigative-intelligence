"""Backend-ready ingestion facade for local daily update simulation."""

from domain.models import ImportReport
from services.data_management import DataManagementService


class IngestionService:
    """Coordinates validated daily packages without claiming live infrastructure."""

    def __init__(self, data_management: DataManagementService) -> None:
        self.data_management = data_management

    def apply_daily_update(self, files: dict[str, bytes], operation: str = "append") -> ImportReport:
        if operation not in {"append", "update"}:
            raise ValueError("Daily updates support append or update operations only")
        return self.data_management.import_dataset(files, operation)

    def describe_pipeline(self) -> tuple[str, ...]:
        return ("ingestion", "validation", "normalization", "deduplication", "upsert", "provider refresh", "graph refresh", "analytics refresh")