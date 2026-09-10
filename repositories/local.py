"""Local repository adapter; replaceable by SQL/API persistence later."""

from pathlib import Path

from domain.models import DatasetSnapshot, ValidationResult
from providers.uploaded import UploadedDataProvider
from repositories.base import DatasetRepository


class LocalUploadedRepository(DatasetRepository):
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def validate(self) -> ValidationResult:
        return UploadedDataProvider(self.data_dir).validate()

    def load_snapshot(self) -> DatasetSnapshot:
        return UploadedDataProvider(self.data_dir).load_snapshot()

    def upsert(self, snapshot: DatasetSnapshot) -> None:
        raise NotImplementedError("Local upsert is coordinated by DataManagementService")