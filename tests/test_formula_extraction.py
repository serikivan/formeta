from backend.formula_graph.layout.formulas import extract_formulas
from backend.formula_graph.models import TextBlock, TextLine, TextSpan


def test_inline_formula_from_prose_uses_span_level_bbox():
    block = TextBlock(
        id="p1_tl_1",
        page_number=1,
        text="Since x = y + z, then the claim follows.",
        bbox=(10, 20, 210, 36),
        source="pdf_text_layer",
        confidence=1.0,
        lines=[
            TextLine(
                text="Since x = y + z, then the claim follows.",
                bbox=(10, 20, 210, 36),
                spans=[
                    TextSpan(text="Since ", bbox=(10, 20, 40, 36)),
                    TextSpan(text="x = y + z", bbox=(40, 20, 96, 36)),
                    TextSpan(text=", then the claim follows.", bbox=(96, 20, 210, 36)),
                ],
            )
        ],
    )

    formulas = extract_formulas([block])
    inline = next(formula for formula in formulas if formula.source == "text_inline_pattern")

    assert inline.latex == "x = y + z"
    assert inline.bbox is not None
    assert inline.bbox[0] >= 38
    assert inline.bbox[2] <= 100
    assert inline.bbox[2] - inline.bbox[0] < 90
