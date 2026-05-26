from pathlib import Path

from PIL import Image

from backend.formula_graph.ingestion.masking import reconstruct_text_with_formula_tokens
from backend.formula_graph.models import FormulaRegion
from backend.formula_graph.models import FormulaBlock, PageImage, TextBlock, TextLine, TextSpan
from backend.formula_graph.pipeline import process_document


def test_pipeline_masks_formula_regions_before_ocr(monkeypatch, tmp_path: Path):
    image_path = tmp_path / "sample.png"
    Image.new("RGB", (800, 400), "white").save(image_path)

    seen_image_paths: list[str] = []

    def fake_structure_parse(self, pages):
        return (
            [],
            [
                FormulaBlock(
                    id="f_1",
                    page_number=1,
                    latex=r"X = \phi_{0}(X)",
                    kind="block",
                    bbox=(120, 90, 260, 130),
                    source="pp_structure_v3",
                    confidence=0.62,
                )
            ],
            [],
        )

    def fake_paddle_ocr(self, pages):
        seen_image_paths.extend(page.image_path for page in pages)
        return (
            [
                TextBlock(
                    id="p1_ocr_1",
                    page_number=1,
                    text="This is surrounding prose.",
                    bbox=(40, 150, 320, 180),
                    source="paddleocr",
                    confidence=0.96,
                )
            ],
            [],
        )

    def fake_refine(self, pages, formulas, text_blocks):
        return formulas, []

    monkeypatch.setattr("backend.formula_graph.ocr.paddle_structure.PaddleStructureAdapter.parse_pages", fake_structure_parse)
    monkeypatch.setattr("backend.formula_graph.ocr.paddle_text.PaddleOCRAdapter.recognize_pages", fake_paddle_ocr)
    monkeypatch.setattr("backend.formula_graph.ocr.formula_recognition.FormulaRecognitionAdapter.refine", fake_refine)

    result = process_document(image_path, "sample.png", ocr_mode="hybrid", ocr_lang="en", prefer_tex_source=False, max_pages=1)

    assert seen_image_paths
    assert seen_image_paths[0].endswith("_masked.png")
    assert result.formula_regions
    assert result.formula_regions[0].token == "[FORMULA_001]"
    assert not any("[FORMULA_001]" in block.text for block in result.text_blocks)
    assert any("[FORMULA_001]" in block.text for block in result.text_with_tokens)
    assert result.formulas
    assert result.formulas[0].token == "[FORMULA_001]"
    assert result.formulas[0].formula_region_id == "fr_1"


def test_standard_mode_refines_low_confidence_formula_candidates(monkeypatch, tmp_path: Path):
    image_path = tmp_path / "sample.png"
    Image.new("RGB", (800, 400), "white").save(image_path)
    long_russian_text = "Пусть x = y задает отображение. " * 30
    refined: list[str] = []

    def fake_render_document(stored_path, document_id, render_dpi, max_pages, progress_callback=None):
        return (
            [
                PageImage(
                    page_number=1,
                    image_path=str(image_path),
                    width=800,
                    height=400,
                    dpi=render_dpi,
                    text_layer=long_russian_text,
                )
            ],
            [
                TextBlock(
                    id="p1_text",
                    page_number=1,
                    text=long_russian_text,
                    bbox=(20, 20, 780, 120),
                    source="pdf_text_layer",
                    confidence=0.98,
                )
            ],
        )

    def fake_structure_parse(self, pages):
        return (
            [],
            [
                FormulaBlock(
                    id="f_1",
                    page_number=1,
                    latex=r"x = y",
                    kind="inline",
                    bbox=(120, 90, 180, 112),
                    source="pp_structure_v3",
                    confidence=0.62,
                )
            ],
            [],
        )

    def fake_refine(self, pages, formulas, text_blocks):
        refined.extend(formula.id for formula in formulas)
        return formulas, []

    monkeypatch.setattr("backend.formula_graph.pipeline.render_document", fake_render_document)
    monkeypatch.setattr("backend.formula_graph.ocr.paddle_structure.PaddleStructureAdapter.parse_pages", fake_structure_parse)
    monkeypatch.setattr("backend.formula_graph.ocr.formula_recognition.FormulaRecognitionAdapter.refine", fake_refine)

    result = process_document(image_path, "sample.png", ocr_mode="standard", ocr_lang="ru", prefer_tex_source=False, max_pages=1)

    assert refined == ["f_1"]
    assert result.formula_regions


def test_reconstruct_text_inserts_formula_token_inside_line():
    text_blocks = [
        TextBlock(id="t1", page_number=1, text="Let", bbox=(20, 50, 42, 60), source="paddleocr", confidence=0.95),
        TextBlock(id="t2", page_number=1, text="be a contraction.", bbox=(90, 50, 180, 60), source="paddleocr", confidence=0.95),
    ]
    regions = [
        FormulaRegion(
            id="fr_1",
            token="[FORMULA_001]",
            page_number=1,
            bbox=(48, 48, 84, 62),
            kind="inline",
            source="detector",
            confidence=0.8,
        )
    ]

    reconstructed = reconstruct_text_with_formula_tokens(text_blocks, regions)

    assert len(reconstructed) == 1
    assert reconstructed[0].text == "Let [FORMULA_001] be a contraction."


def test_reconstruct_text_drops_overlapping_block_formula_fragments():
    text_blocks = [
        TextBlock(
            id="p1_t1",
            page_number=1,
            text="Уравнение записывается в виде:",
            bbox=(20, 20, 220, 36),
            source="pdf_text_layer",
            confidence=0.95,
        ),
        TextBlock(
            id="p1_formula_noise",
            page_number=1,
            text="F\n¶\nF\n+\n=\nG",
            bbox=(100, 40, 220, 82),
            source="pdf_text_layer",
            confidence=0.55,
        ),
        TextBlock(
            id="p1_after",
            page_number=1,
            text="где G - внешний источник.",
            bbox=(20, 92, 220, 108),
            source="pdf_text_layer",
            confidence=0.95,
        ),
    ]
    regions = [
        FormulaRegion(
            id="fr_1",
            token="[FORMULA_001]",
            page_number=1,
            bbox=(96, 38, 228, 86),
            kind="block",
            source="text_pattern",
            confidence=0.55,
        )
    ]

    reconstructed = reconstruct_text_with_formula_tokens(text_blocks, regions)
    combined = "\n".join(block.text for block in reconstructed)

    assert "[FORMULA_001]" in combined
    assert "где G - внешний источник." in combined
    assert "F ¶ F" not in combined


def test_reconstruct_text_preserves_inline_prose_when_spans_are_available():
    text_blocks = [
        TextBlock(
            id="t1",
            page_number=1,
            text="Let x = y be a contraction.",
            bbox=(20, 50, 220, 64),
            source="pdf_text_layer",
            confidence=0.95,
            lines=[
                TextLine(
                    text="Let x = y be a contraction.",
                    bbox=(20, 50, 220, 64),
                    spans=[
                        TextSpan(text="Let ", bbox=(20, 50, 44, 64)),
                        TextSpan(text="x = y", bbox=(44, 50, 86, 64)),
                        TextSpan(text=" be a contraction.", bbox=(86, 50, 220, 64)),
                    ],
                )
            ],
        )
    ]
    regions = [
        FormulaRegion(
            id="fr_1",
            token="[FORMULA_001]",
            page_number=1,
            bbox=(43, 48, 88, 66),
            kind="inline",
            source="detector",
            confidence=0.8,
        )
    ]

    reconstructed = reconstruct_text_with_formula_tokens(text_blocks, regions)

    assert len(reconstructed) == 1
    assert reconstructed[0].text == "Let [FORMULA_001] be a contraction."


def test_reconstruct_text_removes_inline_formula_without_spans():
    text_blocks = [
        TextBlock(
            id="t1",
            page_number=1,
            text="Let s = -1/2 + i/2 be the translation.",
            bbox=(20, 50, 320, 64),
            source="pdf_text_layer",
            confidence=0.95,
        )
    ]
    regions = [
        FormulaRegion(
            id="fr_1",
            token="[FORMULA_001]",
            page_number=1,
            bbox=(52, 48, 155, 66),
            kind="inline",
            source="text_inline_pattern",
            confidence=0.72,
            latex_keys=["s=-1/2+i/2"],
        )
    ]

    reconstructed = reconstruct_text_with_formula_tokens(text_blocks, regions)

    assert len(reconstructed) == 1
    assert reconstructed[0].text == "Let [FORMULA_001] be the translation."
