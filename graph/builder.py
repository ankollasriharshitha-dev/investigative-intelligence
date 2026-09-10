"""Build a typed investigation graph from a normalized dataset snapshot."""

from collections.abc import Iterable
from typing import Any

import networkx as nx
import pandas as pd

from domain.models import DatasetSnapshot


ENTITY_TABLES = {
    "persons": ("person_id", "PERSON", "name"),
    "phones": ("phone_id", "PHONE", "phone_number"),
    "locations": ("location_id", "LOCATION", "label"),
    "vehicles": ("vehicle_id", "VEHICLE", "registration_number"),
    "organizations": ("organization_id", "ORGANIZATION", "name"),
    "accounts": ("account_id", "ACCOUNT", "account_label"),
}


class InvestigationGraphBuilder:
    """Convert provider output into a graph while keeping the storage boundary clean."""

    def build(self, snapshot: DatasetSnapshot) -> nx.Graph:
        graph = nx.Graph()
        cases = snapshot.documents.get("cases", [])
        for case in cases:
            case_id = str(case["case_id"])
            graph.add_node(case_id, entity_type="CASE", label=case.get("title", case_id), **case)

        for table_name, (id_column, entity_type, label_column) in ENTITY_TABLES.items():
            frame = snapshot.tables.get(table_name, pd.DataFrame())
            for row in frame.to_dict(orient="records"):
                entity_id = str(row[id_column])
                metadata = _clean_metadata(row, id_column)
                metadata.pop(label_column, None)
                graph.add_node(
                    entity_id,
                    entity_type=entity_type,
                    label=str(row.get(label_column) or entity_id),
                    **metadata,
                )

        self._add_case_links(graph, snapshot)
        self._add_entity_relationships(graph, snapshot)
        return graph

    def _add_case_links(self, graph: nx.Graph, snapshot: DatasetSnapshot) -> None:
        for table_name in ("persons", "organizations"):
            frame = snapshot.tables.get(table_name, pd.DataFrame())
            for row in frame.to_dict(orient="records"):
                for case_id in _split_ids(row.get("case_ids")):
                    self._add_edge(graph, str(row[next(iter(ENTITY_TABLES[table_name]))]), case_id, "INVOLVED_IN", row)
        for table_name in ("phones", "vehicles", "accounts"):
            frame = snapshot.tables.get(table_name, pd.DataFrame())
            id_column = ENTITY_TABLES[table_name][0]
            for row in frame.to_dict(orient="records"):
                case_id = row.get("case_id")
                if _present(case_id):
                    self._add_edge(graph, str(row[id_column]), str(case_id), "INVOLVED_IN", row)
        for table_name in ("calls", "messages", "transactions", "events"):
            frame = snapshot.tables.get(table_name, pd.DataFrame())
            for row in frame.to_dict(orient="records"):
                if _present(row.get("case_id")):
                    self._add_edge(graph, str(row[frame.columns[0]]), str(row["case_id"]), "MENTIONED_IN", row)

    def _add_entity_relationships(self, graph: nx.Graph, snapshot: DatasetSnapshot) -> None:
        for row in snapshot.tables.get("phones", pd.DataFrame()).to_dict(orient="records"):
            self._add_edge(graph, row["phone_id"], row["owner_person_id"], "OWNS", row)
        for row in snapshot.tables.get("calls", pd.DataFrame()).to_dict(orient="records"):
            self._add_edge(graph, row["caller_id"], row["receiver_id"], "CALLED", row)
        for row in snapshot.tables.get("messages", pd.DataFrame()).to_dict(orient="records"):
            self._add_edge(graph, row["sender_phone_id"], row["receiver_phone_id"], "MESSAGED", row)
        for row in snapshot.tables.get("transactions", pd.DataFrame()).to_dict(orient="records"):
            self._add_edge(graph, row["from_account"], row["to_account"], "TRANSFERRED_TO", row)
        for row in snapshot.tables.get("vehicles", pd.DataFrame()).to_dict(orient="records"):
            self._add_edge(graph, row["owner_person_id"], row["vehicle_id"], "OWNS", row)
        for row in snapshot.tables.get("accounts", pd.DataFrame()).to_dict(orient="records"):
            self._add_edge(graph, row["owner_person_id"], row["account_id"], "OWNS", row)
            if _present(row.get("organization_id")):
                self._add_edge(graph, row["account_id"], row["organization_id"], "ASSOCIATED_WITH", row)
        for row in snapshot.tables.get("events", pd.DataFrame()).to_dict(orient="records"):
            person_id = row.get("person_id")
            if not _present(person_id):
                continue
            relation_targets = {
                "LOCATED_AT": row.get("location_id"),
                "USED": row.get("vehicle_id"),
                "WORKS_FOR": row.get("organization_id"),
            }
            relation = str(row.get("event_type") or "ASSOCIATED_WITH")
            target = relation_targets.get(relation)
            if _present(target):
                self._add_edge(graph, person_id, target, relation, row)

    @staticmethod
    def _add_edge(graph: nx.Graph, source: Any, target: Any, relationship_type: str, metadata: dict[str, Any]) -> None:
        if not _present(source) or not _present(target) or source not in graph or target not in graph:
            return
        source, target = str(source), str(target)
        edge_metadata = _clean_metadata(metadata)
        if graph.has_edge(source, target):
            edge = graph[source][target]
            edge.setdefault("relationships", []).append({"type": relationship_type, **edge_metadata})
            edge.setdefault("relationship_types", []).append(relationship_type)
            edge["relationship_types"] = sorted(set(edge["relationship_types"]))
        else:
            graph.add_edge(
                source,
                target,
                relationship_type=relationship_type,
                relationship_types=[relationship_type],
                relationships=[{"type": relationship_type, **edge_metadata}],
                **edge_metadata,
            )


def _clean_metadata(values: dict[str, Any], excluded: str | None = None) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in values.items()
        if key != excluded and not pd.isna(value)
    }


def _split_ids(value: Any) -> Iterable[str]:
    if not _present(value):
        return ()
    return (item.strip() for item in str(value).split("|") if item.strip())


def _present(value: Any) -> bool:
    return value is not None and not pd.isna(value) and str(value).strip() != ""
