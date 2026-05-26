from __future__ import annotations

from backend.formula_graph.models import (
    Entity,
    FormulaBlock,
    GraphEdge,
    GraphNode,
    KnowledgeGraph,
    Relation,
    TextBlock,
)


def build_graph(text_blocks: list[TextBlock], formulas: list[FormulaBlock], entities: list[Entity], relations: list[Relation]) -> KnowledgeGraph:
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    for block in text_blocks:
        nodes.append(
            GraphNode(
                id=block.id,
                label=_short(block.text),
                kind="text_block",
                payload=block.model_dump(),
            )
        )
    for formula in formulas:
        nodes.append(
            GraphNode(
                id=formula.id,
                label=formula.latex,
                kind=f"formula_{formula.kind}",
                payload=formula.model_dump(),
            )
        )
    for entity in entities:
        nodes.append(
            GraphNode(
                id=entity.id,
                label=entity.label,
                kind=entity.kind,
                payload=entity.model_dump(),
            )
        )
    for relation in relations:
        edges.append(
            GraphEdge(
                id=relation.id,
                source=relation.source_id,
                target=relation.target_id,
                label=relation.kind,
                payload=relation.model_dump(),
            )
        )
    return KnowledgeGraph(nodes=nodes, edges=edges)


def _short(text: str, limit: int = 80) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "..."
