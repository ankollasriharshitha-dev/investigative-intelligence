"""Graph presentation helpers kept outside the frontend implementation."""

from collections import defaultdict
from typing import Any

import networkx as nx
import plotly.graph_objects as go


TYPE_COLORS = {
    "PERSON": "#42b9c6", "PHONE": "#7da7d9", "LOCATION": "#d6a85f",
    "VEHICLE": "#a88bc4", "ORGANIZATION": "#79b68a", "ACCOUNT": "#d78e78",
    "CASE": "#e0e6eb", "EVENT": "#8d9aa8",
}


def filter_graph(graph: Any, case: str, entity_type: str, relationship: str, minimum_degree: int) -> Any:
    keep_nodes = set(graph.nodes)
    if case != "All cases":
        keep_nodes = {node for node in keep_nodes if node == case or case in set(graph.neighbors(node))}
    if entity_type != "All entity types":
        keep_nodes = {node for node in keep_nodes if graph.nodes[node].get("entity_type") == entity_type}
    filtered = graph.subgraph(keep_nodes).copy()
    if relationship != "All relationship types":
        filtered.remove_edges_from([(u, v) for u, v, data in filtered.edges(data=True) if relationship not in data.get("relationship_types", [])])
        filtered.remove_nodes_from(list(nx.isolates(filtered)))
    if minimum_degree:
        filtered.remove_nodes_from([node for node in filtered if filtered.degree(node) < minimum_degree])
    return filtered


def network_figure(graph: Any) -> go.Figure:
    positions = nx.spring_layout(graph, seed=42, k=1.25) if graph else {}
    edge_x, edge_y = [], []
    for source, target in graph.edges:
        edge_x += [positions[source][0], positions[target][0], None]
        edge_y += [positions[source][1], positions[target][1], None]
    figure = go.Figure(go.Scatter(x=edge_x, y=edge_y, mode="lines", line={"color": "#344653", "width": 1}, hoverinfo="none"))
    nodes_by_type: defaultdict[str, list[str]] = defaultdict(list)
    for node, data in graph.nodes(data=True):
        nodes_by_type[str(data.get("entity_type", "UNKNOWN"))].append(node)
    for entity_type, nodes in nodes_by_type.items():
        figure.add_trace(go.Scatter(
            x=[positions[node][0] for node in nodes], y=[positions[node][1] for node in nodes], mode="markers+text",
            text=[graph.nodes[node].get("label", node) for node in nodes], textposition="top center", name=entity_type,
            customdata=nodes, marker={"size": 13, "color": TYPE_COLORS.get(entity_type, "#8d9aa8"), "line": {"color": "#0b1117", "width": 1}},
            hovertemplate="%{customdata}<br>%{text}<extra>" + entity_type + "</extra>",
        ))
    figure.update_layout(template="plotly_dark", height=650, paper_bgcolor="#0b1117", plot_bgcolor="#0b1117", margin={"l": 0, "r": 0, "t": 20, "b": 0}, legend={"orientation": "h"}, xaxis={"visible": False}, yaxis={"visible": False})
    return figure


def path_relationships(graph: Any, path: list[str]) -> list[str]:
    return ["/".join(graph[path[index]][path[index + 1]].get("relationship_types", ["CONNECTED_TO"])) for index in range(len(path) - 1)]
