from __future__ import annotations

from collections import Counter
from typing import Any


def validate_metagraph(metagraph: dict[str, Any]) -> dict[str, Any]:
    errors = [
        *validate_node_references(metagraph),
        *validate_duplicate_edges(metagraph),
    ]
    warnings = [
        *validate_isolated_nodes(metagraph),
        *validate_visualization_density(metagraph),
    ]
    return {"valid": not errors, "errors": errors, "warnings": warnings}


def validate_node_references(metagraph: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    node_ids = {node.get("id") for node in metagraph.get("nodes", [])}
    meta_node_ids = {node.get("id") for node in metagraph.get("meta_nodes", [])}
    all_ids = node_ids | meta_node_ids

    for edge in metagraph.get("edges", []):
        source = edge.get("source")
        target = edge.get("target")
        if source not in node_ids:
            errors.append(f"Edge source is missing: {source}")
        if target not in node_ids:
            errors.append(f"Edge target is missing: {target}")

    for edge in metagraph.get("meta_edges", []):
        source = edge.get("source")
        target = edge.get("target")
        if source not in meta_node_ids:
            errors.append(f"Meta edge source is missing: {source}")
        if target not in meta_node_ids:
            errors.append(f"Meta edge target is missing: {target}")

    for meta_node in metagraph.get("meta_nodes", []):
        if meta_node.get("type") != "formula_context_unit":
            continue
        for key in ("formula", "paragraph"):
            ref = meta_node.get(key)
            if ref and ref not in all_ids:
                errors.append(f"{meta_node.get('id')} references missing {key}: {ref}")
        for key in ("variables", "contexts"):
            for ref in meta_node.get(key, []) or []:
                if ref and ref not in all_ids:
                    errors.append(f"{meta_node.get('id')} references missing {key[:-1]}: {ref}")
    return errors


def validate_duplicate_edges(metagraph: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for collection_name in ("edges", "meta_edges"):
        seen: set[tuple[Any, ...]] = set()
        for edge in metagraph.get(collection_name, []):
            key = (edge.get("source"), edge.get("target"), edge.get("relation") or edge.get("type"), edge.get("variable"))
            if key in seen:
                errors.append(f"Duplicate {collection_name} edge: {key}")
            seen.add(key)
            if edge.get("source") == edge.get("target"):
                errors.append(f"Self-loop in {collection_name}: {key}")
    return errors


def validate_isolated_nodes(metagraph: dict[str, Any]) -> list[str]:
    connected = set()
    for edge in metagraph.get("edges", []):
        connected.add(edge.get("source"))
        connected.add(edge.get("target"))
    for edge in metagraph.get("meta_edges", []):
        connected.add(edge.get("source"))
        connected.add(edge.get("target"))
    warnings: list[str] = []
    for node in metagraph.get("meta_nodes", []):
        if node.get("type") == "formula_context_unit" and node.get("id") not in connected and len(metagraph.get("meta_nodes", [])) > 1:
            warnings.append(f"{node.get('id')} is isolated")
        if node.get("type") == "formula_context_unit" and not node.get("variables"):
            warnings.append(f"{node.get('id')} has no variables")
    return warnings


def validate_visualization_density(metagraph: dict[str, Any]) -> list[str]:
    degree: Counter[str] = Counter()
    for edge in metagraph.get("meta_edges", []):
        degree[str(edge.get("source"))] += 1
        degree[str(edge.get("target"))] += 1
    if not degree:
        return []
    average_degree = sum(degree.values()) / max(1, len(degree))
    if average_degree > 10:
        return [f"Graph is dense: average degree {average_degree:.1f} > 10"]
    return []
