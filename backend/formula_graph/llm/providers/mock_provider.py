from __future__ import annotations

from backend.formula_graph.llm.config import LLMRefinementConfig
from backend.formula_graph.llm.schemas import FormulaVerificationRequest, FormulaVerificationResult


class MockProvider:
    def __init__(self, config: LLMRefinementConfig, disabled: bool = False) -> None:
        self.config = config
        self.disabled = disabled

    def is_available(self) -> tuple[bool, str]:
        if self.disabled:
            return False, "disabled"
        return True, "ok"

    def verify_formula(self, request: FormulaVerificationRequest) -> FormulaVerificationResult:
        if self.disabled:
            return FormulaVerificationResult(status="skipped", reason="disabled", provider="disabled", model=self.config.model)
        latex = request.latex_candidate.strip()
        return FormulaVerificationResult(
            status="ok",
            corrected_latex=latex,
            changed=False,
            confidence=0.81,
            reason="demo mock evidence; no model was loaded",
            provider="mock",
            model=self.config.model,
        )
