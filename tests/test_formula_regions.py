from backend.formula_graph.layout.regions import (
    assign_formula_tokens,
    build_formula_regions,
    consolidate_assigned_formulas,
    merge_formula_candidates,
    reindex_formulas,
)
from backend.formula_graph.models import FormulaBlock


def test_merge_formula_candidates_prefers_text_layer_formula_for_same_region():
    text_formula = FormulaBlock(
        id="f_1",
        page_number=1,
        latex=r"X = \phi_{0}(X) \cup \phi_{1}(X)",
        kind="block",
        bbox=(100, 120, 260, 150),
        source="text_pattern",
        confidence=0.58,
    )
    structure_formula = FormulaBlock(
        id="f_2",
        page_number=1,
        latex=r"X=\varphi_{0}(X)\cup\varphi_{1}(X)",
        kind="block",
        bbox=(102, 121, 261, 151),
        source="pp_structure_v3",
        confidence=0.91,
    )

    merged = merge_formula_candidates([text_formula], [structure_formula])

    assert len(merged) == 1
    assert merged[0].source == "text_pattern"


def test_build_formula_regions_and_assign_tokens():
    formulas = [
        FormulaBlock(
            id="f_1",
            page_number=1,
            latex=r"x = y",
            kind="inline",
            bbox=(20, 30, 80, 46),
            source="text_inline_pattern",
            confidence=0.72,
        ),
        FormulaBlock(
            id="f_2",
            page_number=1,
            latex=r"z = \frac{1}{2}",
            kind="block",
            bbox=(100, 120, 180, 150),
            source="text_pattern",
            confidence=0.61,
        ),
    ]

    regions = build_formula_regions(formulas)
    tokenized = assign_formula_tokens(formulas, regions)

    assert [region.token for region in regions] == ["[FORMULA_001]", "[FORMULA_002]"]
    assert [formula.token for formula in tokenized] == ["[FORMULA_001]", "[FORMULA_002]"]
    assert [formula.formula_region_id for formula in tokenized] == ["fr_1", "fr_2"]


def test_build_formula_regions_clusters_overlapping_formula_variants():
    formulas = [
        FormulaBlock(
            id="f_text",
            page_number=1,
            latex=r"L = \psi_0(L) \cup \psi_1(L)",
            kind="inline",
            bbox=(120, 100, 240, 120),
            source="text_inline_pattern",
            confidence=0.72,
        ),
        FormulaBlock(
            id="f_struct",
            page_number=1,
            latex=r"L=\psi_{0}(L)\cup\psi_{1}(L)",
            kind="block",
            bbox=(118, 98, 246, 123),
            source="pp_structure_v3",
            confidence=0.88,
        ),
    ]

    regions = build_formula_regions(formulas)
    tokenized = assign_formula_tokens(formulas, regions)

    assert len(regions) == 1
    assert regions[0].formula_ids == ["f_text", "f_struct"]
    assert {formula.token for formula in tokenized} == {"[FORMULA_001]"}


def test_assign_formula_tokens_can_match_formula_without_bbox_by_latex():
    formulas = [
        FormulaBlock(
            id="f_text",
            page_number=1,
            latex=r"L = \psi_0(L) \cup \psi_1(L)",
            kind="inline",
            bbox=(120, 100, 240, 120),
            source="text_inline_pattern",
            confidence=0.72,
        ),
        FormulaBlock(
            id="f_struct",
            page_number=1,
            latex=r"L=\psi_{0}(L)\cup\psi_{1}(L)",
            kind="block",
            bbox=None,
            source="pp_structure_v3",
            confidence=0.88,
        ),
    ]

    regions = build_formula_regions([formulas[0]])
    tokenized = assign_formula_tokens(formulas, regions)

    assert tokenized[0].token == "[FORMULA_001]"
    assert tokenized[1].token == "[FORMULA_001]"


def test_assign_formula_tokens_can_fall_back_to_single_page_region():
    text_formula = FormulaBlock(
        id="f_text",
        page_number=1,
        latex=r"broken OCR formula",
        kind="block",
        bbox=(120, 100, 240, 120),
        source="text_pattern",
        confidence=0.4,
    )
    structure_formula = FormulaBlock(
        id="f_struct",
        page_number=1,
        latex=r"\frac{\partial \Phi}{\partial t}",
        kind="block",
        bbox=None,
        source="pp_structure_v3",
        confidence=0.88,
    )

    regions = build_formula_regions([text_formula])
    tokenized = assign_formula_tokens([text_formula, structure_formula], regions)

    assert tokenized[1].token == "[FORMULA_001]"


def test_assign_formula_tokens_does_not_attach_bboxless_raw_formula_to_single_page_region():
    text_formula = FormulaBlock(
        id="f_text",
        page_number=1,
        latex=r"broken OCR formula",
        kind="inline",
        bbox=(120, 100, 240, 120),
        source="text_inline_pattern",
        confidence=0.4,
    )
    raw_formula = FormulaBlock(
        id="f_raw",
        page_number=1,
        latex=r"\mu\mathrm{~-P R O S E}",
        kind="inline",
        bbox=None,
        source="pp_structure_v3_raw",
        confidence=0.45,
        quality_flags=["needs_formula_review", "contains_prose", "needs_review"],
    )

    regions = build_formula_regions([text_formula])
    tokenized = assign_formula_tokens([text_formula, raw_formula], regions)

    assert tokenized[0].token == "[FORMULA_001]"
    assert tokenized[1].token is None


def test_consolidate_assigned_formulas_keeps_best_formula_per_token():
    formulas = [
        FormulaBlock(
            id="f_bad",
            page_number=1,
            latex=r"broken OCR text",
            kind="block",
            token="[FORMULA_001]",
            formula_region_id="fr_1",
            bbox=(100, 100, 260, 140),
            source="text_pattern",
            confidence=0.55,
            quality_flags=["formula_ocr_kept_fallback", "raw_ocr_romanized_ocr_noise"],
        ),
        FormulaBlock(
            id="f_good",
            page_number=1,
            latex=r"\frac{\partial \Phi}{\partial t}",
            kind="block",
            token="[FORMULA_001]",
            formula_region_id="fr_1",
            bbox=None,
            source="pp_structure_v3",
            confidence=0.88,
        ),
    ]

    consolidated = consolidate_assigned_formulas(formulas)

    assert len(consolidated) == 1
    assert consolidated[0].latex == r"\frac{\partial \Phi}{\partial t}"
    assert consolidated[0].bbox == (100, 100, 260, 140)
    assert consolidated[0].quality_flags == []


def test_reindex_formulas_produces_unique_stable_ids():
    formulas = [
        FormulaBlock(id="f_1", page_number=2, latex="b", kind="inline", bbox=(20, 20, 40, 30)),
        FormulaBlock(id="f_1", page_number=1, latex="a", kind="block", bbox=(10, 10, 30, 20)),
    ]

    reindexed = reindex_formulas(formulas)

    assert [formula.id for formula in reindexed] == ["f_1", "f_2"]
    assert [formula.page_number for formula in reindexed] == [1, 2]
