from pathlib import Path

import fitz

from backend.formula_graph.config import settings
from backend.formula_graph.ingestion.loaders import render_document
from backend.formula_graph.models import FormulaBlock, PageImage, TextBlock
from backend.formula_graph.pipeline import _choose_blocks_and_formulas
from backend.formula_graph.pipeline import process_document


def test_pipeline_extracts_text_layer(tmp_path: Path):
    pdf_path = tmp_path / "sample.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Let x is velocity. Formula $E = mc^2$ is important.")
    doc.save(pdf_path)
    doc.close()

    result = process_document(pdf_path, "sample.pdf", ocr_mode="text_layer", max_pages=1)

    assert result.status in {"ok", "partial"}
    assert result.text_blocks
    assert result.text_with_tokens
    assert result.formulas
    assert result.graph.nodes
    assert Path(result.result_path or "").exists()
    assert (settings.results_dir / f"{result.document_id}.structured.json").exists()
    assert (settings.results_dir / f"{result.document_id}.graph_ready.json").exists()


def test_render_document_zero_max_pages_means_all_pages(tmp_path: Path):
    pdf_path = tmp_path / "all-pages.pdf"
    doc = fitz.open()
    for index in range(3):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {index + 1}")
    doc.save(pdf_path)
    doc.close()

    pages, _ = render_document(pdf_path, "pytest-all-pages", dpi=120, max_pages=0)

    assert [page.page_number for page in pages] == [1, 2, 3]


def test_auto_mode_keeps_text_layer_and_adds_visual_formula_candidates(monkeypatch):
    _assert_layer_mode_keeps_text_layer_and_adds_visual_formula_candidates(monkeypatch, "auto")


def test_standard_mode_keeps_text_layer_and_adds_visual_formula_candidates(monkeypatch):
    _assert_layer_mode_keeps_text_layer_and_adds_visual_formula_candidates(monkeypatch, "standard")


def _assert_layer_mode_keeps_text_layer_and_adds_visual_formula_candidates(monkeypatch, mode: str):
    page = PageImage(page_number=1, image_path="page.png", width=1000, height=1400, dpi=300)
    text_block = TextBlock(
        id="p1_tl_1",
        page_number=1,
        text=("The equation below defines the system. " * 20).strip(),
        bbox=(10, 10, 300, 30),
        source="pdf_text_layer",
        confidence=1.0,
    )
    visual_formula = FormulaBlock(
        id="f_visual_1",
        page_number=1,
        latex=r"x = y",
        kind="block",
        bbox=(100, 80, 200, 110),
        source="pp_structure_v3",
        confidence=0.8,
    )

    def fake_parse_pages(self, pages):
        return [], [visual_formula], []

    monkeypatch.setattr("backend.formula_graph.pipeline.PaddleStructureAdapter.parse_pages", fake_parse_pages)

    text_blocks, formulas = _choose_blocks_and_formulas(
        [page],
        [page],
        [text_block],
        mode,
        "cpu",
        "en",
        [],
    )

    assert text_blocks == [text_block]
    assert formulas == [visual_formula]
