from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.formula_graph.config import resolve_device, settings
from backend.formula_graph.models import FormulaBlock, FormulaRegion as LegacyFormulaRegion
from backend.formula_graph.models import ProcessingResult, TextBlock as LegacyTextBlock


StructuredBBox = list[float]
TOKEN_RE = re.compile(r"\[FORMULA_(\d{3})\]")
STYLE_SYMBOL_RE = re.compile(r"\\(?:mathbb|mathcal|mathfrak|mathscr|mathbf|mathit|mathrm)\s*\{\s*([A-Za-zα-ωΑ-Ω])\s*\}")
DEFINITION_MARKERS = (
    "where",
    "denotes",
    "defined as",
    "let",
    "обозначает",
    "где",
    "определяется как",
)
GREEK_COMMANDS = {
    "alpha",
    "beta",
    "gamma",
    "delta",
    "epsilon",
    "varepsilon",
    "zeta",
    "eta",
    "theta",
    "vartheta",
    "iota",
    "kappa",
    "lambda",
    "mu",
    "nu",
    "xi",
    "pi",
    "rho",
    "sigma",
    "tau",
    "upsilon",
    "phi",
    "varphi",
    "chi",
    "psi",
    "omega",
}
UNICODE_GREEK_SYMBOLS = {
    "α",
    "β",
    "γ",
    "δ",
    "ε",
    "ϵ",
    "ζ",
    "η",
    "θ",
    "ι",
    "κ",
    "λ",
    "μ",
    "ν",
    "ξ",
    "π",
    "ρ",
    "σ",
    "τ",
    "υ",
    "φ",
    "χ",
    "ψ",
    "ω",
    "Α",
    "Β",
    "Γ",
    "Δ",
    "Θ",
    "Λ",
    "Ξ",
    "Π",
    "Σ",
    "Φ",
    "Ψ",
    "Ω",
}
LATEX_OPERATOR_COMMANDS = {
    "frac",
    "sum",
    "prod",
    "int",
    "iint",
    "iiint",
    "oint",
    "sin",
    "cos",
    "tan",
    "log",
    "ln",
    "lim",
    "sqrt",
    "min",
    "max",
    "argmin",
    "argmax",
    "exp",
    "det",
    "ker",
    "dim",
    "deg",
    "gcd",
    "lcm",
    "sup",
    "inf",
    "limsup",
    "liminf",
    "cdot",
    "times",
    "div",
    "circ",
    "cdots",
    "dots",
    "ldots",
    "vdots",
    "ddots",
    "cup",
    "cap",
    "setminus",
    "in",
    "notin",
    "subset",
    "subseteq",
    "supset",
    "supseteq",
    "to",
    "mapsto",
    "rightarrow",
    "leftarrow",
    "operatorname",
}
SECTION_MARKERS_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\.?\s+)?(?:introduction|background|method|methods|results|discussion|conclusion|references|"
    r"введение|метод|методы|результаты|обсуждение|заключение|выводы|список литературы|литература)\b",
    re.IGNORECASE,
)


class ProcessingProfile(BaseModel):
    ocr_mode: str = "unknown"
    device: str = "cpu"
    ocr_lang: str = "unknown"
    requested_device: str = "unknown"
    resolved_device: str = "cpu"
    requested_ocr_lang: str = "unknown"
    resolved_ocr_lang: str = "unknown"
    ocr_language_detection_reason: str = "not_provided"
    render_dpi: int | None = None
    prefer_tex_source: bool = False


class DocumentQuality(BaseModel):
    text_layer_quality: Literal["good", "poor", "missing"] = "missing"
    formula_detection_status: Literal["ok", "partial", "failed"] = "failed"
    formula_recognition_status: Literal["ok", "partial", "failed"] = "failed"
    warnings_count: int = 0


class PageTextLayer(BaseModel):
    available: bool = False
    quality: Literal["good", "poor", "missing"] = "missing"
    char_count: int = 0
    used_as_text_source: bool = False


class StructuredPage(BaseModel):
    id: str
    page_number: int
    width: int
    height: int
    dpi: int | None = None
    image_path: str | None = None
    preview_path: str | None = None
    text_layer: PageTextLayer = Field(default_factory=PageTextLayer)


class StructuredTextBlock(BaseModel):
    id: str
    page_id: str
    page_number: int
    type: Literal["title", "author", "abstract", "heading", "paragraph", "caption", "list_item", "footer", "unknown"] = "unknown"
    text: str
    normalized_text: str
    bbox: StructuredBBox | None = None
    reading_order: int | None = None
    source: str = "unknown"
    confidence: float | None = None
    contains_formula_token: bool = False
    formula_tokens: list[str] = Field(default_factory=list)
    section_id: str | None = None


class StructuredFormulaRegion(BaseModel):
    id: str
    formula_id: str | None = None
    token: str
    page_id: str
    page_number: int
    bbox: StructuredBBox | None = None
    kind: Literal["inline_math", "display_math", "unknown"] = "unknown"
    detection_source: str = "unknown"
    confidence: float | None = None
    reading_order: int | None = None
    crop_path: str | None = None
    is_masked_in_text_ocr: bool = True


class FormulaTextPosition(BaseModel):
    before_text_block_id: str | None = None
    after_text_block_id: str | None = None
    nearest_text_block_id: str | None = None


class FormulaSemanticHints(BaseModel):
    definition_like: bool = False
    theorem_like: bool = False
    optimization_like: bool = False
    contains_equality: bool = False
    contains_inequality: bool = False
    contains_sum: bool = False
    contains_integral: bool = False
    contains_fraction: bool = False
    contains_matrix: bool = False


class StructuredFormula(BaseModel):
    id: str
    token: str
    kind: Literal["inline_math", "display_math", "unknown"] = "unknown"
    latex: str = ""
    cleaned_latex: str = ""
    normalized_latex: str = ""
    raw_latex: str = ""
    plain_formula_text: str = ""
    source: str = "unknown"
    confidence: float | None = None
    page_number: int
    region_id: str | None = None
    bbox: StructuredBBox | None = None
    section_id: str | None = None
    formula_number: str | None = None
    text_position: FormulaTextPosition = Field(default_factory=FormulaTextPosition)
    semantic_hints: FormulaSemanticHints = Field(default_factory=FormulaSemanticHints)
    quality_flags: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    operators: list[str] = Field(default_factory=list)


class ReadingOrderItem(BaseModel):
    order: int
    object_id: str
    object_type: Literal["text_block", "formula"]
    page_number: int


class FormulaContext(BaseModel):
    id: str
    formula_id: str
    token: str
    page_number: int
    context_before: str = ""
    context_after: str = ""
    nearest_text_block_ids: list[str] = Field(default_factory=list)
    window_text: str = ""
    definition_markers: list[str] = Field(default_factory=list)
    linked_symbols: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class StructuredEntity(BaseModel):
    id: str
    type: Literal["symbol", "concept", "formula_ref"]
    value: str
    normalized_value: str
    latex: str | None = None
    source: str = "heuristic"
    formula_id: str | None = None
    text_block_id: str | None = None
    context_id: str | None = None
    section_id: str | None = None
    page_number: int | None = None
    confidence: float | None = None
    occurrences: list[EntityOccurrence] = Field(default_factory=list)


class StructuredRelation(BaseModel):
    id: str
    type: Literal["contains_formula", "has_context", "contains_symbol", "near_text", "possibly_defined_by"]
    source_id: str
    target_id: str
    evidence: str | None = None
    confidence: float | None = None


class WarningItem(BaseModel):
    code: str
    message: str
    object_ids: list[str] = Field(default_factory=list)


class DocumentSection(BaseModel):
    id: str
    title: str
    normalized_title: str
    level: int = 1
    page_number: int | None = None
    text_block_id: str | None = None
    start_reading_order: int | None = None
    end_reading_order: int | None = None
    children: list[str] = Field(default_factory=list)


class DocumentStructure(BaseModel):
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    abstract: str | None = None
    sections: list[DocumentSection] = Field(default_factory=list)
    detected_language: Literal["ru", "en", "unknown"] = "unknown"


class StructuredSummary(BaseModel):
    pages_count: int = 0
    text_blocks_count: int = 0
    formula_regions_count: int = 0
    formulas_count: int = 0
    tokens_in_text_count: int = 0
    formula_contexts_count: int = 0
    entities_count: int = 0
    relations_count: int = 0
    warnings_count: int = 0
    status: Literal["ok", "partial", "error"] = "ok"


class EntityOccurrence(BaseModel):
    object_id: str
    object_type: Literal["formula", "text_block", "context"]
    position: int | None = None


class FormulaLink(BaseModel):
    id: str
    source_formula_id: str
    target_formula_id: str
    type: Literal["references", "nearby", "same_symbols"]
    evidence: str | None = None
    confidence: float | None = None


class GraphSeedNode(BaseModel):
    id: str
    type: str
    label: str
    source_object_id: str


class GraphSeedEdge(BaseModel):
    id: str
    source: str
    target: str
    type: str
    confidence: float | None = None


class GraphSeed(BaseModel):
    nodes: list[GraphSeedNode] = Field(default_factory=list)
    edges: list[GraphSeedEdge] = Field(default_factory=list)


class StructuredDocument(BaseModel):
    schema_version: str = "1.0"
    document_id: str
    filename: str
    source_type: Literal["pdf", "image", "unknown"] = "unknown"
    created_at: datetime
    status: Literal["ok", "partial", "error"]
    summary: StructuredSummary = Field(default_factory=StructuredSummary)
    processing_profile: ProcessingProfile = Field(default_factory=ProcessingProfile)
    quality: DocumentQuality = Field(default_factory=DocumentQuality)
    document_structure: DocumentStructure = Field(default_factory=DocumentStructure)
    pages: list[StructuredPage] = Field(default_factory=list)
    reading_order: list[ReadingOrderItem] = Field(default_factory=list)
    text_blocks: list[StructuredTextBlock] = Field(default_factory=list)
    formula_regions: list[StructuredFormulaRegion] = Field(default_factory=list)
    formulas: list[StructuredFormula] = Field(default_factory=list)
    text_with_tokens: str = ""
    formula_contexts: list[FormulaContext] = Field(default_factory=list)
    formula_links: list[FormulaLink] = Field(default_factory=list)
    entities: list[StructuredEntity] = Field(default_factory=list)
    relations: list[StructuredRelation] = Field(default_factory=list)
    warnings: list[WarningItem] = Field(default_factory=list)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    graph_seed: GraphSeed = Field(default_factory=GraphSeed)
    graph: dict[str, Any] = Field(default_factory=dict)
    metagraph: dict[str, Any] = Field(default_factory=dict)


def estimate_text_layer_quality(text: str) -> Literal["good", "poor", "missing"]:
    if not text or not text.strip():
        return "missing"
    clean = text.strip()
    if len(clean) < 300:
        return "poor"
    bad_chars = clean.count("�") + clean.count("□")
    if bad_chars > 10:
        return "poor"
    alpha_count = sum(ch.isalpha() for ch in clean)
    alpha_ratio = alpha_count / max(len(clean), 1)
    if alpha_ratio < 0.35:
        return "poor"
    return "good"


def build_structured_document(
    result: ProcessingResult,
    *,
    ocr_mode: str = "unknown",
    device: str | None = None,
    ocr_lang: str = "unknown",
    requested_device: str | None = None,
    resolved_device: str | None = None,
    requested_ocr_lang: str | None = None,
    resolved_ocr_lang: str | None = None,
    ocr_language_detection_reason: str | None = None,
    render_dpi: int | None = None,
    prefer_tex_source: bool = False,
) -> StructuredDocument:
    pages = _build_pages(result)
    page_id_by_number = {page.page_number: page.id for page in pages}
    legacy_text_blocks = result.text_blocks or result.text_with_tokens
    text_blocks, legacy_text_id_map = _build_text_blocks(legacy_text_blocks, page_id_by_number)
    formula_regions = _build_formula_regions(result.formula_regions, page_id_by_number)
    formulas = _build_formulas(result.formulas, formula_regions)
    formula_regions, formulas = assign_formula_tokens(formula_regions, formulas)
    reading_order = build_reading_order(text_blocks, formula_regions, pages, formulas=formulas)
    _apply_reading_order(text_blocks, formula_regions, formulas, reading_order)
    _apply_formula_text_positions(formulas, text_blocks, reading_order)
    text_with_tokens = _build_text_with_tokens(text_blocks, formulas, reading_order)
    formula_contexts = build_formula_contexts(formulas, text_blocks, reading_order)
    requested_device = requested_device or device or "unknown"
    resolved_device = resolved_device or resolve_device(device)
    requested_ocr_lang = requested_ocr_lang or ocr_lang
    resolved_ocr_lang = resolved_ocr_lang or ocr_lang
    ocr_language_detection_reason = ocr_language_detection_reason or _ocr_lang_reason(requested_ocr_lang, resolved_ocr_lang)
    document_structure = _build_document_structure(text_blocks, reading_order, resolved_ocr_lang)
    section_warnings = _assign_sections(text_blocks, formulas, document_structure, reading_order)
    _apply_formula_numbers_and_semantic_hints(formulas, formula_contexts)
    entities = _build_entities(formulas, text_blocks, legacy_text_id_map, formula_contexts)
    formula_links = _build_formula_links(formulas, formula_contexts, reading_order)
    relations = _build_relations(formulas, formula_contexts, entities)
    graph_seed = _build_graph_seed(formulas, formula_contexts, entities, relations, formula_links)
    warnings = _build_initial_warnings(result, pages, formulas, formula_regions)
    warnings.extend(section_warnings)

    doc = StructuredDocument(
        document_id=result.document_id,
        filename=result.filename,
        source_type=_source_type(result.filename),
        created_at=result.created_at,
        status=result.status,
        processing_profile=ProcessingProfile(
            ocr_mode=ocr_mode,
            device=resolved_device,
            ocr_lang=resolved_ocr_lang,
            requested_device=requested_device,
            resolved_device=resolved_device,
            requested_ocr_lang=requested_ocr_lang,
            resolved_ocr_lang=resolved_ocr_lang,
            ocr_language_detection_reason=ocr_language_detection_reason,
            render_dpi=render_dpi,
            prefer_tex_source=prefer_tex_source,
        ),
        quality=DocumentQuality(
            text_layer_quality=_overall_text_layer_quality(pages),
            formula_detection_status=_formula_detection_status(formula_regions),
            formula_recognition_status=_formula_recognition_status(formulas),
            warnings_count=0,
        ),
        document_structure=document_structure,
        pages=pages,
        reading_order=reading_order,
        text_blocks=text_blocks,
        formula_regions=formula_regions,
        formulas=formulas,
        text_with_tokens=text_with_tokens,
        formula_contexts=formula_contexts,
        formula_links=formula_links,
        entities=entities,
        relations=relations,
        warnings=warnings,
        artifacts={
            "legacy_result_path": result.result_path,
            "processed_dir": str(settings.processed_dir / result.document_id),
        },
        graph_seed=graph_seed,
        graph=result.graph.model_dump() if result.graph else {},
        metagraph=result.metagraph.model_dump() if result.metagraph else {},
    )
    doc.warnings.extend(validate_structured_document(doc))
    doc.quality.warnings_count = len(doc.warnings)
    if doc.status == "ok" and doc.warnings:
        doc.status = "partial"
    _refresh_summary(doc)
    return doc


def save_structured_document(doc: StructuredDocument, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(doc.model_dump_json(indent=2), encoding="utf-8")


def load_structured_document(path: Path) -> StructuredDocument:
    return StructuredDocument.model_validate_json(path.read_text(encoding="utf-8"))


def build_reading_order(
    text_blocks: list[StructuredTextBlock],
    formula_regions: list[StructuredFormulaRegion],
    pages: list[StructuredPage],
    formulas: list[StructuredFormula] | None = None,
) -> list[ReadingOrderItem]:
    page_width = {page.page_number: page.width for page in pages}
    items: list[tuple[int, str, str, int, StructuredBBox | None, str | None, int]] = []
    for sequence, block in enumerate(text_blocks):
        items.append((block.page_number, block.id, "text_block", 0, block.bbox, block.section_id, sequence))
    for sequence, region in enumerate(formula_regions):
        formula_id = region.formula_id or region.id
        items.append((region.page_number, formula_id, "formula", 1, region.bbox, None, sequence))
    known_formula_ids = {item[1] for item in items if item[2] == "formula"}
    for sequence, formula in enumerate(formulas or []):
        if formula.id in known_formula_ids:
            continue
        items.append((formula.page_number, formula.id, "formula", 1, formula.bbox, formula.section_id, sequence))

    def sort_key(item: tuple[int, str, str, int, StructuredBBox | None, str | None, int]) -> tuple[Any, ...]:
        page_number, object_id, _object_type, type_rank, bbox, section_id, sequence = item
        if not bbox:
            section_rank = _legacy_section_rank(section_id)
            return page_number, section_rank, type_rank, sequence, object_id
        x0, y0, x1, _y1 = bbox
        width = page_width.get(page_number, 0)
        center_x = (x0 + x1) / 2
        column = 0
        if width and x0 > width * 0.45 and center_x > width * 0.5:
            column = 1
        return page_number, column, y0, x0, object_id

    ordered = sorted(items, key=sort_key)
    return [
        ReadingOrderItem(order=index, object_id=object_id, object_type=object_type, page_number=page_number)
        for index, (page_number, object_id, object_type, _type_rank, _bbox, _section_id, _sequence) in enumerate(ordered, start=1)
    ]


def assign_formula_tokens(
    formula_regions: list[StructuredFormulaRegion],
    formulas: list[StructuredFormula] | None = None,
) -> tuple[list[StructuredFormulaRegion], list[StructuredFormula]]:
    formulas = list(formulas or [])
    formula_by_region = {formula.region_id: formula for formula in formulas if formula.region_id}
    formula_by_id = {formula.id: formula for formula in formulas}
    ordered_regions = sorted(formula_regions, key=lambda region: _spatial_key(region.page_number, region.bbox))
    next_index = 1
    for region in ordered_regions:
        token = f"[FORMULA_{next_index:03d}]"
        next_index += 1
        region.token = token
        formula = formula_by_region.get(region.id) or formula_by_id.get(region.formula_id or "")
        if formula is None:
            formula = StructuredFormula(
                id=region.formula_id or f"formula_{next_index - 1:04d}",
                token=token,
                kind=region.kind,
                latex="",
                cleaned_latex="",
                normalized_latex="",
                raw_latex="",
                plain_formula_text="",
                source=region.detection_source,
                confidence=region.confidence,
                page_number=region.page_number,
                region_id=region.id,
                bbox=region.bbox,
                quality_flags=["latex_missing"],
            )
            formulas.append(formula)
            formula_by_region[region.id] = formula
        formula.token = token
        formula.region_id = region.id
        formula.page_number = region.page_number
        formula.bbox = formula.bbox or region.bbox
        formula.kind = formula.kind if formula.kind != "unknown" else region.kind
        region.formula_id = formula.id

    for formula in sorted((item for item in formulas if not TOKEN_RE.fullmatch(item.token)), key=lambda item: _spatial_key(item.page_number, item.bbox)):
        formula.token = f"[FORMULA_{next_index:03d}]"
        next_index += 1
    return formula_regions, formulas


def build_formula_contexts(
    formulas: list[StructuredFormula],
    text_blocks: list[StructuredTextBlock],
    reading_order: list[ReadingOrderItem],
) -> list[FormulaContext]:
    block_by_id = {block.id: block for block in text_blocks}
    order_ids = [item.object_id for item in reading_order]
    contexts: list[FormulaContext] = []
    for index, formula in enumerate(formulas, start=1):
        try:
            position = order_ids.index(formula.id)
        except ValueError:
            position = -1
        before = _nearest_text(position, reading_order, block_by_id, step=-1)
        after = _nearest_text(position, reading_order, block_by_id, step=1)
        if before is None or after is None:
            bbox_before, bbox_after = _nearest_context_blocks_by_bbox(formula, text_blocks)
            before = before or bbox_before
            after = after or bbox_after
        nearest_ids = [block.id for block in (before, after) if block is not None]
        before_text = before.normalized_text if before else ""
        after_text = after.normalized_text if after else ""
        window_text = " ".join(part for part in (before_text, formula.token, after_text) if part).strip()
        if formula.token not in window_text:
            window_text = f"{formula.token} {window_text}".strip()
        markers = _definition_markers(window_text)
        contexts.append(
            FormulaContext(
                id=f"ctx_{index:04d}",
                formula_id=formula.id,
                token=formula.token,
                page_number=formula.page_number,
                context_before=before_text,
                context_after=after_text,
                nearest_text_block_ids=nearest_ids,
                window_text=window_text,
                definition_markers=markers,
                linked_symbols=[],
                confidence=0.75 if markers else (0.62 if nearest_ids else 0.25),
            )
        )
    return contexts


def validate_structured_document(doc: StructuredDocument) -> list[WarningItem]:
    warnings: list[WarningItem] = []
    formula_tokens = [formula.token for formula in doc.formulas]
    duplicate_tokens = sorted({token for token in formula_tokens if formula_tokens.count(token) > 1})
    if duplicate_tokens:
        warnings.append(WarningItem(code="duplicate_formula_token", message="Formula tokens must be unique.", object_ids=duplicate_tokens))
    formula_token_set = set(formula_tokens)
    formula_ids = {formula.id for formula in doc.formulas}
    region_ids = {region.id for region in doc.formula_regions}
    context_formula_ids = {context.formula_id for context in doc.formula_contexts}
    context_ids = {context.id for context in doc.formula_contexts}
    section_ids = {section.id for section in doc.document_structure.sections}
    object_ids = {block.id for block in doc.text_blocks} | formula_ids
    tokens_in_text = [match.group(0) for match in TOKEN_RE.finditer(doc.text_with_tokens or "")]
    tokens_in_text_set = set(tokens_in_text)

    unknown_region_tokens = [region.id for region in doc.formula_regions if region.token not in formula_token_set]
    if unknown_region_tokens:
        warnings.append(WarningItem(code="formula_region_token_missing", message="Some formula region tokens do not exist in formulas.", object_ids=unknown_region_tokens))
    missing_region_formula_ids = [region.id for region in doc.formula_regions if not region.formula_id or region.formula_id not in formula_ids]
    if missing_region_formula_ids:
        warnings.append(WarningItem(code="formula_region_formula_missing", message="Some formula regions point to missing formulas.", object_ids=missing_region_formula_ids))
    unknown_formula_regions = [formula.id for formula in doc.formulas if formula.region_id and formula.region_id not in region_ids]
    if unknown_formula_regions:
        warnings.append(WarningItem(code="formula_region_missing", message="Some formulas point to missing formula regions.", object_ids=unknown_formula_regions))
    bad_bbox_objects = [
        item.id
        for item in [*doc.text_blocks, *doc.formula_regions, *doc.formulas]
        if getattr(item, "bbox", None) is not None and len(getattr(item, "bbox")) != 4
    ]
    if bad_bbox_objects:
        warnings.append(WarningItem(code="invalid_bbox", message="Some objects have bbox values that are not four-number arrays.", object_ids=bad_bbox_objects))
    missing_order_objects = [item.object_id for item in doc.reading_order if item.object_id not in object_ids]
    if missing_order_objects:
        warnings.append(WarningItem(code="reading_order_missing_object", message="Reading order contains unknown object ids.", object_ids=missing_order_objects))
    ordered_ids = {item.object_id for item in doc.reading_order}
    missing_order_text_blocks = [block.id for block in doc.text_blocks if block.id not in ordered_ids]
    if missing_order_text_blocks:
        warnings.append(WarningItem(code="reading_order_missing_text_block", message="Reading order does not contain all text blocks.", object_ids=missing_order_text_blocks))
    missing_order_formulas = [
        formula.id
        for formula in doc.formulas
        if formula.id not in ordered_ids and (formula.bbox is not None or formula.page_number is not None)
    ]
    if missing_order_formulas:
        warnings.append(WarningItem(code="reading_order_missing_formula", message="Reading order does not contain all formulas with page geometry.", object_ids=missing_order_formulas))
    unknown_text_tokens = sorted(token for token in tokens_in_text_set if token not in formula_token_set)
    if unknown_text_tokens:
        warnings.append(WarningItem(code="text_with_tokens_unknown_formula", message="text_with_tokens contains unknown formula tokens.", object_ids=unknown_text_tokens))
    tokens_not_inserted = sorted(formula.id for formula in doc.formulas if formula.token and formula.token not in tokens_in_text_set)
    if tokens_not_inserted:
        warnings.append(WarningItem(code="token_not_inserted", message="Some formula tokens are not present in text_with_tokens.", object_ids=tokens_not_inserted))
    empty_ids = [formula.token for formula in doc.formulas if not formula.id]
    if empty_ids:
        warnings.append(WarningItem(code="formula_id_missing", message="Some formulas have empty ids.", object_ids=empty_ids))
    missing_context_formula = [context.id for context in doc.formula_contexts if context.formula_id not in formula_ids]
    if missing_context_formula:
        warnings.append(WarningItem(code="formula_context_missing_formula", message="Some contexts point to missing formulas.", object_ids=missing_context_formula))
    formulas_without_context = sorted(formula.id for formula in doc.formulas if formula.id not in context_formula_ids)
    empty_contexts = sorted(context.formula_id for context in doc.formula_contexts if not context.nearest_text_block_ids)
    context_missing = _dedupe([*formulas_without_context, *empty_contexts])
    if context_missing:
        warnings.append(WarningItem(code="formula_context_missing", message="Some formulas have no usable nearby text context.", object_ids=context_missing))
    context_windows_without_token = [
        context.id for context in doc.formula_contexts if context.token and context.token not in context.window_text
    ]
    if context_windows_without_token:
        warnings.append(WarningItem(code="formula_context_token_missing", message="Some formula contexts do not include the formula token in window_text.", object_ids=context_windows_without_token))
    invalid_text_sections = [block.id for block in doc.text_blocks if block.section_id and block.section_id not in section_ids]
    if invalid_text_sections:
        warnings.append(WarningItem(code="text_block_section_missing", message="Some text blocks point to missing sections.", object_ids=invalid_text_sections))
    invalid_formula_sections = [formula.id for formula in doc.formulas if formula.section_id and formula.section_id not in section_ids]
    if invalid_formula_sections:
        warnings.append(WarningItem(code="formula_section_missing", message="Some formulas point to missing sections.", object_ids=invalid_formula_sections))
    section_number_pairs: dict[tuple[str | None, str], list[str]] = {}
    for formula in doc.formulas:
        if formula.formula_number:
            section_number_pairs.setdefault((formula.section_id, formula.formula_number), []).append(formula.id)
    duplicate_numbers = [item for ids in section_number_pairs.values() if len(ids) > 1 for item in ids]
    if duplicate_numbers:
        warnings.append(WarningItem(code="duplicate_formula_number", message="Formula number is duplicated within a section.", object_ids=duplicate_numbers))
    invalid_links = [
        link.id
        for link in doc.formula_links
        if link.source_formula_id not in formula_ids or link.target_formula_id not in formula_ids
    ]
    if invalid_links:
        warnings.append(WarningItem(code="formula_link_missing_formula", message="Some formula links point to missing formulas.", object_ids=invalid_links))
    node_ids = [node.id for node in doc.graph_seed.nodes]
    duplicate_nodes = sorted({node_id for node_id in node_ids if node_ids.count(node_id) > 1})
    if duplicate_nodes:
        warnings.append(WarningItem(code="graph_seed_duplicate_node", message="graph_seed node ids must be unique.", object_ids=duplicate_nodes))
    graph_node_set = set(node_ids)
    invalid_edges = [
        edge.id for edge in doc.graph_seed.edges if edge.source not in graph_node_set or edge.target not in graph_node_set
    ]
    if invalid_edges:
        warnings.append(WarningItem(code="graph_seed_edge_missing_node", message="graph_seed edges must reference existing nodes.", object_ids=invalid_edges))
    invalid_entities: list[str] = []
    for entity in doc.entities:
        if entity.formula_id and entity.formula_id not in formula_ids:
            invalid_entities.append(entity.id)
        elif entity.context_id and entity.context_id not in context_ids:
            invalid_entities.append(entity.id)
        elif entity.section_id and entity.section_id not in section_ids:
            invalid_entities.append(entity.id)
    if invalid_entities:
        warnings.append(WarningItem(code="entity_reference_missing", message="Some entities point to missing formula/context/section ids.", object_ids=invalid_entities))
    return warnings


def _build_pages(result: ProcessingResult) -> list[StructuredPage]:
    text_source_pages = {block.page_number for block in result.text_blocks if block.source == "pdf_text_layer"}
    pages: list[StructuredPage] = []
    for page in result.pages:
        quality = estimate_text_layer_quality(page.text_layer)
        pages.append(
            StructuredPage(
                id=f"page_{page.page_number:03d}",
                page_number=page.page_number,
                width=page.width,
                height=page.height,
                dpi=page.dpi,
                image_path=page.image_path,
                preview_path=None,
                text_layer=PageTextLayer(
                    available=quality != "missing",
                    quality=quality,
                    char_count=len(page.text_layer or ""),
                    used_as_text_source=page.page_number in text_source_pages,
                ),
            )
        )
    return pages


def _build_text_blocks(
    blocks: list[LegacyTextBlock],
    page_id_by_number: dict[int, str],
) -> tuple[list[StructuredTextBlock], dict[str, str]]:
    ordered = sorted(blocks, key=lambda block: _spatial_key(block.page_number, _bbox_to_list(block.bbox)))
    result: list[StructuredTextBlock] = []
    id_map: dict[str, str] = {}
    current_tex_section_id: str | None = None
    inferred_tex_section_count = 0
    for index, block in enumerate(ordered, start=1):
        tokens = _tokens_in_text(block.text)
        block_id = f"tb_{index:04d}"
        id_map[block.id] = block_id
        role = (block.role or "").lower()
        if block.section_id:
            current_tex_section_id = block.section_id
        elif block.source == "tex_source" and role in {"section", "subsection", "subsubsection", "chapter", "part"}:
            inferred_tex_section_count += 1
            current_tex_section_id = f"sec_{inferred_tex_section_count}"
        legacy_section_id = block.section_id
        if block.source == "tex_source" and role not in {"title", "author", "abstract"}:
            legacy_section_id = legacy_section_id or current_tex_section_id
        result.append(
            StructuredTextBlock(
                id=block_id,
                page_id=page_id_by_number.get(block.page_number, f"page_{block.page_number:03d}"),
                page_number=block.page_number,
                type=_block_type(block),
                text=block.text,
                normalized_text=_normalize_text(block.text),
                bbox=_bbox_to_list(block.bbox),
                source=block.source,
                confidence=block.confidence,
                contains_formula_token=bool(tokens),
                formula_tokens=tokens,
                section_id=legacy_section_id,
            )
        )
    return result, id_map


def _build_formula_regions(
    regions: list[LegacyFormulaRegion],
    page_id_by_number: dict[int, str],
) -> list[StructuredFormulaRegion]:
    ordered = sorted(regions, key=lambda region: _spatial_key(region.page_number, _bbox_to_list(region.bbox)))
    result: list[StructuredFormulaRegion] = []
    for index, region in enumerate(ordered, start=1):
        result.append(
            StructuredFormulaRegion(
                id=f"fr_{index:04d}",
                formula_id=None,
                token=region.token or f"[FORMULA_{index:03d}]",
                page_id=page_id_by_number.get(region.page_number, f"page_{region.page_number:03d}"),
                page_number=region.page_number,
                bbox=_bbox_to_list(region.bbox),
                kind=_formula_kind(region.kind),
                detection_source=_source_name(region.source),
                confidence=region.confidence,
                crop_path=None,
                is_masked_in_text_ocr=True,
            )
        )
    return result


def _build_formulas(
    formulas: list[FormulaBlock],
    regions: list[StructuredFormulaRegion],
) -> list[StructuredFormula]:
    ordered = sorted(formulas, key=lambda formula: _spatial_key(formula.page_number, _bbox_to_list(formula.bbox)))
    regions_by_old_token = {region.token: region for region in regions}
    unmatched_regions = list(regions)
    result: list[StructuredFormula] = []
    for index, formula in enumerate(ordered, start=1):
        region = regions_by_old_token.get(formula.token or "")
        if region is None and formula.bbox is not None:
            region = _nearest_region(formula, unmatched_regions)
        if region is not None and region in unmatched_regions:
            unmatched_regions.remove(region)
        formula_id = f"formula_{index:04d}"
        final_bbox = _bbox_to_list(formula.bbox) or (region.bbox if region else None)
        flags = _quality_flags(formula, final_bbox)
        result.append(
            StructuredFormula(
                id=formula_id,
                token=formula.token or "",
                kind=_formula_kind(formula.kind),
                latex=formula.latex or "",
                cleaned_latex=formula.cleaned_latex or formula.latex or "",
                normalized_latex=formula.normalized_latex or _normalize_latex(formula.latex or ""),
                raw_latex=formula.raw_latex or formula.latex or "",
                plain_formula_text=formula.plain_formula_text or "",
                source=_source_name(formula.source),
                confidence=formula.confidence,
                page_number=formula.page_number,
                region_id=region.id if region else None,
                bbox=final_bbox,
                section_id=formula.section_id,
                quality_flags=flags,
                symbols=_extract_symbols(formula.latex or ""),
                operators=_extract_operators(formula.latex or ""),
            )
        )
    for region in unmatched_regions:
        result.append(
            StructuredFormula(
                id=f"formula_{len(result) + 1:04d}",
                token=region.token,
                kind=region.kind,
                latex="",
                cleaned_latex="",
                normalized_latex="",
                raw_latex="",
                plain_formula_text="",
                source=region.detection_source,
                confidence=region.confidence,
                page_number=region.page_number,
                region_id=region.id,
                bbox=region.bbox,
                quality_flags=["latex_missing"],
            )
        )
    return result


def _apply_reading_order(
    text_blocks: list[StructuredTextBlock],
    formula_regions: list[StructuredFormulaRegion],
    formulas: list[StructuredFormula],
    reading_order: list[ReadingOrderItem],
) -> None:
    text_by_id = {block.id: block for block in text_blocks}
    formula_by_id = {formula.id: formula for formula in formulas}
    region_by_formula_id = {region.formula_id: region for region in formula_regions if region.formula_id}
    for item in reading_order:
        if item.object_type == "text_block" and item.object_id in text_by_id:
            text_by_id[item.object_id].reading_order = item.order
        if item.object_type == "formula" and item.object_id in formula_by_id:
            region = region_by_formula_id.get(item.object_id)
            if region is not None:
                region.reading_order = item.order


def _apply_formula_text_positions(
    formulas: list[StructuredFormula],
    text_blocks: list[StructuredTextBlock],
    reading_order: list[ReadingOrderItem],
) -> None:
    block_by_id = {block.id: block for block in text_blocks}
    order_ids = [item.object_id for item in reading_order]
    for formula in formulas:
        try:
            position = order_ids.index(formula.id)
        except ValueError:
            position = -1
        before = _nearest_text(position, reading_order, block_by_id, step=-1)
        after = _nearest_text(position, reading_order, block_by_id, step=1)
        nearest = _nearest_block_by_distance(formula, text_blocks) or before or after
        formula.text_position = FormulaTextPosition(
            before_text_block_id=before.id if before else None,
            after_text_block_id=after.id if after else None,
            nearest_text_block_id=nearest.id if nearest else None,
        )


def _build_text_with_tokens(
    text_blocks: list[StructuredTextBlock],
    formulas: list[StructuredFormula],
    reading_order: list[ReadingOrderItem],
) -> str:
    block_by_id = {block.id: block for block in text_blocks}
    formula_by_id = {formula.id: formula for formula in formulas}
    tokens_already_in_text = {token for block in text_blocks for token in block.formula_tokens}
    parts: list[str] = []
    for item in reading_order:
        if item.object_type == "text_block":
            text = block_by_id.get(item.object_id).normalized_text if item.object_id in block_by_id else ""
            if text:
                parts.append(text)
        elif item.object_type == "formula":
            formula = formula_by_id.get(item.object_id)
            if formula is None:
                continue
            token = formula.token
            if token in tokens_already_in_text:
                continue
            if formula.kind == "display_math":
                parts.append(f"\n{token}\n")
            else:
                parts.append(token)
    return _normalize_token_text("\n".join(parts))


def _build_document_structure(
    text_blocks: list[StructuredTextBlock],
    reading_order: list[ReadingOrderItem],
    detected_language: str | None,
) -> DocumentStructure:
    block_by_id = {block.id: block for block in text_blocks}
    ordered_blocks = [
        block_by_id[item.object_id]
        for item in reading_order
        if item.object_type == "text_block" and item.object_id in block_by_id
    ]
    title = _detect_document_title(ordered_blocks)
    authors = _detect_document_authors(ordered_blocks)
    abstract = _detect_abstract(ordered_blocks)
    heading_blocks = [block for block in ordered_blocks if _looks_like_section_heading(block)]
    sections: list[DocumentSection] = []
    if not heading_blocks and ordered_blocks:
        heading_blocks = [ordered_blocks[0]]

    order_by_id = {item.object_id: item.order for item in reading_order}
    section_starts = [order_by_id.get(block.id) for block in heading_blocks]
    section_starts = [value for value in section_starts if value is not None]
    max_order = max((item.order for item in reading_order), default=None)
    for index, block in enumerate(heading_blocks, start=1):
        start = order_by_id.get(block.id)
        if index == 1 and start is not None:
            start = 1
        next_start = section_starts[index] if index < len(section_starts) else None
        sections.append(
            DocumentSection(
                id=f"sec_{index:04d}",
                title=block.normalized_text[:220],
                normalized_title=_normalize_section_title(block.normalized_text),
                level=_section_level(block.normalized_text),
                page_number=block.page_number,
                text_block_id=block.id,
                start_reading_order=start,
                end_reading_order=(next_start - 1 if next_start is not None else max_order),
                children=[],
            )
        )
    language = detected_language if detected_language in {"ru", "en"} else "unknown"
    return DocumentStructure(title=title, authors=authors, abstract=abstract, sections=sections, detected_language=language)


def _assign_sections(
    text_blocks: list[StructuredTextBlock],
    formulas: list[StructuredFormula],
    document_structure: DocumentStructure,
    reading_order: list[ReadingOrderItem],
) -> list[WarningItem]:
    if not document_structure.sections:
        return []
    section_by_order: list[tuple[int, int, str]] = []
    for section in document_structure.sections:
        start = section.start_reading_order
        end = section.end_reading_order
        if start is None or end is None:
            continue
        section_by_order.append((start, end, section.id))
    if not section_by_order:
        return []
    text_by_id = {block.id: block for block in text_blocks}
    formula_by_id = {formula.id: formula for formula in formulas}
    assigned = 0
    assignable = 0
    for item in reading_order:
        target = text_by_id.get(item.object_id) if item.object_type == "text_block" else formula_by_id.get(item.object_id)
        if target is None:
            continue
        assignable += 1
        section_id = next((sid for start, end, sid in section_by_order if start <= item.order <= end), None)
        if section_id:
            target.section_id = section_id
            assigned += 1
    if assignable and assigned < assignable:
        return [
            WarningItem(
                code="section_assignment_partial",
                message="Some text blocks or formulas could not be assigned to a detected document section.",
            )
        ]
    return []


def _apply_formula_numbers_and_semantic_hints(
    formulas: list[StructuredFormula],
    contexts: list[FormulaContext],
) -> None:
    context_by_formula_id = {context.formula_id: context for context in contexts}
    for formula in formulas:
        context = context_by_formula_id.get(formula.id)
        formula.formula_number = _detect_formula_number(formula, context)
        formula.semantic_hints = _semantic_hints(formula, context)


def _build_entities(
    formulas: list[StructuredFormula],
    text_blocks: list[StructuredTextBlock],
    _legacy_text_id_map: dict[str, str],
    contexts: list[FormulaContext],
) -> list[StructuredEntity]:
    entities: list[StructuredEntity] = []
    seen: set[tuple[str, str, str | None]] = set()
    context_by_formula_id = {context.formula_id: context for context in contexts}
    for formula in formulas:
        for symbol in formula.symbols:
            key = ("symbol", symbol, formula.id)
            if key in seen:
                continue
            seen.add(key)
            context = context_by_formula_id.get(formula.id)
            entities.append(
                StructuredEntity(
                    id=f"ent_{len(entities) + 1:04d}",
                    type="symbol",
                    value=symbol,
                    normalized_value=symbol,
                    latex=symbol,
                    source="formula",
                    formula_id=formula.id,
                    context_id=context.id if context else None,
                    section_id=formula.section_id,
                    page_number=formula.page_number,
                    confidence=0.7,
                    occurrences=[
                        EntityOccurrence(
                            object_id=formula.id,
                            object_type="formula",
                            position=None,
                        )
                    ],
                )
            )
    formula_ref_re = re.compile(r"(?:equation|формула)?\s*\((\d{1,3})\)", re.IGNORECASE)
    for block in text_blocks:
        for match in formula_ref_re.finditer(block.normalized_text):
            value = match.group(0).strip()
            entities.append(
                StructuredEntity(
                    id=f"ent_{len(entities) + 1:04d}",
                    type="formula_ref",
                    value=value,
                    normalized_value=value.lower(),
                    source="text",
                    text_block_id=block.id,
                    section_id=block.section_id,
                    page_number=block.page_number,
                    confidence=0.62,
                    occurrences=[
                        EntityOccurrence(
                            object_id=block.id,
                            object_type="text_block",
                            position=match.start(),
                        )
                    ],
                )
            )
    return entities


def _build_relations(
    formulas: list[StructuredFormula],
    contexts: list[FormulaContext],
    entities: list[StructuredEntity],
) -> list[StructuredRelation]:
    relations: list[StructuredRelation] = []
    context_by_formula_id = {context.formula_id: context for context in contexts}
    entities_by_formula: dict[str, list[StructuredEntity]] = {}
    for entity in entities:
        if entity.formula_id:
            entities_by_formula.setdefault(entity.formula_id, []).append(entity)
    for formula in formulas:
        context = context_by_formula_id.get(formula.id)
        if context is not None:
            relations.append(
                StructuredRelation(
                    id=f"rel_{len(relations) + 1:04d}",
                    type="has_context",
                    source_id=formula.id,
                    target_id=context.id,
                    evidence=context.window_text[:300],
                    confidence=context.confidence,
                )
            )
            for block_id in context.nearest_text_block_ids:
                relations.append(
                    StructuredRelation(
                        id=f"rel_{len(relations) + 1:04d}",
                        type="near_text",
                        source_id=formula.id,
                        target_id=block_id,
                        evidence=context.window_text[:300],
                        confidence=0.62,
                    )
                )
        for entity in entities_by_formula.get(formula.id, []):
            relations.append(
                StructuredRelation(
                    id=f"rel_{len(relations) + 1:04d}",
                    type="contains_symbol",
                    source_id=formula.id,
                    target_id=entity.id,
                    evidence=formula.latex,
                    confidence=0.7,
                )
            )
            if context is not None and context.definition_markers:
                relations.append(
                    StructuredRelation(
                        id=f"rel_{len(relations) + 1:04d}",
                        type="possibly_defined_by",
                        source_id=entity.id,
                        target_id=context.id,
                        evidence=context.window_text[:300],
                        confidence=0.58,
                    )
                )
    return relations


def _build_formula_links(
    formulas: list[StructuredFormula],
    contexts: list[FormulaContext],
    reading_order: list[ReadingOrderItem],
) -> list[FormulaLink]:
    links: list[FormulaLink] = []
    formula_by_id = {formula.id: formula for formula in formulas}
    formula_by_number = {formula.formula_number: formula for formula in formulas if formula.formula_number}
    for context in contexts:
        source = formula_by_id.get(context.formula_id)
        if source is None:
            continue
        for number in _formula_refs_in_text(context.window_text):
            target = formula_by_number.get(number)
            if target is None or target.id == source.id:
                continue
            links.append(
                FormulaLink(
                    id=f"fl_{len(links) + 1:04d}",
                    source_formula_id=source.id,
                    target_formula_id=target.id,
                    type="references",
                    evidence=context.window_text[:300],
                    confidence=0.6,
                )
            )

    order_formula_ids = [item.object_id for item in reading_order if item.object_type == "formula" and item.object_id in formula_by_id]
    for left_id, right_id in zip(order_formula_ids, order_formula_ids[1:]):
        if _has_formula_link(links, left_id, right_id, "nearby"):
            continue
        links.append(
            FormulaLink(
                id=f"fl_{len(links) + 1:04d}",
                source_formula_id=left_id,
                target_formula_id=right_id,
                type="nearby",
                evidence="adjacent in reading_order",
                confidence=0.35,
            )
        )

    by_symbol: dict[str, list[StructuredFormula]] = {}
    for formula in formulas:
        for symbol in set(formula.symbols):
            by_symbol.setdefault(symbol, []).append(formula)
    seen_same_symbol: set[tuple[str, str]] = set()
    same_symbol_limit = 2500
    for symbol, symbol_formulas in by_symbol.items():
        if len(symbol_formulas) > 48:
            symbol_formulas = symbol_formulas[:48]
        for index, left in enumerate(symbol_formulas):
            for right in symbol_formulas[index + 1 :]:
                key = (left.id, right.id)
                if key in seen_same_symbol:
                    continue
                seen_same_symbol.add(key)
                if _has_formula_link(links, left.id, right.id, "same_symbols"):
                    continue
                links.append(
                    FormulaLink(
                        id=f"fl_{len(links) + 1:04d}",
                        source_formula_id=right.id,
                        target_formula_id=left.id,
                        type="same_symbols",
                        evidence=symbol[:120],
                        confidence=0.45,
                    )
                )
                if len(seen_same_symbol) >= same_symbol_limit:
                    return links
    return links


def _build_graph_seed(
    formulas: list[StructuredFormula],
    contexts: list[FormulaContext],
    entities: list[StructuredEntity],
    relations: list[StructuredRelation],
    formula_links: list[FormulaLink],
) -> GraphSeed:
    nodes: list[GraphSeedNode] = []
    for formula in formulas:
        nodes.append(GraphSeedNode(id=formula.id, type="formula", label=formula.token, source_object_id=formula.id))
    for context in contexts:
        nodes.append(
            GraphSeedNode(
                id=context.id,
                type="formula_context",
                label=f"Context for {context.token}",
                source_object_id=context.id,
            )
        )
    for entity in entities:
        nodes.append(GraphSeedNode(id=entity.id, type=entity.type, label=entity.value, source_object_id=entity.id))

    node_ids = {node.id for node in nodes}
    edges: list[GraphSeedEdge] = []
    for relation in relations:
        if relation.source_id in node_ids and relation.target_id in node_ids:
            edges.append(
                GraphSeedEdge(
                    id=f"edge_{len(edges) + 1:04d}",
                    source=relation.source_id,
                    target=relation.target_id,
                    type=relation.type,
                    confidence=relation.confidence,
                )
            )
    for link in formula_links:
        if link.source_formula_id in node_ids and link.target_formula_id in node_ids:
            edges.append(
                GraphSeedEdge(
                    id=f"edge_{len(edges) + 1:04d}",
                    source=link.source_formula_id,
                    target=link.target_formula_id,
                    type=f"formula_{link.type}",
                    confidence=link.confidence,
                )
            )
    return GraphSeed(nodes=nodes, edges=edges)


def _build_initial_warnings(
    result: ProcessingResult,
    pages: list[StructuredPage],
    formulas: list[StructuredFormula],
    regions: list[StructuredFormulaRegion],
) -> list[WarningItem]:
    warnings = [WarningItem(code="legacy_warning", message=warning) for warning in result.warnings]
    poor_pages = [page.id for page in pages if page.text_layer.quality == "poor"]
    missing_pages = [page.id for page in pages if page.text_layer.quality == "missing"]
    if missing_pages:
        warnings.append(WarningItem(code="text_layer_missing", message="Some pages do not have an embedded text layer.", object_ids=missing_pages))
    if poor_pages:
        warnings.append(WarningItem(code="text_layer_poor", message="Some pages have a poor embedded text layer.", object_ids=poor_pages))
    missing_latex = [formula.id for formula in formulas if not formula.latex]
    if missing_latex:
        warnings.append(WarningItem(code="formula_recognition_partial", message="Some detected formula regions have no recognized LaTeX.", object_ids=missing_latex))
    if regions and not formulas:
        warnings.append(WarningItem(code="formula_detection_partial", message="Formula regions were detected but logical formulas were not built."))
    return warnings


def _quality_flags(formula: FormulaBlock, final_bbox: StructuredBBox | None) -> list[str]:
    flags = list(formula.quality_flags)
    if not formula.latex:
        flags.append("latex_missing")
    if final_bbox is None:
        flags.append("bbox_missing")
    if formula.confidence is not None and formula.confidence < 0.5:
        flags.append("low_confidence")
    if formula.kind == "unknown":
        flags.append("kind_unknown")
    return _dedupe(flags)


def _nearest_text(
    position: int,
    reading_order: list[ReadingOrderItem],
    block_by_id: dict[str, StructuredTextBlock],
    *,
    step: int,
) -> StructuredTextBlock | None:
    if position < 0:
        return None
    index = position + step
    while 0 <= index < len(reading_order):
        item = reading_order[index]
        if item.object_type == "text_block" and item.object_id in block_by_id:
            return block_by_id[item.object_id]
        index += step
    return None


def _nearest_block_by_distance(formula: StructuredFormula, text_blocks: list[StructuredTextBlock]) -> StructuredTextBlock | None:
    if not formula.bbox:
        return next((block for block in text_blocks if block.page_number == formula.page_number), None)
    candidates = [block for block in text_blocks if block.page_number == formula.page_number and block.bbox]
    if not candidates:
        return None
    return min(candidates, key=lambda block: _bbox_distance(formula.bbox, block.bbox or []))


def _nearest_context_blocks_by_bbox(
    formula: StructuredFormula,
    text_blocks: list[StructuredTextBlock],
) -> tuple[StructuredTextBlock | None, StructuredTextBlock | None]:
    page_blocks = [block for block in text_blocks if block.page_number == formula.page_number and block.bbox]
    if not page_blocks:
        return None, None
    if not formula.bbox:
        ordered = sorted(page_blocks, key=lambda block: _spatial_key(block.page_number, block.bbox))
        return (ordered[0], ordered[1] if len(ordered) > 1 else None)

    fx0, fy0, fx1, fy1 = formula.bbox
    before: list[tuple[float, StructuredTextBlock]] = []
    after: list[tuple[float, StructuredTextBlock]] = []
    overlapping: list[tuple[float, StructuredTextBlock]] = []
    for block in page_blocks:
        if block.bbox is None:
            continue
        bx0, by0, bx1, by1 = block.bbox
        if by1 <= fy0:
            before.append((fy0 - by1 + abs(((fx0 + fx1) / 2) - ((bx0 + bx1) / 2)) * 0.05, block))
        elif by0 >= fy1:
            after.append((by0 - fy1 + abs(((fx0 + fx1) / 2) - ((bx0 + bx1) / 2)) * 0.05, block))
        else:
            overlapping.append((_bbox_distance(formula.bbox, block.bbox), block))

    before_block = min(before, key=lambda item: item[0])[1] if before else None
    after_block = min(after, key=lambda item: item[0])[1] if after else None
    if before_block is None and overlapping:
        before_block = min(overlapping, key=lambda item: item[0])[1]
    if after_block is None:
        remaining = [item for item in overlapping if item[1] is not before_block]
        if remaining:
            after_block = min(remaining, key=lambda item: item[0])[1]
    return before_block, after_block


def _nearest_region(formula: FormulaBlock, regions: list[StructuredFormulaRegion]) -> StructuredFormulaRegion | None:
    bbox = _bbox_to_list(formula.bbox)
    if not bbox:
        return None
    same_page = [region for region in regions if region.page_number == formula.page_number and region.bbox]
    if not same_page:
        return None
    return min(same_page, key=lambda region: _bbox_distance(bbox, region.bbox or []))


def _bbox_distance(left: StructuredBBox, right: StructuredBBox) -> float:
    if len(left) != 4 or len(right) != 4:
        return 10_000_000.0
    return abs(((left[0] + left[2]) / 2) - ((right[0] + right[2]) / 2)) + abs(((left[1] + left[3]) / 2) - ((right[1] + right[3]) / 2))


def _spatial_key(page_number: int, bbox: StructuredBBox | None) -> tuple[int, float, float]:
    if not bbox:
        return page_number, 10_000_000.0, 10_000_000.0
    return page_number, bbox[1], bbox[0]


def _legacy_section_rank(section_id: str | None) -> float:
    if not section_id:
        return -1.0
    match = re.search(r"(\d+)$", section_id)
    if match:
        return float(match.group(1))
    return 10_000_000.0


def _bbox_to_list(bbox: Any) -> StructuredBBox | None:
    if bbox is None:
        return None
    values = list(bbox)
    if len(values) != 4:
        return None
    return [float(value) for value in values]


def _block_type(block: LegacyTextBlock) -> str:
    role = (block.role or "").lower()
    if role in {"section", "subsection", "subsubsection", "chapter", "part"}:
        return "heading"
    if role in {"title", "author", "abstract", "heading", "paragraph", "caption", "list_item", "footer"}:
        return role
    text = block.text.strip()
    if len(text) < 120 and text.isupper():
        return "heading"
    return "paragraph" if text else "unknown"


def _formula_kind(kind: str) -> str:
    return {"inline": "inline_math", "block": "display_math", "display": "display_math"}.get(kind, "unknown")


def _source_name(source: str) -> str:
    return {
        "regex": "ocr_regex",
        "text_pattern": "ocr_regex",
        "text_inline_pattern": "ocr_regex",
        "pp_structure_v3": "ppstructure",
        "pp_formula_net": "pp_formulanet",
        "detector": "heuristic",
    }.get(source, source or "unknown")


def _source_type(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}:
        return "image"
    return "unknown"


def _detect_document_title(blocks: list[StructuredTextBlock]) -> str | None:
    for block in blocks[:20]:
        if block.type == "title" and block.normalized_text:
            return block.normalized_text[:260]
    candidates = [
        block
        for block in blocks[:12]
        if 8 <= len(block.normalized_text) <= 260 and block.type not in {"author", "abstract"} and not _looks_like_section_heading(block)
    ]
    if not candidates:
        return blocks[0].normalized_text[:260] if blocks else None
    return min(candidates, key=lambda block: (block.page_number, block.bbox[1] if block.bbox else 10_000.0)).normalized_text


def _detect_document_authors(blocks: list[StructuredTextBlock]) -> list[str]:
    for block in blocks[:20]:
        if block.type == "author" and block.normalized_text:
            return [
                part.strip()
                for part in re.split(r"\s*(?:;|\band\b|,)\s*", block.normalized_text)
                if part.strip()
            ][:12]
    return []


def _detect_abstract(blocks: list[StructuredTextBlock]) -> str | None:
    for index, block in enumerate(blocks[:40]):
        text = block.normalized_text.strip()
        lower = text.lower()
        if block.type == "abstract" and text:
            return text
        if lower.startswith("abstract"):
            value = re.sub(r"^abstract\.?\s*[:.-]?\s*", "", text, flags=re.IGNORECASE).strip()
            if value:
                return value
            return _join_following_blocks(blocks, index + 1, 3)
        if lower.startswith("аннотация"):
            value = re.sub(r"^аннотация\.?\s*[:.-]?\s*", "", text, flags=re.IGNORECASE).strip()
            if value:
                return value
            return _join_following_blocks(blocks, index + 1, 3)
    return None


def _join_following_blocks(blocks: list[StructuredTextBlock], start: int, limit: int) -> str | None:
    parts = [block.normalized_text for block in blocks[start : start + limit] if block.normalized_text]
    value = " ".join(parts).strip()
    return value or None


def _looks_like_section_heading(block: StructuredTextBlock) -> bool:
    text = block.normalized_text.strip()
    if not text or len(text) > 180:
        return False
    if block.type == "heading" and len(text) <= 180:
        return True
    if block.type in {"title", "author", "abstract"}:
        return False
    if re.match(r"^\d+(?:\.\d+)*\.?\s+\S+", text):
        return True
    return bool(SECTION_MARKERS_RE.match(text))


def _normalize_section_title(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip().lower()


def _section_level(title: str) -> int:
    match = re.match(r"^\s*(\d+(?:\.\d+)*)", title)
    if not match:
        return 1
    return min(6, match.group(1).count(".") + 1)


def _detect_formula_number(formula: StructuredFormula, context: FormulaContext | None) -> str | None:
    latex = formula.latex or ""
    tag = re.search(r"\\tag\{([^{}]{1,20})\}", latex)
    if tag:
        return tag.group(1).strip()
    label = re.search(r"\\label\{([^{}]{1,80})\}", latex)
    if label:
        return label.group(1).strip()
    text = context.window_text if context else ""
    refs = _formula_refs_in_text(text)
    if refs:
        return refs[0]
    return None


def _formula_refs_in_text(text: str) -> list[str]:
    refs: list[str] = []
    for match in re.finditer(r"(?:equation|eq\.?|формула)?\s*\((\d{1,4}[a-zA-Z]?)\)", text or "", re.IGNORECASE):
        refs.append(match.group(1))
    return _dedupe(refs)


def _semantic_hints(formula: StructuredFormula, context: FormulaContext | None) -> FormulaSemanticHints:
    latex = formula.latex or ""
    lower_context = (context.window_text if context else "").lower()
    definition_like = bool(_definition_markers(lower_context))
    theorem_like = any(marker in lower_context for marker in ("theorem", "lemma", "proof", "теорема", "лемма", "доказательство"))
    optimization_like = any(marker in latex for marker in ("\\min", "\\max", "\\argmin", "\\argmax")) or any(
        marker in lower_context for marker in ("minimize", "maximize", "arg min", "arg max", "минимиз", "максимиз")
    )
    return FormulaSemanticHints(
        definition_like=definition_like,
        theorem_like=theorem_like,
        optimization_like=optimization_like,
        contains_equality="=" in latex,
        contains_inequality=bool(re.search(r"(?:<|>|\\leq?|\\geq?|\\lt|\\gt)", latex)),
        contains_sum="\\sum" in latex,
        contains_integral="\\int" in latex,
        contains_fraction="\\frac" in latex,
        contains_matrix=any(marker in latex for marker in ("matrix", "pmatrix", "bmatrix", "array", "cases")),
    )


def _has_formula_link(links: list[FormulaLink], source_id: str, target_id: str, link_type: str) -> bool:
    return any(
        link.type == link_type
        and {link.source_formula_id, link.target_formula_id} == {source_id, target_id}
        for link in links
    )


def _ocr_lang_reason(requested: str | None, resolved: str | None) -> str:
    requested = (requested or "unknown").lower()
    resolved = (resolved or "unknown").lower()
    if requested in {"en", "ru"}:
        return "requested_explicitly"
    if requested == "auto" and resolved in {"en", "ru"}:
        return "auto_detected_from_text_layer_or_fallback"
    return "not_provided"


def _refresh_summary(doc: StructuredDocument) -> None:
    doc.summary = StructuredSummary(
        pages_count=len(doc.pages),
        text_blocks_count=len(doc.text_blocks),
        formula_regions_count=len(doc.formula_regions),
        formulas_count=len(doc.formulas),
        tokens_in_text_count=len(TOKEN_RE.findall(doc.text_with_tokens or "")),
        formula_contexts_count=len(doc.formula_contexts),
        entities_count=len(doc.entities),
        relations_count=len(doc.relations),
        warnings_count=len(doc.warnings),
        status=doc.status,
    )


def _overall_text_layer_quality(pages: list[StructuredPage]) -> Literal["good", "poor", "missing"]:
    qualities = [page.text_layer.quality for page in pages]
    if not qualities or all(quality == "missing" for quality in qualities):
        return "missing"
    if any(quality == "poor" for quality in qualities):
        return "poor"
    return "good"


def _formula_detection_status(regions: list[StructuredFormulaRegion]) -> Literal["ok", "partial", "failed"]:
    if not regions:
        return "failed"
    return "partial" if any(region.bbox is None for region in regions) else "ok"


def _formula_recognition_status(formulas: list[StructuredFormula]) -> Literal["ok", "partial", "failed"]:
    if not formulas:
        return "failed"
    missing = [formula for formula in formulas if not formula.latex]
    if len(missing) == len(formulas):
        return "failed"
    return "partial" if missing else "ok"


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _normalize_latex(latex: str) -> str:
    return re.sub(r"\s+", " ", latex or "").strip()


def _normalize_token_text(text: str) -> str:
    value = re.sub(r"\n{3,}", "\n\n", text)
    value = re.sub(r"[ \t]+", " ", value)
    return value.strip()


def _tokens_in_text(text: str) -> list[str]:
    return _dedupe(match.group(0) for match in TOKEN_RE.finditer(text or ""))


def _definition_markers(text: str) -> list[str]:
    lower = text.lower()
    return [marker for marker in DEFINITION_MARKERS if marker in lower]


def _extract_symbols(latex: str) -> list[str]:
    symbols: list[str] = []
    styled_spans: list[tuple[int, int]] = []
    for match in STYLE_SYMBOL_RE.finditer(latex or ""):
        symbols.append(re.sub(r"\s+", "", match.group(0)))
        styled_spans.append(match.span())
    latex_without_styled = _mask_spans(latex or "", styled_spans)
    for command in re.findall(r"\\([A-Za-z]+)", latex_without_styled):
        if command in GREEK_COMMANDS and command not in LATEX_OPERATOR_COMMANDS:
            symbols.append("\\" + command)
    latex_without_commands = re.sub(r"\\[A-Za-z]+", " ", latex_without_styled)
    indexed_spans: list[tuple[int, int]] = []
    indexed_re = re.compile(r"(?<!\\)\b([A-Za-z])_\{?([A-Za-z0-9]+)\}?")
    for match in indexed_re.finditer(latex_without_commands):
        symbol, subscript = match.groups()
        symbols.append(f"{symbol}_{subscript}")
        indexed_spans.append(match.span())
    masked = _mask_spans(latex_without_commands, indexed_spans)
    for symbol in re.findall(r"(?<!\\)\b[A-Za-z]\b", masked):
        symbols.append(symbol)
    for symbol in latex_without_commands:
        if symbol in UNICODE_GREEK_SYMBOLS:
            symbols.append(symbol)
    return _dedupe(symbols)


def _mask_spans(text: str, spans: list[tuple[int, int]]) -> str:
    chars = list(text)
    for start, end in spans:
        for index in range(start, min(end, len(chars))):
            chars[index] = " "
    return "".join(chars)


def _extract_operators(latex: str) -> list[str]:
    operator_pattern = "|".join(sorted((re.escape(item) for item in LATEX_OPERATOR_COMMANDS), key=len, reverse=True))
    return _dedupe(
        re.findall(
            rf"\\(?:{operator_pattern})|[=+\-*/^_<>]",
            latex or "",
        )
    )


def _dedupe(values) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
