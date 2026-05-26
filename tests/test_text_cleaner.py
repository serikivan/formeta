from __future__ import annotations

from backend.formula_graph.postprocessing.text_cleaner import clean_ocr_text


def test_zero_width_and_replacement_symbols_are_removed():
    assert clean_ocr_text("A\u200bB\ufffdC") == "ABC"


def test_formula_token_is_preserved():
    assert "[FORMULA_001]" in clean_ocr_text("text \u200b [FORMULA_001] \ufffd after")


def test_russian_and_english_text_are_preserved():
    text = "Русский текст and English text 123."

    assert clean_ocr_text(text) == text
