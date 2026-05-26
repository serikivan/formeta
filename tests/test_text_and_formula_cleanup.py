from backend.formula_graph.layout.formulas import extract_formulas
from backend.formula_graph.models import FormulaBlock, TextBlock, TextLine
from backend.formula_graph.ocr.formula_recognition import _expanded_bbox, _salvage_math_segment
from backend.formula_graph.ocr.formula_recognition import _is_better_latex
from backend.formula_graph.postprocessing.formulas import (
    reconcile_formula_candidates_with_text_layer,
    repair_formula_latex,
    rescue_formula_definitions,
    validate_formula_latex,
)
from backend.formula_graph.postprocessing.text import normalize_text_blocks


def block(text: str, block_id: str = "b1") -> TextBlock:
    return TextBlock(id=block_id, page_number=1, text=text, source="pdf_text_layer")


def test_repairs_common_pdf_mojibake():
    text = "L\u00c3\u00a9vy\u00e2\u20ac\u2122s curve uses \u00cf\u02c60 and \u00cf\u20201."
    result = normalize_text_blocks([block(text)])

    assert result[0].text == "L\u00e9vy\u2019s curve uses \u03c80 and \u03c61."


def test_joins_ocr_hyphenated_line_breaks_and_spaces():
    result = normalize_text_blocks([block("Это сло- во и пере-\nнос после OCR.")])

    assert result[0].text == "Это слово и перенос после OCR."


def test_explicit_inline_and_block_formulas_are_preserved():
    formulas = extract_formulas(
        [
            block("Let $E = mc^2$ be the inline relation.", "b1"),
            block(r"\[ x = \frac{1}{2} \]", "b2"),
        ]
    )

    assert [(formula.kind, formula.latex) for formula in formulas] == [
        ("inline", "E = mc^2"),
        ("block", r"x = \frac{1}{2}"),
    ]


def test_prose_equations_are_inline_not_block_formulas():
    formulas = extract_formulas(
        [
            block("Proof. Let psi0 = alpha f(2x) and psi1 = (1-alpha)f(2x-1), with alpha = (1-i)/2."),
            block("Figure 2: The first five steps of the construction"),
        ]
    )

    assert formulas
    assert all(formula.kind == "inline" for formula in formulas)
    assert all(formula.source == "text_inline_pattern" for formula in formulas)


def test_standalone_formula_line_is_kept():
    text = "z = lim n\u2192\u221e \u03c8x1 \u25e6 \u03c8x2 \u25e6 \u00b7 \u00b7 \u00b7 \u25e6 \u03c8xn(0)."
    formulas = extract_formulas([block(text)])

    assert len(formulas) == 1
    assert formulas[0].kind == "block"
    assert formulas[0].latex.startswith(r"z = \lim")
    assert r"\to \infty" in formulas[0].latex
    assert r"\psi" in formulas[0].latex


def test_inline_formula_is_extracted_from_prose():
    text = "In this paper, we investigate the translation by s = -1/2 + i/2."
    formulas = extract_formulas([block(text)])

    assert len(formulas) == 1
    assert formulas[0].kind == "inline"
    assert formulas[0].latex == "s = -1/2 + i/2"


def test_inline_formula_trims_unmatched_trailing_parenthesis():
    text = "The estimate holds where y \u2208 Rn)."
    formulas = extract_formulas([block(text)])

    assert len(formulas) == 1
    assert formulas[0].kind == "inline"
    assert formulas[0].latex == r"y \in \mathbb{R}^{n}"


def test_formula_net_candidate_wins_over_broken_text_layer_subscript():
    current = r"X = \phi_{0}(X) \cup \phi_{1}(X) \cup \cdot \cdot \cdot \cup \phi_{m}-1(X), (2)"
    candidate = r"X=\varphi_{0}(X)\cup\varphi_{1}(X)\cup\cdots\cup\varphi_{m-1}(X),\quad(2)"

    assert _is_better_latex(candidate, current)


def test_definition_formula_is_rescued_from_russian_text_layer():
    formulas = [
        FormulaBlock(
            id="f1",
            page_number=2,
            latex=r"\rho\mathrm{~-~}\Pi\mathrm{I O T H O C T b}",
            kind="inline",
            bbox=(150, 232, 220, 248),
            source="pp_structure_v3_raw",
            confidence=0.45,
            quality_flags=["needs_formula_review", "romanized_ocr_noise", "needs_review"],
        )
    ]
    reference_blocks = [
        TextBlock(
            id="p2_tl_8",
            page_number=2,
            text="Здесь r – плотность среды, eff m – эффективная вязкость, p – давление,",
            bbox=(147, 231, 476, 247),
            source="pdf_text_layer",
            lines=[TextLine(text="Здесь r – плотность среды, eff m – эффективная вязкость, p – давление,", bbox=(147, 231, 476, 247))],
        )
    ]

    rescued = rescue_formula_definitions(formulas, reference_blocks)

    assert rescued[0].latex == r"\rho - \text{плотность среды}"
    assert "definition_text_rescued" in rescued[0].quality_flags


def test_spaced_prose_inside_latex_commands_is_flagged():
    latex = r"\mathrm{I f~}1/2\leq x\leq1"

    assert "contains_prose" in validate_formula_latex(latex)


def test_concatenated_prose_around_inline_math_is_flagged():
    latex = r"the corresponding light sequence$(\gamma_n)$is$(\gamma_n)=(1,i)$It is clear that any sequence"

    assert "contains_prose" in validate_formula_latex(latex)


def test_inline_formula_trims_prose_after_top_level_comma():
    formulas = extract_formulas([block("Since alpha = (1-i)/2, f(x) can be written recursively.")])

    assert len(formulas) == 1
    assert formulas[0].latex == r"alpha = (1-i)/2"


def test_inline_formula_trims_as_follows_tail():
    formulas = extract_formulas([block("The function is defined on x \u2208 [0, 1] as follows.")])

    assert len(formulas) == 1
    assert formulas[0].latex == r"x \in [0, 1]"


def test_inline_formula_sequence_after_where_is_split():
    formulas = extract_formulas(
        [
            block(
                "The attractor satisfies equation: L = \u03c80(L) \u222a\u03c81(L), "
                "where \u03c80(z) = ( 1-i 2 )z, \u03c81(z) = ( 1+i 2 )z + 1-i 2."
            )
        ]
    )

    latex = {formula.latex for formula in formulas}
    assert r"L = \psi_{0}(L) \cup \psi_{1}(L)" in latex
    assert r"\psi_{0}(z) = ( 1-i 2 )z" in latex
    assert r"\psi_{1}(z) = ( 1+i 2 )z + 1-i 2" in latex


def test_cross_block_inline_formula_sequence_is_detected():
    text_blocks = [
        TextBlock(
            id="b1",
            page_number=1,
            text="equation: L = \u03c80(L) \u222a\u03c81(L), where\n\u03c80(z) = ( 1-i",
            bbox=(100, 100, 300, 130),
            source="pdf_text_layer",
        ),
        TextBlock(
            id="b2",
            page_number=1,
            text="2 )z,\n\u03c81(z) = ( 1+i",
            bbox=(220, 126, 330, 150),
            source="pdf_text_layer",
        ),
        TextBlock(
            id="b3",
            page_number=1,
            text="2 )z + 1-i",
            bbox=(300, 146, 370, 164),
            source="pdf_text_layer",
        ),
        TextBlock(
            id="b4",
            page_number=1,
            text="2 .",
            bbox=(360, 150, 385, 164),
            source="pdf_text_layer",
        ),
    ]

    formulas = extract_formulas(text_blocks)
    latex = {formula.latex for formula in formulas}

    assert r"\psi_{0}(z) = ( 1-i 2 )z" in latex
    assert r"\psi_{1}(z) = ( 1+i 2 )z + 1-i 2" in latex


def test_malformed_inline_candidate_with_unbalanced_delimiters_is_rejected():
    formulas = extract_formulas([block("Since x = (0 and k) = q(x, k + l) appear in OCR fragments.")])

    assert formulas == []


def test_standalone_formula_uses_line_bbox_not_paragraph_bbox():
    text_block = TextBlock(
        id="b1",
        page_number=1,
        text=r"Proof. The following identity is used.\nX = \phi_{0}(X) \cup \phi_{1}(X)\nThus the claim follows.",
        bbox=(10, 10, 500, 120),
        source="pdf_text_layer",
        lines=[
            TextLine(text="Proof. The following identity is used.", bbox=(10, 10, 420, 28)),
            TextLine(text=r"X = \phi_{0}(X) \cup \phi_{1}(X)", bbox=(180, 48, 360, 66)),
            TextLine(text="Thus the claim follows.", bbox=(10, 86, 260, 104)),
        ],
    )

    formulas = extract_formulas([text_block])

    assert len(formulas) == 1
    assert formulas[0].bbox == (180, 48, 360, 66)


def test_formula_crop_expands_only_to_math_lines_not_prose_block():
    text_blocks = [
        TextBlock(
            id="b1",
            page_number=1,
            text=r"Proof text\nX = \phi_{0}(X)\n\cup \phi_{1}(X)\nThus text",
            bbox=(10, 10, 500, 120),
            source="pdf_text_layer",
            lines=[
                TextLine(text="Proof text", bbox=(10, 10, 420, 28)),
                TextLine(text=r"X = \phi_{0}(X)", bbox=(180, 48, 310, 66)),
                TextLine(text=r"\cup \phi_{1}(X)", bbox=(312, 48, 430, 66)),
                TextLine(text="Thus text", bbox=(10, 86, 260, 104)),
            ],
        )
    ]
    formula = extract_formulas(text_blocks)[0]

    assert _expanded_bbox(formula, text_blocks) == (180, 48, 430, 66)


def test_visual_prose_formula_is_recovered_from_nearby_text_layer_formula():
    visual = FormulaBlock(
        id="f_bad",
        page_number=1,
        latex="Figure 2 shows how L can be constructed by similar contractions",
        kind="block",
        bbox=(130, 550, 477, 597),
        source="pp_structure_v3",
        confidence=0.65,
        quality_flags=["contains_prose", "needs_review"],
    )
    reference_blocks = [
        TextBlock(
            id="b1",
            page_number=1,
            text="Equation and caption",
            bbox=(120, 500, 500, 600),
            source="pdf_text_layer",
            lines=[
                TextLine(text=r"L = ψ0(L) ∪ ψ1(L)", bbox=(210, 515, 360, 536)),
                TextLine(text="Figure 2 shows how L can be constructed by similar contractions", bbox=(130, 550, 477, 575)),
            ],
        )
    ]

    reconciled = reconcile_formula_candidates_with_text_layer([visual], reference_blocks)

    assert len(reconciled) == 1
    assert reconciled[0].source == "text_pattern"
    assert reconciled[0].bbox == (210, 515, 360, 536)
    assert r"\psi" in reconciled[0].latex
    assert "recovered_from_text_layer" in reconciled[0].quality_flags


def test_visual_prose_formula_without_math_recovery_is_not_kept_as_formula():
    visual = FormulaBlock(
        id="f_bad",
        page_number=1,
        latex="The history of systematic mathematical research on self-similar sets dates back",
        kind="block",
        bbox=(40, 80, 520, 130),
        source="pp_formula_net",
        confidence=0.71,
        quality_flags=["contains_prose", "needs_review"],
    )
    reference_blocks = [
        TextBlock(
            id="b1",
            page_number=1,
            text="The history of systematic mathematical research on self-similar sets dates back",
            bbox=(40, 80, 520, 130),
            source="pdf_text_layer",
        )
    ]

    assert reconcile_formula_candidates_with_text_layer([visual], reference_blocks) == []


def test_formula_crop_does_not_merge_separate_display_formulas():
    text_blocks = [
        TextBlock(
            id="b1",
            page_number=1,
            text=r"\phi_{0}(x)=x\n\phi_{1}(x)=x+1",
            bbox=(100, 100, 200, 140),
            source="pdf_text_layer",
            lines=[
                TextLine(text=r"\phi_{0}(x)=x", bbox=(120, 100, 190, 112)),
                TextLine(text=r"\phi_{1}(x)=x+1", bbox=(120, 123, 205, 135)),
            ],
        )
    ]
    formula = extract_formulas(text_blocks)[0]

    assert _expanded_bbox(formula, text_blocks) == (120, 100, 190, 112)


def test_formula_ocr_salvages_math_row_before_prose_row():
    raw = (
        r"\begin{array}{r l}&{\quad X=\varphi_{0}(X)\cup\varphi_{1}(X)\cup\cdots\cup\varphi_{m-1}(X),\quad(2)}\\"
        r"&{}\\"
        r"{\mathrm{w h e r e~}\varphi_{0},\varphi_{1}\mathrm{~a r e~c o n t r a c t i o n s}}"
    )

    assert _salvage_math_segment(raw) == r"X=\varphi_{0}(X)\cup\varphi_{1}(X)\cup\cdots\cup\varphi_{m-1}(X), (2)"


def test_very_long_formula_net_candidate_does_not_replace_fallback():
    current = r"\psi_{0}(z) = ( 1-i"
    candidate = "L=" + r"\psi_0(z)=" * 120

    assert not _is_better_latex(candidate, current)


def test_incomplete_unbalanced_formula_is_flagged_and_not_selected():
    latex = r"\psi_{0}(z) = ( 1-i"

    assert "incomplete_formula" in validate_formula_latex(latex)
    assert "unbalanced_delimiters" in validate_formula_latex(latex)
    assert extract_formulas([block(latex)]) == []


def test_spaced_and_command_is_removed_from_formula_latex():
    latex = r"\frac{1}{2}\mathrm{~a n d~}Fix(\phi_1)"

    assert repair_formula_latex(latex) == r"\frac{1}{2}\quad Fix(\phi_1)"


def test_simple_pi_and_function_equalities_are_not_flagged_incomplete():
    assert "incomplete_formula" not in validate_formula_latex(r"\theta = \pi")
    assert "incomplete_formula" not in validate_formula_latex(r"\phi(x) = x")


def test_prose_fix_prefix_is_removed_without_touching_fix_operator():
    assert repair_formula_latex(r"Fix \theta = \pi") == r"\theta = \pi"
    assert repair_formula_latex(r"Fix(\phi_{0}) = 0") == r"Fix(\phi_{0}) = 0"


def test_condition_if_prefix_is_removed_from_formula():
    assert repair_formula_latex(r"If 0 \le x < 1/2") == r"0 \le x < 1/2"


def test_directed_graph_phrase_is_normalized_to_math_condition():
    latex = r"L=\{\sum_{n=1}^{\infty}\xi_n\alpha^n:(\xi_n)follows the directed-graph \mathcal{G}_1\}"

    assert repair_formula_latex(latex) == r"L=\{\sum_{n=1}^{\infty}\xi_n\alpha^n:(\xi_n)\in \mathcal{G}_1\}"


def test_formula_net_sum_without_lower_bound_is_rejected():
    current = r"F(1/2)=\frac{1}{2}\sum_{n=1}^{0} a_n"
    candidate = r"F(1/2)=\frac{1}{2}\sum^{0} a_n"

    assert "sum_missing_lower_bound" in validate_formula_latex(candidate)
    assert not _is_better_latex(candidate, current)
