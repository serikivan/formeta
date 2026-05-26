from __future__ import annotations

from backend.formula_graph.semantic.formula_interpreter import interpret_formula


def test_formula_interpretation_uses_plain_text_variables_and_definitions():
    interpretation = interpret_formula(
        "E = mc^{2}",
        variables=["E", "m", "c"],
        possible_definitions={"m": "mass", "c": "speed of light"},
        context="where m denotes mass and c denotes speed of light",
    )

    assert interpretation["kind"] == "definition_or_equation"
    assert "squared" in interpretation["plain_text"]
    assert interpretation["definitions"]["m"] == "mass"
    assert "Readable form" in interpretation["summary"]
