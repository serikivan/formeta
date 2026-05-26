from __future__ import annotations

import shutil
import tempfile
import threading
import time
import uuid
import json
import os
import random
import re
import ssl
import subprocess
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.formula_graph.config import ensure_directories, resolve_device, settings
from backend.formula_graph.export.corpus_export import (
    corpus_variable_search,
    create_corpus,
    load_corpus,
    load_corpus_graph,
    load_corpus_metagraph,
    load_corpus_metrics,
    load_corpus_visualization,
)
from backend.formula_graph.export.graph_ready_export import (
    build_graph_ready_document,
    load_graph_ready_document,
    save_graph_ready_document,
    search_variable_in_graph_ready,
)
from backend.formula_graph.export.metagraph_metrics import (
    aggregate_metagraph_metrics,
    compute_metagraph_metrics,
    list_analytics_documents,
)
from backend.formula_graph.export.structured_document import build_structured_document, save_structured_document
from backend.formula_graph.graph.semantic_metagraph import build_semantic_graph_artifacts
from backend.formula_graph.graph.graph_ready_metagraph import build_metagraph_from_graph_ready
from backend.formula_graph.graph.visualization_export import VISUALIZATION_MODES, export_visualization_payload
from backend.formula_graph.graph.visualization_projection import PROJECTION_MODES, build_visualization_projection
from backend.formula_graph.llm import get_llm_status
from backend.formula_graph.llm.client import get_provider
from backend.formula_graph.llm.config import get_llm_config
from backend.formula_graph.llm.formula_verifier import _nearby_text_for_formula, formula_allows_manual_refinement
from backend.formula_graph.llm.schemas import FormulaVerificationRequest
from backend.formula_graph.models import ProcessingResult
from backend.formula_graph.ocr.experimental import experimental_backend_statuses
from backend.formula_graph.ingestion.loaders import build_document_id
from backend.formula_graph.ingestion.arxiv_source import download_arxiv_url, normalize_arxiv_id
from backend.formula_graph.pipeline import process_document

app = FastAPI(title="Formula Graph OCR API", version="0.1.0")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = PROJECT_ROOT / "frontend"

PUBLIC_OCR_MODES = {"standard"}
LEGACY_OCR_MODES = {"auto", "text_layer", "paddle", "structure", "hybrid", "hybrid_tesseract", "tesseract", "marker", "tex_source"}
OCR_MODE_ALIASES = {
}


@dataclass
class ProcessingJob:
    job_id: str
    status: str = "queued"
    progress: float = 0.0
    stage: str = "Ожидание запуска"
    detail: str | None = None
    document_id: str | None = None
    filename: str | None = None
    result_status: str | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


_JOBS: dict[str, ProcessingJob] = {}
_JOBS_LOCK = threading.Lock()


@dataclass
class BatchDocumentStatus:
    document_id: str
    filename: str
    status: str = "queued"
    progress: float = 0.0
    current_stage: str = "queued"
    warnings: list[str] = field(default_factory=list)
    job_id: str | None = None
    result_status: str | None = None
    error: str | None = None


@dataclass
class BatchJob:
    batch_id: str
    status: str = "queued"
    total_documents: int = 0
    completed_documents: int = 0
    failed_documents: int = 0
    documents: list[BatchDocumentStatus] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class CorpusCreateRequest(BaseModel):
    document_ids: list[str] = Field(default_factory=list)
    batch_id: str | None = None
    name: str | None = None


class RandomArxivProcessRequest(BaseModel):
    count: int = Field(3, ge=1, le=20)
    category: str = "math"
    russian_only: bool = False
    device_mode: str = "auto"
    ocr_lang: str = "auto"
    max_pages: int = 20
    render_dpi: int = 220
    prefer_tex_source: bool = True


class FormulaCorrectionDecision(BaseModel):
    action: str = Field("apply", pattern="^(apply|keep_original)$")
    latex: str | None = None


_BATCH_JOBS: dict[str, BatchJob] = {}
_BATCH_LOCK = threading.Lock()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:4175",
        "http://localhost:4175",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    ensure_directories()


@app.get("/api/health")
def health() -> dict[str, object]:
    paddle_cuda = False
    cuda_devices = 0
    try:
        import paddle

        paddle_cuda = bool(paddle.device.is_compiled_with_cuda())
        cuda_devices = int(paddle.device.cuda.device_count()) if paddle_cuda else 0
    except Exception:
        pass
    return {
        "status": "ok",
        "data_dir": str(settings.data_dir),
        "paddle_enabled": settings.enable_paddle,
        "configured_device": settings.device,
        "resolved_device": resolve_device(),
        "paddle_compiled_with_cuda": paddle_cuda,
        "cuda_device_count": cuda_devices,
        "text_ocr_backend": "paddle_or_tesseract",
        "got_ocr_fallback_enabled": False,
        "formula_ocr_backend": settings.formula_ocr_backend,
        "vlm_postprocess_enabled": settings.enable_vlm_postprocess,
        "vlm_postprocess_backend": settings.vlm_postprocess_backend,
        "public_ocr_modes": sorted(PUBLIC_OCR_MODES),
        "experimental_backends": [status.__dict__ for status in experimental_backend_statuses()],
        "llm": get_llm_status(),
    }


@app.post("/api/process")
async def process_upload(
    file: UploadFile | None = File(None),
    ocr_mode: str = Form("auto"),
    device_mode: str = Form("gpu"),
    ocr_lang: str = Form("auto"),
    max_pages: int = Form(0),
    render_dpi: int = Form(300),
    arxiv_id: str = Form(""),
    prefer_tex_source: bool = Form(True),
):
    if ocr_mode not in PUBLIC_OCR_MODES | LEGACY_OCR_MODES:
        raise HTTPException(
            status_code=400,
            detail="ocr_mode должен быть standard",
        )
    if device_mode not in {"auto", "cpu", "gpu"}:
        raise HTTPException(status_code=400, detail="device_mode должен быть auto, cpu или gpu")
    if ocr_lang not in {"auto", "en", "ru"}:
        raise HTTPException(status_code=400, detail="ocr_lang должен быть auto, en или ru")
    tmp_path, filename, suffix = _prepare_input_file(file, arxiv_id, tex_source_only=ocr_mode == "tex_source")
    if suffix not in {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}:
        raise HTTPException(status_code=400, detail="Неподдерживаемый тип файла")
    try:
        result = process_document(
            tmp_path,
            filename,
            ocr_mode=OCR_MODE_ALIASES.get(ocr_mode, ocr_mode),
            device_mode=device_mode,
            ocr_lang=ocr_lang,
            max_pages=0 if max_pages <= 0 else max(1, min(max_pages, 100)),
            render_dpi=max(120, min(render_dpi, 600)),
            arxiv_id=arxiv_id.strip() or None,
            prefer_tex_source=prefer_tex_source,
        )
        return result.model_dump()
    finally:
        tmp_path.unlink(missing_ok=True)


@app.post("/api/process/submit")
async def submit_processing_job(
    file: UploadFile | None = File(None),
    ocr_mode: str = Form("auto"),
    device_mode: str = Form("gpu"),
    ocr_lang: str = Form("auto"),
    max_pages: int = Form(0),
    render_dpi: int = Form(300),
    arxiv_id: str = Form(""),
    prefer_tex_source: bool = Form(True),
):
    if ocr_mode not in PUBLIC_OCR_MODES | LEGACY_OCR_MODES:
        raise HTTPException(status_code=400, detail="ocr_mode должен быть standard")
    if device_mode not in {"auto", "cpu", "gpu"}:
        raise HTTPException(status_code=400, detail="device_mode должен быть auto, cpu или gpu")
    if ocr_lang not in {"auto", "en", "ru"}:
        raise HTTPException(status_code=400, detail="ocr_lang должен быть auto, en или ru")
    tmp_path, filename, suffix = _prepare_input_file(file, arxiv_id, tex_source_only=ocr_mode == "tex_source")
    if suffix not in {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}:
        raise HTTPException(status_code=400, detail="Неподдерживаемый тип файла")

    job = ProcessingJob(job_id=uuid.uuid4().hex, filename=filename)
    with _JOBS_LOCK:
        _JOBS[job.job_id] = job

    thread = threading.Thread(
        target=_run_processing_job,
        kwargs={
            "job_id": job.job_id,
            "tmp_path": tmp_path,
            "filename": filename,
            "ocr_mode": OCR_MODE_ALIASES.get(ocr_mode, ocr_mode),
            "device_mode": device_mode,
            "ocr_lang": ocr_lang,
            "max_pages": 0 if max_pages <= 0 else max(1, min(max_pages, 100)),
            "render_dpi": max(120, min(render_dpi, 600)),
            "arxiv_id": arxiv_id.strip() or None,
            "prefer_tex_source": prefer_tex_source,
        },
        daemon=True,
    )
    thread.start()
    return {"job_id": job.job_id, "status": job.status}


@app.post("/api/process/batch/submit")
async def submit_batch_processing_job(
    files: list[UploadFile] | None = File(None),
    ocr_mode: str = Form("standard"),
    device_mode: str = Form("auto"),
    ocr_lang: str = Form("auto"),
    max_pages: int = Form(0),
    render_dpi: int = Form(300),
    arxiv_id: str = Form(""),
    arxiv_ids: str = Form(""),
    prefer_tex_source: bool = Form(True),
):
    files = files or []
    parsed_arxiv_ids = _split_arxiv_ids(arxiv_ids)
    if not files and not parsed_arxiv_ids:
        raise HTTPException(status_code=400, detail="Нужен хотя бы один файл или arXiv ID")
    if ocr_mode not in PUBLIC_OCR_MODES | LEGACY_OCR_MODES:
        raise HTTPException(status_code=400, detail="ocr_mode должен быть standard")
    if device_mode not in {"auto", "cpu", "gpu"}:
        raise HTTPException(status_code=400, detail="device_mode должен быть auto, cpu или gpu")
    if ocr_lang not in {"auto", "en", "ru"}:
        raise HTTPException(status_code=400, detail="ocr_lang должен быть auto, en или ru")

    tmp_files: list[tuple[Path, str, str | None]] = []
    documents: list[BatchDocumentStatus] = []
    for file in files:
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}:
            raise HTTPException(status_code=400, detail=f"Неподдерживаемый тип файла: {file.filename}")
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = Path(tmp.name)
        filename = file.filename or f"document{suffix}"
        tmp_files.append((tmp_path, filename, arxiv_id.strip() or None))
        document_id = build_document_id(filename)
        documents.append(BatchDocumentStatus(document_id=document_id, filename=filename))

    for item in parsed_arxiv_ids:
        tmp_path, filename, _suffix = _prepare_input_file(None, item, tex_source_only=ocr_mode == "tex_source")
        tmp_files.append((tmp_path, filename, item))
        document_id = build_document_id(filename)
        documents.append(BatchDocumentStatus(document_id=document_id, filename=filename))

    batch = BatchJob(batch_id=f"batch_{uuid.uuid4().hex[:12]}", total_documents=len(documents), documents=documents)
    with _BATCH_LOCK:
        _BATCH_JOBS[batch.batch_id] = batch
    _write_batch_status(batch)

    thread = threading.Thread(
        target=_run_batch_job,
        kwargs={
            "batch_id": batch.batch_id,
            "tmp_files": tmp_files,
            "ocr_mode": OCR_MODE_ALIASES.get(ocr_mode, ocr_mode),
            "device_mode": device_mode,
            "ocr_lang": ocr_lang,
            "max_pages": 0 if max_pages <= 0 else max(1, min(max_pages, 100)),
            "render_dpi": max(120, min(render_dpi, 600)),
            "arxiv_id": arxiv_id.strip() or None,
            "prefer_tex_source": prefer_tex_source,
        },
        daemon=True,
    )
    thread.start()
    return {"batch_id": batch.batch_id, "status": batch.status, "total_documents": batch.total_documents}


@app.post("/api/arxiv/random-process")
def submit_random_arxiv_processing_job(request: RandomArxivProcessRequest):
    if request.device_mode not in {"auto", "cpu", "gpu"}:
        raise HTTPException(status_code=400, detail="device_mode должен быть auto, cpu или gpu")
    if request.ocr_lang not in {"auto", "en", "ru"}:
        raise HTTPException(status_code=400, detail="ocr_lang должен быть auto, en или ru")

    warnings: list[str] = []
    arxiv_ids: list[str] = []
    local_fallback_ids: list[str] = []
    try:
        arxiv_ids = _fetch_random_arxiv_ids(request.count, request.category, russian_only=request.russian_only)
    except HTTPException as exc:
        if request.russian_only and exc.status_code == 404:
            warnings.append(
                "Не удалось быстро найти русскоязычные статьи arXiv для выбранных параметров; "
                "запущена обычная случайная подборка."
            )
            arxiv_ids = _fetch_random_arxiv_ids(request.count, request.category, russian_only=False)
        else:
            local_fallback_ids = _random_local_arxiv_ids(request.count)
            warnings.append(
                "arXiv API или сетевой доступ недоступен; для случайной подборки использованы локально кэшированные PDF."
            )

    tmp_files: list[tuple[Path, str, str | None]] = []
    documents: list[BatchDocumentStatus] = []
    for item in (arxiv_ids or local_fallback_ids):
        tmp_path, filename, _suffix = _prepare_input_file(None, item, tex_source_only=request.prefer_tex_source)
        tmp_files.append((tmp_path, filename, normalize_arxiv_id(item)))
        document_id = build_document_id(filename)
        documents.append(BatchDocumentStatus(document_id=document_id, filename=filename, warnings=list(warnings)))

    batch = BatchJob(batch_id=f"batch_{uuid.uuid4().hex[:12]}", total_documents=len(documents), documents=documents)
    with _BATCH_LOCK:
        _BATCH_JOBS[batch.batch_id] = batch
    _write_batch_status(batch)

    thread = threading.Thread(
        target=_run_batch_job,
        kwargs={
            "batch_id": batch.batch_id,
            "tmp_files": tmp_files,
            "ocr_mode": "tex_source" if request.prefer_tex_source else "standard",
            "device_mode": request.device_mode,
            "ocr_lang": request.ocr_lang,
            "max_pages": 0 if request.max_pages <= 0 else max(1, min(request.max_pages, 100)),
            "render_dpi": max(120, min(request.render_dpi, 600)),
            "arxiv_id": None,
            "prefer_tex_source": request.prefer_tex_source,
        },
        daemon=True,
    )
    thread.start()
    return {
        "batch_id": batch.batch_id,
        "status": batch.status,
        "total_documents": batch.total_documents,
        "arxiv_ids": arxiv_ids or local_fallback_ids,
        "warnings": warnings,
    }

@app.get("/api/process/batch/{batch_id}")
def get_batch_processing_job(batch_id: str):
    return _batch_payload(_get_batch(batch_id))


@app.get("/api/process/batch/{batch_id}/results")
def get_batch_results(batch_id: str):
    batch = _get_batch(batch_id)
    results = []
    for doc in batch.documents:
        path = settings.results_dir / f"{doc.document_id}.json"
        if path.exists():
            results.append(json.loads(path.read_text(encoding="utf-8")))
    return {"batch_id": batch.batch_id, "documents": [asdict(doc) for doc in batch.documents], "results": results}


@app.get("/api/process/batch/{batch_id}/metrics")
def get_batch_metrics(batch_id: str):
    batch = _get_batch(batch_id)
    documents = []
    totals = {"formula_count": 0, "variable_count": 0, "warnings_count": 0, "processing_time": 0.0}
    for doc in batch.documents:
        result_path = settings.results_dir / f"{doc.document_id}.json"
        result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else {}
        metrics = get_metagraph_metrics(doc.document_id) if result_path.exists() else {}
        basic = (metrics.get("basic") or {}) if isinstance(metrics, dict) else {}
        timing = result.get("timing") or {}
        item = {
            "document_id": doc.document_id,
            "filename": doc.filename,
            "status": doc.status,
            "formula_count": basic.get("formula_count", len(result.get("formulas", []))),
            "variable_count": basic.get("variable_count", 0),
            "warnings": doc.warnings or result.get("warnings", []),
            "processing_time": timing.get("total_time_sec", 0.0),
        }
        totals["formula_count"] += int(item["formula_count"] or 0)
        totals["variable_count"] += int(item["variable_count"] or 0)
        totals["warnings_count"] += len(item["warnings"])
        totals["processing_time"] += float(item["processing_time"] or 0.0)
        documents.append(item)
    status_distribution: dict[str, int] = {}
    for doc in batch.documents:
        status_distribution[doc.status] = status_distribution.get(doc.status, 0) + 1
    return {"batch_id": batch.batch_id, "status": batch.status, "documents": documents, "totals": totals, "status_distribution": status_distribution}


@app.get("/api/process/jobs/{job_id}")
def get_processing_job(job_id: str):
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Задача не найдена")
        return asdict(job)


@app.get("/api/results/{document_id}")
def get_result(document_id: str):
    path = settings.results_dir / f"{document_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Результат не найден")
    return FileResponse(path, media_type="application/json", filename=path.name)


@app.get("/api/results/{document_id}/structured")
def get_structured_result(document_id: str):
    path = settings.results_dir / f"{document_id}.structured.json"
    if path.exists():
        return FileResponse(path, media_type="application/json", filename=path.name)

    legacy_path = settings.results_dir / f"{document_id}.json"
    if not legacy_path.exists():
        raise HTTPException(status_code=404, detail="Структурированный результат не найден")
    legacy = ProcessingResult.model_validate_json(legacy_path.read_text(encoding="utf-8"))
    structured = build_structured_document(legacy)
    save_structured_document(structured, path)
    return FileResponse(path, media_type="application/json", filename=path.name)


@app.get("/api/results/{document_id}/graph-ready")
def get_graph_ready_result(document_id: str):
    graph_ready = _load_or_build_graph_ready(document_id)
    path = settings.results_dir / f"{graph_ready.document_id}.graph_ready.json"
    save_graph_ready_document(graph_ready, path)
    return FileResponse(path, media_type="application/json", filename=path.name)


@app.get("/api/results/{document_id}/variables/search")
def search_variable(document_id: str, q: str):
    graph_ready = _load_or_build_graph_ready(document_id)
    return search_variable_in_graph_ready(graph_ready, q)


@app.post("/api/results/{document_id}/formulas/{formula_id}/qwen/suggest")
def suggest_formula_correction(document_id: str, formula_id: str):
    result, path = _load_processing_result(document_id)
    formula = _find_formula(result, formula_id)
    if not formula_allows_manual_refinement(formula):
        return {
            "status": "skipped",
            "reason": "formula has no suspicious OCR quality flag",
            "formula": formula.model_dump(),
        }

    config = _manual_llm_config()
    if config.provider == "disabled":
        return {"status": "skipped", "reason": "manual llm provider disabled", "llm": asdict(config), "formula": formula.model_dump()}

    provider = get_provider(config)
    available, reason = provider.is_available()
    if not available:
        return {"status": "skipped", "reason": reason, "llm": get_llm_status(), "formula": formula.model_dump()}

    request = FormulaVerificationRequest(
        formula_id=formula.id,
        latex_candidate=formula.latex,
        nearby_text=_nearby_text_for_formula(result, formula),
        bbox=list(formula.bbox) if formula.bbox else None,
        source=formula.source,
        quality_flags=formula.quality_flags,
    )
    try:
        response = provider.verify_formula(request)
    except Exception as exc:
        response_payload = {
            "status": "failed",
            "reason": f"{type(exc).__name__}: {str(exc)[:240]}",
            "warnings": [str(exc)[:500]],
            "provider": config.provider,
            "model": config.model,
            "input": request.model_dump(),
        }
        formula.llm_evidence = response_payload
        formula.llm_provider = config.provider
        formula.llm_model = config.model
        formula.llm_confidence = 0.0
        result.save_json(path)
        return {"status": "failed", "evidence": response_payload, "formula": formula.model_dump()}

    formula.original_latex = formula.original_latex or formula.latex
    formula.selected_latex = formula.latex
    formula.llm_corrected_latex = response.corrected_latex or ""
    formula.llm_confidence = response.confidence
    formula.llm_provider = response.provider
    formula.llm_model = response.model
    formula.llm_evidence = response.model_dump()
    formula.llm_evidence["input"] = request.model_dump()
    formula.llm_evidence["applied"] = False
    formula.llm_evidence["manual"] = True
    formula.llm_evidence["decision"] = "pending"
    result.save_json(path)
    return {
        "status": response.status,
        "changed": response.changed,
        "corrected_latex": response.corrected_latex,
        "confidence": response.confidence,
        "reason": response.reason,
        "evidence": formula.llm_evidence,
        "formula": formula.model_dump(),
    }


@app.post("/api/results/{document_id}/formulas/{formula_id}/qwen/apply")
def apply_formula_correction(document_id: str, formula_id: str, decision: FormulaCorrectionDecision):
    result, path = _load_processing_result(document_id)
    formula = _find_formula(result, formula_id)
    formula.original_latex = formula.original_latex or formula.latex
    evidence = dict(formula.llm_evidence or {})
    if decision.action == "apply":
        selected = (decision.latex or formula.llm_corrected_latex or evidence.get("corrected_latex") or "").strip()
        if not selected:
            raise HTTPException(status_code=400, detail="Исправленный LaTeX недоступен")
        formula.selected_latex = selected
        formula.latex = selected
        evidence["applied"] = True
        evidence["decision"] = "applied"
    else:
        formula.selected_latex = formula.original_latex or formula.latex
        evidence["applied"] = False
        evidence["decision"] = "kept_original"
    formula.llm_evidence = evidence or None
    result.save_json(path)
    return {"status": "ok", "formula": formula.model_dump()}


@app.get("/api/results/{document_id}/metagraph")
def get_rich_metagraph(document_id: str):
    graph_ready = _load_or_build_graph_ready(document_id)
    metagraph_path = settings.results_dir / f"{document_id}.metagraph.json"
    graph_input, metagraph, variable_index = build_semantic_graph_artifacts(graph_ready)
    _write_json(settings.results_dir / f"{document_id}.graph_input.json", {"nodes": graph_input["nodes"], "edges": graph_input["edges"]})
    _write_json(metagraph_path, metagraph)
    _write_json(settings.results_dir / f"{document_id}.variable_index.json", variable_index)
    return metagraph


@app.get("/api/results/{document_id}/rich-metagraph")
def get_rich_metagraph_model(document_id: str):
    path = settings.results_dir / f"{document_id}.rich_metagraph.json"
    if path.exists():
        rich = json.loads(path.read_text(encoding="utf-8"))
        if not _rich_metagraph_requires_refresh(rich):
            return rich
    graph_ready = _load_or_build_graph_ready(document_id)
    rich = build_metagraph_from_graph_ready(graph_ready).to_dict()
    _write_json(path, rich)
    return rich


@app.get("/api/results/{document_id}/metrics/metagraph")
def get_metagraph_metrics(document_id: str):
    metrics_path = settings.results_dir / f"{document_id}.metagraph_metrics.json"
    if metrics_path.exists():
        cached_metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        if not _metrics_require_refresh(cached_metrics):
            return cached_metrics
    rich_path = settings.results_dir / f"{document_id}.rich_metagraph.json"
    if rich_path.exists():
        rich = json.loads(rich_path.read_text(encoding="utf-8"))
        if _rich_metagraph_requires_refresh(rich):
            graph_ready = _load_or_build_graph_ready(document_id)
            rich = build_metagraph_from_graph_ready(graph_ready).to_dict()
            _write_json(rich_path, rich)
    else:
        graph_ready = _load_or_build_graph_ready(document_id)
        rich = build_metagraph_from_graph_ready(graph_ready).to_dict()
        _write_json(rich_path, rich)
    result_path = settings.results_dir / f"{document_id}.json"
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else {}
    metrics = compute_metagraph_metrics(rich, result)
    _write_json(metrics_path, metrics)
    return metrics


@app.get("/api/analytics/metagraph")
def get_metagraph_analytics():
    return aggregate_metagraph_metrics(settings.results_dir)


@app.get("/api/analytics/documents")
def get_analytics_documents():
    return {"documents": list_analytics_documents(settings.results_dir)}


@app.post("/api/corpus/create")
def create_corpus_endpoint(request: CorpusCreateRequest):
    document_ids = list(request.document_ids or [])
    if request.batch_id:
        batch = _get_batch(request.batch_id)
        document_ids.extend(doc.document_id for doc in batch.documents if doc.status in {"ok", "partial"})
    document_ids = sorted({document_id for document_id in document_ids if document_id})
    if not document_ids:
        raise HTTPException(status_code=400, detail="Нужно выбрать хотя бы один обработанный документ")
    for document_id in document_ids:
        _load_or_build_graph_ready(document_id)
    try:
        return create_corpus(document_ids, name=request.name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/corpus/{corpus_id}")
def get_corpus_endpoint(corpus_id: str):
    try:
        return load_corpus(corpus_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Корпус не найден") from exc


@app.get("/api/corpus/{corpus_id}/graph")
def get_corpus_graph_endpoint(corpus_id: str):
    try:
        return load_corpus_graph(corpus_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Граф корпуса не найден") from exc


@app.get("/api/corpus/{corpus_id}/metagraph")
def get_corpus_metagraph_endpoint(corpus_id: str):
    try:
        return load_corpus_metagraph(corpus_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Метаграф корпуса не найден") from exc


@app.get("/api/corpus/{corpus_id}/visualization")
def get_corpus_visualization_endpoint(corpus_id: str):
    try:
        return load_corpus_visualization(corpus_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Визуализация корпуса не найдена") from exc


@app.get("/api/corpus/{corpus_id}/metrics")
def get_corpus_metrics_endpoint(corpus_id: str):
    try:
        return load_corpus_metrics(corpus_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Метрики корпуса не найдены") from exc


@app.get("/api/corpus/{corpus_id}/variables/search")
def search_corpus_variable_endpoint(corpus_id: str, q: str):
    try:
        return corpus_variable_search(corpus_id, q)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Корпус не найден") from exc


@app.get("/api/results/{document_id}/visualization")
def get_visualization(
    document_id: str,
    mode: str = "overview",
    limit: int = 420,
    variable: str | None = None,
    formula: str | None = None,
    depth: int = 2,
    include_technical: bool = False,
):
    if mode not in VISUALIZATION_MODES:
        raise HTTPException(status_code=400, detail=f"Режим должен быть одним из: {', '.join(sorted(VISUALIZATION_MODES))}")
    graph_ready = _load_or_build_graph_ready(document_id)
    graph_input, metagraph, variable_index = build_semantic_graph_artifacts(graph_ready)
    _write_json(settings.results_dir / f"{document_id}.graph_input.json", {"nodes": graph_input["nodes"], "edges": graph_input["edges"]})
    _write_json(settings.results_dir / f"{document_id}.metagraph.json", metagraph)
    _write_json(settings.results_dir / f"{document_id}.variable_index.json", variable_index)
    payload = export_visualization_payload(
        graph_ready,
        mode=mode,
        limit=max(40, min(limit, 900)),
        variable=variable,
        formula=formula,
        depth=depth,
        include_technical=include_technical,
    )
    if mode in {"overview", "metagraph_overview", "metagraph_planetary", "metagraph_planetary_overview"}:
        (settings.results_dir / f"{document_id}.visualization.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return payload


@app.get("/api/results/{document_id}/projection")
def get_visualization_projection(
    document_id: str,
    mode: str = "overview",
    formula: str | None = None,
    variable: str | None = None,
    limit: int = 80,
):
    if mode not in PROJECTION_MODES:
        raise HTTPException(status_code=400, detail=f"Режим должен быть одним из: {', '.join(sorted(PROJECTION_MODES))}")
    graph_ready = _load_or_build_graph_ready(document_id)
    return build_visualization_projection(
        graph_ready,
        mode=mode,
        formula=formula,
        variable=variable,
        limit=max(20, min(limit, 120)),
    )


@app.get("/api/results/{document_id}/variables/{variable}/neighborhood")
def get_variable_neighborhood(document_id: str, variable: str, depth: int = 2, limit: int = 420, include_technical: bool = False):
    graph_ready = _load_or_build_graph_ready(document_id)
    return export_visualization_payload(
        graph_ready,
        mode="variable_neighborhood",
        variable=variable,
        depth=depth,
        limit=max(40, min(limit, 900)),
        include_technical=include_technical,
    )


@app.get("/api/artifacts/{document_id}/{artifact_path:path}")
def get_artifact(document_id: str, artifact_path: str):
    base_dir = (settings.processed_dir / document_id).resolve()
    target = (base_dir / artifact_path).resolve()
    if base_dir not in target.parents and target != base_dir:
        raise HTTPException(status_code=400, detail="Некорректный путь артефакта")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Артефакт не найден")
    return FileResponse(target)


def _load_or_build_graph_ready(document_id: str):
    path = settings.results_dir / f"{document_id}.graph_ready.json"
    if path.exists():
        graph_ready = load_graph_ready_document(path)
        save_graph_ready_document(graph_ready, path)
        return graph_ready

    legacy_path = settings.results_dir / f"{document_id}.json"
    if not legacy_path.exists():
        raise HTTPException(status_code=404, detail="Результат для графа не найден")
    legacy = ProcessingResult.model_validate_json(legacy_path.read_text(encoding="utf-8"))
    structured_path = settings.results_dir / f"{document_id}.structured.json"
    if structured_path.exists():
        from backend.formula_graph.export.structured_document import load_structured_document

        structured = load_structured_document(structured_path)
    else:
        structured = build_structured_document(legacy)
        save_structured_document(structured, structured_path)
    graph_ready = build_graph_ready_document(legacy, structured)
    save_graph_ready_document(graph_ready, path)
    return graph_ready


def _rich_metagraph_requires_refresh(rich: dict[str, object]) -> bool:
    metavertices = rich.get("metavertices") if isinstance(rich, dict) else []
    for item in metavertices or []:
        if item.get("type") != "formula_metavertex":
            continue
        attrs = item.get("attributes") or {}
        return "semantic_type" not in attrs or "inner_expression_object" not in attrs
    return False


def _metrics_require_refresh(metrics: dict[str, object]) -> bool:
    if not isinstance(metrics, dict):
        return True
    formulas = metrics.get("formulas") or {}
    semantic = metrics.get("semantic") or {}
    metaedges = metrics.get("metaedges") or {}
    return (
        "formulas_with_metavertex_semantics_ratio" not in formulas
        or "document_context_metaedge_count" not in semantic
        or "semantic_metaedge_count_by_relation" not in metaedges
    )


def _load_processing_result(document_id: str) -> tuple[ProcessingResult, Path]:
    path = settings.results_dir / f"{document_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Результат не найден")
    return ProcessingResult.model_validate_json(path.read_text(encoding="utf-8")), path


def _find_formula(result: ProcessingResult, formula_id: str):
    for formula in result.formulas:
        if formula.id == formula_id:
            return formula
    raise HTTPException(status_code=404, detail="Формула не найдена")


def _manual_llm_config():
    config = get_llm_config()
    if config.provider == "disabled":
        provider = os.getenv("FG_LLM_MANUAL_PROVIDER", "ollama").strip().lower() or "ollama"
        return replace(config, enabled=True, provider=provider)
    return replace(config, enabled=True)


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _split_arxiv_ids(value: str) -> list[str]:
    return [
        item.strip()
        for item in value.replace(",", "\n").replace(";", "\n").split()
        if item.strip()
    ]


def _local_arxiv_pdf_map() -> dict[str, Path]:
    candidates: dict[str, Path] = {}
    for path in settings.input_dir.rglob("*.pdf"):
        arxiv_id = normalize_arxiv_id(path.stem) or normalize_arxiv_id(path.name)
        if arxiv_id and arxiv_id not in candidates:
            candidates[arxiv_id] = path
    return candidates


def _cache_arxiv_pdf(arxiv_id: str, payload: bytes) -> Path | None:
    normalized = normalize_arxiv_id(arxiv_id)
    if not normalized or not payload.startswith(b"%PDF"):
        return None
    cache_dir = settings.input_dir / "arxiv_stage3"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{normalized}.pdf"
    path.write_bytes(payload)
    return path


def _random_local_arxiv_ids(count: int) -> list[str]:
    candidates = sorted(_local_arxiv_pdf_map())
    if len(candidates) < count:
        raise HTTPException(status_code=502, detail="Недостаточно локально кэшированных PDF arXiv для случайной подборки")
    random.shuffle(candidates)
    return candidates[:count]


def _local_arxiv_pdf_path(arxiv_id: str) -> Path | None:
    normalized = normalize_arxiv_id(arxiv_id)
    if not normalized:
        return None
    return _local_arxiv_pdf_map().get(normalized)


def _fetch_random_arxiv_ids(count: int, category: str, russian_only: bool = False) -> list[str]:
    normalized_category = re.sub(r"[^A-Za-z0-9_.-]+", "", (category or "").strip().lower())
    category_query = {
        "math": "cat:math.*",
        "cs": "cat:cs.*",
        "physics": "cat:physics.*",
        "stat": "cat:stat.*",
        "all": "all",
    }.get(normalized_category, f"cat:{normalized_category}" if normalized_category else "all")
    if russian_only:
        return _fetch_random_russian_arxiv_ids(count, category_query)
    params = urllib.parse.urlencode({
        "search_query": category_query,
        "start": random.randint(0, 450),
        "max_results": max(20, min(80, count * 4)),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    })
    entries = _query_arxiv_entries(params)
    ids = _ids_from_arxiv_entries(entries)
    random.shuffle(ids)
    if len(ids) < count:
        raise HTTPException(status_code=502, detail="arXiv API вернул слишком мало статей")
    return ids[:count]


def _fetch_random_russian_arxiv_ids(count: int, category_query: str) -> list[str]:
    russian_query = 'all:ru OR all:russian OR all:россия OR all:русский OR all:россий'
    queries = [category_query, "all"] if category_query != "all" else ["all"]
    candidates: list[ET.Element] = []
    for query in queries:
        for start in random.sample(range(0, 700, 100), k=3):
            params = urllib.parse.urlencode({
                "search_query": query,
                "start": start,
                "max_results": 80,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            })
            candidates.extend(_query_arxiv_entries(params))
            ids = _ids_from_arxiv_entries([entry for entry in candidates if _entry_has_cyrillic(entry)])
            if len(ids) >= count:
                random.shuffle(ids)
                return ids[:count]
    params = urllib.parse.urlencode({
        "search_query": russian_query,
        "start": 0,
        "max_results": 80,
        "sortBy": "relevance",
        "sortOrder": "descending",
    })
    candidates.extend(_query_arxiv_entries(params))
    ids = _ids_from_arxiv_entries([entry for entry in candidates if _entry_has_cyrillic(entry)])
    random.shuffle(ids)
    if len(ids) < count:
        raise HTTPException(status_code=404, detail="Не удалось быстро найти столько русскоязычных статей arXiv. Уменьшите количество или выберите category=all.")
    return ids[:count]


def _query_arxiv_entries(encoded_params: str) -> list[ET.Element]:
    url = f"https://export.arxiv.org/api/query?{encoded_params}"
    try:
        payload = _download_url_with_ssl_fallback(url, timeout=10)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Не удалось запросить arXiv API: {' '.join(str(exc).split())[:240]}") from exc

    root = ET.fromstring(payload)
    return root.findall("atom:entry", {"atom": "http://www.w3.org/2005/Atom"})


def _ids_from_arxiv_entries(entries: list[ET.Element]) -> list[str]:
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    ids = []
    for entry in entries:
        raw_id = entry.findtext("atom:id", default="", namespaces=ns).rstrip("/")
        match = re.search(r"/abs/([^/]+)$", raw_id)
        if match:
            ids.append(match.group(1))
    return list(dict.fromkeys(ids))


def _entry_has_cyrillic(entry: ET.Element) -> bool:
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    text = " ".join(
        item
        for item in [
            entry.findtext("atom:title", default="", namespaces=ns),
            entry.findtext("atom:summary", default="", namespaces=ns),
            entry.findtext("atom:comment", default="", namespaces=ns),
        ]
        if item
    )
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return False
    cyrillic = sum(1 for char in letters if "А" <= char <= "я" or char in "Ёё")
    return cyrillic >= 12 and cyrillic / max(1, len(letters)) >= 0.12


def _download_url_with_ssl_fallback(url: str, timeout: int = 30) -> bytes:
    return download_arxiv_url(url, timeout=timeout)


def _download_url_with_curl_fallback(url: str, timeout: int = 30) -> bytes | None:
    if not url.startswith(("https://arxiv.org/", "https://export.arxiv.org/")):
        return None
    curl = shutil.which("curl")
    if not curl:
        return None
    try:
        completed = subprocess.run(
            [
                curl,
                "--fail",
                "--location",
                "--silent",
                "--show-error",
                "--max-time",
                str(max(5, int(timeout))),
                "--user-agent",
                "formula-graph-ocr/0.1",
                url,
            ],
            check=True,
            capture_output=True,
            timeout=max(10, int(timeout) + 5),
        )
    except Exception:
        return None
    return completed.stdout or None


def _prepare_input_file(file: UploadFile | None, arxiv_id: str | None, *, tex_source_only: bool = False) -> tuple[Path, str, str]:
    if file is not None:
        suffix = Path(file.filename or "").suffix.lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = Path(tmp.name)
        resolved_arxiv_id = normalize_arxiv_id(arxiv_id) or normalize_arxiv_id(file.filename or "")
        if suffix == ".pdf" and resolved_arxiv_id:
            _cache_arxiv_pdf(resolved_arxiv_id, tmp_path.read_bytes())
        return tmp_path, file.filename or f"document{suffix}", suffix
    safe_arxiv = (arxiv_id or "").strip()
    if not safe_arxiv:
        raise HTTPException(status_code=400, detail="Загрузите файл или укажите arXiv ID")
    suffix = ".pdf"
    filename_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", safe_arxiv)
    if tex_source_only:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(b"%PDF-1.4\n% arXiv TeX source placeholder\n%%EOF\n")
            return Path(tmp.name), f"{filename_id}_source.pdf", suffix
    try:
        pdf_bytes = _download_arxiv_pdf(safe_arxiv)
    except Exception as exc:
        cached_pdf = _local_arxiv_pdf_path(safe_arxiv)
        if cached_pdf is None:
            raise HTTPException(status_code=502, detail=f"Не удалось скачать PDF arXiv {safe_arxiv}: {' '.join(str(exc).split())[:240]}") from exc
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(cached_pdf.read_bytes())
            return Path(tmp.name), cached_pdf.name, suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(pdf_bytes)
        _cache_arxiv_pdf(safe_arxiv, pdf_bytes)
        return Path(tmp.name), f"{filename_id}.pdf", suffix


def _download_arxiv_pdf(arxiv_id: str) -> bytes:
    normalized = re.sub(r"^https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/", "", arxiv_id.strip(), flags=re.IGNORECASE)
    normalized = normalized.removesuffix(".pdf").strip("/")
    if not normalized:
        raise ValueError("empty arXiv id")
    payload = _download_url_with_ssl_fallback(f"https://arxiv.org/pdf/{normalized}.pdf", timeout=45)
    if not payload.startswith(b"%PDF"):
        raise ValueError("arXiv returned non-PDF payload")
    return payload


def _run_processing_job(
    job_id: str,
    tmp_path: Path,
    filename: str,
    ocr_mode: str,
    device_mode: str,
    ocr_lang: str,
    max_pages: int,
    render_dpi: int,
    arxiv_id: str | None,
    prefer_tex_source: bool,
) -> None:
    _update_job(job_id, status="running", progress=1.0, stage="Запуск обработки", detail=filename)
    try:
        result = process_document(
            tmp_path,
            filename,
            ocr_mode=ocr_mode,
            device_mode=device_mode,
            ocr_lang=ocr_lang,
            max_pages=max_pages,
            render_dpi=render_dpi,
            arxiv_id=arxiv_id,
            prefer_tex_source=prefer_tex_source,
            progress_callback=lambda percent, stage, detail: _update_job(
                job_id,
                status="running",
                progress=percent,
                stage=stage,
                detail=detail,
            ),
        )
        _update_job(
            job_id,
            status="completed" if result.status != "error" else "failed",
            progress=100.0,
            stage="Готово" if result.status != "error" else "Ошибка обработки",
            detail=result.result_path,
            document_id=result.document_id,
            result_status=result.status,
            error="\n".join(result.warnings) if result.status == "error" else None,
        )
    except Exception as exc:
        _update_job(
            job_id,
            status="failed",
            progress=100.0,
            stage="Ошибка обработки",
            error=" ".join(str(exc).split())[:1000],
        )
    finally:
        tmp_path.unlink(missing_ok=True)


def _run_batch_job(
    batch_id: str,
    tmp_files: list[tuple[Path, str, str | None]],
    ocr_mode: str,
    device_mode: str,
    ocr_lang: str,
    max_pages: int,
    render_dpi: int,
    arxiv_id: str | None,
    prefer_tex_source: bool,
) -> None:
    _update_batch(batch_id, status="running")
    try:
        for index, (tmp_path, filename, item_arxiv_id) in enumerate(tmp_files):
            with _BATCH_LOCK:
                batch = _BATCH_JOBS.get(batch_id)
                if batch is None:
                    return
                doc = batch.documents[index]
                doc.status = "running"
                doc.progress = 1.0
                doc.current_stage = "start"
                batch.updated_at = time.time()
                _refresh_batch_totals(batch)
                _write_batch_status(batch)
            try:
                result = process_document(
                    tmp_path,
                    filename,
                    ocr_mode=ocr_mode,
                    device_mode=device_mode,
                    ocr_lang=ocr_lang,
                    max_pages=max_pages,
                    render_dpi=render_dpi,
                    arxiv_id=item_arxiv_id or arxiv_id,
                    prefer_tex_source=prefer_tex_source,
                    is_batch=True,
                    progress_callback=lambda percent, stage, detail, doc_index=index: _update_batch_document_progress(
                        batch_id, doc_index, percent, stage, detail
                    ),
                )
                _update_batch_document_done(
                    batch_id,
                    index,
                    document_id=result.document_id,
                    status=result.status,
                    warnings=result.warnings,
                )
            except Exception as exc:
                _update_batch_document_failed(batch_id, index, " ".join(str(exc).split())[:1000])
            finally:
                tmp_path.unlink(missing_ok=True)
        _finish_batch(batch_id)
    finally:
        for tmp_path, _filename, _item_arxiv_id in tmp_files:
            tmp_path.unlink(missing_ok=True)


def _get_batch(batch_id: str) -> BatchJob:
    with _BATCH_LOCK:
        batch = _BATCH_JOBS.get(batch_id)
    if batch is None:
        path = _batch_status_path(batch_id)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Пакет не найден")
        payload = json.loads(path.read_text(encoding="utf-8"))
        batch = BatchJob(
            batch_id=payload["batch_id"],
            status=payload.get("status", "queued"),
            total_documents=payload.get("total_documents", 0),
            completed_documents=payload.get("completed_documents", 0),
            failed_documents=payload.get("failed_documents", 0),
            documents=[BatchDocumentStatus(**doc) for doc in payload.get("documents", [])],
            created_at=payload.get("created_at", time.time()),
            updated_at=payload.get("updated_at", time.time()),
        )
        with _BATCH_LOCK:
            _BATCH_JOBS[batch_id] = batch
    return batch


def _batch_payload(batch: BatchJob) -> dict[str, object]:
    payload = asdict(batch)
    payload["progress"] = round(
        sum(doc.progress for doc in batch.documents) / max(1, batch.total_documents),
        2,
    )
    return payload


def _update_batch(batch_id: str, **changes) -> None:
    with _BATCH_LOCK:
        batch = _BATCH_JOBS.get(batch_id)
        if batch is None:
            return
        for key, value in changes.items():
            setattr(batch, key, value)
        batch.updated_at = time.time()
        _refresh_batch_totals(batch)
        _write_batch_status(batch)


def _update_batch_document_progress(batch_id: str, index: int, percent: float, stage: str, detail: str | None) -> None:
    with _BATCH_LOCK:
        batch = _BATCH_JOBS.get(batch_id)
        if batch is None or index >= len(batch.documents):
            return
        doc = batch.documents[index]
        doc.status = "running"
        doc.progress = max(0.0, min(100.0, percent))
        doc.current_stage = stage
        if detail:
            doc.warnings = doc.warnings[-5:]
        batch.updated_at = time.time()
        _refresh_batch_totals(batch)
        _write_batch_status(batch)


def _update_batch_document_done(batch_id: str, index: int, document_id: str, status: str, warnings: list[str]) -> None:
    with _BATCH_LOCK:
        batch = _BATCH_JOBS.get(batch_id)
        if batch is None or index >= len(batch.documents):
            return
        doc = batch.documents[index]
        doc.document_id = document_id
        doc.status = "ok" if status == "ok" else "partial" if status == "partial" else "error"
        doc.result_status = status
        doc.progress = 100.0
        doc.current_stage = "done"
        doc.warnings = list(warnings or [])
        batch.updated_at = time.time()
        _refresh_batch_totals(batch)
        _write_batch_status(batch)


def _update_batch_document_failed(batch_id: str, index: int, error: str) -> None:
    with _BATCH_LOCK:
        batch = _BATCH_JOBS.get(batch_id)
        if batch is None or index >= len(batch.documents):
            return
        doc = batch.documents[index]
        doc.status = "error"
        doc.progress = 100.0
        doc.current_stage = "error"
        doc.error = error
        doc.warnings.append(error)
        batch.updated_at = time.time()
        _refresh_batch_totals(batch)
        _write_batch_status(batch)


def _finish_batch(batch_id: str) -> None:
    with _BATCH_LOCK:
        batch = _BATCH_JOBS.get(batch_id)
        if batch is None:
            return
        _refresh_batch_totals(batch)
        if batch.failed_documents == batch.total_documents:
            batch.status = "error"
        elif batch.failed_documents or any(doc.status == "partial" for doc in batch.documents):
            batch.status = "partial"
        else:
            batch.status = "ok"
        batch.updated_at = time.time()
        _write_batch_status(batch)


def _refresh_batch_totals(batch: BatchJob) -> None:
    batch.completed_documents = sum(1 for doc in batch.documents if doc.status in {"ok", "partial"})
    batch.failed_documents = sum(1 for doc in batch.documents if doc.status == "error")
    if any(doc.status == "running" for doc in batch.documents):
        batch.status = "running"


def _write_batch_status(batch: BatchJob) -> None:
    _write_json(_batch_status_path(batch.batch_id), _batch_payload(batch))


def _batch_status_path(batch_id: str) -> Path:
    return settings.results_dir / "batches" / f"{batch_id}.json"


def _update_job(job_id: str, **changes) -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        for key, value in changes.items():
            setattr(job, key, value)
        job.updated_at = time.time()


if (FRONTEND_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")


@app.get("/")
def frontend_index():
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend is not bundled")
    return FileResponse(index_path)


@app.get("/{path:path}")
def frontend_fallback(path: str):
    if path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API endpoint not found")
    target = (FRONTEND_DIR / path).resolve()
    frontend_root = FRONTEND_DIR.resolve()
    if target.is_file() and frontend_root in [target, *target.parents]:
        return FileResponse(target)
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend is not bundled")
    return FileResponse(index_path)
