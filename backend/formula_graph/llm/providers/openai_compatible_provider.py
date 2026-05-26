from __future__ import annotations

import json
import urllib.error
import urllib.request

from backend.formula_graph.llm.config import LLMRefinementConfig
from backend.formula_graph.llm.prompts import FORMULA_VERIFICATION_PROMPT
from backend.formula_graph.llm.providers.ollama_provider import _parse_formula_response
from backend.formula_graph.llm.schemas import FormulaVerificationRequest, FormulaVerificationResult


class OpenAICompatibleProvider:
    def __init__(self, config: LLMRefinementConfig) -> None:
        self.config = config

    def is_available(self) -> tuple[bool, str]:
        try:
            request = urllib.request.Request(
                self.config.base_url.rstrip("/") + "/models",
                headers=self._headers(),
            )
            with urllib.request.urlopen(request, timeout=min(3, self.config.timeout_sec)) as response:
                return (200 <= response.status < 500), "ok"
        except Exception as exc:
            return False, f"unavailable: {type(exc).__name__}"

    def verify_formula(self, request: FormulaVerificationRequest) -> FormulaVerificationResult:
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": FORMULA_VERIFICATION_PROMPT},
                {"role": "user", "content": request.model_dump_json()},
            ],
            "temperature": 0,
        }
        try:
            raw = self._post("/chat/completions", payload)
            content = raw.get("choices", [{}])[0].get("message", {}).get("content", "{}")
            return _parse_formula_response(content, request=request, provider=self.provider_name, model=self.config.model)
        except Exception as exc:
            return FormulaVerificationResult(
                status="failed",
                corrected_latex=request.latex_candidate,
                confidence=0.0,
                reason=f"provider error: {type(exc).__name__}",
                warnings=[str(exc)[:400]],
                provider=self.provider_name,
                model=self.config.model,
            )

    @property
    def provider_name(self) -> str:
        return "openai_compatible"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key and self.config.api_key != "EMPTY":
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _post(self, path: str, payload: dict) -> dict:
        request = urllib.request.Request(
            self.config.base_url.rstrip("/") + path,
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.config.timeout_sec) as response:
            return json.loads(response.read().decode("utf-8"))
