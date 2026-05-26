from __future__ import annotations

import json
from datetime import datetime

from backend.formula_graph.export.structured_document import build_structured_document, validate_structured_document
from backend.formula_graph.models import FormulaBlock, FormulaRegion, PageImage, ProcessingResult, TextBlock


def _sample_result() -> ProcessingResult:
    return ProcessingResult(
        document_id="doc_test",
        filename="article.pdf",
        created_at=datetime(2026, 5, 21, 12, 0, 0),
        status="ok",
        pages=[
            PageImage(
                page_number=1,
                image_path="data/processed/doc_test/page_0001.png",
                width=2480,
                height=3508,
                dpi=300,
                text_layer="Let the energy of the system be defined as E equals m c squared. " * 8,
            )
        ],
        text_blocks=[
            TextBlock(
                id="old_tb_1",
                page_number=1,
                text="Let the energy of the system be defined as",
                bbox=(120, 300, 1200, 360),
                source="pdf_text_layer",
                confidence=0.94,
            ),
            TextBlock(
                id="old_tb_2",
                page_number=1,
                text="where m denotes mass and c denotes the speed of light.",
                bbox=(120, 460, 1700, 520),
                source="pdf_text_layer",
                confidence=0.93,
            ),
        ],
        text_with_tokens=[
            TextBlock(
                id="old_recon_1",
                page_number=1,
                text="Let the energy of the system be defined as [FORMULA_001].",
                bbox=(120, 300, 1700, 420),
                source="postprocessed",
                confidence=0.9,
            ),
            TextBlock(
                id="old_recon_2",
                page_number=1,
                text="where m denotes mass and c denotes the speed of light.",
                bbox=(120, 460, 1700, 520),
                source="postprocessed",
                confidence=0.93,
            ),
        ],
        formula_regions=[
            FormulaRegion(
                id="fr_1",
                token="[FORMULA_001]",
                page_number=1,
                bbox=(320, 380, 900, 440),
                kind="block",
                source="pp_structure_v3",
                confidence=0.87,
                formula_ids=["f_1"],
            )
        ],
        formulas=[
            FormulaBlock(
                id="f_1",
                token="[FORMULA_001]",
                formula_region_id="fr_1",
                page_number=1,
                latex="E = mc^2",
                raw_latex="E=mc^2",
                kind="block",
                bbox=(320, 380, 900, 440),
                source="pp_formula_net",
                confidence=0.91,
            )
        ],
    )


def _sample_doc():
    return build_structured_document(
        _sample_result(),
        ocr_mode="hybrid",
        device="cpu",
        ocr_lang="en",
        render_dpi=300,
        prefer_tex_source=False,
    )


def test_structured_document_has_required_top_level_fields():
    doc = _sample_doc()

    assert doc.schema_version == "1.0"
    assert doc.pages
    assert doc.text_blocks
    assert doc.formula_regions
    assert doc.formulas
    assert doc.text_with_tokens
    assert doc.formula_contexts
    assert isinstance(doc.warnings, list)


def test_structured_document_accepts_author_text_block_type():
    result = ProcessingResult(
        document_id="doc_author",
        filename="article.tex",
        created_at=datetime(2026, 5, 21, 12, 0, 0),
        status="ok",
        pages=[],
        text_blocks=[
            TextBlock(id="title", page_number=1, text="Paper Title", source="tex_source", role="title"),
            TextBlock(id="author", page_number=1, text="Jane Doe", source="tex_source", role="author"),
            TextBlock(id="abstract", page_number=1, text="Abstract text.", source="tex_source", role="abstract"),
        ],
        text_with_tokens=[],
        formula_regions=[],
        formulas=[],
    )

    doc = build_structured_document(result, ocr_mode="tex_source", ocr_lang="en", prefer_tex_source=True)

    assert [block.type for block in doc.text_blocks[:3]] == ["title", "author", "abstract"]
    assert doc.document_structure.authors == ["Jane Doe"]


def test_tex_section_role_spans_until_next_section():
    result = ProcessingResult(
        document_id="doc_sections",
        filename="article.tex",
        created_at=datetime(2026, 5, 21, 12, 0, 0),
        status="ok",
        pages=[],
        text_blocks=[
            TextBlock(id="sec_1_title", page_number=1, text="Introduction", source="tex_source", role="section"),
            TextBlock(id="sec_1_text", page_number=1, text="Text that belongs to introduction.", source="tex_source", role="paragraph"),
            TextBlock(id="sec_2_title", page_number=1, text="Model", source="tex_source", role="section"),
            TextBlock(id="sec_2_text", page_number=1, text="Text that belongs to model.", source="tex_source", role="paragraph"),
        ],
        formulas=[
            FormulaBlock(id="f_1", token="[FORMULA_001]", page_number=1, latex="x = y", kind="block", source="tex_source", section_id="sec_1"),
            FormulaBlock(id="f_2", token="[FORMULA_002]", page_number=1, latex="z = w", kind="block", source="tex_source", section_id="sec_2"),
        ],
    )

    doc = build_structured_document(result, ocr_mode="tex_source", ocr_lang="en", prefer_tex_source=True)

    assert [section.title for section in doc.document_structure.sections] == ["Introduction", "Model"]
    section_by_title = {section.title: section.id for section in doc.document_structure.sections}
    block_by_text = {block.text: block for block in doc.text_blocks}
    assert block_by_text["Text that belongs to introduction."].section_id == section_by_title["Introduction"]
    assert block_by_text["Text that belongs to model."].section_id == section_by_title["Model"]
    formula_by_latex = {formula.latex: formula for formula in doc.formulas}
    assert formula_by_latex["x = y"].section_id == section_by_title["Introduction"]
    assert formula_by_latex["z = w"].section_id == section_by_title["Model"]


def test_formula_tokens_are_unique():
    doc = _sample_doc()

    tokens = [formula.token for formula in doc.formulas]
    assert tokens == ["[FORMULA_001]"]
    assert len(tokens) == len(set(tokens))


def test_formula_regions_link_to_formulas():
    doc = _sample_doc()

    formula_ids = {formula.id for formula in doc.formulas}
    formula_tokens = {formula.token for formula in doc.formulas}
    assert all(region.formula_id in formula_ids for region in doc.formula_regions)
    assert all(region.token in formula_tokens for region in doc.formula_regions)


def test_text_with_tokens_contains_known_tokens_only():
    doc = _sample_doc()

    known_tokens = {formula.token for formula in doc.formulas}
    tokens_in_text = set(token.group(0) for token in __import__("re").finditer(r"\[FORMULA_\d{3}\]", doc.text_with_tokens))
    assert tokens_in_text <= known_tokens
    assert doc.text_with_tokens.count("[FORMULA_001]") == 1


def test_formula_contexts_created_for_each_formula():
    doc = _sample_doc()

    assert len(doc.formula_contexts) == len(doc.formulas)
    assert doc.formula_contexts[0].formula_id == doc.formulas[0].id
    assert "where" in doc.formula_contexts[0].definition_markers
    assert "denotes" in doc.formula_contexts[0].definition_markers


def test_reading_order_contains_text_and_formulas():
    doc = _sample_doc()

    object_types = {item.object_type for item in doc.reading_order}
    assert {"text_block", "formula"} <= object_types
    assert [item.order for item in doc.reading_order] == list(range(1, len(doc.reading_order) + 1))


def test_structured_json_is_serializable():
    doc = _sample_doc()

    payload = json.loads(doc.model_dump_json())
    assert payload["document_id"] == "doc_test"
    assert not validate_structured_document(doc)


def test_all_tokens_in_text_exist_in_formulas():
    doc = _sample_doc()

    formula_tokens = {formula.token for formula in doc.formulas}
    tokens_in_text = {match.group(0) for match in __import__("re").finditer(r"\[FORMULA_\d{3}\]", doc.text_with_tokens)}
    assert tokens_in_text <= formula_tokens


def test_all_formulas_have_context_or_warning():
    doc = _sample_doc()

    context_formula_ids = {context.formula_id for context in doc.formula_contexts}
    warning_formula_ids = {
        object_id
        for warning in doc.warnings
        if warning.code == "formula_context_missing"
        for object_id in warning.object_ids
    }
    assert {formula.id for formula in doc.formulas} <= context_formula_ids | warning_formula_ids


def test_reading_order_ids_are_valid():
    doc = _sample_doc()

    valid_ids = {block.id for block in doc.text_blocks} | {formula.id for formula in doc.formulas}
    assert all(item.object_id in valid_ids for item in doc.reading_order)


def test_summary_counts_match_arrays():
    doc = _sample_doc()

    assert doc.summary.pages_count == len(doc.pages)
    assert doc.summary.text_blocks_count == len(doc.text_blocks)
    assert doc.summary.formula_regions_count == len(doc.formula_regions)
    assert doc.summary.formulas_count == len(doc.formulas)
    assert doc.summary.tokens_in_text_count == doc.text_with_tokens.count("[FORMULA_001]")
    assert doc.summary.formula_contexts_count == len(doc.formula_contexts)
    assert doc.summary.entities_count == len(doc.entities)
    assert doc.summary.relations_count == len(doc.relations)
    assert doc.summary.warnings_count == len(doc.warnings)
    assert doc.summary.status == doc.status


def test_requested_and_resolved_device_are_saved():
    doc = build_structured_document(_sample_result(), device="gpu", resolved_device="cpu")

    assert doc.processing_profile.requested_device == "gpu"
    assert doc.processing_profile.resolved_device == "cpu"
    assert doc.processing_profile.device == "cpu"


def test_requested_and_resolved_ocr_lang_are_saved():
    doc = build_structured_document(
        _sample_result(),
        ocr_lang="ru",
        requested_ocr_lang="auto",
        resolved_ocr_lang="ru",
        ocr_language_detection_reason="auto_detected_from_text_layer",
    )

    assert doc.processing_profile.requested_ocr_lang == "auto"
    assert doc.processing_profile.resolved_ocr_lang == "ru"
    assert doc.processing_profile.ocr_lang == "ru"
    assert doc.processing_profile.ocr_language_detection_reason == "auto_detected_from_text_layer"


def test_window_text_contains_formula_token():
    doc = _sample_doc()

    assert all(context.token in context.window_text for context in doc.formula_contexts)


def test_document_structure_present():
    doc = _sample_doc()

    assert doc.document_structure
    assert doc.document_structure.detected_language in {"ru", "en", "unknown"}
    assert isinstance(doc.document_structure.sections, list)


def test_sections_have_valid_ranges():
    doc = _sample_doc()

    for section in doc.document_structure.sections:
        assert section.start_reading_order is None or section.start_reading_order >= 1
        assert section.end_reading_order is None or section.end_reading_order >= section.start_reading_order


def test_text_blocks_section_ids_are_valid():
    doc = _sample_doc()

    section_ids = {section.id for section in doc.document_structure.sections}
    assert all(block.section_id is None or block.section_id in section_ids for block in doc.text_blocks)


def test_formulas_section_ids_are_valid():
    doc = _sample_doc()

    section_ids = {section.id for section in doc.document_structure.sections}
    assert all(formula.section_id is None or formula.section_id in section_ids for formula in doc.formulas)


def test_formula_semantic_hints_present():
    doc = _sample_doc()

    hints = doc.formulas[0].semantic_hints
    assert hints.contains_equality is True
    assert isinstance(hints.definition_like, bool)


def test_formula_number_field_present():
    doc = _sample_doc()

    assert hasattr(doc.formulas[0], "formula_number")


def test_formula_links_reference_existing_formulas():
    doc = _sample_doc()

    formula_ids = {formula.id for formula in doc.formulas}
    assert all(link.source_formula_id in formula_ids and link.target_formula_id in formula_ids for link in doc.formula_links)


def test_graph_seed_nodes_are_unique():
    doc = _sample_doc()

    node_ids = [node.id for node in doc.graph_seed.nodes]
    assert len(node_ids) == len(set(node_ids))


def test_graph_seed_edges_reference_existing_nodes():
    doc = _sample_doc()

    node_ids = {node.id for node in doc.graph_seed.nodes}
    assert all(edge.source in node_ids and edge.target in node_ids for edge in doc.graph_seed.edges)


def test_symbol_entities_have_occurrences():
    doc = _sample_doc()

    symbol_entities = [entity for entity in doc.entities if entity.type == "symbol"]
    assert symbol_entities
    assert all(entity.occurrences for entity in symbol_entities)
