from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.formula_graph.config import settings
from backend.formula_graph.export.graph_ready_export import save_graph_ready_document
from backend.formula_graph.graph.visualization_export import export_visualization_payload
from tests.test_graph_ready_export import _graph_ready


def _object_ids(payload: dict) -> set[str]:
    return {item["id"] for item in payload["nodes"]} | {item["id"] for item in payload["metavertices"]}


def test_planetary_payload_has_consistent_edges_and_parents():
    payload = export_visualization_payload(_graph_ready(), mode="metagraph_planetary", limit=160)
    ids = _object_ids(payload)

    assert payload["layout"]["type"] == "planetary_metagraph"
    assert payload["nodes"]
    assert payload["metavertices"]
    assert all(edge["source"] in ids and edge["target"] in ids for edge in payload["edges"])
    assert all(node.get("parent") in ids for node in payload["nodes"] if node.get("parent"))
    assert all(mv.get("parent") in ids for mv in payload["metavertices"] if mv.get("parent"))


def test_sampling_keeps_metavertex_parent_integrity():
    payload = export_visualization_payload(_graph_ready(), mode="metagraph_planetary", limit=45)
    ids = _object_ids(payload)

    assert payload["stats"]["truncated"] is True
    assert all(child in ids for mv in payload["metavertices"] for child in mv["contains"])
    assert all(node.get("parent") in ids for node in payload["nodes"] if node.get("parent"))


def test_variable_neighborhood_contains_formula_context_definition_and_metaedges():
    payload = export_visualization_payload(_graph_ready(), mode="variable_neighborhood", variable="lambda", depth=3)
    node_types = {node["type"] for node in payload["nodes"]}
    metaedge_types = {edge["type"] for edge in payload["metaedges"]}

    assert payload["mode"] == "variable_neighborhood"
    assert {"symbol", "formula", "context", "definition"} <= node_types
    assert {"notation_scope", "definition_context"} & metaedge_types
    assert payload["stats"]["variable"]["formula_count"] == 1


def test_unknown_variable_returns_empty_payload_with_suggestions():
    payload = export_visualization_payload(_graph_ready(), mode="variable_neighborhood", variable="lam", depth=2)

    assert payload["nodes"] == []
    assert payload["stats"]["empty_reason"] == "Variable not found in document."
    assert payload["available_variables"]
    assert payload["suggestions"]


def test_variable_neighborhood_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "results_dir", tmp_path)
    doc = _graph_ready()
    save_graph_ready_document(doc, tmp_path / f"{doc.document_id}.graph_ready.json")

    client = TestClient(app)
    response = client.get(f"/api/results/{doc.document_id}/variables/lambda/neighborhood", params={"depth": 3})

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "variable_neighborhood"
    assert any(node["type"] == "formula" for node in payload["nodes"])


def test_overview_projection_hides_structural_ast_and_metaedge_dump_edges():
    payload = export_visualization_payload(_graph_ready(), mode="overview", limit=160)
    edge_types = {edge["type"] for edge in payload["edges"]}

    assert payload["canonical_mode"] == "overview"
    assert payload["layout"]["type"] == "planetary_metagraph"
    assert "contains" not in edge_types
    assert not edge_types.intersection({"ast_contains", "ast_lhs", "ast_rhs", "has_subexpression", "has_operator"})
    assert not edge_types.intersection({"metaedge_source", "metaedge_target"})
    assert all("visual" in node and "layout" in node for node in payload["nodes"])


def test_specialized_projection_modes_have_distinct_layouts_and_edge_policies():
    doc = _graph_ready()
    hierarchy = export_visualization_payload(doc, mode="document_hierarchy", limit=160)
    semantic = export_visualization_payload(doc, mode="formula_semantic_network", limit=160)
    metaedges = export_visualization_payload(doc, mode="metaedges_view", limit=160)
    ast = export_visualization_payload(doc, mode="formula_ast_focus", formula="formula_0001", limit=160)
    removed = export_visualization_payload(doc, mode="technical_full_graph", limit=160)

    assert hierarchy["layout"]["type"] == "document_tree"
    assert not {node["type"] for node in hierarchy["nodes"]}.intersection({"symbol", "fragment", "metaedge"})
    assert semantic["layout"]["type"] == "semantic_network"
    assert {node["type"] for node in semantic["nodes"]} <= {"formula", "symbol", "context", "definition"}
    assert metaedges["layout"]["type"] == "metaedge_bipartite"
    assert any(node["type"] == "metaedge" for node in metaedges["nodes"])
    assert ast["layout"]["type"] == "formula_ast_tree"
    assert any(node["type"] == "fragment" for node in ast["nodes"])
    assert len({(node.get("attributes") or {}).get("formula_id") for node in ast["nodes"] if node["type"] == "fragment"}) <= 1
    assert removed["canonical_mode"] == "overview"
    assert removed["layout"]["type"] == "planetary_metagraph"
