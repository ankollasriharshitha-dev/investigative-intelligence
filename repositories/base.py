"""Persistence contracts independent of local files or a future database."""

from abc import ABC, abstractmethod

from domain.models import DatasetSnapshot, ValidationResult


class DatasetRepository(ABC):
    @abstractmethod
    def validate(self) -> ValidationResult:
        raise NotImplementedError

    @abstractmethod
    def load_snapshot(self) -> DatasetSnapshot:
        raise NotImplementedError

    @abstractmethod
    def upsert(self, snapshot: DatasetSnapshot) -> None:
        raise NotImplementedError
