from __future__ import annotations

from datetime import datetime

from backend.formula_graph.ingestion.loaders import build_document_id
from backend.formula_graph.storage_cleanup import cleanup_after_processing


def test_document_id_uses_filename_date_and_type():
    document_id = build_document_id("2605.02988.pdf", datetime(2026, 5, 25, 16, 30, 5))

    assert document_id == "2605.02988_20260525_163005_pdf"


def test_storage_cleanup_deletes_input_copy_and_old_bundle(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    results_dir = tmp_path / "results"
    processed_dir = tmp_path / "processed"
    sources_dir = tmp_path / "sources"
    for directory in (input_dir, results_dir, processed_dir, sources_dir):
        directory.mkdir()
    monkeypatch.setattr("backend.formula_graph.storage_cleanup.settings.input_dir", input_dir)
    monkeypatch.setattr("backend.formula_graph.storage_cleanup.settings.results_dir", results_dir)
    monkeypatch.setattr("backend.formula_graph.storage_cleanup.settings.processed_dir", processed_dir)
    monkeypatch.setattr("backend.formula_graph.storage_cleanup.settings.sources_dir", sources_dir)
    monkeypatch.setattr("backend.formula_graph.storage_cleanup.settings.storage_delete_input_after_processing", True)
    monkeypatch.setattr("backend.formula_graph.storage_cleanup.settings.storage_retention_days", 0)
    monkeypatch.setattr("backend.formula_graph.storage_cleanup.settings.storage_max_documents", 1)

    current_input = input_dir / "current_20260525_163005_pdf.pdf"
    current_input.write_text("pdf", encoding="utf-8")
    (results_dir / "old_20260524_120000_pdf.json").write_text("{}", encoding="utf-8")
    (results_dir / "old_20260524_120000_pdf.graph_ready.json").write_text("{}", encoding="utf-8")
    (results_dir / "current_20260525_163005_pdf.json").write_text("{}", encoding="utf-8")
    (processed_dir / "old_20260524_120000_pdf").mkdir()

    counts = cleanup_after_processing("current_20260525_163005_pdf", current_input)

    assert counts["input_files"] == 1
    assert counts["result_files"] == 2
    assert counts["processed_dirs"] == 1
    assert not current_input.exists()
    assert not (results_dir / "old_20260524_120000_pdf.json").exists()
    assert (results_dir / "current_20260525_163005_pdf.json").exists()
