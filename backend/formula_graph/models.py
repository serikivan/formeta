from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


BBox = tuple[float, float, float, float]


class PageImage(BaseModel):
    page_number: int
    image_path: str
    width: int
    height: int
    dpi: int
    text_layer: str = ""


class TextBlock(BaseModel):
    id: str
    page_number: int
    text: str
    bbox: BBox | None = None
    source: Literal["pdf_text_layer", "paddleocr", "tesseract", "got_ocr", "fallback", "postprocessed", "formula_token", "tex_source"] = "fallback"
    confidence: float | None = None
    lines: list["TextLine"] = Field(default_factory=list)
    role: str | None = None
    section_id: str | None = None


class TextSpan(BaseModel):
    text: str
    bbox: BBox | None = None
    font: str | None = None
    size: float | None = None


class TextLine(BaseModel):
    text: str
    bbox: BBox | None = None
    spans: list[TextSpan] = Field(default_factory=list)


class FormulaRegion(BaseModel):
    id: str
    token: str
    page_number: int
    bbox: BBox
    kind: Literal["inline", "block", "unknown"] = "unknown"
    source: str = "detector"
    confidence: float | None = None
    formula_keys: list[str] = Field(default_factory=list)
    formula_ids: list[str] = Field(default_factory=list)
    latex_keys: list[str] = Field(default_factory=list)


class FormulaBlock(BaseModel):
    id: str
    page_number: int
    latex: str
    kind: Literal["inline", "block"]
    token: str | None = None
    formula_region_id: str | None = None
    context_block_id: str | None = None
    bbox: BBox | None = None
    source: str = "regex"
    confidence: float | None = None
    raw_latex: str | None = None
    cleaned_latex: str | None = None
    normalized_latex: str | None = None
    plain_formula_text: str | None = None
    quality_flags: list[str] = Field(default_factory=list)
    section_id: str | None = None
    label: str | None = None
    original_latex: str | None = None
    llm_corrected_latex: str | None = None
    selected_latex: str | None = None
    llm_confidence: float | None = None
    llm_evidence: dict[str, Any] | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    formula_interpretation: dict[str, Any] = Field(default_factory=dict)
    interpretation: str | None = None


class Entity(BaseModel):
    id: str
    label: str
    kind: Literal["variable", "concept", "parameter", "formula_ref"]
    source_block_id: str | None = None
    source_formula_id: str | None = None
    confidence: float | None = None


class Relation(BaseModel):
    id: str
    source_id: str
    target_id: str
    kind: str
    evidence: str | None = None
    confidence: float | None = None


class GraphNode(BaseModel):
    id: str
    label: str
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    label: str
    payload: dict[str, Any] = Field(default_factory=dict)


class KnowledgeGraph(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)


class ProcessingResult(BaseModel):
    document_id: str
    filename: str
    created_at: datetime
    status: Literal["ok", "partial", "error"]
    warnings: list[str] = Field(default_factory=list)
    pages: list[PageImage] = Field(default_factory=list)
    text_blocks: list[TextBlock] = Field(default_factory=list)
    text_with_tokens: list[TextBlock] = Field(default_factory=list)
    formula_regions: list[FormulaRegion] = Field(default_factory=list)
    formulas: list[FormulaBlock] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    graph: KnowledgeGraph = Field(default_factory=KnowledgeGraph)
    metagraph: KnowledgeGraph = Field(default_factory=KnowledgeGraph)
    metagraph_validation: dict[str, Any] = Field(default_factory=dict)
    processing_steps: list[dict[str, Any]] = Field(default_factory=list)
    timing: dict[str, Any] = Field(default_factory=dict)
    result_path: str | None = None

    def save_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")
