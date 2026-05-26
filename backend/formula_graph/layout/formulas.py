from __future__ import annotations

import re

from backend.formula_graph.models import FormulaBlock, TextBlock


INLINE_PATTERNS = [
    re.compile(r"(?<!\\)\$(.+?)(?<!\\)\$"),
    re.compile(r"\\\((.+?)\\\)"),
]
BLOCK_PATTERNS = [
    re.compile(r"(?<!\\)\$\$(.+?)(?<!\\)\$\$", re.DOTALL),
    re.compile(r"\\\[(.+?)\\\]", re.DOTALL),
    re.compile(r"\\begin\{equation\*?\}(.+?)\\end\{equation\*?\}", re.DOTALL),
    re.compile(r"\\begin\{align\*?\}(.+?)\\end\{align\*?\}", re.DOTALL),
]

COMMAND_MATH_RE = re.compile(
    r"\\(?:frac|sum|int|sqrt|lim|prod|begin|alpha|beta|gamma|delta|phi|psi|theta|xi|rho|mu|partial)"
)
RELATION_RE = re.compile(r"(?:=|<=|>=|<|>|≈|≃|≡|≤|≥|∈|∉|⊂|⊆|∪|∩|\\in|\\subset|\\cup|\\cap)")
GREEK_RE = re.compile(r"[\u0370-\u03ff]")
MATH_SYMBOL_RE = re.compile(r"[\u2200-\u22ff+\-*/=<>_^{}()[\]|.,:;]")
PROSE_RE = re.compile(
    r"\b(?:abstract|introduction|figure|table|proof|theorem|lemma|corollary|definition|remark|"
    r"where|let|if|observe|then|since|with|from|that|which|this|these|there|exists|paper|shown|"
    r"represented|expressed|satisfying|defined|respectively|restriction|for|can|have|has|holds|we|as|follows)\b",
    re.IGNORECASE,
)
CAPTION_RE = re.compile(r"^(?:figure|table|section|references|abstract|\*|arxiv:)", re.IGNORECASE)
ALLOWED_MATH_WORDS = {
    "lim",
    "max",
    "min",
    "sup",
    "inf",
    "sin",
    "cos",
    "tan",
    "log",
    "exp",
    "det",
    "dim",
    "ker",
    "mod",
    "gcd",
    "fix",
}


def extract_formulas(text_blocks: list[TextBlock]) -> list[FormulaBlock]:
    formulas: list[FormulaBlock] = []
    for block in text_blocks:
        text = block.text
        for pattern in BLOCK_PATTERNS:
            for match in pattern.finditer(text):
                latex = _clean_latex(match.group(1))
                if latex:
                    formulas.append(_formula(block, latex, "block", len(formulas) + 1, 0.82))
        for pattern in INLINE_PATTERNS:
            for match in pattern.finditer(text):
                latex = _clean_latex(match.group(1))
                if latex:
                    formulas.append(_formula(block, latex, "inline", len(formulas) + 1, 0.78))

        for prose_text, prose_bbox, prose_spans in _iter_formula_lines(block):
            prose_text = _strip_delimited_math(prose_text)
            if not PROSE_RE.search(prose_text) and _line_formula(prose_text):
                continue
            for candidate_text, latex in _inline_formulas_from_prose(prose_text):
                if not _already_has_formula(formulas, block.id, latex):
                    formulas.append(
                        _formula(
                            block,
                            latex,
                            "inline",
                            len(formulas) + 1,
                            0.72,
                            source="text_inline_pattern",
                            quality_flags=["inline_from_text"],
                            bbox=_estimate_inline_bbox(prose_text, candidate_text, prose_bbox, prose_spans),
                        )
                    )

        for line_text, line_bbox, _ in _iter_formula_lines(block):
            if _line_has_delimited_formula(line_text):
                continue
            maybe_formula = _line_formula(line_text)
            if maybe_formula and not _already_has_formula(formulas, block.id, maybe_formula):
                formulas.append(_formula(block, maybe_formula, "block", len(formulas) + 1, 0.58, bbox=line_bbox))
    formulas.extend(_cross_block_inline_formulas(text_blocks, formulas, len(formulas)))
    formulas.extend(_fragment_group_formulas(text_blocks, formulas, len(formulas)))
    return formulas


def _iter_formula_lines(block: TextBlock):
    if block.lines:
        for line in block.lines:
            if line.text.strip():
                yield line.text, line.bbox, line.spans
        return
    for line in block.text.splitlines() or [block.text]:
        if line.strip():
            yield line, block.bbox, []


def _line_has_delimited_formula(text: str) -> bool:
    return any(pattern.search(text) for pattern in [*BLOCK_PATTERNS, *INLINE_PATTERNS])


def _already_has_formula(formulas: list[FormulaBlock], block_id: str, latex: str) -> bool:
    normalized = _normalize_for_compare(latex)
    return any(formula.context_block_id == block_id and _normalize_for_compare(formula.latex) == normalized for formula in formulas)


def _normalize_for_compare(value: str) -> str:
    return re.sub(r"\s+", "", value).strip().lower()


def _formula(
    block: TextBlock,
    latex: str,
    kind: str,
    index: int,
    confidence: float,
    source: str = "text_pattern",
    quality_flags: list[str] | None = None,
    bbox=None,
) -> FormulaBlock:
    return FormulaBlock(
        id=f"f_{index}",
        page_number=block.page_number,
        latex=latex,
        kind=kind,
        context_block_id=block.id,
        bbox=bbox if bbox is not None else block.bbox,
        source=source,
        confidence=confidence,
        quality_flags=quality_flags or [],
    )


def _formula_from_group(blocks: list[TextBlock], latex: str, index: int) -> FormulaBlock:
    bbox = _union_bbox([block.bbox for block in blocks if block.bbox is not None])
    return FormulaBlock(
        id=f"f_{index}",
        page_number=blocks[0].page_number,
        latex=latex,
        kind="block",
        context_block_id=blocks[0].id,
        bbox=bbox,
        source="text_pattern",
        confidence=0.55,
    )


def _clean_latex(value: str) -> str:
    return " ".join(value.strip().split())


def _strip_delimited_math(text: str) -> str:
    result = text
    for pattern in [*BLOCK_PATTERNS, *INLINE_PATTERNS]:
        result = pattern.sub(" ", result)
    return result


def _line_formula(text: str) -> str | None:
    compact = " ".join(text.strip().split())
    compact = re.sub(r"^(?:equation|formula)\s*:\s*", "", compact, flags=re.IGNORECASE)
    compact = compact.rstrip(" ,;")
    if not _is_probable_standalone_formula(compact):
        return None
    return _text_formula_to_latex(compact)


def text_line_to_latex_candidate(text: str) -> str | None:
    return _line_formula(text)


INLINE_RELATION_RE = re.compile(
    r"(?<![A-Za-z])([A-Za-z\u0370-\u03ff][A-Za-z0-9\u0370-\u03ff_(){}]*\s*(?::=|=|∈|≤|≥|<|>)\s*"
    r"(?:[-+*/^_(){}\[\]0-9A-Za-z\u0370-\u03ff∞→←∈∪∩≤≥◦·.,\s]){1,70})"
)


def _inline_formulas_from_prose(text: str) -> list[tuple[str, str]]:
    compact = " ".join(text.split())
    if len(compact) < 8:
        return []
    result: list[tuple[str, str]] = []
    for segment in _inline_formula_segments(compact):
        if len(segment) < 5:
            continue
        if not PROSE_RE.search(segment) and not _is_math_heavy_inline_segment(segment):
            continue
        for match in INLINE_RELATION_RE.finditer(segment):
            candidate = _trim_inline_candidate(match.group(1))
            if not candidate or len(candidate) > 90:
                continue
            if _is_probable_inline_formula(candidate):
                result.append((candidate, _text_formula_to_latex(candidate)))
    return _dedupe_inline_matches(result)


def _inline_formula_segments(text: str) -> list[str]:
    segments = [text]
    for match in re.finditer(r"\b(?:where|with|such that|satisfying|equation:)\b", text, flags=re.IGNORECASE):
        suffix = text[match.end() :].strip(" ,;:")
        if suffix:
            segments.append(suffix)

    result: list[str] = []
    for segment in segments:
        result.extend(_split_inline_formula_sequence(segment))
    return result


def _split_inline_formula_sequence(text: str) -> list[str]:
    parts: list[str] = []
    current_start = 0
    depth = 0
    for index, char in enumerate(text):
        if char in "([{":
            depth += 1
        elif char in ")]}" and depth > 0:
            depth -= 1
        elif char == "," and depth == 0:
            suffix = text[index + 1 :].strip()
            if _starts_with_inline_relation(suffix):
                prefix = text[current_start:index].strip()
                if prefix:
                    parts.append(prefix)
                current_start = index + 1
    tail = text[current_start:].strip()
    if tail:
        parts.append(tail)
    return parts or [text]


def _starts_with_inline_relation(text: str) -> bool:
    return bool(
        re.match(
            r"^[A-Za-z\u0370-\u03ff\\][A-Za-z0-9\u0370-\u03ff_\\{}()]*\s*(?::=|=|∈|≤|≥|<|>|\\in)\s*",
            text,
        )
    )


def _is_math_heavy_inline_segment(text: str) -> bool:
    if not RELATION_RE.search(text):
        return False
    math_symbols = len(MATH_SYMBOL_RE.findall(text))
    has_command = bool(COMMAND_MATH_RE.search(text))
    has_greek = bool(GREEK_RE.search(text))
    letters = sum(char.isalpha() for char in text)
    return (has_greek or has_command or math_symbols >= 2) and letters <= max(26, len(text) * 0.85)


def _dedupe_inline_matches(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for candidate, latex in items:
        key = _normalize_for_compare(latex)
        if key in seen:
            continue
        seen.add(key)
        result.append((candidate, latex))
    return result


def _trim_inline_candidate(candidate: str) -> str:
    candidate = re.split(
        r"\b(?:where|with|and|then|since|which|that|such|so|therefore|observe|is|are|was|were|be|by|for|can|have|has|holds|we|as|follows)\b",
        candidate,
        maxsplit=1,
    )[0]
    candidate = re.split(r"[.;]", candidate, maxsplit=1)[0]
    candidate = candidate.strip(" ,")
    candidate = _trim_after_top_level_comma(candidate)
    while candidate and _has_extra_trailing_closer(candidate):
        candidate = candidate[:-1].rstrip()
    return candidate


def _estimate_inline_bbox(line_text: str, candidate_text: str, fallback_bbox, spans) -> tuple[float, float, float, float] | None:
    if not spans or not line_text or not candidate_text:
        return fallback_bbox
    match = _find_normalized_substring(line_text, candidate_text)
    if match is None:
        return fallback_bbox
    start, end = match
    return _bbox_from_char_range(spans, start, end) or fallback_bbox


def _find_normalized_substring(text: str, query: str) -> tuple[int, int] | None:
    normalized_text, text_map = _normalize_with_mapping(text)
    normalized_query, _ = _normalize_with_mapping(query)
    if not normalized_text or not normalized_query:
        return None
    start = normalized_text.find(normalized_query)
    if start < 0:
        return None
    end = start + len(normalized_query)
    original_start = text_map[start]
    original_end = text_map[end - 1] + 1
    return original_start, original_end


def _normalize_with_mapping(text: str) -> tuple[str, list[int]]:
    result: list[str] = []
    mapping: list[int] = []
    previous_space = True
    for index, char in enumerate(text):
        if char.isspace():
            if previous_space:
                continue
            result.append(" ")
            mapping.append(index)
            previous_space = True
            continue
        result.append(char)
        mapping.append(index)
        previous_space = False
    normalized = "".join(result).strip()
    if normalized == "".join(result):
        return normalized, mapping
    left_trim = 0
    while left_trim < len(result) and result[left_trim] == " ":
        left_trim += 1
    right_trim = len(result)
    while right_trim > left_trim and result[right_trim - 1] == " ":
        right_trim -= 1
    return normalized, mapping[left_trim:right_trim]


def _bbox_from_char_range(spans, start: int, end: int) -> tuple[float, float, float, float] | None:
    boxes = []
    cursor = 0
    for span in spans:
        text = span.text or ""
        bbox = span.bbox
        length = len(text)
        if not bbox or length <= 0:
            cursor += length
            continue
        span_start = cursor
        span_end = cursor + length
        overlap_start = max(start, span_start)
        overlap_end = min(end, span_end)
        if overlap_end > overlap_start:
            x0, y0, x1, y1 = bbox
            width = max(1e-6, x1 - x0)
            local_start = overlap_start - span_start
            local_end = overlap_end - span_start
            sub_x0 = x0 + (width * local_start / length)
            sub_x1 = x0 + (width * local_end / length)
            boxes.append((sub_x0, y0, sub_x1, y1))
        cursor = span_end
    return _union_bbox(boxes)


def _trim_after_top_level_comma(text: str) -> str:
    depth = 0
    for index, char in enumerate(text):
        if char in "([{":
            depth += 1
        elif char in ")]}" and depth > 0:
            depth -= 1
        elif char == "," and depth == 0:
            prefix = text[:index].strip()
            suffix = text[index + 1 :].strip()
            if prefix and RELATION_RE.search(prefix) and suffix and (suffix[0].isalpha() or suffix[0] == "\\"):
                return prefix
    return text


def _has_extra_trailing_closer(text: str) -> bool:
    pairs = {"(": ")", "[": "]", "{": "}"}
    stack: list[str] = []
    for char in text:
        if char in pairs:
            stack.append(pairs[char])
        elif char in pairs.values():
            if not stack or stack[-1] != char:
                return char == text[-1]
            stack.pop()
    return False


def _is_probable_inline_formula(text: str) -> bool:
    if len(text) < 5:
        return False
    if PROSE_RE.search(text) or CAPTION_RE.search(text):
        return False
    if _looks_incomplete(text):
        return False
    if not _has_balanced_inline_delimiters(text):
        return False
    math_symbols = len(MATH_SYMBOL_RE.findall(text))
    has_relation = bool(RELATION_RE.search(text))
    letters = sum(char.isalpha() for char in text)
    if not has_relation or math_symbols < 1:
        return False
    return letters <= max(18, len(text) * 0.75)


def _has_balanced_inline_delimiters(text: str) -> bool:
    pairs = {"(": ")", "[": "]", "{": "}"}
    stack: list[str] = []
    for char in text:
        if char in pairs:
            stack.append(pairs[char])
        elif char in pairs.values():
            if not stack or stack[-1] != char:
                return False
            stack.pop()
    return not stack


def _cross_block_inline_formulas(
    text_blocks: list[TextBlock],
    existing: list[FormulaBlock],
    offset: int,
) -> list[FormulaBlock]:
    result: list[FormulaBlock] = []
    pages = sorted({block.page_number for block in text_blocks})
    for page_number in pages:
        page_blocks = [
            block
            for block in text_blocks
            if block.page_number == page_number and block.bbox is not None and block.text.strip()
        ]
        for start in range(len(page_blocks)):
            window = page_blocks[start : start + 4]
            if len(window) < 2:
                continue
            combined, spans = _combined_block_text(window)
            if not RELATION_RE.search(combined):
                continue
            for candidate_text, latex in _inline_formulas_from_prose(combined):
                if _already_has_page_formula([*existing, *result], page_number, latex):
                    continue
                bbox = _estimate_cross_block_bbox(candidate_text, combined, spans)
                if bbox is None:
                    continue
                normalized = _normalize_for_compare(latex)
                result = [
                    formula
                    for formula in result
                    if not (
                        formula.page_number == page_number
                        and _normalize_for_compare(formula.latex) != normalized
                        and _normalize_for_compare(formula.latex) in normalized
                    )
                ]
                result.append(
                    _formula(
                        window[0],
                        latex,
                        "inline",
                        offset + len(result) + 1,
                        0.68,
                        source="text_inline_pattern",
                        quality_flags=["inline_from_text", "cross_block_inline"],
                        bbox=bbox,
                    )
                )
    return result


def _already_has_page_formula(formulas: list[FormulaBlock], page_number: int, latex: str) -> bool:
    normalized = _normalize_for_compare(latex)
    for formula in formulas:
        if formula.page_number != page_number:
            continue
        current = _normalize_for_compare(formula.latex)
        if current == normalized or (normalized in current and normalized != current):
            return True
    return False


def _combined_block_text(blocks: list[TextBlock]) -> tuple[str, list[tuple[int, int, tuple[float, float, float, float]]]]:
    parts: list[str] = []
    spans: list[tuple[int, int, tuple[float, float, float, float]]] = []
    cursor = 0
    for block in blocks:
        text = " ".join((block.text or "").split())
        if not text or block.bbox is None:
            continue
        if parts:
            parts.append(" ")
            cursor += 1
        start = cursor
        parts.append(text)
        cursor += len(text)
        spans.append((start, cursor, block.bbox))
    return "".join(parts), spans


def _estimate_cross_block_bbox(
    candidate_text: str,
    combined_text: str,
    spans: list[tuple[int, int, tuple[float, float, float, float]]],
) -> tuple[float, float, float, float] | None:
    match = _find_normalized_substring(combined_text, candidate_text)
    if match is None:
        return None
    start, end = match
    boxes = []
    for span_start, span_end, bbox in spans:
        overlap_start = max(start, span_start)
        overlap_end = min(end, span_end)
        if overlap_end <= overlap_start:
            continue
        x0, y0, x1, y1 = bbox
        width = max(1e-6, x1 - x0)
        length = max(1, span_end - span_start)
        local_start = overlap_start - span_start
        local_end = overlap_end - span_start
        boxes.append((x0 + width * local_start / length, y0, x0 + width * local_end / length, y1))
    return _union_bbox(boxes)


def _fragment_group_formulas(text_blocks: list[TextBlock], existing: list[FormulaBlock], offset: int) -> list[FormulaBlock]:
    used = {formula.context_block_id for formula in existing if formula.context_block_id}
    result: list[FormulaBlock] = []
    pages = sorted({block.page_number for block in text_blocks})
    for page_number in pages:
        blocks = [
            block
            for block in text_blocks
            if block.page_number == page_number
            and block.bbox is not None
            and block.id not in used
            and _is_formula_fragment(block.text)
        ]
        blocks.sort(key=lambda block: (block.bbox[1], block.bbox[0]))  # type: ignore[index]
        consumed: set[str] = set()
        for block in blocks:
            if block.id in consumed:
                continue
            group = [block]
            consumed.add(block.id)
            changed = True
            while changed:
                changed = False
                group_bbox = _union_bbox([item.bbox for item in group if item.bbox is not None])
                if group_bbox is None:
                    break
                for candidate in blocks:
                    if candidate.id in consumed or candidate.bbox is None:
                        continue
                    if _nearby_bbox(group_bbox, candidate.bbox):
                        group.append(candidate)
                        consumed.add(candidate.id)
                        changed = True
            if len(group) < 2:
                continue
            group.sort(key=lambda item: (item.bbox[1], item.bbox[0]))  # type: ignore[index]
            text = " ".join(item.text.strip() for item in group)
            formula = _line_formula(text)
            if formula:
                result.append(_formula_from_group(group, formula, offset + len(result) + 1))
    return result


def _is_formula_fragment(text: str) -> bool:
    compact = " ".join(text.split())
    if not compact or len(compact) > 120:
        return False
    if CAPTION_RE.search(compact) or PROSE_RE.search(compact):
        return False
    math_chars = sum(1 for char in compact if char in "=<>+-*/^_{}()[]|,.:;∑∫√∞→←∈∪∩≤≥◦·" or "\u0370" <= char <= "\u03ff")
    if math_chars < 1:
        return False
    letters = sum(char.isalpha() for char in compact)
    return math_chars >= max(1, letters * 0.12)


def _nearby_bbox(a, b) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    vertical_gap = max(0.0, max(ay0 - by1, by0 - ay1))
    horizontal_gap = max(0.0, max(ax0 - bx1, bx0 - ax1))
    center_gap = abs(((ax0 + ax1) / 2) - ((bx0 + bx1) / 2))
    return vertical_gap <= 22 and (horizontal_gap <= 120 or center_gap <= 160)


def _union_bbox(boxes) -> tuple[float, float, float, float] | None:
    boxes = [box for box in boxes if box is not None]
    if not boxes:
        return None
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _is_probable_standalone_formula(text: str) -> bool:
    if len(text) < 8 or len(text) > 220:
        return False
    if CAPTION_RE.search(text) or "?" in text:
        return False
    if _looks_incomplete(text):
        return False
    if not _has_balanced_inline_delimiters(text):
        return False
    if re.match(r"^[•*\-]\s*(?:if|when)\b", text, re.IGNORECASE):
        return False
    if re.match(r"^(?:=|≤|≥|<|>|≈|≃|≡)", text):
        return False
    if re.match(r"^\d+\s*[\),]", text):
        return False
    if re.match(r"^\d", text):
        return False
    if re.match(r"^[A-Za-z]\s*=\s*\d+\b", text):
        return False
    if re.fullmatch(r"[A-Za-z]\([^)]{1,12}\)\s*:?=\s*[-+]?\d+(?:/\d+)?", text):
        return False

    has_relation = bool(RELATION_RE.search(text))
    has_command = bool(COMMAND_MATH_RE.search(text))
    has_greek = bool(GREEK_RE.search(text))
    math_symbols = len(MATH_SYMBOL_RE.findall(text))
    letters = sum(char.isalpha() for char in text)
    digits = sum(char.isdigit() for char in text)
    math_density = (math_symbols + digits) / max(1, len(text))

    if re.match(r"^[A-Za-z]\s*=\s*(?:\d|[A-Za-z])\b", text) and not has_greek and math_density < 0.45:
        return False

    if not has_relation and not has_command:
        return False
    if PROSE_RE.search(text) and math_density < 0.42:
        return False

    prose_words = _prose_words(text)
    if len(prose_words) >= 2:
        return False
    if len(prose_words) == 1 and not (has_command or has_greek or math_density >= 0.45):
        return False
    if "." in text and prose_words:
        return False
    if letters > 34 and math_density < 0.38 and not has_command:
        return False
    if math_symbols < 2 and not has_command and not has_greek:
        return False
    return True


def _looks_incomplete(text: str) -> bool:
    stripped = text.strip()
    if re.search(r"(?:=|[+\-*/,(])\s*$", stripped):
        return True
    if re.fullmatch(r"[A-Za-z\u0370-\u03ff]\w*\s*=", stripped):
        return True
    if re.fullmatch(r"\(?\d+\)?", stripped):
        return True
    return False


def _prose_words(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z]{4,}", text)
    return [word for word in words if word.lower() not in ALLOWED_MATH_WORDS and not word.isupper()]


GREEK_LATEX = {
    "α": r"\alpha",
    "β": r"\beta",
    "γ": r"\gamma",
    "Γ": r"\Gamma",
    "δ": r"\delta",
    "Δ": r"\Delta",
    "θ": r"\theta",
    "λ": r"\lambda",
    "μ": r"\mu",
    "π": r"\pi",
    "ρ": r"\rho",
    "σ": r"\sigma",
    "Σ": r"\Sigma",
    "φ": r"\phi",
    "ϕ": r"\phi",
    "Φ": r"\Phi",
    "ψ": r"\psi",
    "Ψ": r"\Psi",
    "ω": r"\omega",
    "ξ": r"\xi",
}
SYMBOL_LATEX = {
    "∞": r"\infty",
    "→": r"\to",
    "←": r"\leftarrow",
    "∈": r"\in",
    "∉": r"\notin",
    "∪": r"\cup",
    "∩": r"\cap",
    "≤": r"\le",
    "≥": r"\ge",
    "≈": r"\approx",
    "≃": r"\simeq",
    "≡": r"\equiv",
    "·": r"\cdot",
    "◦": r"\circ",
}
GREEK_LATEX.update(
    {
        "α": r"\alpha",
        "β": r"\beta",
        "γ": r"\gamma",
        "Γ": r"\Gamma",
        "δ": r"\delta",
        "Δ": r"\Delta",
        "ε": r"\epsilon",
        "ζ": r"\zeta",
        "η": r"\eta",
        "θ": r"\theta",
        "ϑ": r"\vartheta",
        "κ": r"\kappa",
        "λ": r"\lambda",
        "μ": r"\mu",
        "ν": r"\nu",
        "π": r"\pi",
        "ρ": r"\rho",
        "σ": r"\sigma",
        "Σ": r"\Sigma",
        "τ": r"\tau",
        "φ": r"\phi",
        "ϕ": r"\phi",
        "Φ": r"\Phi",
        "χ": r"\chi",
        "ψ": r"\psi",
        "Ψ": r"\Psi",
        "ω": r"\omega",
        "Ω": r"\Omega",
        "ξ": r"\xi",
        "Ξ": r"\Xi",
    }
)
SYMBOL_LATEX.update(
    {
        "∞": r"\infty",
        "→": r"\to",
        "←": r"\leftarrow",
        "↦": r"\mapsto",
        "⇒": r"\Rightarrow",
        "⇔": r"\Leftrightarrow",
        "∈": r"\in",
        "∉": r"\notin",
        "∋": r"\ni",
        "∪": r"\cup",
        "∩": r"\cap",
        "⊂": r"\subset",
        "⊆": r"\subseteq",
        "≤": r"\le",
        "≥": r"\ge",
        "≈": r"\approx",
        "≃": r"\simeq",
        "≡": r"\equiv",
        "≠": r"\ne",
        "±": r"\pm",
        "×": r"\times",
        "÷": r"\div",
        "∑": r"\sum",
        "∫": r"\int",
        "√": r"\sqrt",
        "∂": r"\partial",
        "∇": r"\nabla",
        "∅": r"\emptyset",
        "∗": r"\ast",
        "·": r"\cdot",
        "⋅": r"\cdot",
        "◦": r"\circ",
        "−": "-",
    }
)
SUBSCRIPTABLE_GREEK = "psi|phi|omega|xi|theta|rho|alpha|beta|gamma|lambda|mu|sigma|tau|nu"


def _text_formula_to_latex(text: str) -> str:
    result = text.strip().rstrip(".")
    result = result.replace("•", "").strip()
    for symbol, latex in GREEK_LATEX.items():
        result = result.replace(symbol, f" {latex} ")
    for symbol, latex in SYMBOL_LATEX.items():
        result = result.replace(symbol, f" {latex} ")
    result = re.sub(r"\blim\b", r"\\lim", result)
    result = re.sub(r"(\\in)\s+R\s*([A-Za-z])\b", r"\1 \\mathbb{R}^{\2}", result)
    result = re.sub(rf"\\({SUBSCRIPTABLE_GREEK})\s*([A-Za-z]?\d+)", r"\\\1_{\2}", result)
    result = re.sub(rf"\\({SUBSCRIPTABLE_GREEK})\s*([A-Za-z]{{2}})(?=\b|\()", r"\\\1_{\2}", result)
    result = re.sub(rf"\\({SUBSCRIPTABLE_GREEK})\s*([A-Za-z])\b", r"\\\1_{\2}", result)
    result = re.sub(r"\b([A-Za-z])(\d+)\b", r"\1_{\2}", result)
    result = re.sub(r"\s+", " ", result)
    return result.strip()
