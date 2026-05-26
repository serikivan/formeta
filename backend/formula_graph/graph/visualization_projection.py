from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from backend.formula_graph.export.graph_ready_export import GraphReadyDocument, normalize_symbol
from backend.formula_graph.graph.graph_ready_metagraph import build_metagraph_from_graph_ready


PROJECTION_MODES = {"overview", "formula_focus", "variable_focus", "metaedge_lanes", "ast_tree"}
TECHNICAL_EDGE_TYPES = {
    "contains",
    "ast_contains",
    "ast_lhs",
    "ast_rhs",
    "ast_operand",
    "ast_argument",
    "extracted_from",
    "source",
    "formula_in_section",
    "text_block_in_section",
    "formula_near_text_block",
}


def build_visualization_projection(
    doc: GraphReadyDocument,
    *,
    mode: str = "overview",
    formula: str | None = None,
    variable: str | None = None,
    limit: int = 80,
) -> dict[str, Any]:
    mode = mode if mode in PROJECTION_MODES else "overview"
    limit = max(20, min(int(limit or 80), 80))
    builders = {
        "overview": _overview_projection,
        "formula_focus": _formula_focus_projection,
        "variable_focus": _variable_focus_projection,
        "metaedge_lanes": _metaedge_lanes_projection,
        "ast_tree": _ast_tree_projection,
    }
    payload = builders[mode](doc, formula=formula, variable=variable, limit=limit)
    payload["mode"] = mode
    payload["document_id"] = doc.document_id
    payload["available_formulas"] = _available_formulas(doc)
    payload["available_variables"] = _available_variables(doc)
    hidden = _hidden_counts(doc, payload, allow_ast=mode == "ast_tree")
    payload["hiddenCounts"] = hidden
    payload["hidden_counts"] = hidden
    payload["selectedObjectDetails"] = payload.get("selectedObjectDetails") or _first_details(payload)
    payload["selected_object_details"] = payload["selectedObjectDetails"]
    return payload


def _overview_projection(doc: GraphReadyDocument, **_: Any) -> dict[str, Any]:
    formula_by_section: dict[str | None, list[Any]] = defaultdict(list)
    variable_by_section: dict[str | None, set[str]] = defaultdict(set)
    definitions_by_section: dict[str | None, list[dict[str, Any]]] = defaultdict(list)
    context_by_formula = {ctx.formula_id: ctx for ctx in doc.formula_contexts}

    for formula in doc.formulas:
        formula_by_section[formula.section_id].append(formula)
    for variable in doc.variables:
        for section_id in variable.section_ids or [None]:
            variable_by_section[section_id].add(variable.normalized_symbol)
            for definition in variable.possible_definitions:
                definitions_by_section[section_id].append(definition)

    sections = (doc.document_structure.sections or [])[:5]
    if not sections:
        sections = [_synthetic_section(doc)]

    groups: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    visible_formula_ids: set[str] = set()
    variable_node_by_section_symbol: dict[tuple[str, str], str] = {}
    for index, section in enumerate(sections, start=1):
        section_id = section.id
        formulas = sorted(formula_by_section.get(section_id, []) or doc.formulas, key=_formula_rank, reverse=True)[:8]
        variables = sorted(variable_by_section.get(section_id, set()))[:16]
        definitions = _dedupe_dicts(definitions_by_section.get(section_id, []))[:8]
        group = {
            "id": section_id,
            "type": "section",
            "title": section.title or f"Раздел {index}",
            "metrics": {"formulas": len(formulas), "variables": len(variables), "definitions": len(definitions)},
            "formulaIds": [formula.id for formula in formulas],
            "variables": variables,
            "definitions": definitions,
        }
        groups.append(group)
        nodes.append(
            _node(
                section_id,
                "section",
                _section_label(section.title or f"Раздел {index}"),
                lane=section_id,
                groupId=section_id,
                details={"id": section_id, "type": "section", "title": group["title"], "metrics": group["metrics"]},
            )
        )
        for formula in formulas:
            visible_formula_ids.add(formula.id)
            nodes.append(_formula_node(formula, lane=section_id, group_id=section_id, context=context_by_formula.get(formula.id)))
            edges.append(_edge(section_id, formula.id, "section_contains_formula"))
        for offset, symbol in enumerate(variables[:8], start=1):
            variable_node_id = f"{section_id}:var:{symbol}"
            variable_node_by_section_symbol[(section_id, symbol)] = variable_node_id
            nodes.append(
                _node(
                    variable_node_id,
                    "variable",
                    _short_symbol(symbol),
                    lane=section_id,
                    groupId=section_id,
                    chip=True,
                    details={"id": symbol, "type": "variable", "symbol": symbol, "section_id": section_id},
                )
            )
        if definitions:
            definition_node_id = f"{section_id}:definitions"
            nodes.append(
                _node(
                    definition_node_id,
                    "definition",
                    f"Definitions x{len(definitions)}",
                    lane=section_id,
                    groupId=section_id,
                    chip=True,
                    details={"id": f"{section_id}:definitions", "type": "definition_group", "definitions": definitions},
                )
            )
            edges.append(_edge(definition_node_id, section_id, "section_definitions"))

    formula_by_id = {formula.id: formula for formula in doc.formulas}
    for formula_id in visible_formula_ids:
        formula = formula_by_id.get(formula_id)
        if not formula or not formula.section_id:
            continue
        for variable in doc.variables:
            if formula_id not in variable.formula_ids:
                continue
            variable_node_id = variable_node_by_section_symbol.get((formula.section_id, variable.normalized_symbol))
            if variable_node_id:
                edges.append(_edge(formula_id, variable_node_id, "uses_variable"))

    edges.extend(
        _edge(relation.source_id, relation.target_id, "formula_dependency", relation)
        for relation in doc.relations
        if relation.type in {"formula_dependency", "formula_references_formula", "depends_on"}
        and relation.source_id in visible_formula_ids
        and relation.target_id in visible_formula_ids
    )
    edges = _dedupe_edges(edges)
    return _projection(
        title="Обзор документа",
        description="Section-lane схема: секции, top-формулы, compact chips переменных и определений. Технические contains/AST/source связи скрыты.",
        layout="section_lanes",
        nodes=nodes[:80],
        edges=edges[:80],
        groups=groups,
        cards=[],
    )


def _formula_focus_projection(doc: GraphReadyDocument, *, formula: str | None = None, **_: Any) -> dict[str, Any]:
    selected = _select_formula(doc, formula)
    if selected is None:
        return _empty("Метавершина формулы", "Формулы не найдены.")
    context = _context_for_formula(doc, selected.id)
    section = _section_for_formula(doc, selected)
    variables = [var for var in doc.variables if selected.id in var.formula_ids][:12]
    definitions = [item.model_dump() for item in (context.possible_definitions if context else [])][:8]
    dependency_edges = _formula_dependency_relations(doc, selected.id)[:8]
    formula_by_id = {item.id: item for item in doc.formulas}
    related = [formula_by_id[item] for item in _related_formula_ids(selected.id, dependency_edges) if item in formula_by_id]

    nodes = [_formula_node(selected, lane="center", group_id="focus", context=context)]
    if section:
        nodes.append(_section_node(section, lane="top", group_id="focus"))
    if context:
        nodes.append(_context_node(context, lane="left", group_id="focus"))
    for index, definition in enumerate(definitions, start=1):
        nodes.append(_definition_node(f"{context.id if context else selected.id}:def:{index}", definition, lane="left", group_id="focus"))
    for variable in variables:
        nodes.append(_variable_node(variable, lane="bottom", group_id="focus"))
    for item in related[:8]:
        nodes.append(_formula_node(item, lane="right", group_id="focus", context=_context_for_formula(doc, item.id)))

    edges = []
    if section:
        edges.append(_edge(section.id, selected.id, "in_section"))
    if context:
        edges.append(_edge(context.id, selected.id, "has_context"))
    for index, _definition in enumerate(definitions, start=1):
        edges.append(_edge(f"{context.id if context else selected.id}:def:{index}", selected.id, "defines"))
    for variable in variables:
        edges.append(_edge(selected.id, variable.id, "uses_variable"))
    edges.extend(_edge(rel.source_id, rel.target_id, rel.type, rel) for rel in dependency_edges)
    return _projection(
        title="Метавершина формулы",
        description="Внешний уровень метавершины: документный объект формулы, ее контекст, определения, связанные формулы и обозначения.",
        layout="formula_focus",
        nodes=nodes[:80],
        edges=edges[:80],
        groups=[],
        cards=[],
        selected=_formula_details(selected, context),
    )


def _variable_focus_projection(doc: GraphReadyDocument, *, variable: str | None = None, limit: int = 80, **_: Any) -> dict[str, Any]:
    selected = _select_variable(doc, variable)
    if selected is None:
        return _empty("Поиск переменной", "Переменные не найдены. Введите обозначение после обработки документа.")
    formula_by_id = {item.id: item for item in doc.formulas}
    context_by_formula = {ctx.formula_id: ctx for ctx in doc.formula_contexts}
    section_by_id = {item.id: item for item in doc.document_structure.sections}
    formulas = [formula_by_id[item] for item in selected.formula_ids if item in formula_by_id][: min(24, limit)]

    nodes = [_variable_node(selected, lane="center", group_id="ego")]
    edges = []
    groups: dict[str, dict[str, Any]] = {}
    for formula in formulas:
        section_id = formula.section_id or "no_section"
        section = section_by_id.get(section_id)
        groups.setdefault(
            section_id,
            {"id": section_id, "type": "section", "title": section.title if section else "Без раздела", "formulaIds": [], "metrics": {"formulas": 0, "contexts": 0}},
        )
        groups[section_id]["formulaIds"].append(formula.id)
        groups[section_id]["metrics"]["formulas"] += 1
        nodes.append(_formula_node(formula, lane=section_id, group_id=section_id, context=context_by_formula.get(formula.id)))
        edges.append(_edge(selected.id, formula.id, "appears_in"))
        context = context_by_formula.get(formula.id)
        if context:
            groups[section_id]["metrics"]["contexts"] += 1
            nodes.append(_context_node(context, lane=section_id, group_id=section_id, compact=True))
            edges.append(_edge(formula.id, context.id, "has_context"))
        if section and not any(node["id"] == section.id for node in nodes):
            nodes.append(_section_node(section, lane=section_id, group_id=section_id, compact=True))
            edges.append(_edge(section.id, formula.id, "section_contains_formula"))

    for index, definition in enumerate(selected.possible_definitions[:8], start=1):
        node_id = f"{selected.id}:definition:{index}"
        nodes.append(_definition_node(node_id, definition, lane="definitions", group_id="ego"))
        edges.append(_edge(node_id, selected.id, "defines"))

    return _projection(
        title="Поиск переменной",
        description="Маленький ego-graph вокруг переменной: формулы, определения, контексты и секции, сгруппированные по разделам.",
        layout="variable_ego",
        nodes=nodes[:80],
        edges=edges[:80],
        groups=list(groups.values()),
        cards=[],
        selected=_variable_details(selected),
    )


def _metaedge_lanes_projection(doc: GraphReadyDocument, *, limit: int = 80, **_: Any) -> dict[str, Any]:
    rich = build_metagraph_from_graph_ready(doc)
    metaedges = sorted(
        rich.metaedges.values(),
        key=lambda item: (len(item.source_set) + len(item.target_set) + len(item.mediator_nodes) + len(item.mediator_metavertices), item.type),
        reverse=True,
    )[: min(12, limit)]
    nodes = []
    edges = []
    groups = []
    for row_index, metaedge in enumerate(metaedges, start=1):
        meta_id = metaedge.id
        groups.append({"id": meta_id, "type": "metaedge_row", "title": metaedge.type, "row": row_index})
        nodes.append(
            _node(
                meta_id,
                "metaedge",
                _metaedge_label(metaedge.type),
                lane="metaedge",
                row=row_index,
                groupId=meta_id,
                details=_metaedge_details(metaedge),
            )
        )
        for lane, values, edge_type in (
            ("source", metaedge.source_set[:8], "metaedge_source"),
            ("mediator", [*metaedge.mediator_nodes, *metaedge.mediator_metavertices][:8], "metaedge_mediator"),
            ("target", metaedge.target_set[:8], "metaedge_target"),
        ):
            for index, value in enumerate(values, start=1):
                node_id = f"{meta_id}:{lane}:{index}"
                nodes.append(
                    _node(
                        node_id,
                        _infer_object_type(value),
                        _short_object_label(value),
                        lane=lane,
                        row=row_index,
                        groupId=meta_id,
                        details={"id": value, "type": lane, "metaedge_id": meta_id, "role": lane},
                    )
                )
                if lane == "target":
                    edges.append(_edge(meta_id, node_id, edge_type))
                else:
                    edges.append(_edge(node_id, meta_id, edge_type))
    return _projection(
        title="Метаребра",
        description="Lane-view для многоместных отношений: SOURCE SET | METAEDGE | MEDIATORS | TARGET SET. Force-layout не используется.",
        layout="metaedge_lanes",
        nodes=nodes[:80],
        edges=edges[:80],
        groups=groups,
        cards=[],
    )


def _ast_tree_projection(doc: GraphReadyDocument, *, formula: str | None = None, **_: Any) -> dict[str, Any]:
    selected = _select_formula(doc, formula)
    if selected is None:
        return _empty("Внутренний граф метавершины", "Формулы не найдены.")
    ast_nodes, ast_edges = _formula_ast_projection(selected)
    return _projection(
        title="Внутренний граф метавершины",
        description="Внутренний уровень метавершины: AST-подобный граф выражения с ролями root, lhs, rhs, operand и operator.",
        layout="ast_tree",
        nodes=ast_nodes[:80],
        edges=ast_edges[:80],
        groups=[],
        cards=[],
        selected=_formula_details(selected, _context_for_formula(doc, selected.id)),
    )


def _formula_ast_projection(formula: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    latex = formula.latex or ""
    nodes = [
        _node(
            formula.id,
            "ast",
            _short_formula_label(latex),
            astRole="root",
            details={**_formula_details(formula, None), "ast_role": "root", "semantic_type": "formula_metavertex_internal"},
        )
    ]
    edges = []
    if "\\begin{cases}" in latex or "\\begin{aligned}" in latex or "\\begin{array}" in latex:
        parts = _split_latex_rows(latex)
        parent = formula.id
    elif "=" in latex:
        lhs, rhs = latex.split("=", 1)
        lhs_id = f"{formula.id}:lhs"
        rhs_id = f"{formula.id}:rhs"
        nodes.append(_node(lhs_id, "ast", _ast_label(lhs, "левая часть"), astRole="lhs", details={"id": lhs_id, "type": "ast_lhs", "text": lhs.strip()}))
        nodes.append(_node(rhs_id, "ast", _ast_label(rhs, "правая часть"), astRole="rhs", details={"id": rhs_id, "type": "ast_rhs", "text": rhs.strip()}))
        edges.append(_edge(formula.id, lhs_id, "ast_lhs"))
        edges.append(_edge(formula.id, rhs_id, "ast_rhs"))
        parts = _split_operands(rhs)
        parent = rhs_id
    else:
        parts = _split_operands(latex)
        parent = formula.id
    for index, operand in enumerate(parts[:12], start=1):
        node_id = f"{formula.id}:operand:{index}"
        nodes.append(_node(node_id, "ast", _ast_label(operand, f"операнд {index}"), astRole="operand", details={"id": node_id, "type": "ast_operand", "text": operand}))
        edges.append(_edge(parent, node_id, "ast_operand"))
    for index, operator in enumerate(formula.operators or _operators_from_latex(latex), start=1):
        node_id = f"{formula.id}:operator:{index}"
        nodes.append(_node(node_id, "ast", operator, astRole="operator", details={"id": node_id, "type": "ast_operator", "operator": operator}))
        edges.append(_edge(formula.id, node_id, "ast_argument"))
    return nodes, edges


def _split_latex_rows(latex: str) -> list[str]:
    value = re.sub(r"\\begin\{(?:cases|aligned|array)\}", "", latex or "")
    value = re.sub(r"\\end\{(?:cases|aligned|array)\}", "", value)
    rows = [row.strip() for row in re.split(r"(?<!\\)\\\\", value) if row.strip()]
    return rows or ([value.strip()] if value.strip() else [])


def _ast_label(value: str, fallback: str) -> str:
    compact = re.sub(r"\s+", " ", str(value or "")).strip()
    return _short_label(compact or fallback, 44)


def _short_formula_label(latex: str) -> str:
    return _ast_label(latex, "формула")


def _projection(
    *,
    title: str,
    description: str,
    layout: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    cards: list[dict[str, Any]],
    selected: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "description": description,
        "layout": layout,
        "nodes": nodes[:80],
        "edges": edges[:80],
        "groups": groups,
        "cards": cards,
        "selectedObjectDetails": selected,
    }


def _node(node_id: str, kind: str, label: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": kind,
        "type": kind,
        "label": _short_label(label),
        **extra,
    }


def _edge(source: str, target: str, edge_type: str, relation: Any | None = None) -> dict[str, Any]:
    return {
        "id": getattr(relation, "id", None) or f"{source}->{target}:{edge_type}",
        "source": source,
        "target": target,
        "type": edge_type,
        "label": edge_type,
        "details": {
            "id": getattr(relation, "id", None) or f"{source}->{target}:{edge_type}",
            "type": edge_type,
            "source": source,
            "target": target,
            "evidence": getattr(relation, "evidence", None),
            "confidence": getattr(relation, "confidence", None),
        },
    }


def _dedupe_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for edge in edges:
        edge_id = str(edge.get("id") or f"{edge.get('source')}->{edge.get('target')}:{edge.get('type')}")
        if edge_id in seen:
            continue
        seen.add(edge_id)
        result.append(edge)
    return result


def _formula_node(formula: Any, *, lane: str, group_id: str, context: Any | None = None) -> dict[str, Any]:
    return _node(
        formula.id,
        "formula",
        _formula_label(formula),
        lane=lane,
        groupId=group_id,
        rank=_formula_rank(formula),
        details=_formula_details(formula, context),
    )


def _variable_node(variable: Any, *, lane: str, group_id: str) -> dict[str, Any]:
    return _node(
        variable.id,
        "variable",
        _short_symbol(variable.normalized_symbol),
        lane=lane,
        groupId=group_id,
        details=_variable_details(variable),
    )


def _definition_node(node_id: str, definition: dict[str, Any], *, lane: str, group_id: str) -> dict[str, Any]:
    return _node(
        node_id,
        "definition",
        "Definition",
        lane=lane,
        groupId=group_id,
        details={"id": node_id, "type": "definition", **definition},
    )


def _context_node(context: Any, *, lane: str, group_id: str, compact: bool = False) -> dict[str, Any]:
    return _node(
        context.id,
        "context",
        "Context",
        lane=lane,
        groupId=group_id,
        compact=compact,
        details={
            "id": context.id,
            "type": "context",
            "formula_id": context.formula_id,
            "token": context.token,
            "text": context.window_text,
            "context_before": context.context_before,
            "context_after": context.context_after,
            "definitions": [item.model_dump() for item in context.possible_definitions],
        },
    )


def _section_node(section: Any, *, lane: str, group_id: str, compact: bool = False) -> dict[str, Any]:
    return _node(
        section.id,
        "section",
        _section_label(section.title),
        lane=lane,
        groupId=group_id,
        compact=compact,
        details={"id": section.id, "type": "section", "title": section.title, "level": section.level, "order": section.order},
    )


def _formula_details(formula: Any, context: Any | None) -> dict[str, Any]:
    meta_semantics = getattr(formula, "meta_semantics", None)
    derived_metaedges = [item.model_dump() for item in getattr(meta_semantics, "metaedges", [])]
    if not derived_metaedges:
        document_targets = []
        if context:
            document_targets.append(context.id)
        if formula.section_id:
            document_targets.append(formula.section_id)
        if document_targets:
            derived_metaedges.append(
                {
                    "relation_type": "document_context",
                    "target_ids": document_targets,
                    "mediator_context_ids": [context.id] if context else [],
                    "description": "Derived fallback metaedge for formula context and section anchoring.",
                }
            )
    return {
        "id": formula.id,
        "type": "formula",
        "semantic_type": "formula_metavertex",
        "token": formula.token,
        "latex": formula.latex,
        "plain_text": formula.plain_formula_text,
        "symbols": formula.symbols,
        "operators": formula.operators,
        "source": formula.source,
        "confidence": formula.confidence,
        "section_id": formula.section_id,
        "rank": round(_formula_rank(formula), 4),
        "context": context.window_text if context else "",
        "definitions": [item.model_dump() for item in context.possible_definitions] if context else [],
        "formula_metavertex": {
            "id": getattr(meta_semantics, "metavertex_id", None) or f"{formula.id}_mv",
            "semantic_type": getattr(meta_semantics, "semantic_type", None) or "formula_metavertex",
            "outer_document_object": getattr(meta_semantics, "outer_document_object", None) or "document_formula_object",
            "inner_expression_object": getattr(meta_semantics, "inner_expression_object", None) or "ast_like_expression_graph",
            "section_id": getattr(meta_semantics, "section_id", None) or formula.section_id,
            "context_ids": list(getattr(meta_semantics, "context_ids", []) or []),
            "paragraph_ids": list(getattr(meta_semantics, "paragraph_ids", []) or []),
            "variable_ids": list(getattr(meta_semantics, "variable_ids", []) or []),
        },
        "internal_structure": {
            "graph_type": getattr(meta_semantics, "inner_expression_object", None) or "ast_like_expression_graph",
            "roles": list(getattr(meta_semantics, "internal_roles", []) or []),
        },
        "metaedges": derived_metaedges,
        "attributes": formula.model_dump() if hasattr(formula, "model_dump") else {},
    }


def _variable_details(variable: Any) -> dict[str, Any]:
    return {
        "id": variable.id,
        "type": "variable",
        "symbol": variable.symbol,
        "normalized_symbol": variable.normalized_symbol,
        "latex": variable.latex,
        "usage_count": variable.usage_count,
        "formula_ids": variable.formula_ids,
        "context_ids": variable.context_ids,
        "section_ids": variable.section_ids,
        "definitions": variable.possible_definitions,
        "attributes": variable.model_dump() if hasattr(variable, "model_dump") else {},
    }


def _metaedge_details(metaedge: Any) -> dict[str, Any]:
    return {
        "id": metaedge.id,
        "type": "metaedge",
        "metaedge_type": metaedge.type,
        "source_set": metaedge.source_set,
        "target_set": metaedge.target_set,
        "mediator_nodes": metaedge.mediator_nodes,
        "mediator_metavertices": metaedge.mediator_metavertices,
        "contains": metaedge.contains,
        "attributes": dict(metaedge.attributes or {}),
    }


def _hidden_counts(doc: GraphReadyDocument, payload: dict[str, Any], *, allow_ast: bool) -> dict[str, int]:
    visible_node_ids = {item.get("id") for item in payload.get("nodes", []) if isinstance(item, dict)}
    visible_edges = len(payload.get("edges", []) or [])
    technical = [rel for rel in doc.relations if rel.type in TECHNICAL_EDGE_TYPES]
    if allow_ast:
        technical = [rel for rel in technical if not rel.type.startswith("ast_")]
    return {
        "nodes": max(0, len(doc.formulas) + len(doc.variables) + len(doc.formula_contexts) + len(doc.document_structure.sections) - len(visible_node_ids)),
        "edges": max(0, len([rel for rel in doc.relations if rel.type not in TECHNICAL_EDGE_TYPES]) - visible_edges),
        "technical_edges": len(technical),
    }


def _first_details(payload: dict[str, Any]) -> dict[str, Any] | None:
    for node in payload.get("nodes", []):
        if node.get("details"):
            return node["details"]
    return None


def _select_formula(doc: GraphReadyDocument, query: str | None):
    if query:
        raw_value = query.strip()
        value = raw_value.lower()
        compact_value = _compact_formula_key(raw_value)
        for formula in doc.formulas:
            aliases = _formula_aliases(formula)
            compact_aliases = {_compact_formula_key(alias) for alias in aliases}
            if value in aliases or compact_value in compact_aliases:
                return formula
        numbered = re.search(r"(?:formula|FORMULA|f)[_\-\s]*(\d{1,4})", raw_value, flags=re.IGNORECASE)
        if numbered:
            requested_number = int(numbered.group(1))
            for formula in doc.formulas:
                if _formula_number(formula) == requested_number:
                    return formula
        return None
    return max(doc.formulas, key=_formula_rank, default=None)


def _select_variable(doc: GraphReadyDocument, query: str | None):
    if query:
        normalized = normalize_symbol(query)
        for variable in doc.variables:
            if variable.normalized_symbol == normalized or variable.symbol == query:
                return variable
    return max(doc.variables, key=lambda item: (len(item.possible_definitions), item.usage_count, len(item.formula_ids)), default=None)


def _context_for_formula(doc: GraphReadyDocument, formula_id: str):
    return next((item for item in doc.formula_contexts if item.formula_id == formula_id), None)


def _section_for_formula(doc: GraphReadyDocument, formula: Any):
    return next((item for item in doc.document_structure.sections if item.id == formula.section_id), None)


def _formula_dependency_relations(doc: GraphReadyDocument, formula_id: str) -> list[Any]:
    return [
        rel
        for rel in doc.relations
        if rel.type in {"formula_dependency", "formula_references_formula", "depends_on"}
        and (rel.source_id == formula_id or rel.target_id == formula_id)
    ]


def _related_formula_ids(formula_id: str, relations: list[Any]) -> list[str]:
    ids = []
    for relation in relations:
        other = relation.target_id if relation.source_id == formula_id else relation.source_id
        if other not in ids:
            ids.append(other)
    return ids


def _formula_rank(formula: Any) -> float:
    return (
        len(formula.symbols) * 2
        + len(formula.operators)
        + (3 if formula.semantic_hints.definition_like else 0)
        + (2 if formula.semantic_hints.contains_equality else 0)
        + (formula.confidence or 0.0)
    )


def _available_formulas(doc: GraphReadyDocument) -> list[dict[str, str]]:
    return [{"id": item.id, "token": item.token, "label": _formula_label(item)} for item in sorted(doc.formulas, key=_formula_rank, reverse=True)[:120]]


def _formula_aliases(formula: Any) -> set[str]:
    values = {
        str(formula.id or ""),
        str(formula.token or ""),
        str(getattr(formula, "formula_number", None) or ""),
    }
    token_match = re.search(r"formula_(\d+)", str(formula.token or ""), flags=re.IGNORECASE)
    id_match = re.search(r"(\d{1,4})$", str(formula.id or ""))
    for match in [token_match, id_match]:
        if not match:
            continue
        number = int(match.group(1))
        values.update({f"f{number}", f"f{number:03d}", f"formula_{number}", f"FORMULA_{number:03d}", str(number)})
    return {value.lower() for value in values if value}


def _formula_number(formula: Any) -> int | None:
    for value in [getattr(formula, "formula_number", None), getattr(formula, "token", None), getattr(formula, "id", None)]:
        match = re.search(r"(\d{1,4})", str(value or ""))
        if match:
            return int(match.group(1))
    return None


def _compact_formula_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _available_variables(doc: GraphReadyDocument) -> list[str]:
    return [item.normalized_symbol for item in sorted(doc.variables, key=lambda item: item.usage_count, reverse=True)[:160]]


def _formula_label(formula: Any) -> str:
    token = formula.token or formula.id
    match = re.search(r"FORMULA_(\d+)", token)
    if match:
        return f"F{int(match.group(1)):03d}"
    return _short_label(token, 10)


def _short_symbol(symbol: str) -> str:
    value = str(symbol or "").replace("\\", "")
    return _short_label(value, 12)


def _section_label(title: str) -> str:
    return _short_label(title or "Section", 34)


def _metaedge_label(kind: str) -> str:
    return _short_label(kind.replace("_", " "), 28)


def _short_object_label(value: str) -> str:
    if "FORMULA_" in value or re.search(r"\bf\d+\b", value, flags=re.IGNORECASE):
        match = re.search(r"(\d+)", value)
        return f"F{int(match.group(1)):03d}" if match else "Formula"
    if "context" in value or "sentence" in value or "text" in value:
        return "Context"
    if "definition" in value:
        return "Definition"
    return _short_label(value, 16)


def _infer_object_type(value: str) -> str:
    text = value.lower()
    if "formula" in text or re.search(r"\bf\d+\b", text):
        return "formula"
    if "definition" in text:
        return "definition"
    if "context" in text or "sentence" in text or "text" in text:
        return "context"
    if "section" in text:
        return "section"
    return "variable"


def _short_label(value: str, limit: int = 24) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _operators_from_latex(latex: str) -> list[str]:
    command_labels = [
        ("\\frac", "fraction"),
        ("\\sum", "sum"),
        ("\\prod", "product"),
        ("\\int", "integral"),
        ("\\lim", "limit"),
        ("\\sqrt", "sqrt"),
        ("\\circ", "composition"),
        ("\\cdots", "ellipsis"),
        ("\\dots", "ellipsis"),
        ("\\cup", "union"),
        ("\\cap", "intersection"),
        ("\\in", "membership"),
        ("\\to", "mapping"),
    ]
    symbol_labels = [
        ("=", "equals"),
        ("+", "plus"),
        ("-", "minus"),
        ("^", "power"),
    ]
    commands = set(re.findall(r"\\[A-Za-z]+", latex or ""))
    operators = [label for command, label in command_labels if command in commands]
    operators.extend(label for needle, label in symbol_labels if needle in (latex or ""))
    result: list[str] = []
    for operator in operators:
        if operator not in result:
            result.append(operator)
    return result


def _split_operands(latex: str) -> list[str]:
    value = re.sub(r"\\(?:left|right)", "", latex or "")
    value = re.sub(r"\\(?:quad|qquad|,|;|:|!)\s*", " ", value)
    parts = _split_latex_top_level(value, separators={"+", "-"}, commands={"\\cdot", "\\times", "\\circ", "\\cdots", "\\dots", "\\ldots"})
    return parts or ([value.strip()] if value.strip() else [])


def _split_latex_top_level(value: str, *, separators: set[str], commands: set[str]) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    index = 0
    while index < len(value):
        char = value[index]
        if char == "\\":
            command_match = re.match(r"\\[A-Za-z]+", value[index:])
            command = command_match.group(0) if command_match else char
            if depth == 0 and command in commands:
                part = "".join(current).strip()
                if part:
                    parts.append(part)
                current = []
                index += len(command)
                continue
            current.append(command)
            index += len(command)
            continue
        if char in "{[(":
            depth += 1
        elif char in "}])" and depth:
            depth -= 1
        if depth == 0 and char in separators:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
            index += 1
            continue
        current.append(char)
        index += 1
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def _synthetic_section(doc: GraphReadyDocument):
    class Section:
        id = "document"
        title = doc.filename or "Document"
        level = 0
        order = 1

    return Section()


def _dedupe_dicts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    seen = set()
    for item in items:
        key = tuple(sorted((str(k), str(v)) for k, v in item.items()))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _empty(title: str, message: str) -> dict[str, Any]:
    return _projection(title=title, description=message, layout="empty", nodes=[], edges=[], groups=[], cards=[], selected=None)
