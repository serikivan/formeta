from backend.formula_graph.export.graph_ready_export import (
    GraphReadyDocument,
    GraphReadyFormula,
    GraphReadyFormulaContext,
    GraphReadyRelation,
    GraphReadySection,
    GraphReadyStructure,
    GraphReadyVariable,
    PossibleDefinition,
)
from backend.formula_graph.graph.visualization_projection import build_visualization_projection


def _doc() -> GraphReadyDocument:
    sections = [
        GraphReadySection(id=f"s{i}", title=f"Section {i}", order=i)
        for i in range(1, 8)
    ]
    formulas = []
    contexts = []
    relations = []
    for section_index, section in enumerate(sections, start=1):
        for local_index in range(1, 11):
            number = (section_index - 1) * 10 + local_index
            formula = GraphReadyFormula(
                id=f"f{number}",
                token=f"[FORMULA_{number:03d}]",
                latex=f"x_{number}=a_{number}+b_{number}",
                section_id=section.id,
                order=number,
                symbols=["x", "a", "b"],
                operators=["equals", "plus"],
                confidence=0.9,
            )
            formulas.append(formula)
            contexts.append(
                GraphReadyFormulaContext(
                    id=f"ctx{number}",
                    formula_id=formula.id,
                    token=formula.token,
                    section_id=section.id,
                    window_text=f"where x denotes value for {formula.token}",
                    possible_definitions=[
                        PossibleDefinition(symbol="x", definition_text="input value", evidence="where x denotes input value")
                    ],
                )
            )
    relations.extend(
        [
            GraphReadyRelation(id="dep1", type="formula_references_formula", source_id="f1", target_id="f2"),
            GraphReadyRelation(id="tech1", type="formula_in_section", source_id="f1", target_id="s1"),
            GraphReadyRelation(id="tech2", type="ast_contains", source_id="f1", target_id="f1:rhs"),
        ]
    )
    return GraphReadyDocument(
        document_id="doc",
        filename="doc.pdf",
        status="ok",
        document_structure=GraphReadyStructure(sections=sections),
        formulas=formulas,
        formula_contexts=contexts,
        variables=[
            GraphReadyVariable(
                id="var_x",
                symbol="x",
                normalized_symbol="x",
                latex="x",
                formula_ids=[formula.id for formula in formulas[:12]],
                context_ids=[context.id for context in contexts[:12]],
                section_ids=["s1", "s2"],
                usage_count=12,
                possible_definitions=[{"symbol": "x", "definition_text": "input value", "context_id": "ctx1"}],
            )
        ],
        relations=relations,
    )


def test_overview_projection_is_limited_section_lane_with_structural_edges():
    payload = build_visualization_projection(_doc(), mode="overview")

    assert payload["layout"] == "section_lanes"
    assert len(payload["groups"]) == 5
    assert len(payload["nodes"]) <= 80
    assert all(len(group["formulaIds"]) <= 8 for group in payload["groups"])
    edge_types = {edge["type"] for edge in payload["edges"]}
    assert {"section_contains_formula", "uses_variable", "section_definitions", "formula_dependency"} <= edge_types
    assert "formula_in_section" not in edge_types
    assert "ast_contains" not in edge_types
    assert all("x_" not in node["label"] for node in payload["nodes"] if node["kind"] == "formula")
    assert payload["hiddenCounts"]["technical_edges"] >= 2


def test_focus_variable_metaedge_and_ast_projections_are_small_and_explainable():
    doc = _doc()

    formula_payload = build_visualization_projection(doc, mode="formula_focus", formula="f1")
    assert formula_payload["layout"] == "formula_focus"
    assert {node["kind"] for node in formula_payload["nodes"]} >= {"formula", "variable", "context", "definition", "section"}
    assert len(formula_payload["nodes"]) <= 80
    assert formula_payload["selectedObjectDetails"]["latex"] == "x_1=a_1+b_1"
    assert formula_payload["selectedObjectDetails"]["semantic_type"] == "formula_metavertex"
    assert formula_payload["selectedObjectDetails"]["formula_metavertex"]["id"] == "f1_mv"
    assert formula_payload["selectedObjectDetails"]["internal_structure"]["graph_type"] == "ast_like_expression_graph"
    assert any(item["relation_type"] == "document_context" for item in formula_payload["selectedObjectDetails"]["metaedges"])

    variable_payload = build_visualization_projection(doc, mode="variable_focus", variable="x")
    assert variable_payload["layout"] == "variable_ego"
    assert variable_payload["selectedObjectDetails"]["normalized_symbol"] == "x"
    assert len(variable_payload["nodes"]) <= 80

    metaedge_payload = build_visualization_projection(doc, mode="metaedge_lanes")
    assert metaedge_payload["layout"] == "metaedge_lanes"
    assert len(metaedge_payload["nodes"]) <= 80

    ast_payload = build_visualization_projection(doc, mode="ast_tree", formula="f1")
    assert ast_payload["layout"] == "ast_tree"
    assert any(edge["type"].startswith("ast_") for edge in ast_payload["edges"])
    assert len(ast_payload["nodes"]) <= 80
    assert ast_payload["title"] == "Внутренний граф метавершины"
    labels = {node["label"] for node in ast_payload["nodes"]}
    assert "Operand 1" not in labels
    assert any("x_1" in label or "a_1" in label or "b_1" in label for label in labels)


def test_formula_projection_accepts_token_and_number_aliases():
    doc = _doc()

    by_token = build_visualization_projection(doc, mode="formula_focus", formula="[FORMULA_001]")
    by_compact_token = build_visualization_projection(doc, mode="formula_focus", formula="FORMULA-001")
    by_number = build_visualization_projection(doc, mode="ast_tree", formula="1")

    assert by_token["selectedObjectDetails"]["id"] == "f1"
    assert by_compact_token["selectedObjectDetails"]["id"] == "f1"
    assert by_number["selectedObjectDetails"]["id"] == "f1"


def test_ast_projection_does_not_treat_subscript_as_operator_or_split_fraction():
    doc = _doc()
    doc.formulas[0].latex = r"x_i=\frac{1-i}{2}(z-s)+s"
    doc.formulas[0].operators = []

    payload = build_visualization_projection(doc, mode="ast_tree", formula="f1")
    operator_labels = {node["label"] for node in payload["nodes"] if node.get("astRole") == "operator"}
    operand_labels = [node["label"] for node in payload["nodes"] if node.get("astRole") == "operand"]

    assert "index" not in operator_labels
    assert any(r"\frac{1-i}{2}(z-s)" in label for label in operand_labels)
