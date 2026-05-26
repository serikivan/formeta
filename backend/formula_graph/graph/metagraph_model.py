from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Node:
    id: str
    type: str
    label: str
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class MetaVertex:
    id: str
    type: str
    label: str
    contains: list[str] = field(default_factory=list)
    entry_points: list[str] = field(default_factory=list)
    exit_points: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class Edge:
    id: str
    source: str
    target: str
    type: str
    directed: bool = True
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class MetaEdge:
    id: str
    type: str
    source_set: list[str]
    target_set: list[str]
    mediator_nodes: list[str] = field(default_factory=list)
    mediator_metavertices: list[str] = field(default_factory=list)
    contains: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class Metagraph:
    nodes: dict[str, Node] = field(default_factory=dict)
    metavertices: dict[str, MetaVertex] = field(default_factory=dict)
    edges: dict[str, Edge] = field(default_factory=dict)
    metaedges: dict[str, MetaEdge] = field(default_factory=dict)
    fragments: dict[str, dict[str, Any]] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def add_node(self, node: Node) -> None:
        self.nodes[node.id] = node

    def add_metavertex(self, metavertex: MetaVertex) -> None:
        self.metavertices[metavertex.id] = metavertex

    def add_edge(self, edge: Edge) -> None:
        self.edges[edge.id] = edge

    def add_metaedge(self, metaedge: MetaEdge) -> None:
        self.metaedges[metaedge.id] = metaedge

    def ensure_contains_edge(self, parent_id: str, child_id: str) -> None:
        edge_id = f"contains:{parent_id}->{child_id}"
        if edge_id not in self.edges:
            self.add_edge(Edge(id=edge_id, source=parent_id, target=child_id, type="contains"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.1",
            "nodes": [asdict(value) for value in self.nodes.values()],
            "metavertices": [asdict(value) for value in self.metavertices.values()],
            "edges": [asdict(value) for value in self.edges.values()],
            "metaedges": [asdict(value) for value in self.metaedges.values()],
            "fragments": list(self.fragments.values()),
            "metrics": self.metrics,
            "provenance": self.provenance,
        }
