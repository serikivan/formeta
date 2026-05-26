from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

import networkx as nx


def compute_metagraph_metrics(rich_metagraph: dict[str, Any], result: dict[str, Any] | None = None) -> dict[str, Any]:
    nodes = _items(rich_metagraph.get("nodes", []))
    edges = _items(rich_metagraph.get("edges", []))
    metavertices = _items(rich_metagraph.get("metavertices", []))
    metaedges = _items(rich_metagraph.get("metaedges", []))
    result = result or {}

    node_by_id = {node.get("id"): node for node in nodes}
    node_types = Counter(node.get("type") for node in nodes)
    formula_ids = {node.get("id") for node in nodes if node.get("type") == "formula"}
    variable_ids = {node.get("id") for node in nodes if node.get("type") in {"variable", "symbol"}}
    definition_ids = {node.get("id") for node in nodes if node.get("type") == "definition"}
    context_ids = {node.get("id") for node in nodes if node.get("type") in {"context", "formula_context"}}

    graph = nx.Graph()
    digraph = nx.DiGraph()
    graph.add_nodes_from(node_by_id)
    digraph.add_nodes_from(node_by_id)
    for edge in edges:
        source, target = edge.get("source"), edge.get("target")
        if source and target:
            graph.add_edge(source, target)
            digraph.add_edge(source, target)

    formula_to_vars: dict[str, set[str]] = {formula_id: set() for formula_id in formula_ids}
    var_to_defs: dict[str, set[str]] = {variable_id: set() for variable_id in variable_ids}
    for edge in edges:
        source, target, edge_type = edge.get("source"), edge.get("target"), edge.get("type")
        if edge_type in {"has_symbol", "formula_contains_variable", "has_variable"} and source in formula_ids and target in variable_ids:
            formula_to_vars[source].add(target)
        if edge_type in {"defined_as", "has_definition", "variable_defined_in_context"} and source in variable_ids:
            var_to_defs.setdefault(source, set()).add(str(target))

    metaedge_types = Counter(edge.get("type") for edge in metaedges)
    confidence_by_type: dict[str, list[float]] = {}
    evidence_sizes: list[int] = []
    source_sizes: list[int] = []
    target_sizes: list[int] = []
    for metaedge in metaedges:
        edge_type = str(metaedge.get("type") or "unknown")
        attrs = metaedge.get("attributes") or {}
        if isinstance(attrs.get("confidence"), (int, float)):
            confidence_by_type.setdefault(edge_type, []).append(float(attrs["confidence"]))
        evidence = attrs.get("evidence")
        evidence_sizes.append(len(evidence) if isinstance(evidence, list) else (1 if evidence else 0))
        source_sizes.append(len(metaedge.get("source_set") or []))
        target_sizes.append(len(metaedge.get("target_set") or []))

    degrees = dict(graph.degree())
    isolated_formulas = sorted(node_id for node_id in formula_ids if degrees.get(node_id, 0) == 0)
    isolated_variables = sorted(node_id for node_id in variable_ids if degrees.get(node_id, 0) == 0)
    orphan_nodes = sorted(node_id for node_id, degree in degrees.items() if degree == 0)
    formulas_with_context = {
        edge.get("source")
        for edge in edges
        if edge.get("type") == "has_context" and edge.get("source") in formula_ids
    }

    metavertex_sizes = [len(item.get("contains") or []) for item in metavertices]
    formula_semantics = []
    for node in nodes:
        if node.get("type") != "formula":
            continue
        attrs = node.get("attributes") or {}
        meta = attrs.get("meta_semantics") or {}
        if meta:
            formula_semantics.append(meta)
    semantic_metaedge_types = Counter(
        edge.get("relation_type")
        for meta in formula_semantics
        for edge in meta.get("metaedges", []) or []
        if edge.get("relation_type")
    )
    internal_role_counts = [len(meta.get("internal_roles") or []) for meta in formula_semantics]
    sources = Counter((formula.get("source") or "unknown") for formula in result.get("formulas", []))
    flags = Counter(flag for formula in result.get("formulas", []) for flag in formula.get("quality_flags", []))
    timing = result.get("timing") or {}
    processing_steps = result.get("processing_steps") or []

    return {
        "basic": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "metavertex_count": len(metavertices),
            "metaedge_count": len(metaedges),
            "formula_count": len(formula_ids),
            "variable_count": len(variable_ids),
            "paragraph_count": node_types.get("paragraph", 0),
            "context_count": len(context_ids),
            "definition_count": len(definition_ids),
        },
        "connectivity": {
            "connected_components": nx.number_connected_components(graph) if graph.nodes else 0,
            "weakly_connected_components": nx.number_weakly_connected_components(digraph) if digraph.nodes else 0,
            "isolated_formulas": isolated_formulas,
            "isolated_variables": isolated_variables,
            "orphan_nodes": orphan_nodes,
            "orphan_rate": round(len(orphan_nodes) / max(1, len(nodes)), 4),
        },
        "formulas": {
            "average_variables_per_formula": _avg(len(value) for value in formula_to_vars.values()),
            "formulas_with_context_ratio": round(len(formulas_with_context) / max(1, len(formula_ids)), 4),
            "formulas_without_context_count": max(0, len(formula_ids) - len(formulas_with_context)),
            "formula_context_coverage": round(len(formulas_with_context) / max(1, len(formula_ids)), 4),
            "formula_dependency_count": metaedge_types.get("formula_dependency", 0),
            "formulas_with_metavertex_semantics_ratio": round(len(formula_semantics) / max(1, len(formula_ids)), 4),
            "average_internal_role_count": _avg(internal_role_counts),
        },
        "variables": {
            "average_definitions_per_variable": _avg(len(value) for value in var_to_defs.values()),
            "variables_with_definition_ratio": round(sum(1 for value in var_to_defs.values() if value) / max(1, len(variable_ids)), 4),
            "ambiguous_variables": [node_id for node_id, defs in var_to_defs.items() if len(defs) > 1],
            "variable_section_spread": _variable_section_spread(nodes),
            "top_variables_by_usage": _top_variables_by_usage(nodes),
        },
        "metavertices": {
            "average_metavertex_size": _avg(metavertex_sizes),
            "max_metavertex_size": max(metavertex_sizes or [0]),
            "average_fragment_interface_size": _avg(len(item.get("entry_points") or []) + len(item.get("exit_points") or []) for item in metavertices),
            "internal_edges_count": sum(1 for edge in edges if _same_metavertex(edge, metavertices)),
            "external_edges_count": sum(1 for edge in edges if not _same_metavertex(edge, metavertices)),
            "cohesion": 0.0,
            "coupling": 0.0,
        },
        "metaedges": {
            "metaedge_count_by_type": dict(sorted(metaedge_types.items())),
            "average_source_set_size": _avg(source_sizes),
            "average_target_set_size": _avg(target_sizes),
            "average_evidence_count": _avg(evidence_sizes),
            "average_confidence_by_type": {key: _avg(values) for key, values in confidence_by_type.items()},
            "semantic_metaedge_count_by_relation": dict(sorted(semantic_metaedge_types.items())),
        },
        "semantic": {
            "formula_metavertex_count": sum(1 for item in metavertices if item.get("type") == "formula_metavertex"),
            "formulas_with_internal_graph_ratio": round(sum(1 for meta in formula_semantics if meta.get("internal_roles")) / max(1, len(formula_ids)), 4),
            "internal_graph_type_distribution": dict(
                sorted(Counter((meta.get("inner_expression_object") or "unknown") for meta in formula_semantics).items())
            ),
            "document_context_metaedge_count": semantic_metaedge_types.get("document_context", 0),
        },
        "quality": {
            "extraction_sources_distribution": dict(sorted(sources.items())),
            "formula_quality_flags_distribution": dict(sorted(flags.items())),
            "OCR warnings count": sum(1 for warning in result.get("warnings", []) if "ocr" in str(warning).lower()),
            "partial/error status count": sum(1 for step in processing_steps if step.get("status") in {"partial", "error"}),
            "text_layer_used": _source_used(result, "pdf_text_layer"),
            "OCR_used": any(_source_used(result, source) for source in ("paddleocr", "tesseract", "got_ocr")),
            "tex_source_used": _source_used(result, "tex_source"),
            "timing": timing,
        },
    }


def aggregate_metagraph_metrics(results_dir: Path) -> dict[str, Any]:
    documents: list[dict[str, Any]] = []
    for rich_path in sorted(results_dir.glob("*.rich_metagraph.json")):
        document_id = rich_path.name.removesuffix(".rich_metagraph.json")
        result_path = results_dir / f"{document_id}.json"
        rich = json.loads(rich_path.read_text(encoding="utf-8"))
        result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else {}
        metrics = compute_metagraph_metrics(rich, result)
        basic = metrics["basic"]
        documents.append(
            {
                "document_id": document_id,
                "filename": result.get("filename"),
                "status": result.get("status", "unknown"),
                "formula_count": basic["formula_count"],
                "isolated_formulas_count": len(metrics["connectivity"]["isolated_formulas"]),
                "formula_context_coverage": metrics["formulas"]["formula_context_coverage"],
                "variables_with_definition_ratio": metrics["variables"]["variables_with_definition_ratio"],
                "formulas_with_metavertex_semantics_ratio": metrics["formulas"]["formulas_with_metavertex_semantics_ratio"],
                "document_context_metaedge_count": metrics["semantic"]["document_context_metaedge_count"],
                "extraction_sources_distribution": metrics["quality"]["extraction_sources_distribution"],
            }
        )
    return _aggregate_documents(documents)


def list_analytics_documents(results_dir: Path) -> list[dict[str, Any]]:
    return aggregate_metagraph_metrics(results_dir)["documents"]


def _aggregate_documents(documents: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = Counter(doc.get("status", "unknown") for doc in documents)
    formula_counts = [doc.get("formula_count", 0) for doc in documents]
    isolated_counts = [doc.get("isolated_formulas_count", 0) for doc in documents]
    source_distribution: Counter[str] = Counter()
    for doc in documents:
        source_distribution.update(doc.get("extraction_sources_distribution", {}))
    return {
        "documents_count": len(documents),
        "documents": documents,
        "status_distribution": dict(sorted(statuses.items())),
        "formula_count": _summary(formula_counts),
        "isolated_formula_count": _summary(isolated_counts),
        "top_documents_by_formulas": sorted(documents, key=lambda item: item["formula_count"], reverse=True)[:10],
        "top_documents_by_isolated_formulas": sorted(documents, key=lambda item: item["isolated_formulas_count"], reverse=True)[:10],
        "average_formula_context_coverage": _avg(doc.get("formula_context_coverage", 0) for doc in documents),
        "average_variable_definition_coverage": _avg(doc.get("variables_with_definition_ratio", 0) for doc in documents),
        "average_metavertex_semantic_coverage": _avg(doc.get("formulas_with_metavertex_semantics_ratio", 0) for doc in documents),
        "document_context_metaedge_count": _summary([int(doc.get("document_context_metaedge_count", 0) or 0) for doc in documents]),
        "formula_source_distribution": dict(sorted(source_distribution.items())),
    }


def _items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return list(value.values())
    return list(value or [])


def _avg(values) -> float:
    items = [float(value) for value in values]
    return round(mean(items), 4) if items else 0.0


def _summary(values: list[int]) -> dict[str, float | int]:
    return {"sum": sum(values), "avg": _avg(values), "min": min(values or [0]), "max": max(values or [0])}


def _same_metavertex(edge: dict[str, Any], metavertices: list[dict[str, Any]]) -> bool:
    source, target = edge.get("source"), edge.get("target")
    return any(source in (mv.get("contains") or []) and target in (mv.get("contains") or []) for mv in metavertices)


def _variable_section_spread(nodes: list[dict[str, Any]]) -> dict[str, int]:
    result = {}
    for node in nodes:
        if node.get("type") not in {"symbol", "variable"}:
            continue
        attrs = node.get("attributes") or {}
        result[node.get("label") or node.get("id")] = len(attrs.get("section_ids") or [])
    return result


def _top_variables_by_usage(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    variables = []
    for node in nodes:
        if node.get("type") not in {"symbol", "variable"}:
            continue
        attrs = node.get("attributes") or {}
        variables.append({"variable": node.get("label") or node.get("id"), "usage_count": attrs.get("usage_count", 0)})
    return sorted(variables, key=lambda item: item["usage_count"], reverse=True)[:20]


def _source_used(result: dict[str, Any], source: str) -> bool:
    return any(item.get("source") == source for item in result.get("text_blocks", [])) or any(
        item.get("source") == source for item in result.get("formulas", [])
    )
