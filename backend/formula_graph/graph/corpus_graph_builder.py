from __future__ import annotations

from collections import defaultdict
from typing import Any

from backend.formula_graph.export.graph_ready_export import GraphReadyDocument, normalize_symbol


def namespace_id(document_id: str, local_id: str) -> str:
    return f"{document_id}::{local_id}"


def build_corpus_graph(corpus_id: str, name: str, documents: list[GraphReadyDocument]) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = [
        {
            "id": corpus_id,
            "type": "corpus",
            "label": name or corpus_id,
            "attributes": {"document_count": len(documents)},
        }
    ]
    edges: list[dict[str, Any]] = []
    variable_index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    formula_index: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def add_edge(source: str, target: str, edge_type: str, **attrs) -> None:
        edges.append(
            {
                "id": f"edge_{len(edges) + 1:06d}",
                "source": source,
                "target": target,
                "type": edge_type,
                "label": edge_type,
                "attributes": attrs,
            }
        )

    for doc in documents:
        doc_node_id = namespace_id(doc.document_id, "document")
        nodes.append(
            {
                "id": doc_node_id,
                "type": "document",
                "label": doc.filename,
                "document_id": doc.document_id,
                "filename": doc.filename,
                "attributes": {
                    "status": doc.status,
                    "source_type": doc.source_type,
                    "summary": doc.summary.model_dump(),
                },
            }
        )
        add_edge(corpus_id, doc_node_id, "corpus_contains_document", document_id=doc.document_id)

        for paragraph in doc.paragraphs:
            node_id = namespace_id(doc.document_id, paragraph.id)
            nodes.append(
                {
                    "id": node_id,
                    "type": "paragraph",
                    "label": f"{doc.filename}: p{paragraph.order}",
                    "document_id": doc.document_id,
                    "filename": doc.filename,
                    "page": paragraph.page_number,
                    "attributes": paragraph.model_dump(),
                    "text": paragraph.text,
                }
            )
            add_edge(doc_node_id, node_id, "document_contains_paragraph")

        for formula in doc.formulas:
            node_id = namespace_id(doc.document_id, formula.id)
            nodes.append(
                {
                    "id": node_id,
                    "type": "formula",
                    "label": formula.token,
                    "document_id": doc.document_id,
                    "filename": doc.filename,
                    "page": None,
                    "latex": formula.latex,
                    "attributes": formula.model_dump(),
                }
            )
            add_edge(doc_node_id, node_id, "document_contains_formula")
            formula_index[_formula_signature(formula.normalized_latex or formula.latex, formula.symbols)].append(
                {"id": node_id, "document_id": doc.document_id, "formula": formula}
            )

        for variable in doc.variables:
            node_id = namespace_id(doc.document_id, variable.id)
            normalized = normalize_symbol(variable.normalized_symbol or variable.symbol)
            nodes.append(
                {
                    "id": node_id,
                    "type": "variable",
                    "label": normalized,
                    "document_id": doc.document_id,
                    "filename": doc.filename,
                    "raw_label": variable.symbol,
                    "normalized_label": normalized,
                    "attributes": variable.model_dump(),
                }
            )
            add_edge(doc_node_id, node_id, "document_contains_variable")
            variable_index[normalized].append({"id": node_id, "document_id": doc.document_id, "variable": variable})
            for formula_id in variable.formula_ids:
                add_edge(namespace_id(doc.document_id, formula_id), node_id, "shared_variable", normalized_label=normalized)
            for definition in variable.possible_definitions:
                definition_id = namespace_id(doc.document_id, f"definition_{variable.id}_{len(nodes)}")
                nodes.append(
                    {
                        "id": definition_id,
                        "type": "definition",
                        "label": str(definition.get("definition_text") or definition.get("evidence") or normalized)[:90],
                        "document_id": doc.document_id,
                        "filename": doc.filename,
                        "text": definition.get("definition_text") or "",
                        "attributes": definition,
                    }
                )
                add_edge(node_id, definition_id, "defined_as", evidence=definition.get("evidence"), confidence=definition.get("confidence"))

        for context in doc.formula_contexts:
            node_id = namespace_id(doc.document_id, context.id)
            nodes.append(
                {
                    "id": node_id,
                    "type": "formula_context",
                    "label": context.token,
                    "document_id": doc.document_id,
                    "filename": doc.filename,
                    "text": context.window_text,
                    "attributes": context.model_dump(),
                }
            )
            add_edge(namespace_id(doc.document_id, context.formula_id), node_id, "has_context", confidence=0.8)

    for normalized, items in variable_index.items():
        docs = {item["document_id"] for item in items}
        if len(docs) < 2:
            continue
        for left_index, left in enumerate(items):
            for right in items[left_index + 1 :]:
                if left["document_id"] != right["document_id"]:
                    add_edge(left["id"], right["id"], "same_variable_label", normalized_label=normalized, confidence=0.82)

    for signature, items in formula_index.items():
        docs = {item["document_id"] for item in items}
        if not signature or len(docs) < 2:
            continue
        for left_index, left in enumerate(items):
            for right in items[left_index + 1 :]:
                if left["document_id"] != right["document_id"]:
                    add_edge(left["id"], right["id"], "similar_formula", signature=signature, confidence=0.68)

    return {
        "schema_version": "1.0",
        "corpus_id": corpus_id,
        "name": name,
        "documents": [_doc_info(doc) for doc in documents],
        "nodes": nodes,
        "edges": edges,
        "indexes": {
            "variables": {key: [item["id"] for item in values] for key, values in variable_index.items()},
            "formulas": {key: [item["id"] for item in values] for key, values in formula_index.items() if key},
        },
    }


def _doc_info(doc: GraphReadyDocument) -> dict[str, Any]:
    return {
        "document_id": doc.document_id,
        "filename": doc.filename,
        "status": doc.status,
        "summary": doc.summary.model_dump(),
    }


def _formula_signature(latex: str, symbols: list[str]) -> str:
    normalized_symbols = ",".join(sorted({normalize_symbol(symbol) for symbol in symbols if normalize_symbol(symbol)}))
    normalized_latex = " ".join(str(latex or "").split())
    if normalized_latex:
        return normalized_latex[:180]
    return normalized_symbols
