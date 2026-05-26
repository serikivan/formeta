from __future__ import annotations

import re

from backend.formula_graph.layout.formulas import text_line_to_latex_candidate
from backend.formula_graph.models import FormulaBlock, TextBlock
from backend.formula_graph.postprocessing.latex_cleaner import (
    clean_latex,
    latex_to_plain_text,
    normalize_latex,
    validate_latex_sanity,
)


PROSE_TOKENS = (
    "proof",
    "thus",
    "where",
    "observe",
    "lemma",
    "first",
    "recall",
    "therefore",
    "exists",
    "dyadic",
    "point",
    "contraction",
    "statement",
    "assumption",
    "again",
    "satisfies",
    "since",
    "unique",
    "following",
    "modified",
    "generalized",
    "which",
    "attractor",
    "for",
    "have",
    "has",
    "holds",
    "if",
    "then",
    "and",
    "follows",
    "directed",
    "graph",
    "corresponding",
    "sequence",
    "clear",
    "satisfy",
    "satisfies",
    "speaking",
    "light",
    "loosely",
    "say",
)

WEIRD_UNICODE = ("é–", "閉", "�", "\ufffd")
MATH_TEXT_WORDS = {
    "arc",
    "arccos",
    "cos",
    "cosh",
    "det",
    "dim",
    "exp",
    "fix",
    "gcd",
    "inf",
    "ker",
    "lim",
    "log",
    "max",
    "min",
    "mod",
    "sec",
    "sech",
    "sin",
    "sup",
    "tan",
}


def normalize_formula_blocks(formulas: list[FormulaBlock]) -> list[FormulaBlock]:
    normalized: list[FormulaBlock] = []
    for formula in formulas:
        original = formula.latex
        cleaned = clean_latex(original)
        repaired = repair_formula_latex(cleaned)
        normalized_latex = normalize_latex(repaired)
        plain_formula_text = latex_to_plain_text(normalized_latex)
        flags = [*formula.quality_flags, *validate_formula_latex(repaired)]
        sanity = validate_latex_sanity(normalized_latex)
        flags.extend(f"latex_{warning}" for warning in sanity.get("warnings", []))
        raw_latex = formula.raw_latex or original
        if repaired != original:
            flags.append("repaired_latex")
        confidence = _adjust_confidence(formula.confidence, flags)
        normalized.append(
            formula.model_copy(
                update={
                    "latex": repaired,
                    "raw_latex": raw_latex,
                    "cleaned_latex": cleaned,
                    "normalized_latex": normalized_latex,
                    "plain_formula_text": plain_formula_text,
                    "quality_flags": _dedupe(flags),
                    "confidence": confidence,
                }
            )
        )
    return _dedupe_formulas(normalized)


def rescue_formula_definitions(formulas: list[FormulaBlock], reference_blocks: list[TextBlock]) -> list[FormulaBlock]:
    reference_lines = _collect_reference_lines(reference_blocks)
    if not reference_lines:
        return formulas
    rescued: list[FormulaBlock] = []
    for formula in formulas:
        rescued.append(_rescue_formula_definition(formula, reference_lines))
    return _dedupe_formulas(rescued)


def reconcile_formula_candidates_with_text_layer(
    formulas: list[FormulaBlock],
    reference_blocks: list[TextBlock],
) -> list[FormulaBlock]:
    reference_lines = _collect_reference_lines(reference_blocks)
    candidates = _collect_text_layer_formula_candidates(reference_lines)

    reconciled: list[FormulaBlock] = []
    for formula in formulas:
        flags = set(formula.quality_flags) | set(validate_formula_latex(formula.latex))
        if not _needs_text_layer_reconciliation(formula, flags):
            reconciled.append(formula)
            continue

        replacement = _best_text_layer_formula_candidate(formula, candidates)
        if replacement is not None:
            reconciled.append(_replace_with_text_layer_formula(formula, replacement, flags))
            continue

        if _is_visual_prose_false_positive(formula, flags):
            continue
        reconciled.append(formula)
    return _dedupe_formulas(reconciled)


def repair_formula_latex(latex: str) -> str:
    value = " ".join(str(latex).strip().strip("$").split())
    value = re.sub(r"(?:é–‘|閉)+\s*", "&", value)
    value = re.sub(r"\\(?:mathrm|mathit|text)\{\s*~?\s*a\s*n\s*d\s*~?\s*\}", r"\\quad ", value)
    value = re.sub(r"^If\s+(.+)$", r"\1", value, flags=re.IGNORECASE)
    value = re.sub(
        r"\(\s*\\xi_?\{?n\}?\s*\)\s*follows\s+the\s+directed-?graph\s+(\\mathcal\{[^{}]+\})",
        r"(\\xi_n)\\in \1",
        value,
        flags=re.IGNORECASE,
    )
    value = value.replace(r"\operatorname*{l i m}", r"\lim")
    value = value.replace(r"\operatorname{l i m}", r"\lim")
    value = re.sub(r"F\s*i\s*x", "Fix", value)
    value = re.sub(r"^Fix\s+(\\[A-Za-z]+(?:_\{?[^{}\s]+\}?)?\s*=)", r"\1", value)
    value = re.sub(r"(?:\\\\\s*&?\s*)?(?:\\therefore\s*(?:\\quad\s*)?){2,}", "", value)
    value = re.sub(r"\\begin\{aligned\}\s*&?\s*(.+?)\s*\\end\{aligned\}", r"\1", value)
    value = value.replace(r"\cdots\circ", r"\cdots \circ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def validate_formula_latex(latex: str) -> list[str]:
    flags: list[str] = []
    if any(marker in latex for marker in WEIRD_UNICODE):
        flags.append("weird_unicode")
    if _unbalanced_braces(latex):
        flags.append("unbalanced_braces")
    if _unbalanced_delimiters(latex):
        flags.append("unbalanced_delimiters")
    if _looks_incomplete_formula(latex) or "unbalanced_delimiters" in flags:
        flags.append("incomplete_formula")
    if re.search(r"\\sum\s*\^\{?[^{}\s]+\}?", latex) and not re.search(r"\\sum\s*_\{?", latex):
        flags.append("sum_missing_lower_bound")
    if _contains_prose(latex):
        flags.append("contains_prose")
    if _looks_like_romanized_ocr(latex):
        flags.append("romanized_ocr_noise")
    if len(latex) > 700:
        flags.append("very_long_formula")
    if not _has_math_signal(latex):
        flags.append("weak_math_signal")
    if flags:
        flags.append("needs_review")
    return flags


def _collect_text_layer_formula_candidates(
    reference_lines: list[tuple[int, tuple[float, float, float, float] | None, str]]
) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    for page_number, bbox, text in reference_lines:
        if bbox is None:
            continue
        latex = text_line_to_latex_candidate(text)
        if not latex:
            continue
        flags = validate_formula_latex(latex)
        if "contains_prose" in flags or "weak_math_signal" in flags:
            continue
        candidates.append({"page_number": page_number, "bbox": bbox, "text": text, "latex": repair_formula_latex(latex)})
    return candidates


def _needs_text_layer_reconciliation(formula: FormulaBlock, flags: set[str]) -> bool:
    if formula.source.startswith("tex_source"):
        return False
    if not _is_visual_formula_source(formula.source):
        return False
    severe_flags = {
        "contains_prose",
        "romanized_ocr_noise",
        "raw_ocr_contains_prose",
        "raw_ocr_romanized_ocr_noise",
        "very_long_formula",
    }
    if flags.intersection(severe_flags):
        return True
    if "needs_formula_review" in flags and _prose_word_count(formula.latex) >= 2:
        return True
    return False


def _is_visual_formula_source(source: str) -> bool:
    return source.startswith("pp_") or source.startswith("paddle") or source.endswith("_raw")


def _best_text_layer_formula_candidate(formula: FormulaBlock, candidates: list[dict[str, object]]) -> dict[str, object] | None:
    if formula.bbox is None:
        return None
    scored: list[tuple[float, dict[str, object]]] = []
    for candidate in candidates:
        if candidate["page_number"] != formula.page_number:
            continue
        bbox = candidate["bbox"]
        assert bbox is not None
        score = _candidate_geometry_score(formula.bbox, bbox) + _candidate_latex_score(str(candidate["latex"]))
        if score >= 1.1:
            scored.append((score, candidate))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def _candidate_geometry_score(formula_bbox, candidate_bbox) -> float:
    fx0, fy0, fx1, fy1 = formula_bbox
    cx0, cy0, cx1, cy1 = candidate_bbox
    vertical_gap = max(0.0, max(fy0 - cy1, cy0 - fy1))
    horizontal_overlap = max(0.0, min(fx1, cx1) - max(fx0, cx0))
    overlap_ratio = horizontal_overlap / max(1.0, min(fx1 - fx0, cx1 - cx0))
    center_gap = abs(((fx0 + fx1) / 2) - ((cx0 + cx1) / 2))
    if vertical_gap > 70 or center_gap > 280:
        return 0.0
    return (1.4 * overlap_ratio) + max(0.0, 1.0 - vertical_gap / 70.0) + max(0.0, 0.6 - center_gap / 500.0)


def _candidate_latex_score(latex: str) -> float:
    math_commands = len(re.findall(r"\\[A-Za-z]+", latex))
    relations = len(re.findall(r"(?:=|\\in|\\cup|\\le|\\ge|\\to|<|>)", latex))
    return min(1.2, 0.18 * math_commands + 0.25 * relations)


def _replace_with_text_layer_formula(
    formula: FormulaBlock,
    candidate: dict[str, object],
    previous_flags: set[str],
) -> FormulaBlock:
    latex = str(candidate["latex"])
    bbox = candidate["bbox"]
    candidate_flags = [
        flag
        for flag in validate_formula_latex(latex)
        if flag not in {"needs_review"}
    ]
    kept_flags = [
        flag
        for flag in formula.quality_flags
        if flag not in {"contains_prose", "romanized_ocr_noise", "needs_review", "needs_formula_review"}
    ]
    if any(flag.startswith("raw_ocr_") for flag in previous_flags):
        kept_flags.append("visual_ocr_replaced")
    latex_fields = _latex_variant_fields(latex)
    return formula.model_copy(
        update={
            "latex": latex,
            "raw_latex": formula.raw_latex or formula.latex,
            **latex_fields,
            "bbox": bbox,
            "source": "text_pattern",
            "confidence": max(formula.confidence or 0.0, 0.62),
            "quality_flags": _dedupe([*kept_flags, *candidate_flags, "recovered_from_text_layer"]),
        }
    )


def _is_visual_prose_false_positive(formula: FormulaBlock, flags: set[str]) -> bool:
    if not _is_visual_formula_source(formula.source):
        return False
    if "contains_prose" not in flags and "raw_ocr_contains_prose" not in flags:
        return False
    if _prose_word_count(formula.latex) < 3:
        return False
    if "contains_prose" in flags:
        return True
    return _math_signal_count(formula.latex) < 8


def _prose_word_count(latex: str) -> int:
    without_commands = re.sub(r"\\[A-Za-z]+", " ", latex)
    return len([word for word in re.findall(r"[A-Za-z]{4,}", without_commands) if word.lower() not in MATH_TEXT_WORDS])


def _math_signal_count(latex: str) -> int:
    return len(re.findall(r"\\[A-Za-z]+|[=<>_^]|\d|[\u0370-\u03ff]", latex))


def _contains_prose(latex: str) -> bool:
    without_commands = re.sub(r"\\[A-Za-z]+", " ", latex)
    words = [word.lower() for word in re.findall(r"[A-Za-z]{2,}", without_commands)]
    if any(word in PROSE_TOKENS for word in words):
        return True
    command_texts = re.findall(r"\\(?:mathit|mathrm|text|mathbf|operatorname\*?)\{([^{}]*)\}", latex)
    for item in command_texts:
        command_words = [word.lower() for word in re.findall(r"[A-Za-z]{1,}", item)]
        compact = "".join(command_words)
        if compact in PROSE_TOKENS:
            return True
        if len(compact) >= 6 and len(command_words) >= 3 and compact not in MATH_TEXT_WORDS:
            return True
        if len(re.findall(r"[A-Za-z]", item)) >= 12 and len(item.split()) >= 3:
            return True
    return False


def _looks_like_romanized_ocr(latex: str) -> bool:
    text_runs = re.findall(r"\\(?:mathrm|mathtt|mathit)\{([^{}]*)\}", latex)
    spaced_letter_runs = [
        item
        for item in text_runs
        if re.fullmatch(r"[A-Za-z](?:\s+[A-Za-z]){1,}", item.strip())
    ]
    single_letter_boxes = len(re.findall(r"\\(?:mathrm|mathtt)\{[A-Za-z]\}", latex))
    if len(spaced_letter_runs) >= 2:
        return True
    if single_letter_boxes >= 5:
        return True
    compact = re.sub(r"\s+", "", latex)
    if compact.count(r"\mathrm{") >= 4 and not any(token in compact for token in (r"\frac", r"\partial", r"\sum", r"\int", r"\sqrt", r"\Delta")):
        return True
    return False


def _has_math_signal(latex: str) -> bool:
    return bool(re.search(r"\\[A-Za-z]+|[=<>_^]|\d|[\u0370-\u03ff]", latex))


def _unbalanced_braces(latex: str) -> bool:
    balance = 0
    escaped = False
    for char in latex:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "{":
            balance += 1
        elif char == "}":
            balance -= 1
            if balance < 0:
                return True
    return balance != 0


def _unbalanced_delimiters(latex: str) -> bool:
    stripped = re.sub(r"\\[A-Za-z]+\{[^{}]*\}", " ", latex)
    pairs = {"(": ")", "[": "]"}
    stack: list[str] = []
    for char in stripped:
        if char in pairs:
            stack.append(pairs[char])
        elif char in pairs.values():
            if not stack or stack[-1] != char:
                return True
            stack.pop()
    return bool(stack)


def _looks_incomplete_formula(latex: str) -> bool:
    value = latex.strip().rstrip(",;")
    if re.search(r"(?:=|[+\-*/,(])\s*$", value):
        return True
    if re.search(r"\\(?:frac|sqrt|sum|int|lim)\s*$", value):
        return True
    return False


def _adjust_confidence(confidence: float | None, flags: list[str]) -> float | None:
    if confidence is None:
        return None
    penalty = 0.0
    if "contains_prose" in flags:
        penalty += 0.25
    if "weird_unicode" in flags:
        penalty += 0.2
    if "unbalanced_braces" in flags:
        penalty += 0.2
    if "unbalanced_delimiters" in flags:
        penalty += 0.2
    if "incomplete_formula" in flags:
        penalty += 0.25
    if "weak_math_signal" in flags:
        penalty += 0.15
    if "sum_missing_lower_bound" in flags:
        penalty += 0.2
    return max(0.1, round(confidence - penalty, 3))


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        if item not in result:
            result.append(item)
    return result


def _dedupe_formulas(formulas: list[FormulaBlock]) -> list[FormulaBlock]:
    result: list[FormulaBlock] = []
    seen: set[tuple[int, str, str]] = set()
    for formula in formulas:
        key = (formula.page_number, formula.kind, re.sub(r"\s+", "", formula.latex).lower())
        if key in seen:
            continue
        seen.add(key)
        result.append(formula)
    return result


def _rescue_formula_definition(formula: FormulaBlock, reference_lines: list[tuple[int, tuple[float, float, float, float] | None, str]]) -> FormulaBlock:
    if formula.source.startswith("tex_source") or formula.bbox is None:
        return formula
    flags = set(formula.quality_flags) | set(validate_formula_latex(formula.latex))
    if not flags.intersection({"contains_prose", "romanized_ocr_noise", "needs_formula_review"}):
        return formula
    head = _extract_definition_head(formula.latex)
    if not head:
        return formula
    line_text = _find_definition_line(formula, reference_lines, head)
    if not line_text:
        return formula
    definition = _pick_definition_segment(line_text, head)
    if definition is None:
        return formula
    _, rhs = definition
    rhs = rhs.strip().rstrip(",;:.")
    if not rhs or not _contains_cyrillic(rhs):
        return formula
    candidate = repair_formula_latex(f"{head} - \\text{{{_escape_latex_text(rhs)}}}")
    candidate_flags = validate_formula_latex(candidate)
    if any(flag in candidate_flags for flag in ("weird_unicode", "romanized_ocr_noise")):
        return formula
    clean_flags = [
        flag
        for flag in formula.quality_flags
        if flag not in {"contains_prose", "romanized_ocr_noise", "needs_review"}
    ]
    keep_candidate_flags = [flag for flag in candidate_flags if flag not in {"needs_review", "contains_prose"}]
    latex_fields = _latex_variant_fields(candidate)
    return formula.model_copy(
        update={
            "latex": candidate,
            "raw_latex": formula.raw_latex or formula.latex,
            **latex_fields,
            "quality_flags": _dedupe([*clean_flags, *keep_candidate_flags, "definition_text_rescued"]),
        }
    )


def _latex_variant_fields(latex: str) -> dict[str, str]:
    cleaned = clean_latex(latex)
    normalized_latex = normalize_latex(cleaned)
    return {
        "cleaned_latex": cleaned,
        "normalized_latex": normalized_latex,
        "plain_formula_text": latex_to_plain_text(normalized_latex),
    }


def _collect_reference_lines(reference_blocks: list[TextBlock]) -> list[tuple[int, tuple[float, float, float, float] | None, str]]:
    lines: list[tuple[int, tuple[float, float, float, float] | None, str]] = []
    for block in reference_blocks:
        if block.source != "pdf_text_layer":
            continue
        if block.lines:
            for line in block.lines:
                text = " ".join(line.text.split()).strip()
                if text:
                    lines.append((block.page_number, line.bbox, text))
        else:
            text = " ".join(block.text.split()).strip()
            if text:
                lines.append((block.page_number, block.bbox, text))
    return lines


def _extract_definition_head(latex: str) -> str | None:
    value = repair_formula_latex(latex)
    inline_chunks = [chunk.strip() for chunk in re.findall(r"\$([^$]{1,120})\$", value)]
    for chunk in inline_chunks:
        head = _cleanup_definition_head(chunk)
        if head is not None:
            return head
    return _cleanup_definition_head(value)


def _cleanup_definition_head(value: str) -> str | None:
    candidate = value
    for marker in (r"\mathrm{", r"\text{", ",", ";"):
        index = candidate.find(marker)
        if index > 0:
            candidate = candidate[:index]
            break
    candidate = re.split(r"\s*-\s*", candidate, maxsplit=1)[0].strip()
    candidate = candidate.rstrip(r"~\-").strip("$ ").strip()
    if not candidate or len(candidate) > 32 or " " in candidate or "$" in candidate:
        return None
    plain = re.sub(r"\\[A-Za-z]+", "", candidate)
    if re.search(r"[A-Za-z]{3,}", plain):
        return None
    if not _has_math_signal(candidate):
        return None
    return candidate


def _find_definition_line(
    formula: FormulaBlock,
    reference_lines: list[tuple[int, tuple[float, float, float, float] | None, str]],
    head: str,
) -> str | None:
    assert formula.bbox is not None
    aliases = _definition_head_aliases(head)
    best_text: str | None = None
    best_score = -1.0
    for page_number, bbox, text in reference_lines:
        if page_number != formula.page_number or bbox is None or not _contains_cyrillic(text):
            continue
        if not _definition_line_is_near(formula.bbox, bbox):
            continue
        segments = _definition_segments(text)
        if not segments:
            continue
        segment_bonus = 0.0
        for lhs, _rhs in segments:
            lhs_key = _normalize_definition_key(lhs)
            if _matches_definition_alias(lhs_key, aliases):
                segment_bonus = 4.0
                break
        vertical_gap = max(0.0, max(formula.bbox[1] - bbox[3], bbox[1] - formula.bbox[3]))
        overlap = max(0.0, min(formula.bbox[2], bbox[2]) - max(formula.bbox[0], bbox[0]))
        score = segment_bonus + overlap * 0.01 - vertical_gap * 0.2
        if score > best_score:
            best_score = score
            best_text = text
    return best_text


def _definition_line_is_near(formula_bbox, line_bbox) -> bool:
    fx0, fy0, fx1, fy1 = formula_bbox
    lx0, ly0, lx1, ly1 = line_bbox
    vertical_gap = max(0.0, max(fy0 - ly1, ly0 - fy1))
    horizontal_overlap = max(0.0, min(fx1, lx1) - max(fx0, lx0))
    center_gap = abs(((fx0 + fx1) / 2) - ((lx0 + lx1) / 2))
    return vertical_gap <= 22 and (horizontal_overlap > 0 or center_gap <= 180)


def _definition_segments(text: str) -> list[tuple[str, str]]:
    normalized = re.sub(r"^\s*(?:Здесь|где)\s+", "", text, flags=re.IGNORECASE)
    parts = [part.strip() for part in re.split(r",\s*", normalized) if part.strip()]
    segments: list[tuple[str, str]] = []
    for part in parts:
        match = re.match(r"(.+?)\s*[–—-]\s*(.+)", part)
        if not match:
            continue
        lhs = match.group(1).strip()
        rhs = match.group(2).strip()
        if lhs and rhs:
            segments.append((lhs, rhs))
    return segments


def _pick_definition_segment(text: str, head: str) -> tuple[str, str] | None:
    segments = _definition_segments(text)
    if not segments:
        return None
    aliases = _definition_head_aliases(head)
    for lhs, rhs in segments:
        if _matches_definition_alias(_normalize_definition_key(lhs), aliases):
            return lhs, rhs
    if len(segments) == 1:
        return segments[0]
    return None


def _definition_head_aliases(head: str) -> set[str]:
    value = head
    for command, replacement in (
        (r"\rho", "rho"),
        (r"\mu", "mu"),
        (r"\phi", "phi"),
        (r"\Phi", "phi"),
        (r"\psi", "psi"),
        (r"\Gamma", "gamma"),
        (r"\Delta", "delta"),
        (r"\varphi", "phi"),
    ):
        value = value.replace(command, replacement)
    value = re.sub(r"\\[A-Za-z]+", "", value)
    base = _normalize_definition_key(value)
    aliases = {base} if base else set()
    if base.startswith("rho"):
        aliases.add("r" + base[3:])
    if base.startswith("mu"):
        suffix = base[2:]
        aliases.add("m" + suffix)
        aliases.add(suffix + "m")
        if suffix:
            aliases.add(suffix)
    if base.startswith("ui"):
        aliases.add("iu")
    if base.startswith("qx"):
        aliases.add("xq")
    if base.startswith("qy"):
        aliases.add("yq")
    if base.startswith("qz"):
        aliases.add("zq")
    if "eff" in base:
        aliases.add("effm")
        aliases.add("meff")
    return {alias for alias in aliases if alias}


def _normalize_definition_key(value: str) -> str:
    lowered = value.lower().replace("ё", "е")
    lowered = re.sub(r"^\s*(?:здесь|где)\s+", "", lowered)
    return re.sub(r"[^a-zа-я0-9]+", "", lowered)


def _matches_definition_alias(lhs_key: str, aliases: set[str]) -> bool:
    for alias in aliases:
        if not alias or not lhs_key:
            continue
        if lhs_key == alias or lhs_key in alias or alias in lhs_key:
            return True
        if len(lhs_key) <= 3 and len(alias) <= 3 and sorted(lhs_key) == sorted(alias):
            return True
    return False


def _contains_cyrillic(text: str) -> bool:
    return any("а" <= char.lower() <= "я" or char in "Ёё" for char in text)


def _escape_latex_text(text: str) -> str:
    escaped = str(text)
    for original, replacement in (
        ("\\", r"\textbackslash{}"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("%", r"\%"),
        ("&", r"\&"),
        ("#", r"\#"),
        ("_", r"\_"),
    ):
        escaped = escaped.replace(original, replacement)
    return escaped
