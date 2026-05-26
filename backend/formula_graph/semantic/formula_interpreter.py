from __future__ import annotations

from typing import Any

from backend.formula_graph.postprocessing.latex_cleaner import latex_to_plain_text, normalize_latex


def interpret_formula(
    latex: str,
    *,
    variables: list[str] | None = None,
    possible_definitions: dict[str, str] | None = None,
    context: str = "",
) -> dict[str, Any]:
    normalized_latex = normalize_latex(latex or "")
    plain_text = latex_to_plain_text(normalized_latex)
    variables = list(variables or [])
    possible_definitions = dict(possible_definitions or {})
    kind = _classify_formula(normalized_latex, context)
    definitions = {
        variable: possible_definitions[variable]
        for variable in variables
        if variable in possible_definitions
    }
    return {
        "kind": kind,
        "plain_text": plain_text,
        "summary": _summary(kind, plain_text, variables, definitions),
        "summary_ru": _summary_ru(kind, plain_text, variables, definitions),
        "variables": variables,
        "definitions": definitions,
        "context_hint": _context_hint(context),
        "confidence": _confidence(normalized_latex, context, definitions),
    }


def interpret_formula_record(formula: Any, context: Any | None = None) -> dict[str, Any]:
    definitions = {}
    if context is not None:
        for item in getattr(context, "possible_definitions", []) or []:
            symbol = str(getattr(item, "symbol", "") or "").strip().lstrip("\\")
            definition = str(getattr(item, "definition_text", "") or "").strip()
            if symbol and definition:
                definitions[symbol] = definition
    variables = [str(item or "").strip().lstrip("\\") for item in getattr(formula, "symbols", []) or [] if str(item or "").strip()]
    text_context = str(getattr(context, "window_text", "") or "") if context is not None else ""
    return interpret_formula(getattr(formula, "normalized_latex", "") or getattr(formula, "latex", ""), variables=variables, possible_definitions=definitions, context=text_context)


def _classify_formula(latex: str, context: str) -> str:
    value = f"{latex} {context}".lower()
    if any(token in value for token in (r"\forall", r"\exists", r"\in ", r"\notin", r"\subset", r"\supset", r"\cup", r"\cap", "there exists", "for all")):
        return "set_or_logic_expression"
    if any(token in value for token in (r"\to", r"\mapsto", r"\rightarrow", r"\leftarrow", r"\Rightarrow", r"\Leftrightarrow")):
        return "mapping_or_implication"
    if any(token in value for token in (r"\sum", "sum", r"\prod", "product", r"\int", "integral", r"\lim", "limit", r"\min", r"\max", r"\argmin", r"\argmax")):
        return "aggregation_or_calculus"
    if any(token in value for token in (r"\le", r"\ge", r"\ne", r"\approx", r"\sim", r"\equiv", "<", ">", "inequality")):
        return "constraint_or_inequality"
    if "=" in latex:
        return "definition_or_equation"
    if any(token in value for token in ("where", "denotes", "обозначает", "где", "пусть")):
        return "notation_context"
    return "mathematical_expression"


def _summary(kind: str, plain_text: str, variables: list[str], definitions: dict[str, str]) -> str:
    pieces = [f"Formula type: {kind}."]
    if plain_text:
        pieces.append(f"Readable form: {plain_text}.")
    if variables:
        pieces.append(f"Variables: {', '.join(variables)}.")
    if definitions:
        defs = "; ".join(f"{name} means {definition}" for name, definition in definitions.items())
        pieces.append(f"Definitions near formula: {defs}.")
    return " ".join(pieces)


def _summary_ru(kind: str, plain_text: str, variables: list[str], definitions: dict[str, str]) -> str:
    pieces = [f"Тип формулы: {_kind_ru(kind)}."]
    if plain_text:
        pieces.append(f"Читаемая запись: {plain_text}.")
    if variables:
        pieces.append(f"Переменные: {', '.join(variables)}.")
    if definitions:
        defs = "; ".join(f"{name} — {definition}" for name, definition in definitions.items())
        pieces.append(f"Найденные рядом определения: {defs}.")
    return " ".join(pieces)


def _kind_ru(kind: str) -> str:
    return {
        "aggregation_or_calculus": "суммирование, интеграл или предельная операция",
        "constraint_or_inequality": "ограничение или неравенство",
        "definition_or_equation": "определение или уравнение",
        "notation_context": "введение обозначений",
        "mathematical_expression": "математическое выражение",
    }.get(kind, kind)


def _context_hint(context: str) -> str:
    context = " ".join(str(context or "").split())
    return context[:300]


def _confidence(latex: str, context: str, definitions: dict[str, str]) -> float:
    score = 0.55
    if latex:
        score += 0.15
    if context:
        score += 0.1
    if definitions:
        score += 0.15
    if any(token in latex for token in ("=", r"\sum", r"\prod", r"\int", r"\lim", r"\frac", r"\sqrt", r"\cup", r"\cap", r"\to")):
        score += 0.05
    return round(min(0.95, score), 2)
