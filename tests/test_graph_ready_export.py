from __future__ import annotations

from datetime import datetime

from backend.formula_graph.export.graph_ready_export import (
    GraphReadyDocument,
    GraphReadyFormula,
    GraphReadyFormulaContext,
    GraphReadyRelation,
    GraphReadyVariable,
    PossibleDefinition,
    build_graph_ready_document,
    extract_formula_symbols,
    load_graph_ready_document,
    normalize_symbol,
    search_variable_in_graph_ready,
    validate_graph_ready_document,
)
from backend.formula_graph.export.structured_document import build_structured_document
from backend.formula_graph.models import FormulaBlock, FormulaRegion, PageImage, ProcessingResult, TextBlock


def _sample_result() -> ProcessingResult:
    return ProcessingResult(
        document_id="doc_graph_ready",
        filename="article.pdf",
        created_at=datetime(2026, 5, 21, 12, 0, 0),
        status="ok",
        pages=[
            PageImage(
                page_number=1,
                image_path="data/processed/doc_graph_ready/page_0001.png",
                width=1200,
                height=1600,
                dpi=300,
                text_layer="Let lambda denote the wavelength. The equation is lambda equals c over f." * 8,
            )
        ],
        text_blocks=[
            TextBlock(
                id="old_tb_1",
                page_number=1,
                text="Mathematical model",
                bbox=(80, 80, 460, 120),
                source="pdf_text_layer",
                confidence=0.99,
                role="heading",
            ),
            TextBlock(
                id="old_tb_2",
                page_number=1,
                text="Let lambda denote the wavelength",
                bbox=(80, 180, 700, 220),
                source="pdf_text_layer",
                confidence=0.95,
            ),
            TextBlock(
                id="old_tb_3",
                page_number=1,
                text="where c denotes speed and f denotes frequency.",
                bbox=(80, 340, 760, 380),
                source="pdf_text_layer",
                confidence=0.95,
            ),
        ],
        text_with_tokens=[
            TextBlock(
                id="tok_1",
                page_number=1,
                text="Mathematical model",
                source="postprocessed",
                confidence=0.99,
            ),
            TextBlock(
                id="tok_2",
                page_number=1,
                text="Let lambda denote the wavelength [FORMULA_001] where c denotes speed and f denotes frequency.",
                source="postprocessed",
                confidence=0.95,
            ),
        ],
        formula_regions=[
            FormulaRegion(
                id="old_fr_1",
                token="[FORMULA_001]",
                page_number=1,
                bbox=(120, 250, 620, 300),
                kind="block",
                source="pp_structure_v3",
                confidence=0.9,
            )
        ],
        formulas=[
            FormulaBlock(
                id="old_f_1",
                page_number=1,
                latex=r"\lambda = \frac{c}{f}",
                kind="block",
                token="[FORMULA_001]",
                bbox=(120, 250, 620, 300),
                source="pp_formula_net",
                confidence=0.92,
            )
        ],
    )


def _graph_ready():
    result = _sample_result()
    structured = build_structured_document(
        result,
        ocr_mode="hybrid",
        device="cpu",
        ocr_lang="en",
        render_dpi=300,
        prefer_tex_source=False,
    )
    return build_graph_ready_document(result, structured)


def test_graph_ready_export_created():
    doc = _graph_ready()

    assert doc.schema_version == "1.1"
    assert doc.document_structure
    assert doc.text_blocks
    assert doc.text_with_tokens
    assert doc.formulas
    assert doc.formula_contexts
    assert doc.variables
    assert doc.relations


def test_graph_ready_does_not_require_bbox():
    payload = _graph_ready().model_dump()

    assert "bbox" not in payload["formulas"][0]
    assert "bbox" not in payload["text_blocks"][0]


def test_formula_tokens_unique_and_present_in_text():
    doc = _graph_ready()
    tokens = [formula.token for formula in doc.formulas]

    assert tokens == ["[FORMULA_001]"]
    assert len(tokens) == len(set(tokens))
    assert "[FORMULA_001]" in doc.text_with_tokens


def test_formula_context_window_contains_token():
    doc = _graph_ready()

    assert doc.formula_contexts[0].token in doc.formula_contexts[0].window_text


def test_variables_extracted_from_latex():
    doc = _graph_ready()
    symbols = {variable.normalized_symbol for variable in doc.variables}

    assert {"\\lambda", "c", "f"} <= symbols


def test_greek_variable_normalization():
    assert normalize_symbol("lambda") == "\\lambda"
    assert normalize_symbol("λ") == "\\lambda"
    assert normalize_symbol(r"\lambda") == "\\lambda"


def test_indexed_variable_normalization():
    assert normalize_symbol("x_{i}") == "x_i"
    assert normalize_symbol(r"\mathbb{R}") == r"\mathbb{R}"


def test_formula_symbol_extraction_ignores_operators_and_environments():
    symbols = set(
        extract_formula_symbols(
            r"\begin{cases}\phi_0(z)=\frac{1-i}{2}(z-s)+s \\ \phi_1(z)=\det A+\ker T+\sup B+\cdots\circ \mathbb{R}^{n}\qquad C\end{cases}"
        )
    )

    assert {"\\phi", "z", "s", "A", "T", "B", "\\mathbb{R}", "n", "C"} <= symbols
    assert not {"cases", "frac", "det", "ker", "sup", "begin", "end", "operator", "operand", "cdots", "circ", "mathbb", "qquad", "R"} & symbols


def test_formula_symbol_extraction_keeps_subscripts_with_variables_not_operators():
    doc = _graph_ready()
    formula = next(item for item in doc.formulas if item.id == "formula_0001")

    assert "_" not in formula.operators

    symbols = set(extract_formula_symbols(r"x_i + y_{12} + \mbox{ where } z"))
    assert {"x_i", "y_12", "z"} <= symbols
    assert "mbox" not in symbols


def test_loading_legacy_graph_ready_sanitizes_operator_variables(tmp_path):
    doc = GraphReadyDocument(
        document_id="legacy_doc",
        filename="legacy.pdf",
        status="ok",
        formulas=[
            GraphReadyFormula(
                id="f_6",
                token="[FORMULA_006]",
                latex=r"z=\lim_{n \to \infty}\psi_{x_1}\circ\psi_{x_2}\dots\mathbb{R}^{n}\qquad",
                order=1,
                symbols=["z", "circ", "dots", "mathbb", "R", "n"],
            )
        ],
        formula_contexts=[
            GraphReadyFormulaContext(
                id="ctx_0006",
                formula_id="f_6",
                token="[FORMULA_006]",
                mentioned_symbols=["circ", "z"],
                possible_definitions=[
                    PossibleDefinition(symbol="dots", definition_text="ellipsis", evidence="dots denotes ellipsis"),
                    PossibleDefinition(symbol="z", definition_text="point", evidence="z denotes point"),
                ],
            )
        ],
        variables=[
            GraphReadyVariable(id="var_0001", symbol="circ", normalized_symbol="circ", latex="circ", formula_ids=["f_6"], usage_count=1),
            GraphReadyVariable(id="var_0002", symbol="dots", normalized_symbol="dots", latex="dots", formula_ids=["f_6"], usage_count=1),
            GraphReadyVariable(id="var_0003", symbol="mathbb", normalized_symbol="mathbb", latex="mathbb", formula_ids=["f_6"], usage_count=1),
            GraphReadyVariable(id="var_0004", symbol="R", normalized_symbol="R", latex="R", formula_ids=["f_6"], usage_count=1),
            GraphReadyVariable(id="var_0005", symbol=r"\mathbb{R}", normalized_symbol=r"\mathbb{R}", latex=r"\mathbb{R}", formula_ids=["f_6"], usage_count=1),
            GraphReadyVariable(id="var_0006", symbol="z", normalized_symbol="z", latex="z", formula_ids=["f_6"], usage_count=1),
        ],
        relations=[
            GraphReadyRelation(id="rel_bad", type="uses_variable", source_id="f_6", target_id="var_0001"),
            GraphReadyRelation(id="rel_good", type="uses_variable", source_id="f_6", target_id="var_0006"),
        ],
    )
    path = tmp_path / "legacy.graph_ready.json"
    path.write_text(doc.model_dump_json(), encoding="utf-8")

    loaded = load_graph_ready_document(path)
    symbols = set(loaded.formulas[0].symbols)
    variables = {variable.normalized_symbol for variable in loaded.variables}

    assert {"z", "n", r"\psi", "x_1", "x_2", r"\mathbb{R}"} <= symbols
    assert not {"circ", "dots", "mathbb", "R"} & symbols
    assert r"\inf" not in loaded.formulas[0].operators
    assert {r"\lim", r"\to", r"\circ", r"\dots"} <= set(loaded.formulas[0].operators)
    assert variables == {"z", "n", r"\psi", "x_1", "x_2", r"\mathbb{R}"}
    assert all(relation.target_id in {variable.id for variable in loaded.variables} for relation in loaded.relations)


def test_variable_has_formula_and_context_links():
    doc = _graph_ready()
    variable = next(item for item in doc.variables if item.normalized_symbol == "\\lambda")

    assert variable.formula_ids == ["formula_0001"]
    assert variable.context_ids


def test_relations_reference_existing_objects():
    doc = _graph_ready()
    warnings = validate_graph_ready_document(doc)

    assert not [warning for warning in warnings if warning.code == "relation_reference_missing"]


def test_variable_search_exact_symbol():
    doc = _graph_ready()
    result = search_variable_in_graph_ready(doc, r"\lambda")

    assert result["normalized_query"] == "\\lambda"
    assert result["matches_count"] == 1
    assert result["matches"][0]["formula_id"] == "formula_0001"


def test_variable_search_greek_alias():
    doc = _graph_ready()
    result = search_variable_in_graph_ready(doc, "λ")

    assert result["normalized_query"] == "\\lambda"
    assert result["matches_count"] == 1


def test_variable_search_latex_fallback():
    doc = _graph_ready()
    doc.variables = []

    result = search_variable_in_graph_ready(doc, "c")

    assert result["matches_count"] == 1
    assert result["variable"]["quality_flags"] == ["fallback_search"]


def test_variable_search_returns_formula_context():
    doc = _graph_ready()
    result = search_variable_in_graph_ready(doc, "lambda")
    match = result["matches"][0]

    assert match["latex"] == r"\lambda = \frac{c}{f}"
    assert "[FORMULA_001]" in match["window_text"]
    assert "denote" in " ".join(match["definition_markers"])
    assert match["formula_semantics"]["semantic_type"] == "formula_metavertex"
    assert match["formula_semantics"]["metavertex_id"] == "formula_0001_mv"


def test_variable_search_empty_result():
    result = search_variable_in_graph_ready(_graph_ready(), "z")

    assert result["matches_count"] == 0


def test_text_inline_variable_mentions_are_searchable():
    result = _sample_result()
    result.text_blocks.append(
        TextBlock(
            id="old_tb_4",
            page_number=1,
            text="We identify another directed graph G_2, that characterizes the translated curve. There exists a unique continuous solution f(x).",
            source="tex_source",
            confidence=0.99,
        )
    )
    result.text_with_tokens.append(
        TextBlock(
            id="tok_3",
            page_number=1,
            text="We identify another directed graph G_2, that characterizes the translated curve. There exists a unique continuous solution f(x).",
            source="tex_source",
            confidence=0.99,
        )
    )
    structured = build_structured_document(
        result,
        ocr_mode="tex_source",
        device="cpu",
        ocr_lang="en",
        render_dpi=300,
        prefer_tex_source=True,
    )
    doc = build_graph_ready_document(result, structured)

    symbols = {variable.normalized_symbol for variable in doc.variables}
    search_result = search_variable_in_graph_ready(doc, "G_2")

    assert "G_2" in symbols
    assert "f(x)" in symbols
    assert search_result["matches_count"] >= 1
    assert search_result["matches"][-1]["kind"] == "text_mention"
    assert "directed graph G_2" in search_result["matches"][-1]["window_text"]
