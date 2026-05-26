from __future__ import annotations

from collections import defaultdict
from typing import Any


def build_corpus_metagraph(corpus_graph: dict[str, Any]) -> dict[str, Any]:
    nodes = list(corpus_graph.get("nodes") or [])
    edges = list(corpus_graph.get("edges") or [])
    corpus_id = corpus_graph.get("corpus_id")
    documents = corpus_graph.get("documents") or []

    metavertices: list[dict[str, Any]] = [
        {
            "id": f"{corpus_id}::mv_corpus",
            "type": "corpus_metavertex",
            "label": corpus_graph.get("name") or corpus_id,
            "contains": [node["id"] for node in nodes if node.get("type") == "document"],
            "attributes": {"document_count": len(documents)},
        }
    ]
    for doc in documents:
        prefix = f"{doc['document_id']}::"
        contained = [node["id"] for node in nodes if str(node.get("id", "")).startswith(prefix)]
        metavertices.append(
            {
                "id": f"{doc['document_id']}::mv_document",
                "type": "document_metavertex",
                "label": doc.get("filename") or doc["document_id"],
                "contains": contained,
                "attributes": {"document_id": doc["document_id"], "filename": doc.get("filename")},
            }
        )

    variables_by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
    formulas_by_signature: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in nodes:
        if node.get("type") == "variable":
            variables_by_label[node.get("normalized_label") or node.get("label")].append(node)
        if node.get("type") == "formula":
            signature = " ".join(str(node.get("latex") or "").split())[:180]
            if signature:
                formulas_by_signature[signature].append(node)

    metaedges: list[dict[str, Any]] = []

    def add_metaedge(edge_type: str, source_set: list[str], target_set: list[str], **attrs) -> None:
        if not source_set or not target_set:
            return
        metaedges.append(
            {
                "id": f"cme_{len(metaedges) + 1:06d}",
                "type": edge_type,
                "source_set": source_set,
                "target_set": target_set,
                "mediator_nodes": attrs.pop("mediator_nodes", []),
                "attributes": attrs,
            }
        )

    for normalized, items in variables_by_label.items():
        docs = sorted({item.get("document_id") for item in items})
        if len(docs) < 2:
            continue
        add_metaedge(
            "cross_document_variable_link",
            [items[0]["id"]],
            [item["id"] for item in items[1:]],
            normalized_label=normalized,
            confidence=0.82,
            evidence=[{"source": "corpus_rule", "rule": "same normalized variable label", "documents": docs}],
        )
        add_metaedge(
            "corpus_notation_scope",
            [item["id"] for item in items],
            [f"{doc_id}::document" for doc_id in docs],
            normalized_label=normalized,
            confidence=0.72,
        )

    for signature, items in formulas_by_signature.items():
        docs = sorted({item.get("document_id") for item in items})
        if len(docs) >= 2:
            add_metaedge(
                "cross_document_formula_similarity",
                [items[0]["id"]],
                [item["id"] for item in items[1:]],
                dependency_type="same_latex_signature",
                confidence=0.68,
                evidence=[{"source": "corpus_rule", "signature": signature[:120], "documents": docs}],
            )

    definition_nodes = [node for node in nodes if node.get("type") == "definition"]
    if definition_nodes:
        add_metaedge(
            "corpus_concept_link",
            [definition_nodes[0]["id"]],
            [node["id"] for node in definition_nodes[1:]],
            confidence=0.45,
            evidence=[{"source": "definition_text_grouping", "count": len(definition_nodes)}],
        )

    source_groups: dict[str, list[str]] = defaultdict(list)
    for node in nodes:
        source = ((node.get("attributes") or {}).get("source") or "unknown") if node.get("type") in {"formula", "formula_context"} else None
        if source:
            source_groups[source].append(node["id"])
    for source, ids in source_groups.items():
        add_metaedge(
            "corpus_extraction_evidence",
            ids[:1],
            ids[1:] or ids[:1],
            confidence=0.7,
            source=source,
            evidence=[{"source": source, "count": len(ids)}],
        )

    return {
        "schema_version": "1.0",
        "corpus_id": corpus_id,
        "name": corpus_graph.get("name"),
        "nodes": nodes,
        "edges": edges,
        "metavertices": metavertices,
        "metaedges": metaedges,
        "fragments": metavertices,
        "provenance": {"source": "corpus_graph_builder", "documents": documents},
        "metrics": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "metavertex_count": len(metavertices),
            "metaedge_count": len(metaedges),
        },
    }
