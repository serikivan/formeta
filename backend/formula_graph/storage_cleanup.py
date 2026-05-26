from __future__ import annotations

import shutil
import time
from pathlib import Path

from backend.formula_graph.config import settings


RESULT_SUFFIXES = (
    ".structured.json",
    ".graph_ready.json",
    ".metagraph_validation.json",
    ".formulas.json",
    ".formula_interpretations.json",
    ".rich_metagraph.json",
    ".metagraph_metrics.json",
    ".visualization.json",
    ".graph_input.json",
    ".metagraph.json",
    ".variable_index.json",
    ".graph_view.html",
    ".formula_graph_view.html",
    ".metagraph_view.html",
    ".json",
)


def cleanup_after_processing(current_document_id: str, stored_input_path: Path | None = None) -> dict[str, int]:
    counts = {"input_files": 0, "result_files": 0, "processed_dirs": 0, "source_dirs": 0}
    if settings.storage_delete_input_after_processing and stored_input_path is not None:
        counts["input_files"] += _unlink(stored_input_path)
    counts.update(_cleanup_old_documents(current_document_id, counts))
    return counts


def _cleanup_old_documents(current_document_id: str, counts: dict[str, int]) -> dict[str, int]:
    max_documents = max(0, int(settings.storage_max_documents or 0))
    retention_days = max(0, int(settings.storage_retention_days or 0))
    if max_documents == 0 and retention_days == 0:
        return counts

    now = time.time()
    cutoff = now - retention_days * 86400 if retention_days else None
    documents = _result_documents()
    delete_ids: set[str] = set()
    if cutoff is not None:
        delete_ids.update(doc_id for doc_id, mtime in documents if doc_id != current_document_id and mtime < cutoff)
    if max_documents and len(documents) > max_documents:
        overflow = [doc_id for doc_id, _mtime in documents[max_documents:] if doc_id != current_document_id]
        delete_ids.update(overflow)

    for document_id in delete_ids:
        counts["result_files"] += _delete_result_files(document_id)
        counts["processed_dirs"] += _rmtree(settings.processed_dir / document_id)
        counts["source_dirs"] += _rmtree(settings.sources_dir / document_id)
        counts["input_files"] += _delete_input_files(document_id)
    return counts


def _result_documents() -> list[tuple[str, float]]:
    by_id: dict[str, float] = {}
    if not settings.results_dir.exists():
        return []
    for path in settings.results_dir.iterdir():
        if not path.is_file():
            continue
        doc_id = _document_id_from_result(path.name)
        if not doc_id:
            continue
        by_id[doc_id] = max(by_id.get(doc_id, 0.0), path.stat().st_mtime)
    return sorted(by_id.items(), key=lambda item: item[1], reverse=True)


def _document_id_from_result(name: str) -> str | None:
    for suffix in RESULT_SUFFIXES:
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[: -len(suffix)]
    return None


def _delete_result_files(document_id: str) -> int:
    count = 0
    for suffix in RESULT_SUFFIXES:
        count += _unlink(settings.results_dir / f"{document_id}{suffix}")
    return count


def _delete_input_files(document_id: str) -> int:
    count = 0
    if not settings.input_dir.exists():
        return 0
    for path in settings.input_dir.glob(f"{document_id}.*"):
        if path.is_file():
            count += _unlink(path)
    return count


def _unlink(path: Path) -> int:
    try:
        if path.exists() and path.is_file():
            path.unlink()
            return 1
    except OSError:
        return 0
    return 0


def _rmtree(path: Path) -> int:
    try:
        if path.exists() and path.is_dir():
            shutil.rmtree(path)
            return 1
    except OSError:
        return 0
    return 0
