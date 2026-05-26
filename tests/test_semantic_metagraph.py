from __future__ import annotations

from backend.formula_graph.graph.semantic_metagraph import (
    build_semantic_graph_artifacts,
    search_variable_context,
)
from backend.formula_graph.graph.semantic_visualization import export_semantic_visualization
from tests.test_graph_ready_export import _graph_ready


def test_semantic_metagraph_contract():
    graph_input, metagraph, variable_index = build_semantic_graph_artifacts(_graph_ready())

    assert set(graph_input) >= {"nodes", "edges"}
    assert set(metagraph) == {"nodes", "edges", "meta_nodes", "meta_edges", "statistics"}
    assert any(node["type"] == "formula" and node["id"] == "FORMULA_001" for node in metagraph["nodes"])
    assert any(node["type"] == "formula_context_unit" and node["formula"] == "FORMULA_001" for node in metagraph["meta_nodes"])
    assert "\\lambda" not in variable_index
    assert "lambda" in variable_index


def test_variable_index_and_search_use_meta_nodes():
    _graph_input, metagraph, variable_index = build_semantic_graph_artifacts(_graph_ready())
    formulas = [node for node in metagraph["nodes"] if node["type"] == "formula"]
    contexts = [node for node in metagraph["nodes"] if node["type"] == "context"]

    result = search_variable_context("lambda", variable_index, formulas, contexts, metagraph)

    assert result["found"] is True
    assert result["variable_node"] == "VAR_lambda"
    assert result["formulas"][0]["formula_id"] == "FORMULA_001"
    assert result["related_meta_nodes"] == ["META_001"]


def test_semantic_visualization_is_compact():
    graph_input, metagraph, _variable_index = build_semantic_graph_artifacts(_graph_ready())

    payload = export_semantic_visualization(graph_input, metagraph, mode="metagraph_overview")

    assert payload["elements"]
    assert payload["stats"]["node_types"] == {"meta_node": 1}
