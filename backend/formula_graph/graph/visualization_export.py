from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from backend.formula_graph.export.graph_ready_export import GraphReadyDocument, normalize_symbol
from backend.formula_graph.graph.graph_ready_metagraph import build_metagraph_from_graph_ready
from backend.formula_graph.graph.metagraph_model import Edge, MetaEdge, MetaVertex, Metagraph, Node


PLANETARY_LAYOUT_DOC = (
    "Идея раскладки основана на планетарной модели визуализации метаграфов из визуализация.pdf: "
    "метавершины рассматриваются как системы, вложенные узлы - как связанные тела, "
    "а масса влияет на размер и силу группировки."
)

VISUALIZATION_MODES = {
    "overview",
    "metagraph_planetary_overview",
    "document_hierarchy",
    "formula_semantic_network",
    "formula_context",
    "variable_focus",
    "metaedges_view",
    "formula_ast_focus",
    "document_structure",
    "metagraph_planetary",
    "formula_contexts",
    "formula_ast",
    "metaedges",
    "variable_neighborhood",
    "extraction_evidence",
    "corpus_graph",
    # Backward-compatible aliases used by the existing UI/tests.
    "graph_view",
    "metagraph_view",
    "formula_context_view",
    "variable_neighborhood_view",
    "extraction_evidence_view",
    "document_structure_view",
    "formula_semantic",
    "metagraph_overview",
    "metagraph_fragments",
}

MODE_ALIASES = {
    "metagraph_planetary": "metagraph_planetary_overview",
    "document_structure": "document_hierarchy",
    "formula_contexts": "formula_context",
    "formula_ast": "formula_ast_focus",
    "metaedges": "metaedges_view",
    "variable_neighborhood": "variable_focus",
    "graph_view": "overview",
    "metagraph_view": "metagraph_planetary_overview",
    "formula_context_view": "formula_context",
    "variable_neighborhood_view": "variable_focus",
    "extraction_evidence_view": "extraction_evidence",
    "document_structure_view": "document_hierarchy",
    "formula_semantic": "formula_semantic_network",
    "metagraph_overview": "metagraph_planetary_overview",
    "metagraph_fragments": "formula_ast_focus",
}

STRUCTURAL_EDGE_TYPES = {"contains", "text_block_in_section", "formula_in_section", "formula_near_text_block"}
AST_EDGE_TYPES = {"has_subexpression", "has_operator", "ast_contains", "ast_lhs", "ast_rhs"}
TECHNICAL_EDGE_TYPES = STRUCTURAL_EDGE_TYPES | AST_EDGE_TYPES | {"extracted_from", "metaedge_source", "metaedge_target"}
SEMANTIC_EDGE_TYPES = {
    "has_symbol",
    "has_context",
    "has_definition",
    "defined_as",
    "depends_on",
    "formula_contains_variable",
    "variable_defined_in_context",
}

NODE_TYPE_MAP = {
    "paper": "document",
    "symbol": "symbol",
    "quality_issue": "issue",
    "subexpression": "fragment",
    "operator": "fragment",
}

NODE_TYPE_WEIGHTS = {
    "document": 80,
    "section": 46,
    "paragraph": 22,
    "formula": 54,
    "symbol": 44,
    "context": 38,
    "definition": 42,
    "fragment": 16,
    "source": 12,
    "issue": 18,
    "metaedge": 36,
}

EDGE_TYPE_WEIGHTS = {
    "contains": 0.35,
    "has_symbol": 1.35,
    "has_context": 1.45,
    "has_definition": 1.55,
    "defined_as": 1.55,
    "depends_on": 1.65,
    "ast_contains": 0.8,
    "ast_lhs": 1.0,
    "ast_rhs": 1.0,
    "extracted_from": 0.7,
}

METAEDGE_TYPE_WEIGHTS = {
    "definition_context": 2.1,
    "notation_scope": 1.8,
    "formula_dependency": 2.0,
    "paragraph_formula_context": 1.6,
    "extraction_evidence": 0.9,
}


MODE_META = {
    "overview": (
        "Обзор статьи",
        "Главные разделы, формулы, переменные и контекстные группы без служебных связей.",
    ),
    "metagraph_planetary_overview": (
        "Планетарный метаграф",
        "Вложенность статьи показана размещением: документ, разделы, формулы, переменные и контексты.",
    ),
    "document_hierarchy": (
        "Структура документа",
        "Дерево документа: статья, разделы, абзацы и формулы без семантического шума.",
    ),
    "formula_semantic_network": (
        "Формулы и переменные",
        "Семантическая сеть формул, переменных, определений, контекстов и зависимостей.",
    ),
    "formula_context": (
        "Контекст формулы",
        "Локальная проекция одной формулы: переменные, определения, контекст и связанные формулы.",
    ),
    "variable_focus": (
        "Связи переменной",
        "Ego-проекция выбранной переменной с формулами, контекстами и зависимостями.",
    ),
    "metaedges_view": (
        "Метаребра",
        "Многоместные отношения вынесены в отдельную grouped/bipartite-проекцию.",
    ),
    "formula_ast_focus": (
        "Фрагмент формулы",
        "AST показывается только для одной выбранной формулы.",
    ),
}


def normalize_visualization_mode(mode: str | None) -> str:
    mode = mode or "overview"
    seen: set[str] = set()
    while mode in MODE_ALIASES and mode not in seen:
        seen.add(mode)
        mode = MODE_ALIASES[mode]
    return mode if mode in {MODE_ALIASES.get(item, item) for item in VISUALIZATION_MODES} else "overview"


def export_visualization_payload(
    doc: GraphReadyDocument,
    *,
    mode: str = "overview",
    limit: int = 420,
    variable: str | None = None,
    formula: str | None = None,
    depth: int = 2,
    include_technical: bool = False,
) -> dict[str, Any]:
    rich = build_metagraph_from_graph_ready(doc)
    requested_mode = mode or "overview"
    normalized_mode = normalize_visualization_mode(mode)
    limit = max(40, min(int(limit or 420), 900))
    depth = max(1, min(int(depth or 2), 4))

    if normalized_mode == "variable_focus":
        payload = export_variable_neighborhood_payload(
            doc,
            rich,
            variable=variable or "",
            limit=limit,
            depth=depth,
            include_technical=include_technical,
        )
        if requested_mode in MODE_ALIASES:
            payload["requested_mode"] = requested_mode
        else:
            payload["mode"] = normalized_mode
        payload["canonical_mode"] = normalized_mode
        return payload

    if normalized_mode == "corpus_graph":
        payload = _empty_payload(
            doc.document_id,
            normalized_mode,
            limit,
            message="Corpus graph is available through /api/corpus/{corpus_id}/visualization.",
        )
        if requested_mode in MODE_ALIASES:
            payload["requested_mode"] = requested_mode
        return payload

    node_ids, metavertex_ids, metaedge_ids = _select_for_mode(
        rich,
        normalized_mode,
        limit,
        include_technical,
        formula=formula,
    )
    payload = _build_payload(
        doc.document_id,
        requested_mode if requested_mode in MODE_ALIASES else normalized_mode,
        rich,
        node_ids=node_ids,
        metavertex_ids=metavertex_ids,
        metaedge_ids=metaedge_ids,
        limit=limit,
        variable=None,
        formula=formula,
        empty_reason=None,
        canonical_mode=normalized_mode,
    )
    if requested_mode in MODE_ALIASES:
        payload["canonical_mode"] = normalized_mode
    return payload


def export_variable_neighborhood_payload(
    doc: GraphReadyDocument,
    rich: Metagraph | None = None,
    *,
    variable: str,
    limit: int = 420,
    depth: int = 2,
    include_technical: bool = True,
) -> dict[str, Any]:
    rich = rich or build_metagraph_from_graph_ready(doc)
    normalized = normalize_symbol(variable)
    variable = variable.strip()
    candidates = _available_variables(doc)
    matched = [item for item in doc.variables if item.normalized_symbol == normalized or item.symbol == variable]
    if not matched:
        payload = _empty_payload(
            doc.document_id,
            "variable_neighborhood",
            limit,
            variable=variable,
            message="Variable not found in document.",
        )
        payload["available_variables"] = candidates[:120]
        payload["suggestions"] = _variable_suggestions(variable, candidates)
        return payload

    selected_var = matched[0]
    symbol_id = _symbol_node_id(selected_var.normalized_symbol)
    node_ids: set[str] = {symbol_id}
    metavertex_ids: set[str] = set()
    metaedge_ids: set[str] = set()

    context_by_formula = {ctx.formula_id: ctx for ctx in doc.formula_contexts}
    context_by_id = {ctx.id: ctx for ctx in doc.formula_contexts}
    formula_ids = set(selected_var.formula_ids)
    for formula_id in formula_ids:
        _add_if_exists(node_ids, rich.nodes, formula_id)
        formula_mv = f"{formula_id}_mv"
        _add_if_exists(metavertex_ids, rich.metavertices, formula_mv)
        ctx = context_by_formula.get(formula_id)
        if ctx:
            _add_context_family(node_ids, metavertex_ids, rich, ctx)
        if depth >= 2:
            for edge in rich.edges.values():
                if edge.type == "depends_on" and (edge.source == formula_id or edge.target == formula_id):
                    _add_if_exists(node_ids, rich.nodes, edge.source)
                    _add_if_exists(node_ids, rich.nodes, edge.target)
                    _add_if_exists(metavertex_ids, rich.metavertices, f"{edge.source}_mv")
                    _add_if_exists(metavertex_ids, rich.metavertices, f"{edge.target}_mv")

    for context_id in selected_var.context_ids:
        ctx = context_by_id.get(context_id)
        if ctx:
            _add_context_family(node_ids, metavertex_ids, rich, ctx)

    for section_id in selected_var.section_ids:
        _add_if_exists(node_ids, rich.nodes, section_id)
        _add_if_exists(metavertex_ids, rich.metavertices, f"{section_id}_mv")

    for paragraph in doc.paragraphs:
        if formula_ids.intersection(paragraph.formula_ids):
            _add_if_exists(node_ids, rich.nodes, paragraph.id)
            _add_if_exists(metavertex_ids, rich.metavertices, f"{paragraph.id}_mv")
            if paragraph.page_id:
                _add_if_exists(node_ids, rich.nodes, paragraph.page_id)

    for metaedge in rich.metaedges.values():
        refs = set(metaedge.source_set) | set(metaedge.target_set) | set(metaedge.mediator_nodes) | set(metaedge.mediator_metavertices)
        if refs.intersection(node_ids | metavertex_ids) or formula_ids.intersection(refs):
            if metaedge.type in {"notation_scope", "definition_context", "paragraph_formula_context", "formula_dependency"}:
                metaedge_ids.add(metaedge.id)
                if depth >= 2:
                    for item in refs:
                        _add_if_exists(node_ids, rich.nodes, item)
                        _add_if_exists(metavertex_ids, rich.metavertices, item)

    if include_technical and depth >= 3:
        for formula_id in formula_ids:
            for edge in rich.edges.values():
                if edge.source == formula_id and edge.type == "extracted_from":
                    _add_if_exists(node_ids, rich.nodes, edge.target)
            for metaedge in rich.metaedges.values():
                if metaedge.type == "extraction_evidence" and formula_id in metaedge.source_set:
                    metaedge_ids.add(metaedge.id)
                    for item in metaedge.target_set:
                        _add_if_exists(node_ids, rich.nodes, item)

    payload = _build_payload(
        doc.document_id,
        "variable_neighborhood",
        rich,
        node_ids=node_ids,
        metavertex_ids=metavertex_ids,
        metaedge_ids=metaedge_ids,
        limit=limit,
        variable=selected_var.normalized_symbol,
        formula=None,
        empty_reason=None,
        canonical_mode="variable_focus",
    )
    payload["variable"] = selected_var.model_dump()
    payload["available_variables"] = candidates[:120]
    payload["stats"]["variable"] = {
        "query": variable,
        "normalized": selected_var.normalized_symbol,
        "formula_count": len(selected_var.formula_ids),
        "context_count": len(selected_var.context_ids),
        "definition_count": len(selected_var.possible_definitions),
        "section_count": len(selected_var.section_ids),
        "ambiguity_score": _ambiguity_score(selected_var),
    }
    return payload


def _select_for_mode(
    rich: Metagraph,
    mode: str,
    limit: int,
    include_technical: bool,
    *,
    formula: str | None = None,
) -> tuple[set[str], set[str], set[str]]:
    node_ids: set[str] = set()
    metavertex_ids: set[str] = set()
    metaedge_ids: set[str] = set()

    if mode == "document_hierarchy":
        node_types = {"paper", "section", "paragraph", "formula"}
        mv_types = {"paper_metavertex", "section_metavertex", "paragraph_metavertex", "formula_metavertex"}
        metaedge_types: set[str] = set()
    elif mode == "formula_semantic_network":
        node_types = {"formula", "symbol", "context", "definition"}
        mv_types = {"formula_metavertex", "definition_context_metavertex"}
        metaedge_types = {"definition_context", "notation_scope", "formula_dependency"}
    elif mode == "formula_context":
        selected_formula = _select_formula_id(rich, formula)
        if not selected_formula:
            return set(), set(), set()
        _add_if_exists(node_ids, rich.nodes, selected_formula)
        _add_if_exists(metavertex_ids, rich.metavertices, f"{selected_formula}_mv")
        for edge in rich.edges.values():
            touches_formula = edge.source == selected_formula or edge.target == selected_formula
            if not touches_formula and edge.type not in {"formula_near_text_block", "formula_in_section", "text_block_in_section"}:
                continue
            if edge.type in SEMANTIC_EDGE_TYPES | {"formula_near_text_block", "formula_in_section", "text_block_in_section"}:
                _add_if_exists(node_ids, rich.nodes, edge.source)
                _add_if_exists(node_ids, rich.nodes, edge.target)
        visible_formula_family = set(node_ids)
        for edge in rich.edges.values():
            if edge.type == "depends_on" and (edge.source in visible_formula_family or edge.target in visible_formula_family):
                _add_if_exists(node_ids, rich.nodes, edge.source)
                _add_if_exists(node_ids, rich.nodes, edge.target)
        for metaedge in rich.metaedges.values():
            refs = set(metaedge.source_set) | set(metaedge.target_set) | set(metaedge.mediator_nodes) | set(metaedge.mediator_metavertices)
            if selected_formula in refs and metaedge.type in {"formula_dependency", "definition_context", "notation_scope"}:
                metaedge_ids.add(metaedge.id)
        return node_ids, metavertex_ids, metaedge_ids
    elif mode == "formula_ast_focus":
        selected_formula = _select_formula_id(rich, formula)
        if not selected_formula:
            return set(), set(), set()
        _add_if_exists(node_ids, rich.nodes, selected_formula)
        _add_if_exists(metavertex_ids, rich.metavertices, f"{selected_formula}_mv")
        for edge in rich.edges.values():
            if edge.source == selected_formula or edge.target == selected_formula or edge.source.startswith(f"{selected_formula}:") or edge.target.startswith(f"{selected_formula}:"):
                if edge.type in AST_EDGE_TYPES | {"has_symbol", "has_context", "has_definition"}:
                    _add_if_exists(node_ids, rich.nodes, edge.source)
                    _add_if_exists(node_ids, rich.nodes, edge.target)
        for metaedge in rich.metaedges.values():
            refs = set(metaedge.source_set) | set(metaedge.target_set) | set(metaedge.mediator_nodes) | set(metaedge.mediator_metavertices)
            if selected_formula in refs and metaedge.type in {"formula_dependency", "definition_context", "notation_scope"}:
                metaedge_ids.add(metaedge.id)
        return node_ids, metavertex_ids, metaedge_ids
    elif mode == "metaedges_view":
        node_types = {"formula", "symbol", "context", "definition", "section", "paragraph"}
        mv_types = {"formula_metavertex", "definition_context_metavertex", "section_metavertex", "paragraph_metavertex"}
        metaedge_types = set(METAEDGE_TYPE_WEIGHTS)
    elif mode == "extraction_evidence":
        node_types = {"paper", "section", "formula", "source", "quality_issue"}
        mv_types = {"paper_metavertex", "section_metavertex", "formula_metavertex"}
        metaedge_types = {"extraction_evidence"}
    elif mode == "metagraph_planetary_overview":
        node_types = {"paper", "section", "formula", "symbol", "context", "definition"}
        mv_types = {"paper_metavertex", "section_metavertex", "paragraph_metavertex", "formula_metavertex", "definition_context_metavertex"}
        metaedge_types = {"formula_dependency", "definition_context", "notation_scope"}
    else:
        node_types = {"paper", "section", "formula", "symbol", "context", "definition"}
        mv_types = {"paper_metavertex", "section_metavertex", "formula_metavertex", "definition_context_metavertex"}
        metaedge_types = {"formula_dependency", "definition_context", "notation_scope"}

    if mode == "overview":
        node_budget = min(max(46, int(limit * 0.58)), 92)
        mv_budget = min(max(12, int(limit * 0.25)), 34)
        metaedge_budget = min(max(4, int(limit * 0.06)), 12)
    elif mode == "metagraph_planetary_overview":
        node_budget = min(max(70, int(limit * 0.46)), 210)
        mv_budget = min(max(24, int(limit * 0.26)), 120)
        metaedge_budget = min(max(10, int(limit * 0.04)), 32)
    elif mode == "formula_context":
        node_budget = min(max(28, int(limit * 0.72)), 160)
        mv_budget = min(max(6, int(limit * 0.18)), 30)
        metaedge_budget = min(max(3, int(limit * 0.06)), 12)
    else:
        node_budget = max(20, int(limit * 0.58))
        mv_budget = max(10, int(limit * 0.32))
        metaedge_budget = max(8, int(limit * 0.10))

    for node in sorted(rich.nodes.values(), key=_rank_node, reverse=True):
        if node.type in node_types:
            node_ids.add(node.id)
        if len(node_ids) >= node_budget:
            break

    for metavertex in sorted(rich.metavertices.values(), key=_rank_metavertex, reverse=True):
        if metavertex.type in mv_types and (_contains_any(metavertex, node_ids) or metavertex.type in {"paper_metavertex", "section_metavertex"}):
            metavertex_ids.add(metavertex.id)
        if len(metavertex_ids) >= mv_budget:
            break

    if mode == "metaedges_view":
        # Metaedge mode starts from higher-order links and expands endpoints.
        for metaedge in sorted(rich.metaedges.values(), key=_rank_metaedge, reverse=True)[:metaedge_budget]:
            metaedge_ids.add(metaedge.id)
            for item in [*metaedge.source_set, *metaedge.target_set, *metaedge.mediator_nodes, *metaedge.mediator_metavertices]:
                _add_if_exists(node_ids, rich.nodes, item)
                _add_if_exists(metavertex_ids, rich.metavertices, item)
    else:
        visible = node_ids | metavertex_ids
        for metaedge in sorted(rich.metaedges.values(), key=_rank_metaedge, reverse=True):
            if metaedge.type not in metaedge_types:
                continue
            refs = set(metaedge.source_set) | set(metaedge.target_set) | set(metaedge.mediator_nodes) | set(metaedge.mediator_metavertices)
            if refs.intersection(visible) or set(metaedge.contains).intersection(_edge_ids_between(rich, node_ids | metavertex_ids)):
                metaedge_ids.add(metaedge.id)
            if len(metaedge_ids) >= metaedge_budget:
                break

    return node_ids, metavertex_ids, metaedge_ids


def _build_payload(
    document_id: str,
    mode: str,
    rich: Metagraph,
    *,
    node_ids: set[str],
    metavertex_ids: set[str],
    metaedge_ids: set[str],
    limit: int,
    variable: str | None,
    formula: str | None,
    empty_reason: str | None,
    canonical_mode: str | None = None,
) -> dict[str, Any]:
    canonical_mode = canonical_mode or normalize_visualization_mode(mode)
    node_parent, mv_parent = _parent_maps(rich)
    node_ids, metavertex_ids, metaedge_ids = _close_structural_selection(rich, node_ids, metavertex_ids, metaedge_ids, node_parent, mv_parent, limit, canonical_mode)

    serialized_nodes = [
        _serialize_node(rich.nodes[node_id], node_parent, metavertex_ids, canonical_mode)
        for node_id in _ordered_ids(node_ids, rich.nodes, _rank_node)
    ]
    serialized_mvs = [
        _serialize_metavertex(rich.metavertices[mv_id], node_ids, metavertex_ids, mv_parent, canonical_mode)
        for mv_id in _ordered_ids(metavertex_ids, rich.metavertices, _rank_metavertex)
    ]

    visible_objects = set(node_ids) | set(metavertex_ids)
    serialized_edges = [
        _serialize_edge(edge, canonical_mode)
        for edge in rich.edges.values()
        if edge.source in visible_objects and edge.target in visible_objects and _edge_visible_in_mode(edge, canonical_mode)
    ]
    edge_budget = {
        "overview": 240,
        "metagraph_planetary_overview": 300,
        "formula_semantic_network": 360,
        "formula_context": 180,
        "variable_focus": 220,
        "metaedges_view": 220,
    }.get(canonical_mode)
    if edge_budget is not None and len(serialized_edges) > edge_budget:
        serialized_edges = sorted(serialized_edges, key=lambda item: float(item.get("weight") or 1.0), reverse=True)[:edge_budget]

    serialized_metaedges: list[dict[str, Any]] = []
    metaedge_nodes: list[dict[str, Any]] = []
    metaedge_edges: list[dict[str, Any]] = []
    for metaedge_id in _ordered_ids(metaedge_ids, rich.metaedges, _rank_metaedge):
        metaedge = rich.metaedges[metaedge_id]
        item = _serialize_metaedge(metaedge, visible_objects, {edge["id"] for edge in serialized_edges})
        if item is None:
            continue
        serialized_metaedges.append(item)
        if canonical_mode == "metaedges_view":
            node, edges = _metaedge_node_and_links(item)
            metaedge_nodes.append(node)
            metaedge_edges.extend(edges)

    all_nodes = [*serialized_nodes, *metaedge_nodes]
    node_id_set = {node["id"] for node in all_nodes} | {mv["id"] for mv in serialized_mvs}
    all_edges = [edge for edge in [*serialized_edges, *metaedge_edges] if edge["source"] in node_id_set and edge["target"] in node_id_set]

    stats = {
        "original_node_count": len(rich.nodes),
        "original_metavertex_count": len(rich.metavertices),
        "original_edge_count": len(rich.edges),
        "original_metaedge_count": len(rich.metaedges),
        "node_count": len(all_nodes),
        "metavertex_count": len(serialized_mvs),
        "edge_count": len(all_edges),
        "metaedge_count": len(serialized_metaedges),
        "hidden_nodes": max(0, len(rich.nodes) - len(serialized_nodes)),
        "hidden_metavertices": max(0, len(rich.metavertices) - len(serialized_mvs)),
        "hidden_edges": max(0, len(rich.edges) - len(serialized_edges)),
        "hidden_metaedges": max(0, len(rich.metaedges) - len(serialized_metaedges)),
        "truncated": len(rich.nodes) > len(serialized_nodes) or len(rich.metavertices) > len(serialized_mvs),
        "node_types": dict(Counter(node["type"] for node in all_nodes)),
        "edge_types": dict(Counter(edge["type"] for edge in all_edges)),
        "metavertex_types": dict(Counter(mv["type"] for mv in serialized_mvs)),
        "metaedge_types": dict(Counter(edge["type"] for edge in serialized_metaedges)),
        "empty_reason": empty_reason,
    }
    stats.update(
        {
            "visibleNodes": stats["node_count"] + stats["metavertex_count"],
            "hiddenNodes": stats["hidden_nodes"] + stats["hidden_metavertices"],
            "visibleEdges": stats["edge_count"] + stats["metaedge_count"],
            "hiddenEdges": stats["hidden_edges"] + stats["hidden_metaedges"],
            "totalNodes": stats["original_node_count"] + stats["original_metavertex_count"],
            "totalEdges": stats["original_edge_count"] + stats["original_metaedge_count"],
        }
    )
    title, description = MODE_META.get(canonical_mode, MODE_META["overview"])
    warnings = []
    if stats["hiddenNodes"] or stats["hiddenEdges"]:
        warnings.append("Показана пресетная проекция, полный граф скрыт.")

    payload = {
        "document_id": document_id,
        "mode": mode,
        "canonical_mode": canonical_mode,
        "title": title,
        "description": description,
        "layout": {
            "type": _layout_type(canonical_mode),
            "version": "1.0",
            "params": {
                "limit": limit,
                "variable": variable,
                "formula": formula,
                "compact_threshold": 360,
                "theory": "визуализация.pdf",
                "description": PLANETARY_LAYOUT_DOC,
                "notice": _notice_for_mode(canonical_mode),
            },
        },
        "nodes": all_nodes,
        "metavertices": serialized_mvs,
        "edges": all_edges,
        "metaedges": serialized_metaedges,
        "stats": stats,
        "legend": _legend(),
        "warnings": warnings,
        "available_formulas": _available_formulas(rich),
    }
    payload["elements"] = _compat_elements(payload)
    return payload


def _close_structural_selection(
    rich: Metagraph,
    node_ids: set[str],
    metavertex_ids: set[str],
    metaedge_ids: set[str],
    node_parent: dict[str, str],
    mv_parent: dict[str, str],
    limit: int,
    mode: str,
) -> tuple[set[str], set[str], set[str]]:
    for node_id in list(node_ids):
        _add_metavertex_chain(metavertex_ids, node_parent.get(node_id), mv_parent)
    for mv_id in list(metavertex_ids):
        _add_metavertex_chain(metavertex_ids, mv_parent.get(mv_id), mv_parent)
    for metaedge_id in list(metaedge_ids):
        metaedge = rich.metaedges[metaedge_id]
        for item in [*metaedge.source_set, *metaedge.target_set, *metaedge.mediator_nodes]:
            _add_if_exists(node_ids, rich.nodes, item)
            _add_metavertex_chain(metavertex_ids, node_parent.get(item), mv_parent)
        for item in metaedge.mediator_metavertices:
            _add_if_exists(metavertex_ids, rich.metavertices, item)
            _add_metavertex_chain(metavertex_ids, mv_parent.get(item), mv_parent)

    node_budget = max(20, limit - len(metavertex_ids) - len(metaedge_ids))
    if len(node_ids) > node_budget:
        mandatory_types = {"paper", "section"}
        if mode in {"formula_context", "formula_ast_focus", "variable_focus"}:
            mandatory_types.update({"formula", "symbol"})
        mandatory = {node_id for node_id in node_ids if rich.nodes[node_id].type in mandatory_types}
        ordered = _ordered_ids(node_ids, rich.nodes, _rank_node)
        kept: set[str] = set()
        for node_id in ordered:
            if node_id in mandatory or len(kept) < node_budget:
                kept.add(node_id)
            if len(kept) >= node_budget and mandatory.issubset(kept):
                break
        node_ids = kept
        metavertex_ids = {mv_id for mv_id in metavertex_ids if mv_id in rich.metavertices}
        for node_id in list(node_ids):
            _add_metavertex_chain(metavertex_ids, node_parent.get(node_id), mv_parent)

    metavertex_ids = {
        mv_id
        for mv_id in metavertex_ids
        if mv_id in rich.metavertices and (_contains_any(rich.metavertices[mv_id], node_ids | metavertex_ids) or rich.metavertices[mv_id].type == "paper_metavertex")
    }
    for node_id in list(node_ids):
        _add_metavertex_chain(metavertex_ids, node_parent.get(node_id), mv_parent)

    visible = node_ids | metavertex_ids
    valid_metaedges = set()
    for metaedge_id in metaedge_ids:
        metaedge = rich.metaedges.get(metaedge_id)
        if not metaedge:
            continue
        if set(metaedge.source_set).intersection(visible) and set(metaedge.target_set).intersection(visible):
            valid_metaedges.add(metaedge_id)
    return node_ids, metavertex_ids, valid_metaedges


def _serialize_node(node: Node, node_parent: dict[str, str], visible_mvs: set[str], mode: str) -> dict[str, Any]:
    attrs = dict(node.attributes or {})
    node_type = _display_type(node.type)
    preview = _preview_for_node(node)
    parent = node_parent.get(node.id)
    rank = round(_rank_node(node), 4)
    mass = _mass(attrs)
    result = {
        "id": node.id,
        "type": node_type,
        "label": _label_for_node(node),
        "short_label": _short_label(node),
        "mass": mass,
        "rank": rank,
        "depth": _depth(attrs),
        "importance": round(_importance(rank), 4),
        "visual": _visual_metadata(node.id, node_type, mass, rank, attrs, mode, parent),
        "layout": _layout_metadata(node.id, node_type, attrs, mode, parent),
        "attributes": attrs,
        "preview": preview,
    }
    if parent in visible_mvs:
        result["parent"] = parent
    return result


def _serialize_metavertex(mv: MetaVertex, visible_nodes: set[str], visible_mvs: set[str], mv_parent: dict[str, str], mode: str) -> dict[str, Any]:
    attrs = dict(mv.attributes or {})
    visible_contains = [item for item in mv.contains if item in visible_nodes or item in visible_mvs]
    rank = round(_rank_metavertex(mv), 4)
    mass = _mass(attrs)
    parent = mv_parent.get(mv.id)
    result = {
        "id": mv.id,
        "type": mv.type,
        "label": mv.label,
        "short_label": _short(mv.label, 42),
        "contains": visible_contains,
        "mass": mass,
        "rank": rank,
        "depth": _depth(attrs),
        "entry_points": [item for item in mv.entry_points if item in visible_nodes or item in visible_mvs],
        "exit_points": [item for item in mv.exit_points if item in visible_nodes or item in visible_mvs],
        "metrics": {
            "contains_count": len(mv.contains),
            "visible_contains_count": len(visible_contains),
            "hidden_contains_count": max(0, len(mv.contains) - len(visible_contains)),
            "complete": len(visible_contains) == len(mv.contains),
        },
        "visual": _visual_metadata(mv.id, mv.type, mass, rank, attrs, mode, parent),
        "layout": _layout_metadata(mv.id, mv.type, attrs, mode, parent),
        "attributes": attrs,
    }
    if parent in visible_mvs:
        result["parent"] = parent
    return result


def _serialize_edge(edge: Edge, mode: str) -> dict[str, Any]:
    return {
        "id": edge.id,
        "source": edge.source,
        "target": edge.target,
        "type": edge.type,
        "directed": edge.directed,
        "weight": EDGE_TYPE_WEIGHTS.get(edge.type, 1.0),
        "visual": {
            "semantic": edge.type in SEMANTIC_EDGE_TYPES,
            "technical": edge.type in TECHNICAL_EDGE_TYPES,
            "bundled": mode in {"metagraph_planetary_overview", "formula_semantic_network"} and edge.type in {"has_symbol", "depends_on"},
            "hiddenByDefault": edge.type in TECHNICAL_EDGE_TYPES,
        },
        "attributes": dict(edge.attributes or {}),
    }


def _edge_visible_in_mode(edge: Edge, mode: str) -> bool:
    if mode == "document_hierarchy":
        return edge.type in STRUCTURAL_EDGE_TYPES
    if mode == "formula_context":
        return edge.type in SEMANTIC_EDGE_TYPES | {"formula_near_text_block", "formula_in_section"}
    if mode == "formula_ast_focus":
        return edge.type in AST_EDGE_TYPES | {"has_symbol", "has_context", "has_definition"}
    if mode == "formula_semantic_network":
        return edge.type in SEMANTIC_EDGE_TYPES
    if mode == "variable_focus":
        return edge.type in SEMANTIC_EDGE_TYPES or edge.type == "extracted_from"
    if mode == "metaedges_view":
        return edge.type in {"metaedge_source", "metaedge_target"}
    if mode == "extraction_evidence":
        return edge.type == "extracted_from"
    return edge.type in SEMANTIC_EDGE_TYPES


def _layout_type(mode: str) -> str:
    return {
        "document_hierarchy": "document_tree",
        "formula_semantic_network": "semantic_network",
        "formula_context": "formula_context_ego",
        "variable_focus": "variable_ego",
        "metaedges_view": "metaedge_bipartite",
        "formula_ast_focus": "formula_ast_tree",
    }.get(mode, "planetary_metagraph")


def _notice_for_mode(mode: str) -> str:
    if mode == "formula_context":
        return "Показан локальный контекст одной формулы без AST всего документа."
    if mode == "formula_ast_focus":
        return "AST показывается только для выбранной или наиболее важной формулы."
    if mode == "variable_focus":
        return "Показана ego-проекция выбранной переменной с ограниченной глубиной."
    if mode == "metaedges_view":
        return "Метаребра вынесены в отдельную проекцию и не смешиваются с обзором."
    return "Показан обзорный подграф. Используйте поиск, фильтры или раскрытие узла для детализации."


def _visual_metadata(object_id: str, object_type: str, mass: float, rank: float, attrs: dict[str, Any], mode: str, parent: str | None) -> dict[str, Any]:
    level = _level_for_type(object_type, attrs)
    return {
        "role": _visual_role(object_type),
        "mass": mass,
        "rank": rank,
        "level": level,
        "groupId": attrs.get("section_id") or attrs.get("formula_id") or parent,
        "parentId": parent,
        "parentMetavertexId": parent,
        "importanceReason": _importance_reason(object_type, attrs, mode),
        "collapsed": mode in {"metagraph_planetary_overview", "document_hierarchy"} and object_type in {"paragraph_metavertex", "definition_context_metavertex"},
        "labelPriority": _label_priority(object_type, rank, mode),
        "labelPolicy": _label_policy(object_type, rank, mode),
    }


def _layout_metadata(object_id: str, object_type: str, attrs: dict[str, Any], mode: str, parent: str | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "level": _level_for_type(object_type, attrs),
        "groupId": attrs.get("section_id") or attrs.get("formula_id") or parent,
        "parentMetavertexId": parent,
    }
    if mode == "metaedges_view":
        if object_type == "metaedge":
            result["lane"] = "metaedge"
        elif object_type in {"context", "definition"}:
            result["lane"] = "mediator"
        else:
            result["lane"] = "endpoint"
    return result


def _visual_role(object_type: str) -> str:
    if object_type in {"document", "paper", "paper_metavertex"}:
        return "paper"
    if object_type in {"section", "section_metavertex"}:
        return "section"
    if object_type in {"formula", "formula_metavertex"}:
        return "formula"
    if object_type in {"symbol", "variable"}:
        return "variable"
    if object_type == "definition":
        return "definition"
    if object_type in {"context", "definition_context_metavertex"}:
        return "context"
    if object_type == "metaedge":
        return "metaedge"
    if object_type.endswith("_metavertex"):
        return "metavertex"
    if object_type == "fragment":
        return "technical"
    return object_type


def _label_priority(object_type: str, rank: float, mode: str) -> int:
    if object_type in {"document", "paper_metavertex"}:
        return 100
    if object_type in {"section", "section_metavertex"}:
        return 88
    if mode in {"formula_context", "formula_ast_focus", "metaedges_view"}:
        return 76
    if rank >= 70:
        return 70
    if rank >= 48:
        return 50
    return 20


def _level_for_type(object_type: str, attrs: dict[str, Any]) -> int:
    if object_type in {"document", "paper_metavertex"}:
        return 0
    if object_type in {"section", "section_metavertex"}:
        return 1
    if object_type in {"paragraph", "paragraph_metavertex"}:
        return 2
    if object_type in {"formula", "formula_metavertex"}:
        return 3
    if object_type in {"symbol", "context", "definition", "definition_context_metavertex"}:
        return 4
    if object_type == "fragment":
        return 5
    return _depth(attrs)


def _importance_reason(object_type: str, attrs: dict[str, Any], mode: str) -> str:
    if object_type == "formula":
        return "formula rank combines symbols, context, references and visible degree"
    if object_type == "symbol":
        return "symbol rank combines usage count, formula count and definition evidence"
    if object_type in {"context", "definition"}:
        return "context rank is driven by evidence and linked symbols"
    if object_type.endswith("_metavertex"):
        return "metavertex mass includes visible nested elements and hierarchy role"
    return "projection policy keeps this object as semantically important"


def _label_policy(object_type: str, rank: float, mode: str) -> str:
    if object_type in {"document", "section", "paper_metavertex", "section_metavertex"}:
        return "always"
    if mode in {"formula_ast_focus", "metaedges_view"}:
        return "visible"
    if rank >= 70:
        return "zoom_out"
    if rank >= 48:
        return "medium_zoom"
    return "selected_or_zoom_in"


def _serialize_metaedge(metaedge: MetaEdge, visible: set[str], visible_edge_ids: set[str]) -> dict[str, Any] | None:
    source_set = [item for item in metaedge.source_set if item in visible]
    target_set = [item for item in metaedge.target_set if item in visible]
    if not source_set or not target_set:
        return None
    return {
        "id": metaedge.id,
        "type": metaedge.type,
        "source_set": source_set,
        "target_set": target_set,
        "mediator_nodes": [item for item in metaedge.mediator_nodes if item in visible],
        "mediator_metavertices": [item for item in metaedge.mediator_metavertices if item in visible],
        "contains": [item for item in metaedge.contains if item in visible_edge_ids],
        "weight": METAEDGE_TYPE_WEIGHTS.get(metaedge.type, 1.0),
        "visual": {
            "mass": round(METAEDGE_TYPE_WEIGHTS.get(metaedge.type, 1.0) + len(metaedge.source_set) + len(metaedge.target_set) + len(metaedge.mediator_nodes) * 0.5, 4),
            "rank": round(_rank_metaedge(metaedge), 4),
            "level": 3,
            "source_size": len(metaedge.source_set),
            "target_size": len(metaedge.target_set),
            "mediator_count": len(metaedge.mediator_nodes) + len(metaedge.mediator_metavertices),
            "evidence_count": _metaedge_evidence_count(metaedge),
            "metaedge_complexity": round(len(metaedge.source_set) + len(metaedge.target_set) + len(metaedge.mediator_nodes) + len(metaedge.contains) * 0.5, 4),
        },
        "attributes": {
            **dict(metaedge.attributes or {}),
            "original_source_set": metaedge.source_set,
            "original_target_set": metaedge.target_set,
            "original_contains": metaedge.contains,
        },
    }


def _metaedge_node_and_links(metaedge: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    node_id = f"metaedge_node:{_safe_id(metaedge['id'])}"
    node = {
        "id": node_id,
        "type": "metaedge",
        "label": metaedge["type"],
        "short_label": _short(metaedge["type"], 28),
        "mass": 1.0 + float(metaedge.get("weight") or 1.0),
        "rank": 35.0 + float(metaedge.get("weight") or 1.0),
        "depth": 0,
        "importance": 0.62,
        "visual": dict(metaedge.get("visual") or {}),
        "layout": {"lane": "metaedge", "level": 2},
        "attributes": metaedge,
        "preview": {"text": metaedge["type"]},
    }
    edges: list[dict[str, Any]] = []
    for source in metaedge.get("source_set", []):
        edges.append(
            {
                "id": f"{metaedge['id']}:source:{source}",
                "source": source,
                "target": node_id,
                "type": "metaedge_source",
                "directed": True,
                "weight": metaedge.get("weight", 1.0),
                "attributes": {"metaedge_id": metaedge["id"], "metaedge_type": metaedge["type"]},
            }
        )
    for target in metaedge.get("target_set", []):
        edges.append(
            {
                "id": f"{metaedge['id']}:target:{target}",
                "source": node_id,
                "target": target,
                "type": "metaedge_target",
                "directed": True,
                "weight": metaedge.get("weight", 1.0),
                "attributes": {"metaedge_id": metaedge["id"], "metaedge_type": metaedge["type"]},
            }
        )
    return node, edges


def _empty_payload(document_id: str, mode: str, limit: int, *, variable: str | None = None, message: str) -> dict[str, Any]:
    title, description = MODE_META.get(normalize_visualization_mode(mode), MODE_META["overview"])
    payload = {
        "document_id": document_id,
        "mode": mode,
        "canonical_mode": normalize_visualization_mode(mode),
        "title": title,
        "description": description,
        "layout": {"type": "planetary_metagraph", "version": "1.0", "params": {"limit": limit, "variable": variable, "theory": "визуализация.pdf"}},
        "nodes": [],
        "metavertices": [],
        "edges": [],
        "metaedges": [],
        "stats": {
            "node_count": 0,
            "metavertex_count": 0,
            "edge_count": 0,
            "metaedge_count": 0,
            "hidden_nodes": 0,
            "hidden_metavertices": 0,
            "hidden_edges": 0,
            "hidden_metaedges": 0,
            "visibleNodes": 0,
            "hiddenNodes": 0,
            "visibleEdges": 0,
            "hiddenEdges": 0,
            "totalNodes": 0,
            "totalEdges": 0,
            "truncated": False,
            "empty_reason": message,
        },
        "legend": _legend(),
        "warnings": [message] if message else [],
        "available_variables": [],
        "suggestions": [],
    }
    payload["elements"] = []
    return payload


def _compat_elements(payload: dict[str, Any]) -> list[dict[str, Any]]:
    elements: list[dict[str, Any]] = []
    for mv in payload.get("metavertices", []):
        elements.append({"data": {"id": mv["id"], "label": mv["label"], "type": mv["type"], "parent": mv.get("parent"), "attributes": mv}})
    for node in payload.get("nodes", []):
        elements.append(
            {
                "data": {
                    "id": node["id"],
                    "label": node["label"],
                    "type": node["type"],
                    "parent": node.get("parent"),
                    "latex": (node.get("preview") or {}).get("latex"),
                    "text": (node.get("preview") or {}).get("text"),
                    "attributes": node.get("attributes") or node,
                }
            }
        )
    for edge in payload.get("edges", []):
        elements.append({"data": {"id": edge["id"], "source": edge["source"], "target": edge["target"], "label": edge["type"], "type": edge["type"], "attributes": edge.get("attributes") or edge}})
    return elements


def _parent_maps(rich: Metagraph) -> tuple[dict[str, str], dict[str, str]]:
    node_parent: dict[str, str] = {}
    mv_parent: dict[str, str] = {}
    ordered = sorted(rich.metavertices.values(), key=lambda item: _depth(item.attributes))
    for mv in ordered:
        for child in mv.contains:
            if child in rich.nodes:
                current = node_parent.get(child)
                if current is None or _depth(rich.metavertices[current].attributes) <= _depth(mv.attributes):
                    node_parent[child] = mv.id
            elif child in rich.metavertices and child != mv.id:
                current = mv_parent.get(child)
                if current is None or _depth(rich.metavertices[current].attributes) <= _depth(mv.attributes):
                    mv_parent[child] = mv.id
    return node_parent, mv_parent


def _add_metavertex_chain(target: set[str], mv_id: str | None, mv_parent: dict[str, str]) -> None:
    while mv_id and mv_id not in target:
        target.add(mv_id)
        mv_id = mv_parent.get(mv_id)


def _add_context_family(node_ids: set[str], metavertex_ids: set[str], rich: Metagraph, ctx) -> None:
    _add_if_exists(node_ids, rich.nodes, ctx.id)
    _add_if_exists(metavertex_ids, rich.metavertices, f"{ctx.id}_mv")
    for index, _definition in enumerate(ctx.possible_definitions, start=1):
        _add_if_exists(node_ids, rich.nodes, f"definition:{ctx.id}:{index}")
    for block_id in ctx.nearest_text_block_ids:
        _add_if_exists(node_ids, rich.nodes, block_id)
        _add_if_exists(metavertex_ids, rich.metavertices, f"{block_id}_mv")
    if ctx.section_id:
        _add_if_exists(node_ids, rich.nodes, ctx.section_id)
        _add_if_exists(metavertex_ids, rich.metavertices, f"{ctx.section_id}_mv")


def _available_variables(doc: GraphReadyDocument) -> list[str]:
    result = []
    for variable in doc.variables:
        for item in (variable.normalized_symbol, variable.symbol, variable.latex):
            if item and item not in result:
                result.append(item)
    return result


def _available_formulas(rich: Metagraph) -> list[dict[str, str]]:
    formulas = [node for node in rich.nodes.values() if node.type == "formula"]
    result = []
    for node in sorted(formulas, key=_rank_node, reverse=True)[:160]:
        attrs = node.attributes or {}
        result.append(
            {
                "id": node.id,
                "token": str(attrs.get("token") or node.id),
                "label": _short(str(attrs.get("latex") or attrs.get("normalized_latex") or node.label or node.id), 120),
            }
        )
    return result


def _variable_suggestions(query: str, variables: list[str]) -> list[str]:
    query_norm = normalize_symbol(query).lstrip("\\").lower()
    scored = []
    for variable in variables:
        value = str(variable).lstrip("\\").lower()
        score = 0
        if query_norm and query_norm in value:
            score += 10
        if value.startswith(query_norm[:1]):
            score += 2
        score -= abs(len(value) - len(query_norm)) * 0.1
        if score > 0:
            scored.append((score, variable))
    return [item for _score, item in sorted(scored, reverse=True)[:12]]


def _ambiguity_score(variable) -> float:
    definitions = {str(item.get("definition_text") or item.get("evidence") or "").strip().lower() for item in variable.possible_definitions if item}
    sections = set(variable.section_ids)
    return round(min(1.0, max(0.0, (len(definitions) - 1) * 0.25 + max(0, len(sections) - 1) * 0.12)), 4)


def _rank_node(node: Node) -> float:
    display_type = _display_type(node.type)
    attrs = node.attributes or {}
    base = NODE_TYPE_WEIGHTS.get(display_type, 10)
    mass = _mass(attrs)
    evidence_bonus = 4 if attrs.get("possible_definitions") else 0
    context_bonus = 3 if attrs.get("context_id") else 0
    return base + math.log1p(max(mass, 0)) * 8 + evidence_bonus + context_bonus


def _rank_metavertex(mv: MetaVertex) -> float:
    depth_penalty = _depth(mv.attributes) * 1.5
    type_bonus = 35 if mv.type == "paper_metavertex" else 24 if mv.type == "section_metavertex" else 18 if mv.type == "formula_metavertex" else 12
    return type_bonus + math.log1p(max(_mass(mv.attributes), 0)) * 10 + len(mv.contains) * 0.04 - depth_penalty


def _rank_metaedge(metaedge: MetaEdge) -> float:
    return METAEDGE_TYPE_WEIGHTS.get(metaedge.type, 1.0) * 20 + len(metaedge.source_set) + len(metaedge.target_set)


def _metaedge_evidence_count(metaedge: MetaEdge) -> int:
    evidence = (metaedge.attributes or {}).get("evidence")
    if isinstance(evidence, list):
        return len(evidence)
    return 1 if evidence else 0


def _select_formula_id(rich: Metagraph, formula: str | None) -> str | None:
    if formula and formula in rich.nodes and rich.nodes[formula].type == "formula":
        return formula
    query = str(formula or "").strip().lower()
    if query:
        for node in rich.nodes.values():
            if node.type != "formula":
                continue
            haystack = " ".join(
                str(value or "")
                for value in [
                    node.id,
                    node.label,
                    node.attributes.get("token"),
                    node.attributes.get("latex"),
                    node.attributes.get("normalized_latex"),
                ]
            ).lower()
            if query in haystack:
                return node.id
    formulas = [node for node in rich.nodes.values() if node.type == "formula"]
    if not formulas:
        return None
    return max(formulas, key=_rank_node).id


def _edge_ids_between(rich: Metagraph, visible: set[str]) -> set[str]:
    return {edge.id for edge in rich.edges.values() if edge.source in visible and edge.target in visible}


def _contains_any(mv: MetaVertex, ids: set[str]) -> bool:
    return bool(set(mv.contains).intersection(ids))


def _ordered_ids(ids: set[str], values: dict[str, Any], ranker) -> list[str]:
    return [item.id for item in sorted((values[item] for item in ids if item in values), key=ranker, reverse=True)]


def _add_if_exists(target: set[str], values: dict[str, Any], item: str) -> None:
    if item in values:
        target.add(item)


def _display_type(node_type: str) -> str:
    return NODE_TYPE_MAP.get(node_type, node_type)


def _mass(attrs: dict[str, Any]) -> float:
    try:
        return round(float(attrs.get("mass", 1.0)), 4)
    except (TypeError, ValueError):
        return 1.0


def _depth(attrs: dict[str, Any]) -> int:
    try:
        return int(attrs.get("nesting_depth", 0))
    except (TypeError, ValueError):
        return 0


def _importance(rank: float) -> float:
    return min(1.0, max(0.05, rank / 110.0))


def _label_for_node(node: Node) -> str:
    if node.type == "paper":
        return node.label or "Document"
    if node.type == "formula":
        return node.attributes.get("token") or node.id
    if node.type == "symbol":
        return node.label
    if node.type in {"paragraph", "context", "definition", "subexpression"}:
        return _short(node.label, 120)
    return node.label or node.id


def _short_label(node: Node) -> str:
    if node.type == "formula":
        return node.attributes.get("token") or _short(node.label, 24)
    if node.type == "symbol":
        return node.label.lstrip("\\")
    if node.type == "subexpression":
        return _short(node.label, 28)
    return _short(_label_for_node(node), 32)


def _preview_for_node(node: Node) -> dict[str, Any]:
    attrs = node.attributes or {}
    preview: dict[str, Any] = {
        "page": attrs.get("page_number") or attrs.get("page"),
        "token": attrs.get("token"),
    }
    if node.type == "formula":
        preview["latex"] = attrs.get("latex") or attrs.get("normalized_latex") or node.label
    elif node.type in {"subexpression", "operator"}:
        preview["latex"] = node.label
    elif node.type in {"paragraph", "context", "definition", "section"}:
        preview["text"] = attrs.get("text_with_tokens") or attrs.get("text") or attrs.get("window_text") or node.label
    elif node.type == "symbol":
        preview["text"] = attrs.get("normalized_symbol") or node.label
    else:
        preview["text"] = node.label
    return {key: value for key, value in preview.items() if value not in {None, ""}}


def _symbol_node_id(symbol: str) -> str:
    return f"symbol:{_safe_id(symbol)}"


def _safe_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", str(value).strip("\\"))
    return safe.strip("_") or "item"


def _short(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _legend() -> dict[str, Any]:
    return {
        "node_types": {
            "document": "document or paper root",
            "section": "document section",
            "paragraph": "text block or paragraph",
            "formula": "LaTeX formula",
            "symbol": "variable/symbol",
            "context": "formula context window",
            "definition": "candidate variable definition",
            "fragment": "formula AST/subexpression/operator",
            "metaedge": "higher-order relation object",
            "source": "extraction source",
            "issue": "quality issue",
        },
        "edge_types": EDGE_TYPE_WEIGHTS,
        "metaedge_types": METAEDGE_TYPE_WEIGHTS,
        "layout": PLANETARY_LAYOUT_DOC,
    }
