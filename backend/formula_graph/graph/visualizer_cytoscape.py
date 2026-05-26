from __future__ import annotations

from collections import Counter
from typing import Any

from backend.formula_graph.graph.metagraph_model import Metagraph


VISUALIZATION_MODES = {
    "document_structure",
    "formula_semantic",
    "metagraph_overview",
    "metagraph_fragments",
}


def export_cytoscape_elements(metagraph: Metagraph, mode: str = "metagraph_overview", limit: int = 900) -> dict[str, Any]:
    mode = mode if mode in VISUALIZATION_MODES else "metagraph_overview"
    node_ids = _select_node_ids(metagraph, mode, limit)
    metavertex_ids = _select_metavertex_ids(metagraph, mode, node_ids)
    edge_ids = _select_edge_ids(metagraph, mode, node_ids, metavertex_ids, limit)
    metaedge_ids = _select_metaedge_ids(metagraph, mode, node_ids, edge_ids, limit)

    elements: list[dict[str, object]] = []
    parent_map = _parent_map(metagraph)
    for mv_id in metavertex_ids:
        metavertex = metagraph.metavertices[mv_id]
        elements.append(
            {
                "data": {
                    "id": metavertex.id,
                    "label": metavertex.label,
                    "type": metavertex.type,
                    "attributes": metavertex.attributes,
                    "contains": metavertex.contains,
                    "entry_points": metavertex.entry_points,
                    "exit_points": metavertex.exit_points,
                }
            }
        )
    for node_id in node_ids:
        node = metagraph.nodes[node_id]
        data: dict[str, object] = {
            "id": node.id,
            "label": _display_label(node.type, node.id, node.label),
            "type": node.type,
            "attributes": node.attributes,
        }
        if node.type == "formula":
            data["latex"] = node.label
        if node.type in {"paragraph", "context", "definition", "section"}:
            data["text"] = node.label
        parent = parent_map.get(node.id)
        if parent in metavertex_ids and mode != "metagraph_fragments":
            data["parent"] = parent
        elements.append({"data": data})

    for edge_id in edge_ids:
        edge = metagraph.edges[edge_id]
        elements.append(
            {
                "data": {
                    "id": edge.id,
                    "source": edge.source,
                    "target": edge.target,
                    "label": edge.type,
                    "type": edge.type,
                    "attributes": edge.attributes,
                }
            }
        )

    for metaedge_id in metaedge_ids:
        metaedge = metagraph.metaedges[metaedge_id]
        elements.append(
            {
                "data": {
                    "id": metaedge.id,
                    "label": metaedge.type,
                    "type": "metaedge",
                    "attributes": {
                        **metaedge.attributes,
                        "metaedge_type": metaedge.type,
                        "source_set": metaedge.source_set,
                        "target_set": metaedge.target_set,
                        "mediator_nodes": metaedge.mediator_nodes,
                        "mediator_metavertices": metaedge.mediator_metavertices,
                        "contains": metaedge.contains,
                    },
                }
            }
        )
        for source in metaedge.source_set:
            if source in node_ids or source in metavertex_ids:
                elements.append(
                    {
                        "data": {
                            "id": f"{metaedge.id}:source:{source}",
                            "source": source,
                            "target": metaedge.id,
                            "label": metaedge.type,
                            "type": "metaedge_source",
                        }
                    }
                )
        for target in metaedge.target_set:
            if target in node_ids or target in metavertex_ids:
                elements.append(
                    {
                        "data": {
                            "id": f"{metaedge.id}:target:{target}",
                            "source": metaedge.id,
                            "target": target,
                            "label": metaedge.type,
                            "type": "metaedge_target",
                        }
                    }
                )

    node_elements = [item for item in elements if "source" not in item["data"]]
    edge_elements = [item for item in elements if "source" in item["data"]]
    return {
        "mode": mode,
        "elements": elements,
        "stats": {
            "original_node_count": len(metagraph.nodes) + len(metagraph.metavertices) + len(metagraph.metaedges),
            "original_edge_count": len(metagraph.edges),
            "node_count": len(node_elements),
            "edge_count": len(edge_elements),
            "total_element_count": len(elements),
            "truncated": len(node_ids) < len(metagraph.nodes) or len(edge_ids) < len(metagraph.edges),
            "node_types": dict(Counter(item["data"].get("type") for item in node_elements)),
        },
    }


def _select_node_ids(metagraph: Metagraph, mode: str, limit: int) -> set[str]:
    if mode == "document_structure":
        allowed = {"paper", "section", "paragraph", "title", "abstract", "heading"}
    elif mode == "formula_semantic":
        allowed = {"formula", "symbol", "context", "definition", "operator"}
    elif mode == "metagraph_fragments":
        allowed = {"paper", "section", "formula", "symbol", "context", "definition", "subexpression", "operator"}
    else:
        allowed = {"paper", "section", "paragraph", "formula", "symbol", "context", "definition", "source", "quality_issue"}

    candidates = [node for node in metagraph.nodes.values() if node.type in allowed]
    candidates.sort(key=lambda node: _node_rank(node), reverse=True)
    selected = {node.id for node in candidates[:limit]}
    if mode == "formula_semantic":
        selected.update(node.id for node in candidates if node.type == "formula")
    return selected


def _select_metavertex_ids(metagraph: Metagraph, mode: str, node_ids: set[str]) -> set[str]:
    if mode == "formula_semantic":
        return {mv.id for mv in metagraph.metavertices.values() if mv.type in {"formula_metavertex", "definition_context_metavertex"} and set(mv.contains).intersection(node_ids)}
    if mode == "document_structure":
        return {mv.id for mv in metagraph.metavertices.values() if mv.type in {"paper_metavertex", "section_metavertex", "paragraph_metavertex"}}
    if mode == "metagraph_fragments":
        return {mv.id for mv in metagraph.metavertices.values() if mv.type in {"paper_metavertex", "section_metavertex", "formula_metavertex", "definition_context_metavertex"} and set(mv.contains).intersection(node_ids)}
    return {mv.id for mv in metagraph.metavertices.values() if mv.type in {"paper_metavertex", "section_metavertex", "formula_metavertex", "definition_context_metavertex"} and set(mv.contains).intersection(node_ids)}


def _select_edge_ids(metagraph: Metagraph, mode: str, node_ids: set[str], metavertex_ids: set[str], limit: int) -> set[str]:
    visible = node_ids | metavertex_ids
    edge_type_allow = None
    if mode == "formula_semantic":
        edge_type_allow = {"has_symbol", "has_context", "has_definition", "formula_contains_variable", "variable_defined_in_context", "depends_on", "has_operator"}
    elif mode == "document_structure":
        edge_type_allow = {"contains", "text_block_in_section", "formula_in_section", "formula_near_text_block"}
    elif mode == "metagraph_fragments":
        edge_type_allow = {"contains", "has_symbol", "has_context", "has_definition", "depends_on", "has_subexpression", "ast_contains", "ast_lhs", "ast_rhs", "has_operator"}
    result: list[str] = []
    for edge in metagraph.edges.values():
        if edge.source not in visible or edge.target not in visible:
            continue
        if edge_type_allow is not None and edge.type not in edge_type_allow:
            continue
        result.append(edge.id)
        if len(result) >= limit * 2:
            break
    return set(result)


def _select_metaedge_ids(metagraph: Metagraph, mode: str, node_ids: set[str], edge_ids: set[str], limit: int) -> set[str]:
    if mode not in {"metagraph_overview", "metagraph_fragments", "formula_semantic"}:
        return set()
    result: list[str] = []
    for metaedge in metagraph.metaedges.values():
        if set(metaedge.source_set).intersection(node_ids) or set(metaedge.target_set).intersection(node_ids) or set(metaedge.contains).intersection(edge_ids):
            result.append(metaedge.id)
        if len(result) >= max(40, limit // 6):
            break
    return set(result)


def _parent_map(metagraph: Metagraph) -> dict[str, str]:
    result: dict[str, str] = {}
    for metavertex in metagraph.metavertices.values():
        for child in metavertex.contains:
            result.setdefault(child, metavertex.id)
    return result


def _node_rank(node) -> float:
    attrs = node.attributes or {}
    return float(attrs.get("mass", 1.0)) + (20 if node.type == "paper" else 0) + (10 if node.type == "section" else 0) + (6 if node.type == "formula" else 0)


def _display_label(node_type: str, node_id: str, label: str) -> str:
    if node_type in {"formula", "paragraph", "context", "definition"}:
        return node_id
    return label
