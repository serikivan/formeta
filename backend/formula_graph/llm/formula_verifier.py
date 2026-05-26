from __future__ import annotations

import time

from backend.formula_graph.llm.client import get_provider
from backend.formula_graph.llm.config import get_llm_config
from backend.formula_graph.llm.schemas import FormulaVerificationRequest
from backend.formula_graph.models import ProcessingResult

SUSPICIOUS_FORMULA_FLAGS = {
    "formula_ocr_kept_fallback",
    "raw_ocr_weird_unicode",
    "raw_ocr_contains_prose",
    "raw_ocr_romanized_ocr_noise",
    "formula_ocr_failed",
    "contains_prose",
    "romanized_ocr_noise",
    "weird_unicode",
    "unbalanced_braces",
    "latex_missing",
}


def apply_formula_refinement(result: ProcessingResult, *, is_batch: bool = False) -> dict[str, object]:
    config = get_llm_config()
    step = {
        "stage": "llm_refinement",
        "status": "disabled",
        "description": "Дополнительная проверка формул и контекста",
        "count": 0,
        "source": "llm/vlm",
        "warnings": [],
        "duration_sec": 0.0,
        "diagnostic": {"provider": config.provider, "model": config.model, "demo_mock": config.demo_mock},
    }
    if not config.enabled or config.provider == "disabled":
        step["diagnostic"]["reason"] = "disabled"
        return step
    if is_batch and config.skip_in_batch:
        step["status"] = "skipped"
        step["diagnostic"]["reason"] = "batch mode"
        return step

    provider = get_provider(config)
    available, reason = provider.is_available()
    if not available:
        step["status"] = "skipped"
        step["warnings"] = [reason]
        step["diagnostic"]["reason"] = "provider unavailable"
        result.warnings.append(f"Дополнительная проверка формул пропущена: {reason}")
        return step

    started_at = time.perf_counter()
    processed = 0
    succeeded = 0
    failed = 0
    proposed_changes = 0
    applied_changes = 0
    outcomes: list[dict[str, object]] = []
    for formula in result.formulas:
        if processed >= config.max_formulas_per_doc:
            break
        if config.only_low_confidence and not _needs_refinement(formula):
            continue
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
            warning = f"{formula.id}: ошибка провайдера {type(exc).__name__}: {str(exc)[:180]}"
            result.warnings.append(f"Дополнительная проверка формул: {warning}")
            step["warnings"] = [*step.get("warnings", []), warning]
            formula.original_latex = formula.original_latex or formula.latex
            formula.selected_latex = formula.latex
            formula.llm_provider = config.provider
            formula.llm_model = config.model
            formula.llm_confidence = 0.0
            formula.llm_evidence = {
                "status": "failed",
                "reason": "provider exception",
                "warnings": [warning],
                "provider": config.provider,
                "model": config.model,
                "input": request.model_dump(),
            }
            processed += 1
            failed += 1
            outcomes.append({"formula_id": formula.id, "status": "failed", "confidence": 0.0, "reason": warning})
            continue
        processed += 1
        formula.original_latex = formula.original_latex or formula.latex
        formula.llm_corrected_latex = response.corrected_latex or None
        formula.llm_confidence = response.confidence
        formula.llm_provider = response.provider
        formula.llm_model = response.model
        formula.llm_evidence = response.model_dump()
        formula.llm_evidence["input"] = request.model_dump()
        formula.llm_evidence["applied"] = False
        if response.status == "ok" and response.changed and response.confidence >= config.min_confidence_to_apply:
            formula.selected_latex = response.corrected_latex
            formula.latex = response.corrected_latex
            formula.llm_evidence["applied"] = True
            applied_changes += 1
        else:
            formula.selected_latex = formula.latex
        if response.changed and response.corrected_latex and response.corrected_latex != formula.original_latex:
            proposed_changes += 1
        if response.status in {"ok", "uncertain"} and response.confidence > 0:
            succeeded += 1
        else:
            failed += 1
        if response.warnings:
            result.warnings.extend(f"Дополнительная проверка формул {formula.id}: {warning}" for warning in response.warnings)
        outcomes.append(
            {
                "formula_id": formula.id,
                "status": response.status,
                "confidence": response.confidence,
                "changed": response.changed,
                "applied": formula.llm_evidence["applied"],
                "reason": response.reason,
                "raw_status": response.raw_status,
                "nearby_text_chars": len(request.nearby_text or ""),
            }
        )

    if not processed:
        step["status"] = "skipped"
    elif failed and succeeded:
        step["status"] = "warning"
    elif failed and not succeeded:
        step["status"] = "warning"
    else:
        step["status"] = "ok"
    step["count"] = processed
    step["warnings"] = [*step.get("warnings", []), *[f"{item['formula_id']}: {item['status']} {item.get('reason') or ''}".strip() for item in outcomes if item.get("status") == "failed"]]
    step["diagnostic"]["reason"] = "processed" if processed else "no low-confidence items"
    step["diagnostic"]["succeeded"] = succeeded
    step["diagnostic"]["failed"] = failed
    step["diagnostic"]["proposed_changes"] = proposed_changes
    step["diagnostic"]["applied_changes"] = applied_changes
    step["diagnostic"]["outcomes"] = outcomes[: config.max_formulas_per_doc]
    step["duration_sec"] = round(time.perf_counter() - started_at, 4)
    return step


def formula_allows_manual_refinement(formula) -> bool:
    flags = {str(flag) for flag in getattr(formula, "quality_flags", []) or []}
    source = str(getattr(formula, "source", "") or "").lower()
    if source == "tex_source" or "from_tex_source" in flags:
        return False
    if flags & SUSPICIOUS_FORMULA_FLAGS:
        return True
    markers = ("raw_ocr", "ocr", "fallback", "weird", "unicode", "prose", "romanized", "noise", "failed")
    return any(any(marker in flag.lower() for marker in markers) for flag in flags)


def manual_refinement_step(result: ProcessingResult) -> dict[str, object]:
    candidates = [formula.id for formula in result.formulas if formula_allows_manual_refinement(formula)]
    return {
        "stage": "llm_refinement",
        "status": "skipped",
        "description": "Ручная проверка формулы через Qwen; не выполняется во время обработки документа.",
        "count": len(candidates),
        "source": "manual llm/vlm",
        "warnings": [],
        "duration_sec": 0.0,
        "diagnostic": {
            "reason": "manual_on_demand",
            "candidate_formula_ids": candidates[:25],
            "candidate_count": len(candidates),
            "auto_run": False,
        },
    }


def _needs_refinement(formula) -> bool:
    latex = str(formula.latex or "")
    confidence = formula.confidence if formula.confidence is not None else 1.0
    return (
        confidence < 0.7
        or bool(formula.quality_flags)
        or str(formula.source or "").lower() in {"ocr", "paddleocr", "tesseract"}
        or latex.count("{") != latex.count("}")
        or (formula.bbox is not None and len(latex.strip()) <= 2)
    )


def _nearby_text_for_formula(result: ProcessingResult, formula) -> str:
    token = str(formula.token or "")
    candidates: list[str] = []
    if token:
        for block in result.text_with_tokens or []:
            text = str(getattr(block, "text", "") or "")
            if token in text:
                candidates.append(text)
        for block in result.text_blocks or []:
            text = str(getattr(block, "text", "") or "")
            if formula.context_block_id and getattr(block, "id", None) == formula.context_block_id:
                candidates.append(text)
    if not candidates:
        same_page = [
            str(getattr(block, "text", "") or "")
            for block in (result.text_with_tokens or result.text_blocks or [])
            if getattr(block, "page_number", None) == formula.page_number
        ]
        candidates.extend(same_page[:3])
    text = " ".join(part for part in candidates if part).strip()
    return text[:1800]
