from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ProviderName = Literal["disabled", "mock", "ollama", "vllm", "openai_compatible"]


class FormulaVerificationRequest(BaseModel):
    formula_id: str
    latex_candidate: str
    nearby_text: str = ""
    bbox: list[float] | None = None
    source: str = "unknown"
    quality_flags: list[str] = Field(default_factory=list)
    crop_path: str | None = None


class FormulaVerificationResult(BaseModel):
    status: Literal["ok", "uncertain", "failed", "skipped"] = "skipped"
    corrected_latex: str = ""
    changed: bool = False
    confidence: float = 0.0
    reason: str = ""
    warnings: list[str] = Field(default_factory=list)
    provider: str = "disabled"
    model: str = ""
    raw_response: str | None = None
    raw_status: str | None = None


class ContextDefinition(BaseModel):
    variable: str
    definition: str
    evidence_text: str
    scope: Literal["paragraph", "section", "document"] = "paragraph"
    confidence: float = 0.0


class ContextRefinementRequest(BaseModel):
    formula_id: str
    formula_latex: str
    variables: list[str] = Field(default_factory=list)
    previous_sentence: str = ""
    current_sentence: str = ""
    next_sentence: str = ""
    paragraph_fragments: list[str] = Field(default_factory=list)
    language: Literal["ru", "en", "unknown"] = "unknown"


class ContextRefinementResult(BaseModel):
    formula_id: str
    context_summary: str = ""
    definitions: list[ContextDefinition] = Field(default_factory=list)
    related_variables: list[str] = Field(default_factory=list)
    context_quality: Literal["complete", "partial", "weak"] = "weak"
    warnings: list[str] = Field(default_factory=list)
    provider: str = "disabled"
    model: str = ""
