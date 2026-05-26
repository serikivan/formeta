from __future__ import annotations

from typing import Any

from backend.formula_graph.postprocessing.latex_cleaner import validate_latex_sanity


def assess_formula_recognition_quality(record: dict[str, Any]) -> dict[str, Any]:
    sanity = validate_latex_sanity(record.get("normalized_latex") or record.get("cleaned_latex") or record.get("raw_latex") or "")
    confidence = float(record.get("recognition_confidence") or 0.0)
    warnings = list(record.get("warnings") or []) + list(sanity.get("warnings") or [])
    score = round(max(0.0, min(1.0, confidence * 0.7 + float(sanity.get("score") or 0.0) * 0.3 - 0.05 * len(warnings))), 2)
    return {"quality": "ok" if score >= 0.7 else "partial" if score >= 0.35 else "failed", "score": score, "warnings": warnings}
