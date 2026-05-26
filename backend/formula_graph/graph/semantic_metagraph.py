from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from backend.formula_graph.export.graph_ready_export import (
    GraphReadyDocument,
    GraphReadyFormula,
    GraphReadyFormulaContext,
    normalize_symbol,
)
from backend.formula_graph.semantic.formula_interpreter import interpret_formula


def build_semantic_graph_artifacts(doc: GraphReadyDocument) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    graph_input = build_graph_input(doc)
    metagraph = build_metagraph(graph_input, doc.formulas, doc.formula_contexts)
    variable_index = build_variable_index(doc.formulas, doc.formula_contexts, metagraph)
    return graph_input, metagraph, variable_index


def build_graph_input(doc: GraphReadyDocument) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    add_node, add_edge = _dedupe_helpers(nodes, edges)

    doc_id = "DOC_001"
    add_node({"id": doc_id, "type": "document", "value": doc.document_structure.title or doc.filename or "PDF Document"})

    pages = sorted({1})
    for page in pages:
        page_id = _page_id(page)
        add_node({"id": page_id, "type": "page", "page": page, "value": f"Page {page}"})
        add_edge({"source": doc_id, "target": page_id, "relation": "contains"})

    paragraph_by_token: dict[str, str] = {}
    for index, block in enumerate(doc.text_blocks, start=1):
        paragraph_id = f"P_{index:03d}"
        page = 1
        value = block.text_with_tokens or block.text
        add_node({"id": paragraph_id, "type": "paragraph", "page": page, "value": value})
        add_edge({"source": _page_id(page), "target": paragraph_id, "relation": "contains"})
        for token in block.formula_tokens:
            paragraph_by_token.setdefault(token, paragraph_id)

    formula_id_by_old = {_old_formula_id(formula): _formula_id(formula, index) for index, formula in enumerate(doc.formulas, start=1)}
    context_by_formula = {ctx.formula_id: ctx for ctx in doc.formula_contexts}
    variable_id_by_symbol: dict[str, str] = {}

    for index, formula in enumerate(doc.formulas, start=1):
        formula_id = _formula_id(formula, index)
        paragraph_id = paragraph_by_token.get(formula.token) or _nearest_paragraph_id(doc, formula)
        page = 1
        ctx = context_by_formula.get(formula.id)
        definitions = _definitions_by_symbol(ctx)
        variable_names = [_variable_label(normalize_symbol(symbol)) for symbol in formula.symbols if normalize_symbol(symbol)]
        interpretation = interpret_formula(
            formula.normalized_latex or formula.latex,
            variables=variable_names,
            possible_definitions=definitions,
            context=ctx.window_text if ctx else "",
        )
        add_node(
            {
                "id": formula_id,
                "type": "formula",
                "latex": formula.normalized_latex or formula.latex,
                "raw_latex": formula.raw_latex,
                "cleaned_latex": formula.cleaned_latex,
                "plain_formula_text": formula.plain_formula_text or interpretation.get("plain_text", ""),
                "formula_interpretation": interpretation,
                "interpretation": interpretation.get("summary", ""),
                "formula_type": formula.kind,
                "token": formula.token,
                "page": page,
                "paragraph_id": paragraph_id,
            }
        )
        if paragraph_id:
            add_edge({"source": paragraph_id, "target": formula_id, "relation": "contains_formula"})
            add_edge({"source": formula_id, "target": paragraph_id, "relation": "appears_in"})
        if ctx:
            context_id = _context_id(formula_id)
            add_node(
                {
                    "id": context_id,
                    "type": "context",
                    "formula_id": formula_id,
                    "value": ctx.window_text,
                    "context_before": ctx.context_before,
                    "context_after": ctx.context_after,
                    "sentence": ctx.window_text,
                }
            )
            add_edge({"source": formula_id, "target": context_id, "relation": "has_context"})

        for symbol in formula.symbols:
            normalized = normalize_symbol(symbol)
            if not normalized:
                continue
            variable_id = variable_id_by_symbol.setdefault(normalized, _variable_id(normalized))
            add_node({"id": variable_id, "type": "variable", "value": _variable_label(normalized), "normalized": normalized})
            add_edge({"source": formula_id, "target": variable_id, "relation": "has_variable"})
            if ctx:
                context_id = _context_id(formula_id)
                add_edge({"source": variable_id, "target": context_id, "relation": "mentioned_in"})

        if ctx:
            for definition in ctx.possible_definitions:
                normalized = normalize_symbol(definition.symbol)
                if not normalized:
                    continue
                variable_id = variable_id_by_symbol.setdefault(normalized, _variable_id(normalized))
                context_id = _context_id(formula_id)
                term_id = _term_id(definition.definition_text)
                add_node({"id": variable_id, "type": "variable", "value": _variable_label(normalized), "normalized": normalized})
                add_node({"id": term_id, "type": "term", "value": definition.definition_text})
                add_edge({"source": variable_id, "target": context_id, "relation": "defined_near"})
                add_edge({"source": variable_id, "target": term_id, "relation": "defined_as"})

    return {"nodes": nodes, "edges": edges, "_formula_id_by_old": formula_id_by_old}


def build_metagraph(
    graph_input: dict[str, Any],
    formulas: list[GraphReadyFormula],
    formula_contexts: list[GraphReadyFormulaContext],
    *,
    max_edges_per_meta_node: int = 8,
) -> dict[str, Any]:
    meta_nodes = create_meta_nodes(formulas, formula_contexts, graph_input)
    meta_edges = create_meta_edges(meta_nodes, max_edges_per_meta_node=max_edges_per_meta_node)
    metagraph = {
        "nodes": _strip_private_nodes(graph_input.get("nodes", [])),
        "edges": graph_input.get("edges", []),
        "meta_nodes": meta_nodes,
        "meta_edges": meta_edges,
        "statistics": {},
    }
    metagraph["statistics"] = compute_metagraph_statistics(metagraph)
    return metagraph


def create_meta_nodes(
    formulas: list[GraphReadyFormula],
    formula_contexts: list[GraphReadyFormulaContext],
    graph_input: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    context_by_formula = {ctx.formula_id: ctx for ctx in formula_contexts}
    graph_nodes = {node["id"]: node for node in (graph_input or {}).get("nodes", [])}
    formula_id_by_old = (graph_input or {}).get("_formula_id_by_old", {})
    result: list[dict[str, Any]] = []

    for index, formula in enumerate(formulas, start=1):
        formula_id = formula_id_by_old.get(formula.id) or _formula_id(formula, index)
        formula_node = graph_nodes.get(formula_id, {})
        ctx = context_by_formula.get(formula.id)
        context_id = _context_id(formula_id) if ctx else None
        definitions = _definitions_by_symbol(ctx)
        variables = [_variable_id(normalize_symbol(symbol)) for symbol in formula.symbols if normalize_symbol(symbol)]
        variable_names = [_variable_label(normalize_symbol(symbol)) for symbol in formula.symbols if normalize_symbol(symbol)]
        interpretation = interpret_formula(
            formula.normalized_latex or formula.latex,
            variables=variable_names,
            possible_definitions=definitions,
            context=ctx.window_text if ctx else "",
        )
        result.append(
            {
                "id": f"META_{index:03d}",
                "type": "formula_context_unit",
                "formula": formula_id,
                "latex": formula.normalized_latex or formula.latex,
                "raw_latex": formula.raw_latex,
                "cleaned_latex": formula.cleaned_latex,
                "plain_formula_text": formula.plain_formula_text or interpretation.get("plain_text", ""),
                "variables": _dedupe(variables),
                "variable_names": _dedupe(variable_names),
                "contexts": [context_id] if context_id else [],
                "paragraph": formula_node.get("paragraph_id"),
                "page": formula_node.get("page", 1),
                "sentence": ctx.window_text if ctx else "",
                "context_before": ctx.context_before if ctx else "",
                "context_after": ctx.context_after if ctx else "",
                "possible_definitions": definitions,
                "formula_interpretation": interpretation,
                "interpretation": interpretation.get("summary", ""),
                "order": formula.order,
                "token": formula.token,
                "formula_type": formula.kind,
            }
        )
    result.extend(_create_variable_usage_clusters(result))
    result.extend(_create_paragraph_formula_groups(result))
    return result


def create_meta_edges(
    meta_nodes: list[dict[str, Any]],
    max_same_page_edges_per_node: int = 2,
    *,
    max_edges_per_meta_node: int = 8,
    enable_sequence_edges: bool = True,
    enable_same_page_edges: bool = False,
    enable_weak_semantic_edges: bool = True,
    min_edge_weight: float = 0.3,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    def candidate(edge: dict[str, Any]) -> None:
        if edge.get("source") == edge.get("target"):
            return
        if float(edge.get("weight", 0.0)) < min_edge_weight:
            return
        candidates.append(edge)

    ordered = sorted(
        [node for node in meta_nodes if node.get("type") == "formula_context_unit"],
        key=lambda node: (node.get("order", 0), node["id"]),
    )
    if enable_sequence_edges:
        for left, right in zip(ordered, ordered[1:]):
            candidate({"source": left["id"], "target": right["id"], "relation": "sequence", "weight": 0.3, "legacy_relation": "next_formula"})

    definitions: dict[str, list[tuple[dict[str, Any], str]]] = defaultdict(list)
    for node in ordered:
        for variable, definition in node.get("possible_definitions", {}).items():
            definitions[variable].append((node, definition))

    for variable, defining_nodes in definitions.items():
        for source, definition in defining_nodes:
            for target in ordered:
                if target.get("order", 0) <= source.get("order", 0):
                    continue
                if variable in target.get("variable_names", []):
                    candidate(
                        {
                            "source": source["id"],
                            "target": target["id"],
                            "relation": "definition_usage",
                            "variable": variable,
                            "definition": definition,
                            "weight": 0.9,
                            "legacy_relation": "definition_to_usage",
                        }
                    )

    for index, left in enumerate(ordered):
        left_vars = set(left.get("variable_names", []))
        for right in ordered[index + 1 :]:
            shared = sorted(left_vars.intersection(right.get("variable_names", [])))
            for variable in shared:
                candidate(
                    {
                        "source": left["id"],
                        "target": right["id"],
                        "relation": "shared_variable",
                        "variable": variable,
                        "weight": 0.7,
                        "legacy_relation": "shares_variable",
                    }
                )
                if enable_weak_semantic_edges and _has_definition_for_variable(left, variable):
                    candidate(
                        {
                            "source": left["id"],
                            "target": right["id"],
                            "relation": "possible_semantic_dependency",
                            "reason": "shared variable + previous definition + document order",
                            "variable": variable,
                            "weight": 0.85,
                            "legacy_relation": "semantic_dependency",
                        }
                    )

    by_paragraph: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for node in ordered:
        if node.get("paragraph"):
            by_paragraph[str(node["paragraph"])].append(node)
        by_page[int(node.get("page") or 1)].append(node)

    for paragraph, nodes in by_paragraph.items():
        for left, right in zip(nodes, nodes[1:]):
            candidate({"source": left["id"], "target": right["id"], "relation": "same_context", "paragraph_id": paragraph, "weight": 0.5, "legacy_relation": "same_paragraph"})

    if enable_same_page_edges:
        same_page_degree: Counter[str] = Counter()
        for page, nodes in by_page.items():
            for left, right in zip(nodes, nodes[1:]):
                if same_page_degree[left["id"]] >= max_same_page_edges_per_node or same_page_degree[right["id"]] >= max_same_page_edges_per_node:
                    continue
                candidate({"source": left["id"], "target": right["id"], "relation": "same_page", "page": page, "weight": 0.35})
                same_page_degree[left["id"]] += 1
                same_page_degree[right["id"]] += 1

    return _limit_meta_edges(candidates, max_edges_per_meta_node=max_edges_per_meta_node)


def _create_variable_usage_clusters(meta_nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_variable: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in meta_nodes:
        for variable in node.get("variable_names", []):
            by_variable[variable].append(node)

    clusters: list[dict[str, Any]] = []
    for variable, nodes in sorted(by_variable.items()):
        if len(nodes) < 2:
            continue
        definitions = _dedupe([node.get("possible_definitions", {}).get(variable) for node in nodes if node.get("possible_definitions", {}).get(variable)])
        related_variables = sorted(
            {
                other
                for node in nodes
                for other in node.get("variable_names", [])
                if other and other != variable
            }
        )
        clusters.append(
            {
                "id": f"META_VARIABLE_{_safe_id(variable)}",
                "type": "variable_usage_cluster",
                "variable": variable,
                "variable_node": _variable_id(variable),
                "formulas": [node.get("formula") for node in nodes if node.get("formula")],
                "meta_units": [node["id"] for node in nodes],
                "definitions": definitions,
                "related_variables": related_variables,
            }
        )
    return clusters


def _create_paragraph_formula_groups(meta_nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_paragraph: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in meta_nodes:
        paragraph = node.get("paragraph")
        if paragraph:
            by_paragraph[str(paragraph)].append(node)

    groups: list[dict[str, Any]] = []
    for paragraph, nodes in sorted(by_paragraph.items()):
        if len(nodes) < 2:
            continue
        groups.append(
            {
                "id": f"META_PARAGRAPH_{_safe_id(paragraph)}",
                "type": "paragraph_formula_group",
                "paragraph_id": paragraph,
                "formulas": [node.get("formula") for node in nodes if node.get("formula")],
                "meta_units": [node["id"] for node in nodes],
                "variables": sorted({variable for node in nodes for variable in node.get("variable_names", [])}),
            }
        )
    return groups


def _has_definition_for_variable(node: dict[str, Any], variable: str) -> bool:
    return variable in (node.get("possible_definitions") or {})


def _limit_meta_edges(edges: list[dict[str, Any]], *, max_edges_per_meta_node: int) -> list[dict[str, Any]]:
    max_edges_per_meta_node = max(1, int(max_edges_per_meta_node or 8))
    relation_priority = {
        "definition_usage": 0,
        "possible_semantic_dependency": 1,
        "shared_variable": 2,
        "same_context": 3,
        "sequence": 4,
        "same_page": 5,
    }
    ordered = sorted(
        edges,
        key=lambda edge: (
            relation_priority.get(edge.get("relation"), 9),
            -float(edge.get("weight", 0.0)),
            edge.get("source", ""),
            edge.get("target", ""),
            edge.get("variable", ""),
        ),
    )
    limited: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    degree: Counter[str] = Counter()
    for edge in ordered:
        key = (edge.get("source"), edge.get("target"), edge.get("relation"), edge.get("variable"), edge.get("paragraph_id"), edge.get("page"))
        if key in seen:
            continue
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if not source or not target or source == target:
            continue
        if degree[source] >= max_edges_per_meta_node or degree[target] >= max_edges_per_meta_node:
            continue
        seen.add(key)
        limited.append(edge)
        degree[source] += 1
        degree[target] += 1
    return sorted(limited, key=lambda edge: (edge.get("source", ""), edge.get("target", ""), edge.get("relation", ""), edge.get("variable", "")))


def compute_metagraph_statistics(metagraph: dict[str, Any]) -> dict[str, Any]:
    relation_counts = Counter(edge.get("relation") for edge in metagraph.get("edges", []))
    relation_counts.update(edge.get("relation") for edge in metagraph.get("meta_edges", []))
    node_types = Counter(node.get("type") for node in metagraph.get("nodes", []))
    return {
        "nodes_count": len(metagraph.get("nodes", [])),
        "edges_count": len(metagraph.get("edges", [])),
        "meta_nodes_count": len(metagraph.get("meta_nodes", [])),
        "meta_edges_count": len(metagraph.get("meta_edges", [])),
        "formulas_count": node_types.get("formula", 0),
        "variables_count": node_types.get("variable", 0),
        "contexts_count": node_types.get("context", 0),
        "paragraphs_count": node_types.get("paragraph", 0),
        "relations": dict(sorted((key, value) for key, value in relation_counts.items() if key)),
    }


def build_variable_index(
    formulas: list[GraphReadyFormula],
    formula_contexts: list[GraphReadyFormulaContext],
    metagraph: dict[str, Any],
) -> dict[str, Any]:
    meta_by_formula = {node.get("formula"): node for node in metagraph.get("meta_nodes", [])}
    formula_by_id = {node.get("formula"): node for node in metagraph.get("meta_nodes", [])}
    index: dict[str, dict[str, Any]] = {}

    for meta_node in metagraph.get("meta_nodes", []):
        variables = meta_node.get("variable_names", [])
        for variable in variables:
            entry = index.setdefault(
                variable,
                {
                    "variable_node": _variable_id(normalize_symbol(variable)),
                    "formulas": [],
                    "meta_nodes": [],
                    "contexts": [],
                    "definitions": [],
                    "related_variables": [],
                },
            )
            _append_unique(entry["formulas"], meta_node.get("formula"))
            _append_unique(entry["meta_nodes"], meta_node.get("id"))
            for context in meta_node.get("contexts", []):
                _append_unique(entry["contexts"], context)
            for other in variables:
                if other != variable:
                    _append_unique(entry["related_variables"], other)
            definition = meta_node.get("possible_definitions", {}).get(variable)
            if definition:
                _append_unique(entry["definitions"], definition)

    for ctx in formula_contexts:
        for definition in ctx.possible_definitions:
            variable = _variable_label(normalize_symbol(definition.symbol))
            entry = index.setdefault(
                variable,
                {
                    "variable_node": _variable_id(normalize_symbol(variable)),
                    "formulas": [],
                    "meta_nodes": [],
                    "contexts": [],
                    "definitions": [],
                    "related_variables": [],
                },
            )
            _append_unique(entry["contexts"], _context_id(_formula_id_from_token(ctx.token)))
            _append_unique(entry["definitions"], definition.definition_text)

    return dict(sorted(index.items()))


def search_variable_context(
    variable_name: str,
    variable_index: dict[str, Any],
    formulas: list[dict[str, Any]],
    formula_contexts: list[dict[str, Any]],
    metagraph: dict[str, Any],
) -> dict[str, Any]:
    normalized = _variable_label(normalize_symbol(variable_name))
    entry = variable_index.get(normalized)
    if not entry:
        return {"variable": variable_name, "found": False, "message": "Variable not found in document."}

    formula_nodes = {node["id"]: node for node in formulas}
    context_nodes = {node["id"]: node for node in formula_contexts}
    meta_by_id = {node["id"]: node for node in metagraph.get("meta_nodes", [])}
    result_formulas: list[dict[str, Any]] = []
    for formula_id in entry.get("formulas", []):
        formula = formula_nodes.get(formula_id, {})
        meta = next((node for node in metagraph.get("meta_nodes", []) if node.get("formula") == formula_id), {})
        context_id = (meta.get("contexts") or [None])[0]
        context = context_nodes.get(context_id, {})
        result_formulas.append(
            {
                "formula_id": formula_id,
                "latex": formula.get("latex", meta.get("latex", "")),
                "type": formula.get("formula_type", meta.get("formula_type", "")),
                "page": formula.get("page", meta.get("page")),
                "paragraph_id": formula.get("paragraph_id", meta.get("paragraph")),
                "sentence": context.get("sentence", meta.get("sentence", "")),
                "context_before": context.get("context_before", meta.get("context_before", "")),
                "context_after": context.get("context_after", meta.get("context_after", "")),
                "possible_definition": meta.get("possible_definitions", {}).get(normalized),
            }
        )

    meta_ids = set(entry.get("meta_nodes", []))
    meta_relations = [
        edge
        for edge in metagraph.get("meta_edges", [])
        if edge.get("source") in meta_ids or edge.get("target") in meta_ids
        if edge.get("variable") in {None, normalized}
        or edge.get("relation") in {"sequence", "next_formula", "same_page", "same_context", "same_paragraph"}
    ]
    return {
        "variable": normalized,
        "variable_node": entry.get("variable_node"),
        "found": True,
        "formulas": result_formulas,
        "related_meta_nodes": entry.get("meta_nodes", []),
        "related_variables": entry.get("related_variables", []),
        "meta_relations": meta_relations,
    }


def save_semantic_artifacts(doc: GraphReadyDocument, output_dir: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    graph_input, metagraph, variable_index = build_semantic_graph_artifacts(doc)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / f"{doc.document_id}.graph_input.json", {"nodes": graph_input["nodes"], "edges": graph_input["edges"]})
    _write_json(output_dir / f"{doc.document_id}.metagraph.json", metagraph)
    _write_json(output_dir / f"{doc.document_id}.variable_index.json", variable_index)
    return graph_input, metagraph, variable_index


def _dedupe_helpers(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]):
    node_ids: set[str] = set()
    edge_keys: set[tuple[Any, ...]] = set()

    def add_node(node: dict[str, Any]) -> None:
        if not node.get("id") or node["id"] in node_ids:
            return
        node_ids.add(node["id"])
        nodes.append(node)

    def add_edge(edge: dict[str, Any]) -> None:
        key = (edge.get("source"), edge.get("target"), edge.get("relation"), edge.get("variable"))
        if not edge.get("source") or not edge.get("target") or key in edge_keys:
            return
        edge_keys.add(key)
        edges.append(edge)

    return add_node, add_edge


def _nearest_paragraph_id(doc: GraphReadyDocument, formula: GraphReadyFormula) -> str | None:
    for index, block in enumerate(doc.text_blocks, start=1):
        if formula.token and formula.token in (block.text_with_tokens or block.text):
            return f"P_{index:03d}"
    return "P_001" if doc.text_blocks else None


def _definitions_by_symbol(ctx: GraphReadyFormulaContext | None) -> dict[str, str]:
    if not ctx:
        return {}
    result: dict[str, str] = {}
    for definition in ctx.possible_definitions:
        key = _variable_label(normalize_symbol(definition.symbol))
        if key:
            result.setdefault(key, definition.definition_text)
    return result


def _formula_id(formula: GraphReadyFormula, index: int) -> str:
    return _formula_id_from_token(formula.token) or f"FORMULA_{index:03d}"


def _old_formula_id(formula: GraphReadyFormula) -> str:
    return formula.id


def _formula_id_from_token(token: str) -> str:
    match = re.search(r"FORMULA_(\d{3})", token or "")
    return f"FORMULA_{match.group(1)}" if match else ""


def _context_id(formula_id: str) -> str:
    return f"CTX_{formula_id}"


def _page_id(page: int) -> str:
    return f"PAGE_{page:03d}"


def _variable_id(symbol: str) -> str:
    return f"VAR_{_safe_id(_variable_label(symbol))}"


def _variable_label(symbol: str) -> str:
    normalized = normalize_symbol(symbol)
    if normalized.startswith("\\"):
        return normalized.lstrip("\\")
    return normalized


def _term_id(value: str) -> str:
    return f"TERM_{_safe_id(value)}"


def _safe_id(value: str) -> str:
    value = str(value or "").strip().replace("\\", "")
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"[^\w\u0400-\u04FF]+", "_", value, flags=re.UNICODE)
    value = value.strip("_")
    return value or "unknown"


def _dedupe(values: list[Any]) -> list[Any]:
    result: list[Any] = []
    for value in values:
        _append_unique(result, value)
    return result


def _append_unique(values: list[Any], value: Any) -> None:
    if value is not None and value not in values:
        values.append(value)


def _strip_private_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: value for key, value in node.items() if not key.startswith("_")} for node in nodes]


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
