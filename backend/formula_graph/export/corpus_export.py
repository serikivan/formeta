from __future__ import annotations

import json
import uuid
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from backend.formula_graph.config import settings
from backend.formula_graph.export.graph_ready_export import (
    GraphReadyDocument,
    load_graph_ready_document,
    search_variable_in_graph_ready,
    normalize_symbol,
)
from backend.formula_graph.graph.corpus_graph_builder import build_corpus_graph
from backend.formula_graph.graph.corpus_metagraph_builder import build_corpus_metagraph


def create_corpus(document_ids: list[str], name: str | None = None, corpus_id: str | None = None) -> dict[str, Any]:
    documents = [_load_graph_ready(document_id) for document_id in document_ids]
    corpus_id = corpus_id or f"corpus_{uuid.uuid4().hex[:12]}"
    corpus_name = name or f"Корпус: {len(documents)} документов"
    graph = build_corpus_graph(corpus_id, corpus_name, documents)
    metagraph = build_corpus_metagraph(graph)
    metrics = compute_corpus_metrics(graph, metagraph)
    visualization = corpus_visualization_payload(graph, metagraph)
    root = _corpus_dir(corpus_id)
    root.mkdir(parents=True, exist_ok=True)
    _write(root / "corpus.json", {"corpus_id": corpus_id, "name": corpus_name, "document_ids": document_ids, "documents": graph["documents"]})
    _write(root / "graph.json", graph)
    _write(root / "metagraph.json", metagraph)
    _write(root / "metrics.json", metrics)
    _write(root / "visualization.json", visualization)
    return {"corpus_id": corpus_id, "name": corpus_name, "document_ids": document_ids, "documents": graph["documents"]}


def load_corpus(corpus_id: str) -> dict[str, Any]:
    return _read(_corpus_dir(corpus_id) / "corpus.json")


def load_corpus_graph(corpus_id: str) -> dict[str, Any]:
    return _read(_corpus_dir(corpus_id) / "graph.json")


def load_corpus_metagraph(corpus_id: str) -> dict[str, Any]:
    return _read(_corpus_dir(corpus_id) / "metagraph.json")


def load_corpus_metrics(corpus_id: str) -> dict[str, Any]:
    return _read(_corpus_dir(corpus_id) / "metrics.json")


def load_corpus_visualization(corpus_id: str) -> dict[str, Any]:
    return _read(_corpus_dir(corpus_id) / "visualization.json")


def compute_corpus_metrics(graph: dict[str, Any], metagraph: dict[str, Any]) -> dict[str, Any]:
    docs = graph.get("documents") or []
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    formulas = [node for node in nodes if node.get("type") == "formula"]
    variables = [node for node in nodes if node.get("type") == "variable"]
    normalized = {node.get("normalized_label") or node.get("label") for node in variables}
    cross_variable_edges = [edge for edge in edges if edge.get("type") == "same_variable_label"]
    cross_formula_edges = [edge for edge in edges if edge.get("type") == "similar_formula"]
    status_distribution = Counter(doc.get("status", "unknown") for doc in docs)
    source_distribution = Counter((node.get("attributes") or {}).get("source", "unknown") for node in formulas)
    warning_counts = {doc["document_id"]: len(doc.get("warnings") or []) for doc in docs}
    return {
        "corpus_id": graph.get("corpus_id"),
        "total_documents": len(docs),
        "total_formulas": len(formulas),
        "total_variables": len(variables),
        "unique_normalized_variables": len([item for item in normalized if item]),
        "cross_document_variable_links": len(cross_variable_edges),
        "cross_document_formula_links": len(cross_formula_edges),
        "average_formula_context_coverage": _avg((doc.get("summary") or {}).get("contexts_count", 0) / max(1, (doc.get("summary") or {}).get("formulas_count", 0)) for doc in docs),
        "average_variable_definition_coverage": _avg(_doc_definition_coverage(doc) for doc in docs),
        "conflicting_variable_meanings": _count_conflicts(graph),
        "documents_by_formula_count": sorted(docs, key=lambda item: (item.get("summary") or {}).get("formulas_count", 0), reverse=True),
        "documents_by_warning_count": sorted(docs, key=lambda item: warning_counts.get(item["document_id"], 0), reverse=True),
        "extraction_sources_distribution": dict(sorted(source_distribution.items())),
        "status_distribution": dict(sorted(status_distribution.items())),
        "graph": {"node_count": len(nodes), "edge_count": len(edges)},
        "metagraph": metagraph.get("metrics") or {},
    }


def corpus_variable_search(corpus_id: str, query: str) -> dict[str, Any]:
    corpus = load_corpus(corpus_id)
    normalized_query = normalize_symbol(query)
    results_by_document = []
    raw_variants: set[str] = set()
    total_occurrences = 0
    definitions_by_text: dict[str, list[dict[str, Any]]] = defaultdict(list)
    graph = load_corpus_graph(corpus_id)

    for doc in corpus.get("documents") or []:
        graph_ready = _load_graph_ready(doc["document_id"])
        search = search_variable_in_graph_ready(graph_ready, query)
        if not search.get("matches_count"):
            continue
        variable = search.get("variable") or {}
        raw_variants.add(variable.get("symbol") or normalized_query)
        total_occurrences += search.get("matches_count", 0)
        for definition in search.get("definitions") or []:
            key = str(definition.get("definition_text") or definition.get("evidence") or "").strip().lower()
            if key:
                definitions_by_text[key].append({"document_id": doc["document_id"], "definition": definition})
        results_by_document.append(
            {
                "document_id": doc["document_id"],
                "filename": doc.get("filename"),
                "formulas": search.get("related_formulas") or [],
                "definitions": search.get("definitions") or [],
                "contexts": search.get("matches") or [],
                "semantic_matches": [
                    item.get("formula_semantics")
                    for item in (search.get("matches") or [])
                    if item.get("formula_semantics")
                ],
                "scope": search.get("scope"),
                "confidence": max([item.get("confidence", 0.0) for item in search.get("matches") or []] or [0.0]),
            }
        )

    conflicts = _definition_conflicts(normalized_query, definitions_by_text)
    visualization = _variable_search_visualization(graph, normalized_query)
    return {
        "query": query,
        "normalized_query": normalized_query,
        "documents_count": len(results_by_document),
        "total_occurrences": total_occurrences,
        "raw_variants": sorted(raw_variants),
        "results_by_document": results_by_document,
        "conflicts": conflicts,
        "cross_document_links": [edge for edge in graph.get("edges", []) if edge.get("type") == "same_variable_label" and edge.get("attributes", {}).get("normalized_label") == normalized_query],
        "visualization": visualization,
    }


def corpus_visualization_payload(graph: dict[str, Any], metagraph: dict[str, Any]) -> dict[str, Any]:
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    return {
        "mode": "corpus_graph",
        "elements": [{"data": _display_node(node)} for node in nodes[:260]] + [{"data": _display_edge(edge)} for edge in edges[:520]],
        "stats": {
            "original_node_count": len(nodes),
            "original_edge_count": len(edges),
            "node_count": min(len(nodes), 260),
            "edge_count": min(len(edges), 520),
            "truncated": len(nodes) > 260 or len(edges) > 520,
            "metaedge_count": len(metagraph.get("metaedges") or []),
        },
    }


def _display_node(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": node.get("id"),
        "label": node.get("label") or node.get("id"),
        "type": node.get("type"),
        "document_id": node.get("document_id"),
        "filename": node.get("filename"),
        "latex": node.get("latex"),
        "text": node.get("text"),
        "attributes": node.get("attributes") or node,
    }


def _display_edge(edge: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": edge.get("id"),
        "source": edge.get("source"),
        "target": edge.get("target"),
        "label": edge.get("type"),
        "type": edge.get("type"),
        "attributes": edge.get("attributes") or edge,
    }


def _load_graph_ready(document_id: str) -> GraphReadyDocument:
    path = settings.results_dir / f"{document_id}.graph_ready.json"
    if not path.exists():
        raise FileNotFoundError(f"graph_ready JSON not found for {document_id}")
    return load_graph_ready_document(path)


def _corpus_dir(corpus_id: str) -> Path:
    return settings.results_dir / "corpus" / corpus_id


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(str(path))
    return json.loads(path.read_text(encoding="utf-8"))


def _avg(values) -> float:
    items = [float(value) for value in values]
    return round(sum(items) / len(items), 4) if items else 0.0


def _doc_definition_coverage(doc: dict[str, Any]) -> float:
    summary = doc.get("summary") or {}
    variables = summary.get("variables_count", 0)
    contexts = summary.get("contexts_count", 0)
    return min(1.0, contexts / max(1, variables))


def _count_conflicts(graph: dict[str, Any]) -> int:
    return len([edge for edge in graph.get("edges", []) if edge.get("type") == "same_variable_label"]) // 4


def _definition_conflicts(variable: str, definitions_by_text: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    keys = [key for key, items in definitions_by_text.items() if items]
    if len(keys) < 2:
        return []
    first = definitions_by_text[keys[0]][0]
    return [
        {
            "variable": variable,
            "document_a": first["document_id"],
            "meaning_a": keys[0],
            "document_b": definitions_by_text[key][0]["document_id"],
            "meaning_b": key,
        }
        for key in keys[1:6]
    ]


def _variable_search_visualization(graph: dict[str, Any], normalized_query: str) -> dict[str, Any]:
    variable_ids = {
        node["id"]
        for node in graph.get("nodes", [])
        if node.get("type") == "variable" and (node.get("normalized_label") or node.get("label")) == normalized_query
    }
    related_ids = set(variable_ids)
    edges = []
    for edge in graph.get("edges", []):
        if edge.get("source") in related_ids or edge.get("target") in related_ids:
            edges.append(edge)
            related_ids.add(edge.get("source"))
            related_ids.add(edge.get("target"))
    nodes = [node for node in graph.get("nodes", []) if node.get("id") in related_ids]
    return {"nodes": [_display_node(node) for node in nodes[:120]], "edges": [_display_edge(edge) for edge in edges[:220]]}
