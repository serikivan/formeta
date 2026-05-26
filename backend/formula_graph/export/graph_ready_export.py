from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.formula_graph.export.structured_document import (
    FormulaContext as StructuredFormulaContext,
    StructuredDocument,
    StructuredFormula,
    StructuredTextBlock,
)
from backend.formula_graph.models import ProcessingResult, TextBlock
from backend.formula_graph.semantic.rules import extract_definition_evidence


TOKEN_RE = re.compile(r"\[FORMULA_(\d{3})\]")
WORD_RE = re.compile(r"(?<!\\)\b[A-Za-z]\b")
INDEXED_RE = re.compile(r"(?<!\\)\b([A-Za-z])_\{?([A-Za-z0-9]+)\}?")
COMMAND_RE = re.compile(r"\\[A-Za-z]+")
STYLE_SYMBOL_RE = re.compile(r"\\(?:mathbb|mathcal|mathfrak|mathscr|mathbf|mathit|mathrm)\s*\{\s*([A-Za-zα-ωΑ-Ω])\s*\}")
TEXT_VARIABLE_RE = re.compile(r"\b[A-Z]_[A-Za-z0-9]+\b|\b[A-Z]\b|\b[A-Za-z]\([A-Za-z]\)")
INFIX_OPERATOR_CHARS = set("=+-*/^<>")
OPERATOR_WORDS = {
    "equals",
    "plus",
    "minus",
    "times",
    "divide",
    "power",
    "fraction",
    "sum",
    "product",
    "integral",
    "limit",
    "composition",
    "ellipsis",
}
STYLE_COMMANDS = {"\\mathbb", "\\mathcal", "\\mathfrak", "\\mathscr", "\\mathbf", "\\mathit", "\\mathrm"}

IGNORED_COMMANDS = {
    "\\frac",
    "\\tfrac",
    "\\dfrac",
    "\\cfrac",
    "\\binom",
    "\\tbinom",
    "\\dbinom",
    "\\sum",
    "\\prod",
    "\\int",
    "\\iint",
    "\\iiint",
    "\\oint",
    "\\sin",
    "\\cos",
    "\\tan",
    "\\log",
    "\\ln",
    "\\exp",
    "\\sqrt",
    "\\left",
    "\\right",
    "\\cdot",
    "\\times",
    "\\div",
    "\\begin",
    "\\end",
    "\\mathrm",
    "\\mathbf",
    "\\mathit",
    "\\operatorname",
    "\\text",
    "\\mbox",
    "\\lim",
    "\\min",
    "\\max",
    "\\argmin",
    "\\argmax",
    "\\det",
    "\\ker",
    "\\dim",
    "\\deg",
    "\\gcd",
    "\\lcm",
    "\\mod",
    "\\bmod",
    "\\pmod",
    "\\Pr",
    "\\Re",
    "\\Im",
    "\\sup",
    "\\inf",
    "\\limsup",
    "\\liminf",
    "\\le",
    "\\leq",
    "\\ge",
    "\\geq",
    "\\ne",
    "\\neq",
    "\\approx",
    "\\sim",
    "\\equiv",
    "\\in",
    "\\notin",
    "\\subset",
    "\\subseteq",
    "\\supset",
    "\\supseteq",
    "\\cup",
    "\\cap",
    "\\setminus",
    "\\forall",
    "\\exists",
    "\\land",
    "\\lor",
    "\\neg",
    "\\to",
    "\\mapsto",
    "\\rightarrow",
    "\\leftarrow",
    "\\Rightarrow",
    "\\Leftrightarrow",
    "\\partial",
    "\\nabla",
    "\\infty",
    "\\label",
    "\\tag",
    "\\cdots",
    "\\dots",
    "\\ldots",
    "\\vdots",
    "\\ddots",
    "\\circ",
    "\\quad",
    "\\qquad",
    "\\mathbb",
    "\\mathcal",
    "\\mathfrak",
    "\\mathscr",
}
OPERATOR_COMMANDS = {
    "\\frac",
    "\\tfrac",
    "\\dfrac",
    "\\cfrac",
    "\\binom",
    "\\tbinom",
    "\\dbinom",
    "\\sum",
    "\\prod",
    "\\int",
    "\\iint",
    "\\iiint",
    "\\oint",
    "\\sin",
    "\\cos",
    "\\tan",
    "\\log",
    "\\ln",
    "\\exp",
    "\\sqrt",
    "\\lim",
    "\\min",
    "\\max",
    "\\argmin",
    "\\argmax",
    "\\det",
    "\\ker",
    "\\dim",
    "\\deg",
    "\\gcd",
    "\\lcm",
    "\\mod",
    "\\bmod",
    "\\pmod",
    "\\Pr",
    "\\Re",
    "\\Im",
    "\\sup",
    "\\inf",
    "\\limsup",
    "\\liminf",
    "\\le",
    "\\leq",
    "\\ge",
    "\\geq",
    "\\ne",
    "\\neq",
    "\\approx",
    "\\sim",
    "\\equiv",
    "\\in",
    "\\notin",
    "\\subset",
    "\\subseteq",
    "\\supset",
    "\\supseteq",
    "\\cup",
    "\\cap",
    "\\setminus",
    "\\forall",
    "\\exists",
    "\\land",
    "\\lor",
    "\\neg",
    "\\to",
    "\\mapsto",
    "\\rightarrow",
    "\\leftarrow",
    "\\Rightarrow",
    "\\Leftrightarrow",
    "\\partial",
    "\\nabla",
    "\\cdot",
    "\\times",
    "\\div",
    "\\cdots",
    "\\dots",
    "\\ldots",
    "\\vdots",
    "\\ddots",
    "\\circ",
}
IGNORED_SYMBOL_WORDS = {
    "cases",
    "matrix",
    "pmatrix",
    "bmatrix",
    "vmatrix",
    "array",
    "align",
    "aligned",
    "equation",
    "split",
    "gather",
    "gathered",
    "operator",
    "operand",
    "lhs",
    "rhs",
    "root",
    "cdot",
    "times",
    "div",
    "circ",
    "cdots",
    "dots",
    "ldots",
    "vdots",
    "ddots",
    "quad",
    "qquad",
    "mathbb",
    "mathcal",
    "mathfrak",
    "mathscr",
    "mathbf",
    "mathit",
    "mathrm",
    "mbox",
    "where",
    "if",
    "then",
    "for",
    "and",
    "or",
}

GREEK_ALIASES = {
    "alpha": "\\alpha",
    "α": "\\alpha",
    "\\alpha": "\\alpha",
    "beta": "\\beta",
    "β": "\\beta",
    "\\beta": "\\beta",
    "gamma": "\\gamma",
    "γ": "\\gamma",
    "\\gamma": "\\gamma",
    "delta": "\\delta",
    "δ": "\\delta",
    "\\delta": "\\delta",
    "lambda": "\\lambda",
    "λ": "\\lambda",
    "\\lambda": "\\lambda",
    "mu": "\\mu",
    "μ": "\\mu",
    "\\mu": "\\mu",
    "sigma": "\\sigma",
    "σ": "\\sigma",
    "\\sigma": "\\sigma",
    "phi": "\\phi",
    "φ": "\\phi",
    "\\phi": "\\phi",
    "varphi": "\\varphi",
    "\\varphi": "\\varphi",
    "theta": "\\theta",
    "θ": "\\theta",
    "\\theta": "\\theta",
    "omega": "\\omega",
    "ω": "\\omega",
    "\\omega": "\\omega",
}

DEFINITION_MARKERS = (
    "where",
    "denotes",
    "denote",
    "defined as",
    "is defined as",
    "let",
    "represents",
    "обозначает",
    "где",
    "определяется как",
    "задается как",
    "задаётся как",
    "пусть",
)


class GraphReadyWarning(BaseModel):
    code: str
    message: str
    object_ids: list[str] = Field(default_factory=list)


class GraphReadySection(BaseModel):
    id: str
    title: str
    level: int = 1
    order: int = 1
    parent_id: str | None = None
    text_block_ids: list[str] = Field(default_factory=list)
    formula_tokens: list[str] = Field(default_factory=list)


class GraphReadyStructure(BaseModel):
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    abstract: str | None = None
    language: Literal["ru", "en", "unknown"] = "unknown"
    sections: list[GraphReadySection] = Field(default_factory=list)


class GraphReadyTextBlock(BaseModel):
    id: str
    type: str = "unknown"
    page_number: int = 1
    section_id: str | None = None
    order: int
    text: str
    text_with_tokens: str
    formula_tokens: list[str] = Field(default_factory=list)
    source: str = "unknown"
    quality_flags: list[str] = Field(default_factory=list)


class FormulaSemanticHints(BaseModel):
    definition_like: bool = False
    contains_equality: bool = False
    contains_inequality: bool = False
    contains_sum: bool = False
    contains_integral: bool = False
    contains_fraction: bool = False
    contains_matrix: bool = False


class FormulaSemanticMetaEdge(BaseModel):
    relation_type: str
    target_ids: list[str] = Field(default_factory=list)
    mediator_context_ids: list[str] = Field(default_factory=list)
    description: str = ""


class FormulaMetavertexSemantics(BaseModel):
    semantic_type: Literal["formula_metavertex"] = "formula_metavertex"
    metavertex_id: str | None = None
    outer_document_object: Literal["document_formula_object"] = "document_formula_object"
    inner_expression_object: Literal["ast_like_expression_graph"] = "ast_like_expression_graph"
    internal_roles: list[str] = Field(
        default_factory=lambda: [
            "root_operation",
            "subformula",
            "operand",
            "numerator_denominator",
            "base_exponent",
            "function_argument",
            "bound_limit",
            "symbol_leaf",
        ]
    )
    section_id: str | None = None
    context_ids: list[str] = Field(default_factory=list)
    paragraph_ids: list[str] = Field(default_factory=list)
    variable_ids: list[str] = Field(default_factory=list)
    metaedges: list[FormulaSemanticMetaEdge] = Field(default_factory=list)


class GraphReadyFormula(BaseModel):
    id: str
    token: str
    kind: Literal["inline_math", "display_math", "unknown"] = "unknown"
    latex: str = ""
    raw_latex: str = ""
    cleaned_latex: str = ""
    normalized_latex: str = ""
    plain_formula_text: str = ""
    source: str = "unknown"
    confidence: float | None = None
    section_id: str | None = None
    order: int
    formula_number: str | None = None
    symbols: list[str] = Field(default_factory=list)
    operators: list[str] = Field(default_factory=list)
    semantic_hints: FormulaSemanticHints = Field(default_factory=FormulaSemanticHints)
    meta_semantics: FormulaMetavertexSemantics = Field(default_factory=FormulaMetavertexSemantics)
    quality_flags: list[str] = Field(default_factory=list)


class PossibleDefinition(BaseModel):
    symbol: str
    definition_text: str
    evidence: str
    confidence: float = 0.7
    rule: str | None = None
    source: str = "rule_based"
    language: str | None = None


class GraphReadyFormulaContext(BaseModel):
    id: str
    formula_id: str
    token: str
    section_id: str | None = None
    context_before: str = ""
    context_after: str = ""
    window_text: str = ""
    nearest_text_block_ids: list[str] = Field(default_factory=list)
    definition_markers: list[str] = Field(default_factory=list)
    mentioned_symbols: list[str] = Field(default_factory=list)
    possible_definitions: list[PossibleDefinition] = Field(default_factory=list)
    quality_flags: list[str] = Field(default_factory=list)


class GraphReadyParagraph(BaseModel):
    id: str
    page_id: str
    page_number: int
    order: int
    text: str
    sentence_ids: list[str] = Field(default_factory=list)
    formula_tokens: list[str] = Field(default_factory=list)
    formula_ids: list[str] = Field(default_factory=list)
    source: str = "unknown"


class GraphReadyVariable(BaseModel):
    id: str
    symbol: str
    normalized_symbol: str
    latex: str
    formula_ids: list[str] = Field(default_factory=list)
    context_ids: list[str] = Field(default_factory=list)
    section_ids: list[str] = Field(default_factory=list)
    possible_definitions: list[dict[str, Any]] = Field(default_factory=list)
    usage_count: int = 0
    quality_flags: list[str] = Field(default_factory=list)


class GraphReadyRelation(BaseModel):
    id: str
    type: str
    source_id: str
    target_id: str
    evidence: str | None = None
    confidence: float | None = None


class GraphReadySummary(BaseModel):
    sections_count: int = 0
    text_blocks_count: int = 0
    formulas_count: int = 0
    variables_count: int = 0
    contexts_count: int = 0
    relations_count: int = 0
    warnings_count: int = 0


class GraphReadyDocument(BaseModel):
    schema_version: str = "1.1"
    document_id: str
    filename: str
    source_type: str = "unknown"
    status: Literal["ok", "partial", "error"]
    document_structure: GraphReadyStructure = Field(default_factory=GraphReadyStructure)
    text_blocks: list[GraphReadyTextBlock] = Field(default_factory=list)
    paragraphs: list[GraphReadyParagraph] = Field(default_factory=list)
    text_with_tokens: str = ""
    formulas: list[GraphReadyFormula] = Field(default_factory=list)
    formula_contexts: list[GraphReadyFormulaContext] = Field(default_factory=list)
    variables: list[GraphReadyVariable] = Field(default_factory=list)
    relations: list[GraphReadyRelation] = Field(default_factory=list)
    processing_steps: list[dict[str, Any]] = Field(default_factory=list)
    timing: dict[str, Any] = Field(default_factory=dict)
    summary: GraphReadySummary = Field(default_factory=GraphReadySummary)
    warnings: list[GraphReadyWarning] = Field(default_factory=list)


def build_graph_ready_document(
    result: ProcessingResult,
    structured: StructuredDocument,
    *,
    source_type: str | None = None,
) -> GraphReadyDocument:
    text_blocks = _build_graph_text_blocks(structured.text_blocks)
    formulas = _build_graph_formulas(structured.formulas, structured.reading_order)
    text_with_tokens = _best_text_with_tokens(result, structured)
    contexts = _build_graph_contexts(formulas, text_blocks, structured.formula_contexts, text_with_tokens)
    paragraphs = _build_graph_paragraphs(text_blocks, formulas, contexts)
    variables = _build_variables(formulas, contexts, structured.entities, text_blocks)
    document_structure = _build_graph_structure(structured, text_blocks, formulas)
    relations = _build_relations(document_structure.sections, text_blocks, formulas, contexts, variables)
    _attach_formula_meta_semantics(formulas, contexts, paragraphs, relations, variables)
    warnings = _initial_warnings(structured)

    doc = GraphReadyDocument(
        document_id=result.document_id,
        filename=result.filename,
        source_type=source_type or _source_type_from_profile(structured),
        status=result.status,
        document_structure=document_structure,
        text_blocks=text_blocks,
        paragraphs=paragraphs,
        text_with_tokens=text_with_tokens,
        formulas=formulas,
        formula_contexts=contexts,
        variables=variables,
        relations=relations,
        processing_steps=list(result.processing_steps or []),
        timing=dict(result.timing or {}),
        warnings=warnings,
    )
    doc.warnings.extend(validate_graph_ready_document(doc))
    _refresh_summary(doc)
    if doc.status == "ok" and doc.warnings:
        doc.status = "partial"
        doc.summary.warnings_count = len(doc.warnings)
    return doc


def _attach_formula_meta_semantics(
    formulas: list[GraphReadyFormula],
    contexts: list[GraphReadyFormulaContext],
    paragraphs: list[GraphReadyParagraph],
    relations: list[GraphReadyRelation],
    variables: list[GraphReadyVariable],
) -> None:
    context_ids_by_formula: dict[str, list[str]] = defaultdict(list)
    for context in contexts:
        context_ids_by_formula[context.formula_id].append(context.id)

    paragraph_ids_by_formula: dict[str, list[str]] = defaultdict(list)
    for paragraph in paragraphs:
        for formula_id in paragraph.formula_ids:
            paragraph_ids_by_formula[formula_id].append(paragraph.id)

    variable_ids_by_formula: dict[str, list[str]] = defaultdict(list)
    for variable in variables:
        for formula_id in variable.formula_ids:
            variable_ids_by_formula[formula_id].append(variable.id)

    relation_refs_by_formula: dict[str, list[FormulaSemanticMetaEdge]] = defaultdict(list)
    for relation in relations:
        if relation.type not in {"has_context", "formula_dependency", "formula_references_formula", "depends_on", "contains_symbol", "possibly_defined_by"}:
            continue
        if relation.source_id.startswith("f") or relation.source_id.startswith("formula_"):
            relation_refs_by_formula[relation.source_id].append(
                FormulaSemanticMetaEdge(
                    relation_type=relation.type,
                    target_ids=[relation.target_id],
                    description=_metaedge_description(relation.type),
                )
            )
        if relation.target_id.startswith("f") or relation.target_id.startswith("formula_"):
            relation_refs_by_formula[relation.target_id].append(
                FormulaSemanticMetaEdge(
                    relation_type=relation.type,
                    target_ids=[relation.source_id],
                    description=_metaedge_description(relation.type),
                )
            )

    for context in contexts:
        if not context.possible_definitions:
            continue
        relation_refs_by_formula[context.formula_id].append(
            FormulaSemanticMetaEdge(
                relation_type="definition_context",
                target_ids=[context.id],
                mediator_context_ids=[context.id],
                description="Metaedge between the formula, its textual definition window, and extracted symbol definitions.",
            )
        )

    for formula in formulas:
        formula.meta_semantics = FormulaMetavertexSemantics(
            metavertex_id=f"{formula.id}_mv",
            section_id=formula.section_id,
            context_ids=_dedupe(context_ids_by_formula.get(formula.id, [])),
            paragraph_ids=_dedupe(paragraph_ids_by_formula.get(formula.id, [])),
            variable_ids=_dedupe(variable_ids_by_formula.get(formula.id, [])),
            metaedges=_dedupe_metaedges(
                [
                    FormulaSemanticMetaEdge(
                        relation_type="document_context",
                        target_ids=_dedupe(
                            [
                                *context_ids_by_formula.get(formula.id, []),
                                *paragraph_ids_by_formula.get(formula.id, []),
                                *([formula.section_id] if formula.section_id else []),
                            ]
                        ),
                        mediator_context_ids=_dedupe(context_ids_by_formula.get(formula.id, [])),
                        description="Metaedge that anchors the formula metavertex in section, paragraph, and local textual context.",
                    ),
                    *relation_refs_by_formula.get(formula.id, []),
                ]
            ),
        )


def _metaedge_description(relation_type: str) -> str:
    return {
        "has_context": "Binary document link from formula to its context window.",
        "formula_dependency": "Metaedge describing dependency between this formula and neighboring formulas.",
        "formula_references_formula": "Document-level relation between formulas that reference each other.",
        "depends_on": "Directed dependency based on shared symbols and reading order.",
        "contains_symbol": "Document relation that links the formula to mentioned notation.",
        "possibly_defined_by": "Heuristic definition relation for a symbol used by the formula.",
    }.get(relation_type, "Semantic relation connected to the formula metavertex.")


def _dedupe_metaedges(items: list[FormulaSemanticMetaEdge]) -> list[FormulaSemanticMetaEdge]:
    seen: set[tuple[str, tuple[str, ...], tuple[str, ...]]] = set()
    result: list[FormulaSemanticMetaEdge] = []
    for item in items:
        key = (
            item.relation_type,
            tuple(item.target_ids),
            tuple(item.mediator_context_ids),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def save_graph_ready_document(doc: GraphReadyDocument, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(doc.model_dump_json(indent=2), encoding="utf-8")


def load_graph_ready_document(path: Path) -> GraphReadyDocument:
    doc = GraphReadyDocument.model_validate_json(path.read_text(encoding="utf-8"))
    changed = _sanitize_graph_ready_document(doc)
    if changed or doc.schema_version != "1.1" or _graph_ready_needs_meta_semantics(doc):
        _attach_formula_meta_semantics(doc.formulas, doc.formula_contexts, doc.paragraphs, doc.relations, doc.variables)
        doc.schema_version = "1.1"
        _refresh_summary(doc)
    return doc


def _sanitize_graph_ready_document(doc: GraphReadyDocument) -> bool:
    changed = False
    formula_ids = {formula.id for formula in doc.formulas}

    for formula in doc.formulas:
        latex = formula.normalized_latex or formula.latex or formula.cleaned_latex or formula.raw_latex
        symbol_candidates = extract_formula_symbols(latex) if latex else [normalize_symbol(item) for item in formula.symbols]
        sanitized_symbols = _dedupe(
            symbol
            for symbol in symbol_candidates
            if _is_variable_symbol(symbol)
        )
        sanitized_operators = _extract_operators(latex) if latex else _sanitize_operators(formula.operators)
        if sanitized_symbols != formula.symbols:
            formula.symbols = sanitized_symbols
            changed = True
        if sanitized_operators != formula.operators:
            formula.operators = sanitized_operators
            changed = True

    valid_symbols_by_formula: dict[str, set[str]] = {
        formula.id: set(formula.symbols)
        for formula in doc.formulas
    }

    for ctx in doc.formula_contexts:
        mentioned = _dedupe(normalize_symbol(symbol) for symbol in ctx.mentioned_symbols if _is_variable_symbol(symbol))
        if mentioned != ctx.mentioned_symbols:
            ctx.mentioned_symbols = mentioned
            changed = True
        definitions = []
        for definition in ctx.possible_definitions:
            normalized = normalize_symbol(definition.symbol)
            if not _is_variable_symbol(normalized):
                changed = True
                continue
            if normalized != definition.symbol:
                definition.symbol = normalized
                changed = True
            definitions.append(definition)
        if len(definitions) != len(ctx.possible_definitions):
            ctx.possible_definitions = definitions
            changed = True

    variables_by_symbol: dict[str, GraphReadyVariable] = {}
    variable_id_map: dict[str, str] = {}
    for variable in doc.variables:
        normalized = normalize_symbol(variable.normalized_symbol or variable.symbol or variable.latex)
        if not _is_variable_symbol(normalized):
            changed = True
            continue
        formula_links = _dedupe(
            formula_id
            for formula_id in variable.formula_ids
            if formula_id in formula_ids and normalized in valid_symbols_by_formula.get(formula_id, set())
        )
        if not formula_links and variable.formula_ids:
            changed = True
        has_non_formula_evidence = bool(
            variable.context_ids
            or variable.section_ids
            or variable.possible_definitions
            or "text_mention" in variable.quality_flags
        )
        if not formula_links and not has_non_formula_evidence:
            changed = True
            continue
        existing = variables_by_symbol.get(normalized)
        if existing is None:
            existing = GraphReadyVariable(
                id=variable.id,
                symbol=normalized,
                normalized_symbol=normalized,
                latex=normalized,
                formula_ids=formula_links,
                context_ids=_dedupe(variable.context_ids),
                section_ids=_dedupe(variable.section_ids),
                possible_definitions=_sanitize_variable_definitions(variable.possible_definitions),
                usage_count=variable.usage_count,
                quality_flags=_dedupe(variable.quality_flags),
            )
            variables_by_symbol[normalized] = existing
        else:
            existing.formula_ids = _dedupe(existing.formula_ids + formula_links)
            existing.context_ids = _dedupe(existing.context_ids + variable.context_ids)
            existing.section_ids = _dedupe(existing.section_ids + variable.section_ids)
            existing.possible_definitions = _dedupe_dicts(
                existing.possible_definitions + _sanitize_variable_definitions(variable.possible_definitions)
            )
            existing.quality_flags = _dedupe(existing.quality_flags + variable.quality_flags)
            existing.usage_count = max(existing.usage_count, variable.usage_count)
            changed = True
        variable_id_map[variable.id] = existing.id

    for formula in doc.formulas:
        for symbol in formula.symbols:
            normalized = normalize_symbol(symbol)
            if not _is_variable_symbol(normalized):
                continue
            existing = variables_by_symbol.get(normalized)
            if existing is None:
                existing = GraphReadyVariable(
                    id=f"var_pending_{len(variables_by_symbol) + 1:04d}",
                    symbol=normalized,
                    normalized_symbol=normalized,
                    latex=normalized,
                    formula_ids=[formula.id],
                    section_ids=[formula.section_id] if formula.section_id else [],
                    usage_count=1,
                )
                variables_by_symbol[normalized] = existing
                changed = True
            else:
                before = list(existing.formula_ids)
                _append_unique(existing.formula_ids, formula.id)
                if formula.section_id:
                    _append_unique(existing.section_ids, formula.section_id)
                if existing.formula_ids != before:
                    changed = True

    sanitized_variables = sorted(variables_by_symbol.values(), key=lambda item: item.normalized_symbol)
    for index, variable in enumerate(sanitized_variables, start=1):
        old_id = variable.id
        new_id = f"var_{index:04d}"
        variable.id = new_id
        variable.symbol = variable.normalized_symbol
        variable.latex = variable.normalized_symbol
        variable.formula_ids = _dedupe(variable.formula_ids)
        variable.context_ids = _dedupe(variable.context_ids)
        variable.section_ids = _dedupe(variable.section_ids)
        variable.possible_definitions = _dedupe_dicts(variable.possible_definitions)
        variable.usage_count = max(len(variable.formula_ids), 1 if "text_mention" in variable.quality_flags else 0, variable.usage_count)
        if old_id != new_id:
            changed = True
        for source_id, mapped_id in list(variable_id_map.items()):
            if mapped_id == old_id:
                variable_id_map[source_id] = new_id

    if len(sanitized_variables) != len(doc.variables) or any(old.id != new.id for old, new in zip(doc.variables, sanitized_variables)):
        changed = True
    doc.variables = sanitized_variables

    variable_ids = {variable.id for variable in doc.variables}
    for formula in doc.formulas:
        variable_ids_for_formula = [
            variable.id
            for variable in doc.variables
            if formula.id in variable.formula_ids
        ]
        if formula.meta_semantics.variable_ids != variable_ids_for_formula:
            formula.meta_semantics.variable_ids = variable_ids_for_formula
            changed = True

    remapped_relations: list[GraphReadyRelation] = []
    object_ids = _graph_ready_object_ids(doc)
    for relation in doc.relations:
        source_id = variable_id_map.get(relation.source_id, relation.source_id)
        target_id = variable_id_map.get(relation.target_id, relation.target_id)
        if source_id not in object_ids or target_id not in object_ids:
            changed = True
            continue
        if source_id != relation.source_id or target_id != relation.target_id:
            relation.source_id = source_id
            relation.target_id = target_id
            changed = True
        remapped_relations.append(relation)
    if len(remapped_relations) != len(doc.relations):
        changed = True
    doc.relations = _dedupe_relations(remapped_relations)

    return changed


def _is_variable_symbol(value: str) -> bool:
    normalized = normalize_symbol(value)
    if not normalized:
        return False
    if normalized in IGNORED_COMMANDS or normalized in OPERATOR_COMMANDS:
        return False
    if normalized in INFIX_OPERATOR_CHARS:
        return False
    bare = normalized.lstrip("\\").lower()
    if bare in IGNORED_SYMBOL_WORDS:
        return False
    if bare in {operator.lstrip("\\").lower() for operator in OPERATOR_COMMANDS}:
        return False
    return True


def _sanitize_variable_definitions(definitions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for definition in definitions:
        item = dict(definition)
        raw_symbol = item.get("symbol") or ""
        symbol = normalize_symbol(raw_symbol)
        if raw_symbol and not _is_variable_symbol(symbol):
            continue
        if symbol:
            item["symbol"] = symbol
        sanitized.append(item)
    return _dedupe_dicts(sanitized)


def _dedupe_relations(relations: list[GraphReadyRelation]) -> list[GraphReadyRelation]:
    seen: set[tuple[str, str, str]] = set()
    result: list[GraphReadyRelation] = []
    for relation in relations:
        key = (relation.type, relation.source_id, relation.target_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(relation)
    return result


def _graph_ready_object_ids(doc: GraphReadyDocument) -> set[str]:
    return (
        {item.id for item in doc.formulas}
        | {item.id for item in doc.formula_contexts}
        | {item.id for item in doc.variables}
        | {item.id for item in doc.document_structure.sections}
        | {item.id for item in doc.text_blocks}
    )


def _graph_ready_needs_meta_semantics(doc: GraphReadyDocument) -> bool:
    if not doc.formulas:
        return False
    return any(not getattr(formula.meta_semantics, "metavertex_id", None) for formula in doc.formulas)


def _formula_semantic_payload(formula: GraphReadyFormula) -> dict[str, Any]:
    meta = formula.meta_semantics
    return {
        "semantic_type": meta.semantic_type,
        "metavertex_id": meta.metavertex_id or f"{formula.id}_mv",
        "outer_document_object": meta.outer_document_object,
        "inner_expression_object": meta.inner_expression_object,
        "internal_roles": list(meta.internal_roles),
        "section_id": meta.section_id or formula.section_id,
        "context_ids": list(meta.context_ids),
        "paragraph_ids": list(meta.paragraph_ids),
        "variable_ids": list(meta.variable_ids),
        "metaedges": [item.model_dump() for item in meta.metaedges],
    }


def search_variable_in_graph_ready(doc: GraphReadyDocument, query: str) -> dict[str, Any]:
    normalized_query = normalize_symbol(query)
    if not _is_variable_symbol(normalized_query):
        return {
            "document_id": doc.document_id,
            "query": query,
            "normalized_query": normalized_query,
            "matches_count": 0,
            "variable": None,
            "matches": [],
            "definitions": [],
            "related_variables": [],
            "related_formulas": [],
            "scope": None,
            "neighborhood": {"nodes": [], "edges": []},
        }
    variables = [var for var in doc.variables if var.normalized_symbol == normalized_query]
    fallback = False
    if not variables:
        fallback = True
        variables = _fallback_variables(doc, normalized_query, query)

    if not variables:
        return {
            "document_id": doc.document_id,
            "query": query,
            "normalized_query": normalized_query,
            "matches_count": 0,
            "variable": None,
            "matches": [],
            "definitions": [],
            "related_variables": [],
            "related_formulas": [],
            "scope": None,
            "neighborhood": {"nodes": [], "edges": []},
        }

    variable = variables[0]
    formula_by_id = {formula.id: formula for formula in doc.formulas}
    context_by_formula_id = {ctx.formula_id: ctx for ctx in doc.formula_contexts}
    section_by_id = {section.id: section for section in doc.document_structure.sections}
    variables_by_formula: dict[str, list[str]] = defaultdict(list)
    for item in doc.variables:
        for formula_id in item.formula_ids:
            if item.normalized_symbol != variable.normalized_symbol:
                variables_by_formula[formula_id].append(item.normalized_symbol)

    matches: list[dict[str, Any]] = []
    definitions: list[dict[str, Any]] = []
    related_variables: set[str] = set()
    neighborhood_nodes: dict[str, dict[str, Any]] = {
        variable.id: {"id": variable.id, "type": "variable", "label": variable.normalized_symbol}
    }
    neighborhood_edges: list[dict[str, Any]] = []
    for formula_id in variable.formula_ids:
        formula = formula_by_id.get(formula_id)
        if formula is None:
            continue
        context = context_by_formula_id.get(formula_id)
        section = section_by_id.get(formula.section_id or "")
        context_defs = [
            item.model_dump()
            for item in (context.possible_definitions if context else [])
            if normalize_symbol(item.symbol) == variable.normalized_symbol
        ]
        definitions.extend(context_defs)
        for related in variables_by_formula.get(formula.id, []):
            related_variables.add(related)
        neighborhood_nodes[formula.id] = {
            "id": formula.id,
            "type": "formula",
            "label": formula.token,
            "latex": formula.latex,
            "formula_semantics": _formula_semantic_payload(formula),
        }
        neighborhood_edges.append({"source": variable.id, "target": formula.id, "type": "appears_in", "confidence": 0.82})
        if context:
            neighborhood_nodes[context.id] = {"id": context.id, "type": "context", "label": context.window_text[:80]}
            neighborhood_edges.append({"source": formula.id, "target": context.id, "type": "has_context", "confidence": 0.8})
        matches.append(
            {
                "formula_id": formula.id,
                "token": formula.token,
                "latex": formula.latex,
                "kind": formula.kind,
                "section_id": formula.section_id,
                "section_title": section.title if section else None,
                "matched_symbols": [variable.normalized_symbol],
                "related_variables": sorted(set(variables_by_formula.get(formula.id, []))),
                "context_id": context.id if context else None,
                "context_before": context.context_before if context else "",
                "context_after": context.context_after if context else "",
                "window_text": context.window_text if context else "",
                "definition_markers": context.definition_markers if context else [],
                "possible_definitions": context_defs,
                "confidence": 0.55 if fallback else (0.9 if context else 0.78),
                "scope": _variable_scope(variable),
                "evidence": context_defs,
                "formula_semantics": _formula_semantic_payload(formula),
            }
        )
    if not fallback:
        formula_context_windows = {item.get("window_text", "") for item in matches}
        for block in doc.text_blocks:
            text = block.text_with_tokens or block.text
            if not _mentions_symbol(text, variable.normalized_symbol):
                continue
            if text in formula_context_windows:
                continue
            section = section_by_id.get(block.section_id or "")
            matches.append(
                {
                    "formula_id": None,
                    "token": None,
                    "latex": "",
                    "kind": "text_mention",
                    "section_id": block.section_id,
                    "section_title": section.title if section else None,
                    "matched_symbols": [variable.normalized_symbol],
                    "related_variables": sorted(symbol for symbol in _text_variable_mentions(text) if normalize_symbol(symbol) != variable.normalized_symbol),
                    "context_id": block.id,
                    "context_before": "",
                    "context_after": "",
                    "window_text": text,
                    "definition_markers": _definition_markers(text),
                    "possible_definitions": [],
                    "confidence": 0.62,
                    "scope": _variable_scope(variable),
                    "evidence": [],
                }
            )

    return {
        "document_id": doc.document_id,
        "query": query,
        "normalized_query": normalized_query,
        "matches_count": len(matches),
        "variable": variable.model_dump(),
        "matches": matches,
        "definitions": _dedupe_dicts(definitions),
        "related_variables": sorted(related_variables),
        "related_formulas": [
            {
                "id": formula_id,
                "latex": formula_by_id[formula_id].latex,
                "token": formula_by_id[formula_id].token,
                "formula_semantics": _formula_semantic_payload(formula_by_id[formula_id]),
            }
            for formula_id in variable.formula_ids
            if formula_id in formula_by_id
        ],
        "scope": _variable_scope(variable),
        "neighborhood": {"nodes": list(neighborhood_nodes.values()), "edges": neighborhood_edges},
    }


def validate_graph_ready_document(doc: GraphReadyDocument) -> list[GraphReadyWarning]:
    warnings: list[GraphReadyWarning] = []
    formula_tokens = [formula.token for formula in doc.formulas if formula.token]
    duplicate_tokens = sorted({token for token in formula_tokens if formula_tokens.count(token) > 1})
    if duplicate_tokens:
        warnings.append(GraphReadyWarning(code="duplicate_formula_token", message="Formula tokens must be unique.", object_ids=duplicate_tokens))

    formula_ids = {formula.id for formula in doc.formulas}
    context_ids = {ctx.id for ctx in doc.formula_contexts}
    variable_ids = {var.id for var in doc.variables}
    section_ids = {section.id for section in doc.document_structure.sections}
    text_block_ids = {block.id for block in doc.text_blocks}
    tokens_in_text = set(TOKEN_RE.findall(doc.text_with_tokens or ""))
    full_tokens_in_text = {f"[FORMULA_{number}]" for number in tokens_in_text}

    missing_tokens = [formula.id for formula in doc.formulas if formula.token and formula.token not in full_tokens_in_text]
    if missing_tokens:
        warnings.append(GraphReadyWarning(code="formula_token_not_inserted", message="Some formula tokens are not present in text_with_tokens.", object_ids=missing_tokens))

    for ctx in doc.formula_contexts:
        if ctx.formula_id not in formula_ids:
            warnings.append(GraphReadyWarning(code="formula_context_missing_formula", message="A formula context points to a missing formula.", object_ids=[ctx.id]))
        if ctx.token and ctx.token not in ctx.window_text:
            warnings.append(GraphReadyWarning(code="formula_context_token_missing", message="A formula context window does not contain its token.", object_ids=[ctx.id]))

    for var in doc.variables:
        bad_formula_ids = [formula_id for formula_id in var.formula_ids if formula_id not in formula_ids]
        bad_context_ids = [context_id for context_id in var.context_ids if context_id not in context_ids]
        if bad_formula_ids or bad_context_ids:
            warnings.append(
                GraphReadyWarning(
                    code="variable_reference_missing",
                    message="A variable points to missing formulas or contexts.",
                    object_ids=[var.id, *bad_formula_ids, *bad_context_ids],
                )
            )

    known_ids = formula_ids | context_ids | variable_ids | section_ids | text_block_ids
    invalid_relations = [rel.id for rel in doc.relations if rel.source_id not in known_ids or rel.target_id not in known_ids]
    if invalid_relations:
        warnings.append(GraphReadyWarning(code="relation_reference_missing", message="Some relations point to unknown graph-ready objects.", object_ids=invalid_relations))

    invalid_sections = [
        item.id
        for item in [*doc.text_blocks, *doc.formulas, *doc.formula_contexts]
        if item.section_id and item.section_id not in section_ids
    ]
    if invalid_sections:
        warnings.append(GraphReadyWarning(code="section_reference_missing", message="Some objects point to unknown sections.", object_ids=invalid_sections))

    expected = {
        "sections_count": len(doc.document_structure.sections),
        "text_blocks_count": len(doc.text_blocks),
        "formulas_count": len(doc.formulas),
        "variables_count": len(doc.variables),
        "contexts_count": len(doc.formula_contexts),
        "relations_count": len(doc.relations),
    }
    for field, value in expected.items():
        if getattr(doc.summary, field) not in {0, value}:
            warnings.append(GraphReadyWarning(code="summary_count_mismatch", message=f"Summary field {field} does not match payload.", object_ids=[field]))
    return _dedupe_warnings(warnings)


def normalize_symbol(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    value = value.strip("$")
    value = re.sub(r"\s+", "", value)
    styled = re.fullmatch(r"\\(mathbb|mathcal|mathfrak|mathscr|mathbf|mathit|mathrm)\{([^{}]+)\}", value)
    if styled:
        inner = normalize_symbol(styled.group(2))
        if inner and re.fullmatch(r"\\?[A-Za-zα-ωΑ-Ω](?:_[A-Za-z0-9]+)?", inner):
            return f"\\{styled.group(1)}{{{inner}}}"
        return ""
    value = value.replace("{", "").replace("}", "")
    if value in GREEK_ALIASES:
        return GREEK_ALIASES[value]
    lower = value.lower()
    if lower in GREEK_ALIASES:
        return GREEK_ALIASES[lower]
    if lower in IGNORED_SYMBOL_WORDS:
        return ""
    value = re.sub(r"_([A-Za-z0-9]+)$", r"_\1", value)
    return value


def extract_formula_symbols(latex: str) -> list[str]:
    symbols: list[str] = []
    styled_spans: list[tuple[int, int]] = []
    for match in STYLE_SYMBOL_RE.finditer(latex or ""):
        styled_symbol = normalize_symbol(match.group(0))
        if styled_symbol:
            symbols.append(styled_symbol)
            styled_spans.append(match.span())
    masked_latex = _mask_spans(latex or "", styled_spans)

    for command in COMMAND_RE.findall(masked_latex):
        normalized = normalize_symbol(command)
        if normalized and normalized not in IGNORED_COMMANDS:
            symbols.append(normalized)

    masked = COMMAND_RE.sub(" ", masked_latex)
    for match in INDEXED_RE.finditer(masked):
        symbols.append(normalize_symbol(f"{match.group(1)}_{match.group(2)}"))
    masked = INDEXED_RE.sub(" ", masked)
    for match in WORD_RE.finditer(masked):
        symbols.append(normalize_symbol(match.group(0)))
    return _dedupe(symbol for symbol in symbols if symbol and symbol not in IGNORED_COMMANDS and symbol.lower().lstrip("\\") not in IGNORED_SYMBOL_WORDS)


def _mask_spans(text: str, spans: list[tuple[int, int]]) -> str:
    if not spans:
        return text
    chars = list(text)
    for start, end in spans:
        for index in range(max(0, start), min(end, len(chars))):
            chars[index] = " "
    return "".join(chars)


def _build_graph_text_blocks(blocks: list[StructuredTextBlock]) -> list[GraphReadyTextBlock]:
    result: list[GraphReadyTextBlock] = []
    ordered = sorted(blocks, key=lambda block: block.reading_order or 10_000_000)
    for index, block in enumerate(ordered, start=1):
        text = block.normalized_text or block.text
        flags: list[str] = []
        if not text.strip():
            flags.append("empty_text")
        result.append(
            GraphReadyTextBlock(
                id=block.id,
                type=block.type,
                page_number=block.page_number,
                section_id=block.section_id,
                order=block.reading_order or index,
                text=block.text,
                text_with_tokens=text,
                formula_tokens=_tokens_in_text(text),
                source=block.source,
                quality_flags=flags,
            )
        )
    return result


def _build_graph_paragraphs(
    text_blocks: list[GraphReadyTextBlock],
    formulas: list[GraphReadyFormula],
    contexts: list[GraphReadyFormulaContext],
) -> list[GraphReadyParagraph]:
    formula_by_token = {formula.token: formula.id for formula in formulas if formula.token}
    tokens_by_formula = {formula.id: formula.token for formula in formulas if formula.token}
    formula_ids_by_block: dict[str, list[str]] = defaultdict(list)
    for context in contexts:
        for block_id in context.nearest_text_block_ids:
            _append_unique(formula_ids_by_block.setdefault(block_id, []), context.formula_id)
    paragraphs: list[GraphReadyParagraph] = []
    for index, block in enumerate(text_blocks, start=1):
        if block.type not in {"paragraph", "unknown", "abstract"}:
            continue
        text = block.text_with_tokens or block.text
        tokens = _tokens_in_text(text)
        formula_ids = _dedupe([formula_by_token[token] for token in tokens if token in formula_by_token] + formula_ids_by_block.get(block.id, []))
        tokens = _dedupe([*tokens, *[tokens_by_formula[item] for item in formula_ids if item in tokens_by_formula]])
        sentence_ids = [f"{block.id}:sent_{sent_index:03d}" for sent_index, _sent in enumerate(_split_sentences(text), start=1)]
        paragraphs.append(
            GraphReadyParagraph(
                id=f"para_{index:04d}",
                page_id=f"page_{block.page_number:03d}",
                page_number=block.page_number,
                order=block.order,
                text=text,
                sentence_ids=sentence_ids,
                formula_tokens=tokens,
                formula_ids=formula_ids,
                source=block.source,
            )
        )
    return paragraphs


def _build_graph_formulas(formulas: list[StructuredFormula], reading_order) -> list[GraphReadyFormula]:
    order_by_id = {item.object_id: item.order for item in reading_order}
    ordered = sorted(formulas, key=lambda formula: order_by_id.get(formula.id, 10_000_000))
    result: list[GraphReadyFormula] = []
    for index, formula in enumerate(ordered, start=1):
        normalized_latex = formula.normalized_latex or _normalize_latex(formula.latex)
        extracted_symbols = extract_formula_symbols(normalized_latex)
        symbol_candidates = extracted_symbols or [normalize_symbol(symbol) for symbol in formula.symbols]
        symbols = _dedupe(symbol for symbol in symbol_candidates if _is_variable_symbol(symbol))
        operators = _extract_operators(normalized_latex) if normalized_latex else _sanitize_operators(formula.operators)
        flags = list(formula.quality_flags)
        if not formula.latex and "latex_missing" not in flags:
            flags.append("latex_missing")
        result.append(
            GraphReadyFormula(
                id=formula.id,
                token=formula.token or f"[FORMULA_{index:03d}]",
                kind=formula.kind,
                latex=normalized_latex or formula.latex,
                raw_latex=formula.raw_latex,
                cleaned_latex=formula.cleaned_latex,
                normalized_latex=normalized_latex,
                plain_formula_text=formula.plain_formula_text,
                source=formula.source,
                confidence=formula.confidence,
                section_id=formula.section_id,
                order=order_by_id.get(formula.id, index),
                formula_number=formula.formula_number,
                symbols=symbols,
                operators=operators,
                semantic_hints=FormulaSemanticHints(
                    definition_like=formula.semantic_hints.definition_like,
                    contains_equality=formula.semantic_hints.contains_equality,
                    contains_inequality=formula.semantic_hints.contains_inequality,
                    contains_sum=formula.semantic_hints.contains_sum,
                    contains_integral=formula.semantic_hints.contains_integral,
                    contains_fraction=formula.semantic_hints.contains_fraction,
                    contains_matrix=formula.semantic_hints.contains_matrix,
                ),
                quality_flags=_dedupe(flags),
            )
        )
    return result


def _best_text_with_tokens(result: ProcessingResult, structured: StructuredDocument) -> str:
    legacy = _join_legacy_token_stream(result.text_with_tokens)
    if TOKEN_RE.search(legacy):
        return legacy
    return structured.text_with_tokens or legacy


def _join_legacy_token_stream(blocks: list[TextBlock]) -> str:
    if not blocks:
        return ""
    parts: list[str] = []
    for block in blocks:
        text = re.sub(r"\s+", " ", block.text or "").strip()
        if not text:
            continue
        if TOKEN_RE.fullmatch(text):
            parts.append(f"\n{text}\n")
        else:
            parts.append(text)
    return _normalize_text("\n".join(parts))


def _build_graph_contexts(
    formulas: list[GraphReadyFormula],
    text_blocks: list[GraphReadyTextBlock],
    structured_contexts: list[StructuredFormulaContext],
    text_with_tokens: str,
) -> list[GraphReadyFormulaContext]:
    structured_by_formula = {ctx.formula_id: ctx for ctx in structured_contexts}
    text_by_order = sorted(text_blocks, key=lambda block: block.order)
    result: list[GraphReadyFormulaContext] = []
    for index, formula in enumerate(formulas, start=1):
        structured = structured_by_formula.get(formula.id)
        before = structured.context_before if structured else ""
        after = structured.context_after if structured else ""
        nearest_ids = list(structured.nearest_text_block_ids if structured else [])
        sentence_before, sentence_after, sentence_window = _sentence_context_around_token(text_with_tokens, formula.token)
        has_sentence_window = bool(sentence_window)
        if has_sentence_window:
            before = sentence_before
            after = sentence_after
            window = sentence_window
        else:
            window = _window_around_token(text_with_tokens, formula.token)
        if not window:
            window = structured.window_text if structured else ""
        if not has_sentence_window and not before and not after:
            before_block, after_block = _neighbor_blocks(formula, text_by_order)
            before = before_block.text_with_tokens if before_block else ""
            after = after_block.text_with_tokens if after_block else ""
            nearest_ids = [block.id for block in (before_block, after_block) if block]
        if formula.token not in window:
            window = " ".join(part for part in (before, formula.token, after) if part).strip()
        flags: list[str] = []
        if formula.token not in window:
            flags.append("token_missing_in_window")
            window = f"{formula.token} {window}".strip()
        markers = _definition_markers(window)
        mentioned = _symbols_in_text(window, formula.symbols)
        possible_definitions = _possible_definitions(window, formula.symbols)
        result.append(
            GraphReadyFormulaContext(
                id=f"ctx_{index:04d}",
                formula_id=formula.id,
                token=formula.token,
                section_id=formula.section_id,
                context_before=_clip_context(before),
                context_after=_clip_context(after),
                window_text=_clip_context(window, 900),
                nearest_text_block_ids=_dedupe(nearest_ids),
                definition_markers=markers,
                mentioned_symbols=mentioned,
                possible_definitions=possible_definitions,
                quality_flags=flags,
            )
        )
    return result


def _build_variables(
    formulas: list[GraphReadyFormula],
    contexts: list[GraphReadyFormulaContext],
    entities: list[Any],
    text_blocks: list[GraphReadyTextBlock],
) -> list[GraphReadyVariable]:
    by_symbol: dict[str, GraphReadyVariable] = {}
    context_by_formula = {ctx.formula_id: ctx for ctx in contexts}

    def ensure(symbol: str) -> GraphReadyVariable:
        normalized = normalize_symbol(symbol)
        if normalized not in by_symbol:
            by_symbol[normalized] = GraphReadyVariable(
                id=f"var_{len(by_symbol) + 1:04d}",
                symbol=normalized,
                normalized_symbol=normalized,
                latex=normalized,
            )
        return by_symbol[normalized]

    for formula in formulas:
        context = context_by_formula.get(formula.id)
        for symbol in formula.symbols:
            normalized = normalize_symbol(symbol)
            if not normalized or normalized in IGNORED_COMMANDS:
                continue
            variable = ensure(normalized)
            _append_unique(variable.formula_ids, formula.id)
            if context:
                _append_unique(variable.context_ids, context.id)
            if formula.section_id:
                _append_unique(variable.section_ids, formula.section_id)

    for ctx in contexts:
        for symbol in ctx.mentioned_symbols:
            variable = ensure(symbol)
            _append_unique(variable.context_ids, ctx.id)
            if ctx.section_id:
                _append_unique(variable.section_ids, ctx.section_id)
        for definition in ctx.possible_definitions:
            variable = ensure(definition.symbol)
            _append_unique(variable.context_ids, ctx.id)
            variable.possible_definitions.append(
                {
                    "context_id": ctx.id,
                    "definition_text": definition.definition_text,
                    "evidence": definition.evidence,
                    "confidence": definition.confidence,
                }
            )

    for block in text_blocks:
        for symbol in _text_variable_mentions(block.text_with_tokens or block.text):
            variable = ensure(symbol)
            if block.section_id:
                _append_unique(variable.section_ids, block.section_id)
            _append_unique(variable.quality_flags, "text_mention")

    for entity in entities:
        if getattr(entity, "type", "") != "symbol" and getattr(entity, "kind", "") != "variable":
            continue
        variable = ensure(getattr(entity, "normalized_value", "") or getattr(entity, "value", "") or getattr(entity, "label", ""))
        formula_id = getattr(entity, "formula_id", None) or getattr(entity, "source_formula_id", None)
        if formula_id:
            _append_unique(variable.formula_ids, formula_id)
        context_id = getattr(entity, "context_id", None)
        if context_id:
            _append_unique(variable.context_ids, context_id)
        section_id = getattr(entity, "section_id", None)
        if section_id:
            _append_unique(variable.section_ids, section_id)

    variables = sorted(by_symbol.values(), key=lambda item: item.normalized_symbol)
    for index, variable in enumerate(variables, start=1):
        variable.id = f"var_{index:04d}"
        variable.formula_ids = _dedupe(variable.formula_ids)
        variable.context_ids = _dedupe(variable.context_ids)
        variable.section_ids = _dedupe(variable.section_ids)
        variable.possible_definitions = _dedupe_dicts(variable.possible_definitions)
        variable.usage_count = max(len(variable.formula_ids), 1 if "text_mention" in variable.quality_flags else 0)
    return variables


def _build_graph_structure(
    structured: StructuredDocument,
    text_blocks: list[GraphReadyTextBlock],
    formulas: list[GraphReadyFormula],
) -> GraphReadyStructure:
    text_by_section: dict[str, list[str]] = defaultdict(list)
    tokens_by_section: dict[str, list[str]] = defaultdict(list)
    for block in text_blocks:
        if block.section_id:
            text_by_section[block.section_id].append(block.id)
    for formula in formulas:
        if formula.section_id:
            tokens_by_section[formula.section_id].append(formula.token)

    sections: list[GraphReadySection] = []
    for index, section in enumerate(structured.document_structure.sections, start=1):
        sections.append(
            GraphReadySection(
                id=section.id,
                title=section.title,
                level=section.level,
                order=index,
                parent_id=None,
                text_block_ids=_dedupe(text_by_section.get(section.id, [])),
                formula_tokens=_dedupe(tokens_by_section.get(section.id, [])),
            )
        )
    return GraphReadyStructure(
        title=structured.document_structure.title,
        authors=structured.document_structure.authors,
        abstract=structured.document_structure.abstract,
        language=structured.document_structure.detected_language,
        sections=sections,
    )


def _build_relations(
    sections: list[GraphReadySection],
    text_blocks: list[GraphReadyTextBlock],
    formulas: list[GraphReadyFormula],
    contexts: list[GraphReadyFormulaContext],
    variables: list[GraphReadyVariable],
) -> list[GraphReadyRelation]:
    relations: list[GraphReadyRelation] = []
    variable_by_symbol = {var.normalized_symbol: var for var in variables}
    context_by_formula = {ctx.formula_id: ctx for ctx in contexts}
    formula_by_number = {formula.formula_number: formula for formula in formulas if formula.formula_number}

    def add(kind: str, source_id: str, target_id: str, evidence: str | None = None, confidence: float | None = None) -> None:
        relations.append(
            GraphReadyRelation(
                id=f"rel_{len(relations) + 1:04d}",
                type=kind,
                source_id=source_id,
                target_id=target_id,
                evidence=evidence,
                confidence=confidence,
            )
        )

    for formula in formulas:
        for symbol in formula.symbols:
            variable = variable_by_symbol.get(normalize_symbol(symbol))
            if variable:
                add("formula_contains_variable", formula.id, variable.id, f"{symbol} in {formula.latex}", 0.82)
        ctx = context_by_formula.get(formula.id)
        if ctx:
            add("formula_has_context", formula.id, ctx.id, f"{formula.token} appears in window_text", 0.8)
            for text_block_id in ctx.nearest_text_block_ids:
                add("formula_near_text_block", formula.id, text_block_id, ctx.window_text[:240], 0.62)
        if formula.section_id:
            add("formula_in_section", formula.id, formula.section_id, None, 0.85)

    for block in text_blocks:
        if block.section_id:
            add("text_block_in_section", block.id, block.section_id, None, 0.85)

    for variable in variables:
        for context_id in variable.context_ids:
            evidence = next((item.get("evidence") for item in variable.possible_definitions if item.get("context_id") == context_id), None)
            confidence = 0.72 if evidence else 0.55
            add("variable_defined_in_context", variable.id, context_id, evidence, confidence)

    for formula in formulas:
        ctx = context_by_formula.get(formula.id)
        if not ctx:
            continue
        for number in re.findall(r"(?:equation|eq\.?|формула)?\s*\((\d{1,4}[a-zA-Z]?)\)", ctx.window_text, flags=re.IGNORECASE):
            target = formula_by_number.get(number)
            if target and target.id != formula.id:
                add("formula_references_formula", formula.id, target.id, f"reference ({number}) in context", 0.62)

    return relations


def _fallback_variables(doc: GraphReadyDocument, normalized_query: str, raw_query: str) -> list[GraphReadyVariable]:
    formula_ids = [
        formula.id
        for formula in doc.formulas
        if normalized_query in [normalize_symbol(symbol) for symbol in formula.symbols]
        or raw_query in formula.latex
        or normalized_query in formula.latex
    ]
    context_ids = [
        ctx.id
        for ctx in doc.formula_contexts
        if raw_query in ctx.window_text or normalized_query in ctx.window_text
    ]
    if not formula_ids and not context_ids:
        return []
    return [
        GraphReadyVariable(
            id="var_fallback",
            symbol=normalized_query,
            normalized_symbol=normalized_query,
            latex=normalized_query,
            formula_ids=_dedupe(formula_ids),
            context_ids=_dedupe(context_ids),
            usage_count=len(set(formula_ids)),
            quality_flags=["fallback_search"],
        )
    ]


def _variable_scope(variable: GraphReadyVariable) -> dict[str, Any]:
    if len(variable.section_ids) == 1:
        level = "section"
        ids = list(variable.section_ids)
    elif variable.section_ids:
        level = "document"
        ids = list(variable.section_ids)
    elif variable.context_ids:
        level = "paragraph"
        ids = list(variable.context_ids)
    else:
        level = "document"
        ids = []
    confidence = 0.78 if variable.possible_definitions else 0.55
    return {"level": level, "ids": ids, "confidence": confidence}


def _source_type_from_profile(structured: StructuredDocument) -> str:
    mode = structured.processing_profile.ocr_mode
    if mode == "tex_source" or structured.processing_profile.prefer_tex_source:
        return "tex_source"
    if mode in {"text_layer"}:
        return "pdf_text_layer"
    if mode in {"hybrid", "hybrid_tesseract", "standard", "auto"}:
        return "hybrid"
    if mode in {"tesseract", "structure", "marker"}:
        return "ocr"
    return mode or "unknown"


def _initial_warnings(structured: StructuredDocument) -> list[GraphReadyWarning]:
    return [
        GraphReadyWarning(code=warning.code, message=warning.message, object_ids=warning.object_ids)
        for warning in structured.warnings
    ]


def _window_around_token(text: str, token: str, radius: int = 360) -> str:
    if not text or not token:
        return ""
    index = text.find(token)
    if index < 0:
        return ""
    start = max(0, index - radius)
    end = min(len(text), index + len(token) + radius)
    return _normalize_text(text[start:end])


def _sentence_context_around_token(text: str, token: str, radius: int = 1) -> tuple[str, str, str]:
    if not text or not token:
        return "", "", ""
    sentences = _split_sentences(text)
    if not sentences:
        return "", "", ""
    token_index = next((index for index, sentence in enumerate(sentences) if token in sentence), -1)
    if token_index < 0:
        return "", "", ""
    before = " ".join(sentences[max(0, token_index - radius) : token_index])
    current = sentences[token_index]
    after = " ".join(sentences[token_index + 1 : token_index + 1 + radius])
    if token in current and not before and not after:
        left, right = current.split(token, 1)
        before = left
        after = right
    window = " ".join(part for part in (before, current, after) if part)
    return _normalize_text(before), _normalize_text(after), _normalize_text(window)


def _split_sentences(text: str) -> list[str]:
    text = _normalize_text(text)
    if not text:
        return []
    matches = re.findall(r"[^.!?。！？]+(?:[.!?。！？]+|$)", text)
    sentences = [_normalize_text(match) for match in matches if _normalize_text(match)]
    if sentences:
        return sentences
    return [text]


def _neighbor_blocks(formula: GraphReadyFormula, blocks: list[GraphReadyTextBlock]) -> tuple[GraphReadyTextBlock | None, GraphReadyTextBlock | None]:
    before = [block for block in blocks if block.order <= formula.order and (not formula.section_id or block.section_id == formula.section_id)]
    after = [block for block in blocks if block.order >= formula.order and (not formula.section_id or block.section_id == formula.section_id)]
    return (before[-1] if before else None, after[0] if after else None)


def _definition_markers(text: str) -> list[str]:
    lower = text.lower()
    return [marker for marker in DEFINITION_MARKERS if marker in lower]


def _symbols_in_text(text: str, symbols: list[str]) -> list[str]:
    found: list[str] = []
    for symbol in symbols:
        normalized = normalize_symbol(symbol)
        plain = normalized.lstrip("\\")
        aliases = {normalized, plain}
        aliases.update(alias for alias, canonical in GREEK_ALIASES.items() if canonical == normalized)
        if any(_mentions_symbol(text, alias) for alias in aliases):
            found.append(normalized)
    return _dedupe(found)


def _text_variable_mentions(text: str) -> list[str]:
    mentions: list[str] = []
    for match in TEXT_VARIABLE_RE.finditer(text or ""):
        value = normalize_symbol(match.group(0))
        if value and value.lower() not in {"i", "a"}:
            mentions.append(value)
    return _dedupe(mentions)


def _possible_definitions(text: str, symbols: list[str]) -> list[PossibleDefinition]:
    definitions: list[PossibleDefinition] = []
    for record in extract_definition_evidence(text, symbols):
        definitions.append(
            PossibleDefinition(
                symbol=normalize_symbol(record.symbol),
                definition_text=record.definition_text,
                evidence=record.evidence,
                confidence=record.confidence,
                rule=record.rule,
                source=record.source,
                language=record.language,
            )
        )
    for symbol in symbols:
        normalized = normalize_symbol(symbol)
        aliases = _symbol_aliases(normalized)
        for alias in aliases:
            escaped = re.escape(alias.lstrip("\\"))
            patterns = [
                rf"\b{escaped}\b\s+(?:denotes|denote|represents|is defined as|is)\s+([^.;,\n]{{2,120}})",
                rf"(?:where|где)\s+\b{escaped}\b\s*(?:[-–—]|:|,)?\s*([^.;\n]{{2,120}})",
                rf"\b{escaped}\b\s+(?:обозначает|определяется как|задается как|задаётся как)\s+([^.;,\n]{{2,120}})",
            ]
            for pattern in patterns:
                match = re.search(pattern, text, flags=re.IGNORECASE)
                if not match:
                    continue
                definition_text = _normalize_text(match.group(1))
                evidence = _normalize_text(match.group(0))
                definitions.append(
                    PossibleDefinition(
                        symbol=normalized,
                        definition_text=definition_text,
                        evidence=evidence,
                        confidence=0.72,
                    )
                )
    unique: list[PossibleDefinition] = []
    seen: set[tuple[str, str]] = set()
    for item in definitions:
        key = (item.symbol, item.definition_text.lower())
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _symbol_aliases(normalized: str) -> set[str]:
    aliases = {normalized, normalized.lstrip("\\")}
    aliases.update(alias for alias, canonical in GREEK_ALIASES.items() if canonical == normalized)
    return aliases


def _mentions_symbol(text: str, symbol: str) -> bool:
    if not symbol:
        return False
    if symbol.startswith("\\"):
        return symbol in text
    return bool(re.search(rf"(?<![A-Za-z0-9_\\]){re.escape(symbol)}(?![A-Za-z0-9_])", text))


def _extract_operators(latex: str) -> list[str]:
    operators = [cmd for cmd in COMMAND_RE.findall(latex or "") if cmd in OPERATOR_COMMANDS]
    operators.extend(re.findall(r"[=+\-*/^<>]", latex or ""))
    return _dedupe(operators)


def _sanitize_operators(values: list[str] | None) -> list[str]:
    operators: list[str] = []
    for value in values or []:
        operator = str(value or "").strip()
        if not operator:
            continue
        if operator in OPERATOR_COMMANDS or operator in INFIX_OPERATOR_CHARS or operator.lower() in OPERATOR_WORDS:
            operators.append(operator)
    return operators


def _tokens_in_text(text: str) -> list[str]:
    return _dedupe(match.group(0) for match in TOKEN_RE.finditer(text or ""))


def _normalize_latex(latex: str) -> str:
    return re.sub(r"\s+", " ", latex or "").strip()


def _normalize_text(text: str) -> str:
    value = re.sub(r"[ \t]+", " ", text or "")
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _clip_context(text: str, limit: int = 420) -> str:
    text = _normalize_text(text)
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


def _refresh_summary(doc: GraphReadyDocument) -> None:
    doc.summary = GraphReadySummary(
        sections_count=len(doc.document_structure.sections),
        text_blocks_count=len(doc.text_blocks),
        formulas_count=len(doc.formulas),
        variables_count=len(doc.variables),
        contexts_count=len(doc.formula_contexts),
        relations_count=len(doc.relations),
        warnings_count=len(doc.warnings),
    )


def _append_unique(items: list[str], value: str | None) -> None:
    if value and value not in items:
        items.append(value)


def _dedupe(values) -> list:
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _dedupe_dicts(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for value in values:
        key = tuple(sorted(value.items()))
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _dedupe_warnings(warnings: list[GraphReadyWarning]) -> list[GraphReadyWarning]:
    result: list[GraphReadyWarning] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for warning in warnings:
        key = (warning.code, tuple(warning.object_ids))
        if key not in seen:
            seen.add(key)
            result.append(warning)
    return result
