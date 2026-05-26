from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.formula_graph.config import settings
from backend.formula_graph.export.graph_ready_export import save_graph_ready_document
from backend.formula_graph.models import ProcessingResult
from tests.test_graph_ready_export import _graph_ready


def test_variable_search_endpoint_exact_symbol(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "results_dir", tmp_path)
    doc = _graph_ready()
    save_graph_ready_document(doc, tmp_path / f"{doc.document_id}.graph_ready.json")

    client = TestClient(app)
    response = client.get(f"/api/results/{doc.document_id}/variables/search", params={"q": "lambda"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["normalized_query"] == "\\lambda"
    assert payload["matches_count"] == 1
    assert payload["matches"][0]["token"] == "[FORMULA_001]"
    assert payload["matches"][0]["formula_semantics"]["semantic_type"] == "formula_metavertex"


def test_variable_search_endpoint_empty_result(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "results_dir", tmp_path)
    doc = _graph_ready()
    save_graph_ready_document(doc, tmp_path / f"{doc.document_id}.graph_ready.json")

    client = TestClient(app)
    response = client.get(f"/api/results/{doc.document_id}/variables/search", params={"q": "z"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["matches_count"] == 0
    assert payload["variable"] is None


def test_visualization_endpoint_returns_formula_semantic_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "results_dir", tmp_path)
    doc = _graph_ready()
    save_graph_ready_document(doc, tmp_path / f"{doc.document_id}.graph_ready.json")

    client = TestClient(app)
    response = client.get(f"/api/results/{doc.document_id}/visualization", params={"mode": "formula_semantic"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "formula_semantic"
    assert payload["elements"]
    assert payload["stats"]["node_count"] > 0


def test_visualization_endpoint_rejects_unknown_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "results_dir", tmp_path)
    doc = _graph_ready()
    save_graph_ready_document(doc, tmp_path / f"{doc.document_id}.graph_ready.json")

    client = TestClient(app)
    response = client.get(f"/api/results/{doc.document_id}/visualization", params={"mode": "bad"})

    assert response.status_code == 400


def test_async_process_job_reports_real_progress(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "results_dir", tmp_path)

    def fake_process_document(*args, progress_callback=None, **kwargs):
        if progress_callback is not None:
            progress_callback(12, "Рендер страниц", "1/2")
            progress_callback(63, "OCR текста", "2/2")
            progress_callback(100, "Готово", "doc_async")
        return ProcessingResult(
            document_id="doc_async",
            filename="demo.pdf",
            created_at=datetime(2026, 5, 21, 12, 0, 0),
            status="ok",
            warnings=[],
        )

    monkeypatch.setattr("backend.app.main.process_document", fake_process_document)

    client = TestClient(app)
    submit = client.post(
        "/api/process/submit",
        data={
            "ocr_mode": "standard",
            "device_mode": "cpu",
            "ocr_lang": "en",
            "max_pages": 1,
            "render_dpi": 200,
            "prefer_tex_source": "false",
        },
        files={"file": ("demo.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert submit.status_code == 200
    job_id = submit.json()["job_id"]
    status = client.get(f"/api/process/jobs/{job_id}")

    assert status.status_code == 200
    payload = status.json()
    assert payload["status"] in {"running", "completed"}
    final = payload
    for _ in range(10):
        if final["status"] == "completed":
            break
        final = client.get(f"/api/process/jobs/{job_id}").json()
    assert final["status"] == "completed"
    assert final["document_id"] == "doc_async"
