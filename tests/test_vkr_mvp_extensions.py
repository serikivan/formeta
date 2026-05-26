from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.formula_graph.config import settings
from backend.formula_graph.export.metagraph_metrics import aggregate_metagraph_metrics, compute_metagraph_metrics
from backend.formula_graph.graph.graph_ready_metagraph import build_metagraph_from_graph_ready
from backend.formula_graph.ingestion.arxiv_source import fetch_arxiv_source
from backend.formula_graph.models import TextBlock
from backend.formula_graph.pipeline import _needs_text_ocr
from backend.formula_graph.semantic.rules import extract_definition_evidence
from tests.test_graph_ready_export import _graph_ready


def test_rule_based_context_extraction_ru():
    evidence = extract_definition_evidence("где x — скорость частицы, а t обозначает время.", ["x", "t"])

    assert any(item.symbol == "x" and item.rule == "ru_where_dash" for item in evidence)
    assert any(item.symbol == "t" and item.rule == "ru_denotes" for item in evidence)


def test_rule_based_context_extraction_en():
    evidence = extract_definition_evidence("where x is the coordinate and y denotes the response.", ["x", "y"])

    assert any(item.symbol == "x" and item.rule == "en_where_is" for item in evidence)
    assert any(item.symbol == "y" and item.rule == "en_denotes" for item in evidence)


def test_rich_metagraph_schema_and_required_metaedges():
    metagraph = build_metagraph_from_graph_ready(_graph_ready())
    payload = metagraph.to_dict()
    metaedge_types = {item["type"] for item in payload["metaedges"]}

    assert {"nodes", "edges", "metavertices", "metaedges", "fragments", "metrics", "provenance"} <= set(payload)
    assert "definition_context" in metaedge_types
    assert "notation_scope" in metaedge_types
    assert "extraction_evidence" in metaedge_types
    assert payload["metrics"]["formula_count"] >= 1


def test_formula_dependency_metaedge():
    doc = _graph_ready()
    duplicate = doc.formulas[0].model_copy(update={"id": "formula_0002", "token": "[FORMULA_002]", "order": 99})
    doc.formulas.append(duplicate)
    metagraph = build_metagraph_from_graph_ready(doc)

    assert any(item.type == "formula_dependency" for item in metagraph.metaedges.values())


def test_paragraph_context_extraction():
    doc = _graph_ready()

    assert doc.paragraphs
    assert doc.paragraphs[0].id.startswith("para_")
    assert doc.formula_contexts[0].context_before or doc.formula_contexts[0].context_after


def test_variable_search_response_has_neighborhood():
    payload = _graph_ready()
    result = __import__("backend.formula_graph.export.graph_ready_export", fromlist=["search_variable_in_graph_ready"]).search_variable_in_graph_ready(
        payload, "lambda"
    )

    assert result["neighborhood"]["nodes"]
    assert result["scope"]["level"] in {"paragraph", "section", "document"}
    assert result["related_formulas"]
    assert result["matches"][0]["formula_semantics"]["semantic_type"] == "formula_metavertex"


def test_metagraph_metrics_for_one_document_and_aggregate(tmp_path):
    doc = _graph_ready()
    rich = build_metagraph_from_graph_ready(doc).to_dict()
    result = {"document_id": doc.document_id, "filename": doc.filename, "status": "ok", "formulas": [item.model_dump() for item in doc.formulas]}
    metrics = compute_metagraph_metrics(rich, result)

    assert metrics["basic"]["formula_count"] >= 1
    assert "metaedge_count_by_type" in metrics["metaedges"]
    assert "semantic_metaedge_count_by_relation" in metrics["metaedges"]
    assert metrics["semantic"]["formula_metavertex_count"] >= 1

    (tmp_path / f"{doc.document_id}.rich_metagraph.json").write_text(json.dumps(rich), encoding="utf-8")
    (tmp_path / f"{doc.document_id}.json").write_text(json.dumps(result), encoding="utf-8")
    aggregate = aggregate_metagraph_metrics(tmp_path)
    assert aggregate["documents_count"] == 1
    assert "average_metavertex_semantic_coverage" in aggregate


def test_metrics_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "results_dir", tmp_path)
    doc = _graph_ready()
    rich = build_metagraph_from_graph_ready(doc).to_dict()
    (tmp_path / f"{doc.document_id}.graph_ready.json").write_text(doc.model_dump_json(), encoding="utf-8")
    (tmp_path / f"{doc.document_id}.rich_metagraph.json").write_text(json.dumps(rich), encoding="utf-8")
    (tmp_path / f"{doc.document_id}.json").write_text(
        json.dumps({"document_id": doc.document_id, "filename": doc.filename, "status": "ok", "formulas": []}),
        encoding="utf-8",
    )

    response = TestClient(app).get(f"/api/results/{doc.document_id}/metrics/metagraph")

    assert response.status_code == 200
    assert response.json()["basic"]["formula_count"] >= 1


def test_standard_ocr_mode_does_not_require_ocr_for_good_text_layer():
    blocks = [
        TextBlock(id="tb", page_number=1, text="This is a good text layer. " * 40, source="pdf_text_layer"),
    ]

    assert _needs_text_ocr("standard", blocks, blocks, "en") is False


def test_timing_fields_are_present_in_default_result():
    from backend.formula_graph.pipeline import _ensure_timing

    timing = _ensure_timing({})

    assert "total_time_sec" in timing
    assert "pages_render_time" in timing
    assert "per_stage_time_sec" in timing


def test_prepare_input_file_falls_back_to_cached_local_arxiv_pdf(tmp_path, monkeypatch):
    from backend.app.main import _prepare_input_file

    cached_dir = tmp_path / "input" / "arxiv_stage3"
    cached_dir.mkdir(parents=True)
    cached_pdf = cached_dir / "2501.00001.pdf"
    cached_pdf.write_bytes(b"%PDF-1.4\ncached\n")

    monkeypatch.setattr(settings, "input_dir", tmp_path / "input")
    monkeypatch.setattr("backend.app.main._download_arxiv_pdf", lambda _arxiv_id: (_ for _ in ()).throw(OSError("blocked")))

    tmp_path_result, filename, suffix = _prepare_input_file(None, "2501.00001")
    try:
        assert suffix == ".pdf"
        assert filename == "2501.00001.pdf"
        assert Path(tmp_path_result).read_bytes().startswith(b"%PDF")
    finally:
        Path(tmp_path_result).unlink(missing_ok=True)


def test_random_arxiv_endpoint_falls_back_to_cached_local_pdf(tmp_path, monkeypatch):
    cached_dir = tmp_path / "input" / "arxiv_stage3"
    cached_dir.mkdir(parents=True)
    for arxiv_id in ("2501.00001", "2501.00002", "2501.00003"):
        (cached_dir / f"{arxiv_id}.pdf").write_bytes(b"%PDF-1.4\ncached\n")

    monkeypatch.setattr(settings, "input_dir", tmp_path / "input")
    monkeypatch.setattr(
        "backend.app.main._fetch_random_arxiv_ids",
        lambda *args, **kwargs: (_ for _ in ()).throw(HTTPException(status_code=502, detail="socket blocked")),
    )
    monkeypatch.setattr("backend.app.main._run_batch_job", lambda *args, **kwargs: None)

    response = TestClient(app).post(
        "/api/arxiv/random-process",
        json={"count": 2, "category": "math", "device_mode": "cpu", "ocr_lang": "en", "prefer_tex_source": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_documents"] == 2
    assert len(payload["arxiv_ids"]) == 2
    assert any("локально кэшированные PDF" in warning for warning in payload["warnings"])


def test_fetch_arxiv_source_uses_cached_extracted_source(tmp_path, monkeypatch):
    sources_dir = tmp_path / "sources"
    cached_extract = sources_dir / "older_doc" / "2501.00001" / "extracted"
    cached_extract.mkdir(parents=True)
    (cached_extract / "main.tex").write_text(r"\[E = mc^2\]", encoding="utf-8")

    monkeypatch.setattr(settings, "sources_dir", sources_dir)
    monkeypatch.setattr("backend.formula_graph.ingestion.arxiv_source._download", lambda _url: (_ for _ in ()).throw(OSError("blocked")))

    path, warnings = fetch_arxiv_source("2501.00001", "new_doc")

    assert path is not None
    assert path.exists()
    assert (path / "main.tex").exists()
    assert any("локально кэшированный TeX-источник" in warning for warning in warnings)
