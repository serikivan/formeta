from __future__ import annotations

import json
import urllib.request
from typing import Any

from backend.formula_graph.llm.config import LLMRefinementConfig
from backend.formula_graph.llm.prompts import FORMULA_VERIFICATION_PROMPT
from backend.formula_graph.llm.schemas import FormulaVerificationRequest, FormulaVerificationResult


class OllamaProvider:
    def __init__(self, config: LLMRefinementConfig) -> None:
        self.config = config

    def is_available(self) -> tuple[bool, str]:
        try:
            with urllib.request.urlopen(self.config.base_url.rstrip("/") + "/api/tags", timeout=min(3, self.config.timeout_sec)) as response:
                return (200 <= response.status < 500), "ok"
        except Exception as exc:
            return False, f"unavailable: {type(exc).__name__}"

    def verify_formula(self, request: FormulaVerificationRequest) -> FormulaVerificationResult:
        payload = {
            "model": self.config.model,
            "stream": False,
            "format": "json",
            "prompt": f"{FORMULA_VERIFICATION_PROMPT}\n\nInput JSON:\n{request.model_dump_json()}",
        }
        try:
            raw = self._post("/api/generate", payload)
            return _parse_formula_response(
                raw.get("response") or "{}",
                request=request,
                provider="ollama",
                model=self.config.model,
            )
        except Exception as exc:
            return FormulaVerificationResult(
                status="failed",
                corrected_latex=request.latex_candidate,
                confidence=0.0,
                reason=f"provider error: {type(exc).__name__}",
                warnings=[str(exc)[:400]],
                provider="ollama",
                model=self.config.model,
            )

    def _post(self, path: str, payload: dict) -> dict:
        request = urllib.request.Request(
            self.config.base_url.rstrip("/") + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.config.timeout_sec) as response:
            return json.loads(response.read().decode("utf-8"))


def _parse_formula_response(
    content: str,
    *,
    request: FormulaVerificationRequest,
    provider: str,
    model: str,
) -> FormulaVerificationResult:
    raw_content = str(content or "").strip()
    try:
        payload = json.loads(raw_content or "{}")
    except json.JSONDecodeError as exc:
        return FormulaVerificationResult(
            status="failed",
            corrected_latex=request.latex_candidate,
            confidence=0.0,
            reason="provider returned invalid JSON",
            warnings=[f"invalid_json: {exc.msg}"],
            provider=provider,
            model=model,
            raw_response=raw_content[:1200],
        )
    if not isinstance(payload, dict):
        return FormulaVerificationResult(
            status="failed",
            corrected_latex=request.latex_candidate,
            confidence=0.0,
            reason="provider returned non-object JSON",
            warnings=["non_object_json"],
            provider=provider,
            model=model,
            raw_response=raw_content[:1200],
        )
    normalized = _normalize_formula_payload(payload, request.latex_candidate, provider, model)
    return FormulaVerificationResult.model_validate(normalized)


def _normalize_formula_payload(payload: dict[str, Any], fallback_latex: str, provider: str, model: str) -> dict[str, Any]:
    status = str(payload.get("status") or "").strip().lower()
    allowed = {"ok", "uncertain", "failed", "skipped"}
    raw_status = status or None
    if status not in allowed:
        status = "failed" if status in {"error", "fail", "failure"} else "uncertain"
    corrected = payload.get("corrected_latex")
    if corrected is None:
        corrected = payload.get("latex") or payload.get("selected_latex") or fallback_latex
    if not isinstance(corrected, str):
        corrected = str(corrected)
    confidence = payload.get("confidence", 0.0)
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = 0.0
    warnings = payload.get("warnings") or []
    if isinstance(warnings, str):
        warnings = [warnings]
    if raw_status and raw_status not in allowed:
        warnings = [*warnings, f"provider_status={raw_status}"]
    return {
        "status": status,
        "corrected_latex": corrected,
        "changed": bool(payload.get("changed", corrected != fallback_latex)),
        "confidence": confidence,
        "reason": str(payload.get("reason") or payload.get("message") or ""),
        "warnings": [str(item) for item in warnings],
        "provider": str(payload.get("provider") or provider),
        "model": str(payload.get("model") or model),
        "raw_response": json.dumps(payload, ensure_ascii=False)[:1200],
        "raw_status": raw_status,
    }
