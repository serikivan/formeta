from __future__ import annotations

import json
import time
from datetime import datetime

from fastapi.testclient import TestClient

from backend.app.main import app, _prepare_input_file
from backend.formula_graph.config import settings
from backend.formula_graph.export.corpus_export import create_corpus, corpus_variable_search, load_corpus_graph, load_corpus_metrics
from backend.formula_graph.export.graph_ready_export import save_graph_ready_document
from backend.formula_graph.llm import apply_formula_refinement, get_llm_status
from backend.formula_graph.llm.providers.ollama_provider import _parse_formula_response
from backend.formula_graph.llm.schemas import ContextRefinementResult, FormulaVerificationRequest, FormulaVerificationResult
from backend.formula_graph.models import FormulaBlock, ProcessingResult, TextBlock
from tests.test_graph_ready_export import _graph_ready


def _doc_copy(document_id: str, filename: str, symbol: str = "lambda"):
    doc = _graph_ready()
    doc.document_id = document_id
    doc.filename = filename
    for variable in doc.variables:
        if variable.normalized_symbol == "\\lambda":
            variable.symbol = symbol
            variable.normalized_symbol = "\\lambda"
    return doc


def test_batch_submit_status_results_and_metrics(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "results_dir", tmp_path)

    def fake_process_document(_path, filename, progress_callback=None, **kwargs):
        if progress_callback:
            progress_callback(40, "fake", filename)
            progress_callback(100, "done", filename)
        document_id = f"doc_{filename.split('.')[0]}"
        result = ProcessingResult(
            document_id=document_id,
            filename=filename,
            created_at=datetime(2026, 5, 23, 12, 0, 0),
            status="ok",
            warnings=[],
            timing={"total_time_sec": 0.1, "per_stage_time_sec": {}},
        )
        result.save_json(tmp_path / f"{document_id}.json")
        doc = _doc_copy(document_id, filename)
        save_graph_ready_document(doc, tmp_path / f"{document_id}.graph_ready.json")
        return result

    monkeypatch.setattr("backend.app.main.process_document", fake_process_document)
    client = TestClient(app)
    response = client.post(
        "/api/process/batch/submit",
        data={"ocr_mode": "standard", "device_mode": "cpu", "ocr_lang": "en", "prefer_tex_source": "false"},
        files=[
            ("files", ("a.pdf", b"%PDF-1.4", "application/pdf")),
            ("files", ("b.pdf", b"%PDF-1.4", "application/pdf")),
        ],
    )
    assert response.status_code == 200
    batch_id = response.json()["batch_id"]

    status = {}
    for _ in range(20):
        status = client.get(f"/api/process/batch/{batch_id}").json()
        if status["status"] in {"ok", "partial", "error"}:
            break
        time.sleep(0.02)

    assert status["total_documents"] == 2
    assert {doc["status"] for doc in status["documents"]} <= {"ok", "partial"}
    assert all(doc["document_id"] for doc in status["documents"])
    assert client.get(f"/api/process/batch/{batch_id}/results").status_code == 200
    assert client.get(f"/api/process/batch/{batch_id}/metrics").status_code == 200


def test_corpus_create_namespaces_graph_search_and_metrics(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "results_dir", tmp_path)
    doc_a = _doc_copy("doc_a", "a.pdf")
    doc_b = _doc_copy("doc_b", "b.pdf")
    save_graph_ready_document(doc_a, tmp_path / "doc_a.graph_ready.json")
    save_graph_ready_document(doc_b, tmp_path / "doc_b.graph_ready.json")

    corpus = create_corpus(["doc_a", "doc_b"], name="Demo corpus", corpus_id="corpus_test")
    graph = load_corpus_graph(corpus["corpus_id"])
    metrics = load_corpus_metrics(corpus["corpus_id"])
    search = corpus_variable_search(corpus["corpus_id"], "lambda")

    assert all("::" in node["id"] or node["type"] == "corpus" for node in graph["nodes"])
    assert len({node["id"] for node in graph["nodes"]}) == len(graph["nodes"])
    assert any(edge["type"] == "same_variable_label" for edge in graph["edges"])
    assert metrics["total_documents"] == 2
    assert search["documents_count"] == 2
    assert len(search["results_by_document"]) == 2


def test_corpus_create_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "results_dir", tmp_path)
    doc = _doc_copy("doc_endpoint", "endpoint.pdf")
    save_graph_ready_document(doc, tmp_path / "doc_endpoint.graph_ready.json")

    response = TestClient(app).post("/api/corpus/create", json={"document_ids": ["doc_endpoint"], "name": "Endpoint corpus"})

    assert response.status_code == 200
    corpus_id = response.json()["corpus_id"]
    assert TestClient(app).get(f"/api/corpus/{corpus_id}/metrics").status_code == 200


def test_random_arxiv_process_falls_back_when_russian_pool_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "results_dir", tmp_path)

    calls = []

    def fake_fetch_random(count, category, russian_only=False):
        calls.append((count, category, russian_only))
        if russian_only:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="no russian arxiv candidates")
        return ["2605.00001"]

    def fake_run_batch_job(**_kwargs):
        return None

    def fake_prepare_input_file(_file, arxiv_id, *, tex_source_only=False):
        path = tmp_path / f"{arxiv_id}.pdf"
        path.write_bytes(b"%PDF-1.4\n")
        assert tex_source_only is True
        return path, f"{arxiv_id}.pdf", ".pdf"

    monkeypatch.setattr("backend.app.main._fetch_random_arxiv_ids", fake_fetch_random)
    monkeypatch.setattr("backend.app.main._prepare_input_file", fake_prepare_input_file)
    monkeypatch.setattr("backend.app.main._run_batch_job", fake_run_batch_job)

    response = TestClient(app).post(
        "/api/arxiv/random-process",
        json={"count": 1, "category": "all", "device_mode": "cpu", "ocr_lang": "auto", "russian_only": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["arxiv_ids"] == ["2605.00001"]
    assert payload["warnings"]
    assert calls == [(1, "all", True), (1, "all", False)]


def test_tex_source_only_arxiv_prepare_skips_pdf_download(monkeypatch):
    def fail_pdf_download(_arxiv_id):
        raise AssertionError("PDF download must not run for TeX-source-only arXiv processing")

    monkeypatch.setattr("backend.app.main._download_arxiv_pdf", fail_pdf_download)

    path, filename, suffix = _prepare_input_file(None, "2605.02988v1", tex_source_only=True)

    try:
        assert suffix == ".pdf"
        assert filename == "2605.02988v1_source.pdf"
        assert path.read_bytes().startswith(b"%PDF-1.4")
    finally:
        path.unlink(missing_ok=True)


def test_llm_refinement_disabled_does_not_touch_formula(monkeypatch):
    monkeypatch.delenv("FG_ENABLE_LLM_REFINEMENT", raising=False)
    monkeypatch.setenv("FG_LLM_PROVIDER", "disabled")
    result = ProcessingResult(
        document_id="doc_llm",
        filename="x.pdf",
        created_at=datetime(2026, 5, 23, 12, 0, 0),
        status="ok",
        formulas=[FormulaBlock(id="f1", page_number=1, latex="x", kind="inline", confidence=0.1)],
    )

    step = apply_formula_refinement(result)

    assert step["status"] == "disabled"
    assert result.formulas[0].llm_evidence is None


def test_llm_mock_provider_returns_valid_schema(monkeypatch):
    monkeypatch.setenv("FG_ENABLE_LLM_REFINEMENT", "true")
    monkeypatch.setenv("FG_LLM_PROVIDER", "mock")
    result = ProcessingResult(
        document_id="doc_llm_mock",
        filename="x.pdf",
        created_at=datetime(2026, 5, 23, 12, 0, 0),
        status="ok",
        formulas=[FormulaBlock(id="f1", page_number=1, latex="x", kind="inline", confidence=0.1)],
    )

    step = apply_formula_refinement(result)

    assert step["status"] == "ok"
    assert result.formulas[0].llm_provider == "mock"
    assert FormulaVerificationResult.model_validate(result.formulas[0].llm_evidence)
    assert ContextRefinementResult(formula_id="f1").context_quality == "weak"


def test_llm_refinement_sends_nearby_text(monkeypatch):
    monkeypatch.setenv("FG_ENABLE_LLM_REFINEMENT", "true")
    monkeypatch.setenv("FG_LLM_PROVIDER", "mock")
    result = ProcessingResult(
        document_id="doc_llm_context",
        filename="x.pdf",
        created_at=datetime(2026, 5, 23, 12, 0, 0),
        status="ok",
        text_with_tokens=[
            TextBlock(
                id="tb1",
                page_number=1,
                text="where x denotes the coordinate [FORMULA_001] and y is the response",
            )
        ],
        formulas=[
            FormulaBlock(
                id="f1",
                page_number=1,
                latex="x",
                kind="inline",
                token="[FORMULA_001]",
                confidence=0.1,
            )
        ],
    )

    apply_formula_refinement(result)

    assert "where x denotes" in result.formulas[0].llm_evidence["input"]["nearby_text"]


def test_unavailable_provider_and_batch_skip_fail_open(monkeypatch):
    monkeypatch.setenv("FG_ENABLE_LLM_REFINEMENT", "true")
    monkeypatch.setenv("FG_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("FG_LLM_BASE_URL", "http://127.0.0.1:9")
    result = ProcessingResult(
        document_id="doc_llm_unavailable",
        filename="x.pdf",
        created_at=datetime(2026, 5, 23, 12, 0, 0),
        status="ok",
        formulas=[FormulaBlock(id="f1", page_number=1, latex="x", kind="inline", confidence=0.1)],
    )

    unavailable = apply_formula_refinement(result)
    assert unavailable["status"] == "skipped"
    assert result.status == "ok"

    monkeypatch.setenv("FG_LLM_PROVIDER", "mock")
    monkeypatch.setenv("FG_LLM_SKIP_IN_BATCH", "true")
    skipped = apply_formula_refinement(result, is_batch=True)
    assert skipped["status"] == "skipped"
    assert skipped["diagnostic"]["reason"] == "batch mode"


def test_ollama_error_payload_becomes_failed_evidence():
    response = _parse_formula_response(
        '{"status":"error","corrected_latex":null,"confidence":0,"reason":"cannot verify"}',
        request=FormulaVerificationRequest(
            formula_id="f1",
            latex_candidate="x",
        ),
        provider="ollama",
        model="qwen2.5vl:7b",
    )

    assert response.status == "failed"
    assert response.corrected_latex == "x"
    assert response.raw_status == "error"
    assert "provider_status=error" in response.warnings


def test_manual_qwen_suggest_works_when_auto_refinement_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "results_dir", tmp_path)
    monkeypatch.setenv("FG_ENABLE_LLM_REFINEMENT", "false")
    monkeypatch.setenv("FG_LLM_PROVIDER", "mock")
    result = ProcessingResult(
        document_id="doc_manual_qwen",
        filename="x.pdf",
        created_at=datetime(2026, 5, 23, 12, 0, 0),
        status="partial",
        formulas=[
            FormulaBlock(
                id="f1",
                page_number=1,
                latex="x",
                kind="inline",
                confidence=0.2,
                quality_flags=["formula_ocr_kept_fallback"],
            )
        ],
    )
    result.save_json(tmp_path / "doc_manual_qwen.json")

    response = TestClient(app).post("/api/results/doc_manual_qwen/formulas/f1/qwen/suggest")

    assert response.status_code == 200
    payload = response.json()
    assert payload["formula"]["llm_provider"] == "mock"
    assert payload["formula"]["llm_evidence"]["manual"] is True


def test_health_endpoint_exposes_llm_status(monkeypatch):
    monkeypatch.setenv("FG_LLM_PROVIDER", "disabled")
    payload = TestClient(app).get("/api/health").json()

    assert payload["llm"]["provider"] == "disabled"
    assert payload["llm"]["reason"] == "disabled"
    assert get_llm_status()["reason"] == "disabled"


def test_frontend_static_contracts():
    html = open("frontend/index.html", encoding="utf-8").read()
    js = open("frontend/assets/app.js", encoding="utf-8").read()

    assert "ПМИ" not in html + js
    assert "ТЗ" not in html + js
    assert "3.1.1" not in html + js
    assert '<select id="ocrMode"' not in html
    assert 'value="auto" selected>auto' in html
    assert "gpu -> cpu fallback" not in html
    assert "processDetailRow" in js
    assert "collectTextForDisplay" in js
    assert "corpus_graph_view" in js
    assert "Дополнительная проверка" in js
