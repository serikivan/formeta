from __future__ import annotations

from backend.formula_graph.graph.semantic_metagraph import build_semantic_graph_artifacts
from backend.formula_graph.graph.semantic_visualization import (
    generate_formula_graph_view,
    generate_graph_view,
    generate_metagraph_view,
    generate_variable_focus_view,
)
from tests.test_graph_ready_export import _graph_ready


def test_html_visualizations_have_filters_legend_and_variable_focus(tmp_path):
    graph_input, metagraph, variable_index = build_semantic_graph_artifacts(_graph_ready())

    generate_graph_view(graph_input, tmp_path / "graph_view.html")
    generate_formula_graph_view(graph_input, tmp_path / "formula_graph_view.html")
    generate_metagraph_view(metagraph, tmp_path / "metagraph_view.html")
    generate_variable_focus_view("lambda", graph_input, metagraph, variable_index, tmp_path / "variable_focus_lambda.html")

    for name in ("graph_view.html", "formula_graph_view.html", "metagraph_view.html", "variable_focus_lambda.html"):
        html = (tmp_path / name).read_text(encoding="utf-8")
        assert "nodeTypeFilter" in html
        assert "edgeTypeFilter" in html
        assert "legend" in html


def test_pyvis_absence_does_not_break_static_visualization(tmp_path):
    graph_input, metagraph, _variable_index = build_semantic_graph_artifacts(_graph_ready())

    generate_graph_view(graph_input, tmp_path / "graph_view.html")
    generate_metagraph_view(metagraph, tmp_path / "metagraph_view.html")

    assert (tmp_path / "graph_view.html").exists()
    assert (tmp_path / "metagraph_view.html").exists()
