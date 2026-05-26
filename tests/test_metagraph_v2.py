from __future__ import annotations

from backend.formula_graph.graph.metagraph_validator import validate_metagraph
from backend.formula_graph.graph.semantic_metagraph import build_semantic_graph_artifacts, create_meta_edges
from tests.test_graph_ready_export import _graph_ready


def _two_formula_doc():
    doc = _graph_ready()
    duplicate = doc.formulas[0].model_copy(update={"id": "formula_0002", "token": "[FORMULA_002]", "order": 99})
    doc.formulas.append(duplicate)
    return doc


def test_variable_usage_cluster_is_created_for_reused_variable():
    _graph_input, metagraph, _variable_index = build_semantic_graph_artifacts(_two_formula_doc())

    assert any(node["type"] == "variable_usage_cluster" and node["variable"] == "lambda" for node in metagraph["meta_nodes"])


def test_definition_usage_points_forward_and_no_self_loops():
    _graph_input, metagraph, _variable_index = build_semantic_graph_artifacts(_two_formula_doc())
    definition_edges = [edge for edge in metagraph["meta_edges"] if edge["relation"] == "definition_usage"]

    assert definition_edges
    assert all(edge["source"] != edge["target"] for edge in metagraph["meta_edges"])
    assert all(edge["source"] < edge["target"] for edge in definition_edges)


def test_max_edges_per_meta_node_limits_density():
    _graph_input, metagraph, _variable_index = build_semantic_graph_artifacts(_two_formula_doc())
    limited = create_meta_edges(metagraph["meta_nodes"], max_edges_per_meta_node=1)
    degree = {}
    for edge in limited:
        degree[edge["source"]] = degree.get(edge["source"], 0) + 1
        degree[edge["target"]] = degree.get(edge["target"], 0) + 1

    assert degree
    assert max(degree.values()) <= 1


def test_metagraph_validator_returns_valid_payload():
    _graph_input, metagraph, _variable_index = build_semantic_graph_artifacts(_two_formula_doc())

    assert validate_metagraph(metagraph)["valid"] is True
