"""Provider boundary. Storage implementations must satisfy this interface."""

from abc import ABC, abstractmethod

from domain.models import DatasetSnapshot, DataSourceInfo, ValidationResult


class DataProvider(ABC):
    """Read-only dataset contract consumed by application services."""

    @abstractmethod
    def get_source_info(self) -> DataSourceInfo:
        raise NotImplementedError

    @abstractmethod
    def validate(self) -> ValidationResult:
        raise NotImplementedError

    @abstractmethod
    def load_snapshot(self) -> DatasetSnapshot:
        raise NotImplementedError
