from __future__ import annotations

from backend.formula_graph.postprocessing.latex_cleaner import (
    build_latex_variants,
    clean_latex,
    latex_to_plain_text,
    normalize_latex,
)


def test_markdown_fenced_latex_is_cleaned_and_normalized():
    assert normalize_latex(clean_latex("```latex\nE = mc^2\n```")) == "E = mc^{2}"


def test_dollar_wrapped_latex_is_cleaned_and_normalized():
    assert normalize_latex(clean_latex("$$ E = mc^2 $$")) == "E = mc^{2}"


def test_left_right_are_removed_without_breaking_brackets():
    assert normalize_latex(r"\left( x + y \right)") == "(x + y)"


def test_fraction_and_sum_keep_math_structure():
    assert normalize_latex(r"\frac{x}{y}") == r"\frac{x}{y}"
    assert r"\sum_{i=1}^{n} x_{i}" == normalize_latex(r"\sum_{i=1}^{n} x_i")


def test_raw_latex_is_kept_separate_from_normalized_latex():
    variants = build_latex_variants("```latex\nE = mc^2\n```")

    assert variants["raw_latex"].startswith("```latex")
    assert variants["normalized_latex"] == "E = mc^{2}"
    assert "squared" in latex_to_plain_text(variants["normalized_latex"])


def test_plain_text_covers_common_operators():
    text = latex_to_plain_text(r"\forall x \in A:\ f(x) \le \sqrt{x} + \prod_{i=1}^{n} y_i \to z")

    assert "for all" in text
    assert "in" in text
    assert "less than or equal to" in text
    assert "square root" in text
    assert "product" in text
    assert "to" in text
    assert "productsubscript" not in text


def test_adjacent_commands_do_not_merge_words():
    text = latex_to_plain_text(r"L = \psi_0(L) \cup\psi_1(L)")

    assert "union psi" in text
    assert "unionpsi" not in text


def test_mbox_is_normalized_to_katex_supported_text_command():
    assert normalize_latex(clean_latex(r"x=\mbox{where } y")) == r"x=\text{where} y"
