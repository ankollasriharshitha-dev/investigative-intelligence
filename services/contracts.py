"""Backend-ready application service contracts for a future API layer."""

from typing import Protocol

from domain.models import DatasetSnapshot


class DatasetServiceContract(Protocol):
    def current_snapshot(self) -> DatasetSnapshot: ...


class GraphServiceContract(Protocol):
    def build_active_graph(self): ...


class AnalyticsServiceContract(Protocol):
    def investigative_analytics(self): ...


class LeadServiceContract(Protocol):
    def investigative_analytics(self): ...