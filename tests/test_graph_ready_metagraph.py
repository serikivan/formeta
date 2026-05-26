from __future__ import annotations

from backend.formula_graph.graph.graph_ready_metagraph import build_metagraph_from_graph_ready, metagraph_to_knowledge_graph
from backend.formula_graph.graph.visualizer_cytoscape import export_cytoscape_elements
from tests.test_graph_ready_export import _graph_ready


def test_graph_ready_metagraph_has_metavertices_and_metaedges():
    metagraph = build_metagraph_from_graph_ready(_graph_ready())

    assert metagraph.metavertices
    assert any(item.type == "formula_metavertex" for item in metagraph.metavertices.values())
    assert any(item.type == "definition_context" for item in metagraph.metaedges.values())
    assert any(item.type == "symbol" for item in metagraph.nodes.values())
    assert any(item.type == "has_symbol" for item in metagraph.edges.values())
    formula_metavertex = next(item for item in metagraph.metavertices.values() if item.type == "formula_metavertex")
    assert formula_metavertex.attributes["semantic_type"] == "formula_metavertex"
    assert formula_metavertex.attributes["inner_expression_object"] == "ast_like_expression_graph"


def test_graph_ready_metagraph_converts_to_legacy_knowledge_graph():
    metagraph = build_metagraph_from_graph_ready(_graph_ready())
    legacy = metagraph_to_knowledge_graph(metagraph)

    assert legacy.nodes
    assert legacy.edges
    assert any(node.kind == "metaedge" for node in legacy.nodes)
    assert any(edge.label == "has_symbol" for edge in legacy.edges)


def test_cytoscape_export_modes_return_elements_and_stats():
    metagraph = build_metagraph_from_graph_ready(_graph_ready())

    for mode in ("document_structure", "formula_semantic", "metagraph_overview", "metagraph_fragments"):
        payload = export_cytoscape_elements(metagraph, mode=mode)
        assert payload["mode"] == mode
        assert payload["elements"]
        assert payload["stats"]["node_count"] > 0
