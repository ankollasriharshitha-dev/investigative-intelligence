"""Explainable investigative analytics built from the active snapshot and graph."""

from dataclasses import dataclass
from typing import Any

import networkx as nx
import pandas as pd

from domain.models import DatasetSnapshot
from graph.analytics import GraphAnalytics


@dataclass(frozen=True)
class InvestigativeLead:
    lead_id: str
    lead_type: str
    entities: tuple[str, ...]
    cases: tuple[str, ...]
    reason: str
    evidence: str
    metrics: dict[str, float | int | str]
    priority: str
    status: str = "Requires Verification"


class InvestigativeAnalytics:
    def __init__(self, snapshot: DatasetSnapshot, graph: nx.Graph) -> None:
        self.snapshot = snapshot
        self.graph = graph
        self.graph_analytics = GraphAnalytics(graph)
        self._centrality_rows: list[dict[str, Any]] | None = None

    def centrality(self) -> list[dict[str, Any]]:
        if self._centrality_rows is not None:
            return self._centrality_rows
        degree = nx.degree_centrality(self.graph)
        betweenness = nx.betweenness_centrality(self.graph, normalized=True)
        closeness = nx.closeness_centrality(self.graph)
        pagerank = nx.pagerank(self.graph) if self.graph else {}
        rows = []
        for node, data in self.graph.nodes(data=True):
            score = self._significance(degree.get(node, 0.0), betweenness.get(node, 0.0), pagerank.get(node, 0.0))
            rows.append({
                "entity_id": node, "label": data.get("label", node),
                "entity_type": data.get("entity_type", "UNKNOWN"), "degree": self.graph.degree(node),
                "degree_centrality": degree.get(node, 0.0), "betweenness": betweenness.get(node, 0.0),
                "closeness": closeness.get(node, 0.0), "pagerank": pagerank.get(node, 0.0),
                "network_significance": score,
                "cases": tuple(self._cases_for(node)),
            })
        self._centrality_rows = sorted(rows, key=lambda row: row["network_significance"], reverse=True)
        return self._centrality_rows

    def clusters(self) -> list[dict[str, Any]]:
        if not self.graph:
            return []
        communities = nx.community.greedy_modularity_communities(self.graph)
        membership = {node: index for index, community in enumerate(communities, start=1) for node in community}
        results = []
        for index, community in enumerate(communities, start=1):
            entity_types = pd.Series([self.graph.nodes[node].get("entity_type", "UNKNOWN") for node in community]).value_counts().to_dict()
            significant = sorted(community, key=lambda node: self._row_for(node)["network_significance"], reverse=True)[:5]
            cross_edges = sum(1 for source, target in self.graph.edges(community) if membership.get(source) != membership.get(target)) // 2
            results.append({"cluster_id": f"CLUSTER-{index:02d}", "size": len(community), "major_entity_types": dict(entity_types), "significant_entities": significant, "cross_cluster_connections": cross_edges, "entities": sorted(community)})
        return results

    def communication_activity(self) -> list[dict[str, Any]]:
        rows = []
        phones = self.snapshot.tables.get("phones", pd.DataFrame())
        owner_by_phone = dict(zip(phones.get("phone_id", []), phones.get("owner_person_id", [])))
        for table_name, source_column, target_column in (("calls", "caller_id", "receiver_id"), ("messages", "sender_phone_id", "receiver_phone_id")):
            frame = self.snapshot.tables.get(table_name, pd.DataFrame())
            for row in frame.to_dict(orient="records"):
                source = owner_by_phone.get(row.get(source_column), row.get(source_column))
                target = owner_by_phone.get(row.get(target_column), row.get(target_column))
                rows.append({"record_type": table_name[:-1].upper(), "source": source, "target": target, "case_id": row.get("case_id"), "timestamp": row.get("timestamp")})
        if not rows:
            return []
        frame = pd.DataFrame(rows)
        counts = frame["source"].value_counts().add(frame["target"].value_counts(), fill_value=0)
        baseline = counts.mean()
        return [{"entity_id": str(entity), "communication_count": int(count), "unique_contacts": len(set(frame.loc[(frame.source == entity) | (frame.target == entity), "source"].tolist() + frame.loc[(frame.source == entity) | (frame.target == entity), "target"].tolist()) - {entity}), "signal": "High communication activity" if count > baseline * 1.5 else "Observed communication activity", "cases": sorted(frame.loc[(frame.source == entity) | (frame.target == entity), "case_id"].dropna().unique())} for entity, count in counts.items()]

    def transaction_activity(self) -> list[dict[str, Any]]:
        frame = self.snapshot.tables.get("transactions", pd.DataFrame()).copy()
        if frame.empty:
            return []
        frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce").fillna(0)
        outgoing = frame.groupby("from_account").agg(transaction_count=("transaction_id", "count"), total_value=("amount", "sum"), cases=("case_id", lambda values: sorted(set(values))))
        count_baseline = outgoing["transaction_count"].mean()
        value_baseline = outgoing["total_value"].mean()
        return [{"entity_id": str(entity), "transaction_count": int(row.transaction_count), "total_value": float(row.total_value), "cases": tuple(row.cases), "signal": "Potential Unusual Transaction Pattern" if row.transaction_count > count_baseline * 1.5 or row.total_value > value_baseline * 1.5 else "Observed transaction activity"} for entity, row in outgoing.iterrows()]

    def location_associations(self) -> list[dict[str, Any]]:
        events = self.snapshot.tables.get("events", pd.DataFrame())
        if events.empty or "location_id" not in events:
            return []
        grouped = events.dropna(subset=["location_id"]).groupby("location_id")
        return [{"location_id": str(location), "entities": sorted(set(group["person_id"].dropna())), "cases": sorted(set(group["case_id"].dropna())), "event_count": len(group), "signal": "Potential Cross-Case Location Association" if group["case_id"].nunique() > 1 else "Potential Location Association"} for location, group in grouped if len(set(group["person_id"].dropna())) > 1]

    def vehicle_associations(self) -> list[dict[str, Any]]:
        vehicles = self.snapshot.tables.get("vehicles", pd.DataFrame())
        if vehicles.empty:
            return []
        return [{"vehicle_id": str(row.vehicle_id), "entities": [row.owner_person_id], "cases": [row.case_id], "signal": "Potential Vehicle Association"} for row in vehicles.itertuples()]

    def leads(self) -> list[InvestigativeLead]:
        leads: list[InvestigativeLead] = []
        for row in self.centrality()[:8]:
            if row["entity_type"] in {"CASE", "EVIDENCE", "EVENT"}:
                continue
            if row["network_significance"] < 0.15:
                continue
            bridge = row["betweenness"] >= 0.05
            leads.append(InvestigativeLead(f"LEAD-{len(leads) + 1:03d}", "NETWORK_BRIDGE" if bridge else "HIGH_NETWORK_SIGNIFICANCE", (str(row["entity_id"]),), tuple(row["cases"]), "Potential network significance based on explainable graph metrics.", f"Degree centrality={row['degree_centrality']:.3f}; betweenness={row['betweenness']:.3f}; PageRank={row['pagerank']:.3f}.", {"network_significance": row["network_significance"]}, "High" if bridge else "Medium"))
        for activity in self.communication_activity():
            if activity["signal"] == "High communication activity":
                leads.append(InvestigativeLead(f"LEAD-{len(leads) + 1:03d}", "UNUSUAL_COMMUNICATION", (str(activity["entity_id"]),), tuple(activity["cases"]), "Communication activity is high relative to the active dataset baseline.", f"Observed {activity['communication_count']} communication records and {activity['unique_contacts']} unique contacts.", {"communication_count": activity["communication_count"]}, "Medium"))
        for activity in self.transaction_activity():
            if activity["signal"] == "Potential Unusual Transaction Pattern":
                leads.append(InvestigativeLead(f"LEAD-{len(leads) + 1:03d}", "UNUSUAL_TRANSACTION", (str(activity["entity_id"]),), tuple(activity["cases"]), "Transaction count or total value is high relative to the active dataset baseline.", f"Observed {activity['transaction_count']} outgoing transfers totaling {activity['total_value']:.2f} synthetic units.", {"transaction_count": activity["transaction_count"], "total_value": activity["total_value"]}, "Medium"))
        for item in self.graph_analytics.cross_case_entities():
            leads.append(InvestigativeLead(f"LEAD-{len(leads) + 1:03d}", "CROSS_CASE_ASSOCIATION", (str(item["entity_id"]),), tuple(item["cases"]), "The entity is connected to more than one case in the active graph.", f"Case associations: {', '.join(item['cases'])}.", {"case_count": len(item["cases"])}, "Medium"))
        return leads

    def _row_for(self, node: str) -> dict[str, Any]:
        return next(row for row in self.centrality() if row["entity_id"] == node)

    def _cases_for(self, node: str) -> list[str]:
        return sorted(neighbor for neighbor in self.graph.neighbors(node) if self.graph.nodes[neighbor].get("entity_type") == "CASE")

    @staticmethod
    def _significance(degree: float, betweenness: float, pagerank: float) -> float:
        return round(100 * (0.35 * degree + 0.40 * betweenness + 0.25 * pagerank), 3)
