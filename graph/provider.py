"""Graph provider boundary for NetworkX now and Neo4j later."""

from abc import ABC, abstractmethod

import networkx as nx

from domain.models import DatasetSnapshot
from graph.builder import InvestigationGraphBuilder


class GraphProvider(ABC):
    @abstractmethod
    def build(self, snapshot: DatasetSnapshot) -> nx.Graph:
        raise NotImplementedError


class NetworkXGraphProvider(GraphProvider):
    def __init__(self) -> None:
        self.builder = InvestigationGraphBuilder()

    def build(self, snapshot: DatasetSnapshot) -> nx.Graph:
        return self.builder.build(snapshot)