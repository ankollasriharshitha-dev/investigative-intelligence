"""Reusable graph analytics for investigative decision support."""

from dataclasses import dataclass

import networkx as nx


@dataclass(frozen=True)
class NetworkLead:
    lead_id: str
    entities: tuple[str, ...]
    lead_type: str
    reason: str
    evidence: str
    cases: tuple[str, ...]
    significance: str
    status: str = "Requires Verification"


class GraphAnalytics:
    def __init__(self, graph: nx.Graph) -> None:
        self.graph = graph

    def centrality(self) -> list[dict[str, object]]:
        degree = nx.degree_centrality(self.graph)
        betweenness = nx.betweenness_centrality(self.graph, normalized=True)
        pagerank = nx.pagerank(self.graph) if self.graph else {}
        rows = []
        for node in self.graph.nodes:
            rows.append({
                "entity_id": node,
                "label": self.graph.nodes[node].get("label", node),
                "entity_type": self.graph.nodes[node].get("entity_type", "UNKNOWN"),
                "degree": self.graph.degree(node),
                "degree_centrality": degree.get(node, 0.0),
                "betweenness": betweenness.get(node, 0.0),
                "pagerank": pagerank.get(node, 0.0),
            })
        return sorted(rows, key=lambda row: (row["betweenness"], row["pagerank"]), reverse=True)

    def connected_components(self) -> list[set[str]]:
        return sorted((set(component) for component in nx.connected_components(self.graph)), key=len, reverse=True)

    def shortest_path(self, source: str, target: str) -> list[str] | None:
        if source not in self.graph or target not in self.graph:
            return None
        try:
            return nx.shortest_path(self.graph, source, target)
        except nx.NetworkXNoPath:
            return None

    def hop_connections(self, source: str, hops: int) -> list[list[str]]:
        if source not in self.graph:
            return []
        paths: list[list[str]] = []
        for target, path_length in nx.single_source_shortest_path_length(self.graph, source, cutoff=hops).items():
            if target != source and path_length == hops:
                paths.append(nx.shortest_path(self.graph, source, target))
        return sorted(paths, key=lambda path: path[-1])

    def cross_case_entities(self) -> list[dict[str, object]]:
        results = []
        for node, data in self.graph.nodes(data=True):
            cases = sorted(neighbor for neighbor in self.graph.neighbors(node) if self.graph.nodes[neighbor].get("entity_type") == "CASE")
            if len(cases) > 1:
                results.append({"entity_id": node, "label": data.get("label", node), "entity_type": data.get("entity_type"), "cases": cases})
        return results

    def leads(self) -> list[NetworkLead]:
        cross_case = {item["entity_id"]: item["cases"] for item in self.cross_case_entities()}
        centrality = self.centrality()
        leads: list[NetworkLead] = []
        for rank, row in enumerate(centrality[:5], start=1):
            entity_id = str(row["entity_id"])
            if row["degree"] < 3 and entity_id not in cross_case:
                continue
            reasons = []
            if row["degree"] >= 3:
                reasons.append("high relationship count")
            if row["betweenness"] >= 0.05:
                reasons.append("potential bridge position")
            if entity_id in cross_case:
                reasons.append("repeated cross-case association")
            leads.append(NetworkLead(
                lead_id=f"LEAD-{rank:03d}",
                entities=(entity_id,),
                lead_type="Potential Investigative Lead",
                reason="Network significance requires verification.",
                evidence="; ".join(reasons) or "network position",
                cases=tuple(cross_case.get(entity_id, self._cases_for(entity_id))),
                significance="Potential Bridge Entity" if row["betweenness"] >= 0.05 else "Network Significance",
            ))
        return leads

    def _cases_for(self, node: str) -> list[str]:
        return sorted(neighbor for neighbor in self.graph.neighbors(node) if self.graph.nodes[neighbor].get("entity_type") == "CASE")
