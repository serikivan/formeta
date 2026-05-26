from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from backend.formula_graph.layout.tex_source import BLOCK_PATTERNS, INLINE_PATTERNS, apply_simple_macros, extract_simple_macros
from backend.formula_graph.models import FormulaBlock, TextBlock
from backend.formula_graph.postprocessing.formulas import repair_formula_latex


SECTION_LEVELS = {
    "part": 0,
    "chapter": 1,
    "section": 2,
    "subsection": 3,
    "subsubsection": 4,
    "paragraph": 5,
}
SECTION_RE = re.compile(
    r"\\(?P<kind>part|chapter|section|subsection|subsubsection|paragraph)\*?"
    r"(?:\[[^\]]*\])?\{(?P<title>(?:[^{}]|\{[^{}]*\})*)\}",
    re.DOTALL,
)
TITLE_RE = re.compile(r"\\title(?:\[[^\]]*\])?\{(?P<value>(?:[^{}]|\{[^{}]*\})*)\}", re.DOTALL)
AUTHOR_RE = re.compile(r"\\author(?:\[[^\]]*\])?\{(?P<value>(?:[^{}]|\{[^{}]*\})*)\}", re.DOTALL)
ABSTRACT_RE = re.compile(r"\\begin\{abstract\}(?P<value>.*?)\\end\{abstract\}", re.DOTALL | re.IGNORECASE)
TOKEN_RE = re.compile(r"\[FORMULA_\d{3}\]")
INPUT_RE = re.compile(r"\\(?:input|include)\{([^{}]+)\}")
NON_TEXT_ENVIRONMENTS = (
    "figure",
    "figure*",
    "table",
    "table*",
    "picture",
    "tikzpicture",
    "pspicture",
)
TEXT_ENVIRONMENT_LABELS = {
    "theorem": "Theorem",
    "definition": "Definition",
    "corollary": "Corollary",
    "example": "Example",
    "lemma": "Lemma",
    "remark": "Remark",
    "proposition": "Proposition",
    "proof": "Proof",
}


@dataclass(frozen=True)
class TexDocument:
    text_blocks: list[TextBlock]
    text_with_tokens: list[TextBlock]
    formulas: list[FormulaBlock]
    warnings: list[str]


@dataclass(frozen=True)
class _TexEvent:
    start: int
    end: int
    kind: str
    value: str
    subtype: str = ""
    label: str | None = None


def parse_tex_document(source_dir: Path) -> TexDocument:
    tex_files = sorted(source_dir.rglob("*.tex"))
    if not tex_files:
        return TexDocument([], [], [], ["arXiv source archive contains no .tex files."])

    main = _find_main_tex(tex_files)
    try:
        text = _expand_tex_file(main, set())
    except Exception as exc:
        return TexDocument([], [], [], [f"Не удалось разобрать TeX-источник: {' '.join(str(exc).split())[:240]}"])

    macros = extract_simple_macros(text)
    preamble = apply_simple_macros(text[: max(0, text.find(r"\begin{document}"))], macros)
    title = _extract_tex_command(TITLE_RE, preamble)
    author = _extract_tex_command(AUTHOR_RE, preamble)
    body = apply_simple_macros(_document_body(text), macros)
    body = _normalize_text_environments(_strip_non_text_environments(_strip_comments(body)))
    events = _collect_events(body)
    text_blocks: list[TextBlock] = []
    text_with_tokens: list[TextBlock] = []
    formulas: list[FormulaBlock] = []
    current_section_id: str | None = None
    current_section_title = "Document"
    section_count = 0
    paragraph_text_parts: list[str] = []
    paragraph_token_parts: list[str] = []
    last = 0

    def append_metadata_block(role: str, value: str) -> None:
        cleaned = _clean_paragraph_text(_clean_tex_text(value))
        if not cleaned:
            return
        block = TextBlock(
            id=f"tex_{role}_{len(text_blocks) + 1}",
            page_number=1,
            text=cleaned,
            source="tex_source",
            confidence=0.99,
            role=role,
            section_id=None,
        )
        text_blocks.append(block)
        text_with_tokens.append(block.model_copy())

    def flush_paragraph() -> None:
        text = _clean_paragraph_text(" ".join(paragraph_text_parts))
        token_text = _clean_paragraph_text(" ".join(paragraph_token_parts))
        paragraph_text_parts.clear()
        paragraph_token_parts.clear()
        if not _is_meaningful_paragraph(text) and not _is_meaningful_paragraph(token_text):
            return
        block_id = f"tex_t_{len(text_blocks) + 1}"
        raw_block = TextBlock(
            id=block_id,
            page_number=1,
            text=text or token_text,
            source="tex_source",
            confidence=0.99,
            role="paragraph",
            section_id=current_section_id,
        )
        token_block = raw_block.model_copy(update={"text": token_text or text})
        text_blocks.append(raw_block)
        text_with_tokens.append(token_block)

    def append_text(segment: str) -> None:
        cleaned = _clean_tex_text(segment)
        if not cleaned:
            return
        chunks = [chunk for chunk in re.split(r"\n\s*\n+", cleaned) if _is_meaningful_paragraph(chunk)]
        for chunk_index, chunk in enumerate(chunks):
            if chunk_index > 0:
                flush_paragraph()
            paragraph_text_parts.append(chunk)
            paragraph_token_parts.append(chunk)

    def append_formula_token(token: str) -> None:
        paragraph_token_parts.append(token)

    def append_section(title: str) -> None:
        nonlocal current_section_id, current_section_title, section_count
        flush_paragraph()
        section_count += 1
        current_section_id = f"sec_{section_count}"
        current_section_title = _clean_tex_text(title) or current_section_title
        section_block = TextBlock(
            id=f"tex_s_{section_count}",
            page_number=1,
            text=current_section_title,
            source="tex_source",
            confidence=0.99,
            role="section",
            section_id=current_section_id,
        )
        text_blocks.append(section_block)
        text_with_tokens.append(section_block.model_copy())

    append_metadata_block("title", title)
    append_metadata_block("author", author)

    for event in events:
        if event.start < last:
            continue
        append_text(body[last:event.start])
        if event.kind == "section":
            append_section(event.value)
        elif event.kind == "abstract":
            flush_paragraph()
            append_metadata_block("abstract", event.value)
        elif event.kind == "formula":
            token = f"[FORMULA_{len(formulas) + 1:03d}]"
            formulas.append(
                FormulaBlock(
                    id=f"f_{len(formulas) + 1}",
                    page_number=1,
                    latex=repair_formula_latex(_clean_tex_formula(event.value)),
                    kind=event.subtype,  # type: ignore[arg-type]
                    token=token,
                    source="tex_source",
                    confidence=0.99,
                    quality_flags=["from_tex_source"],
                    section_id=current_section_id,
                    label=event.label,
                )
            )
            append_formula_token(token)
        last = event.end
    append_text(body[last:])
    flush_paragraph()

    return TexDocument(text_blocks, text_with_tokens, formulas, [])


def _find_main_tex(tex_files: list[Path]) -> Path:
    candidates = []
    for path in tex_files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        score = 0
        if "\\documentclass" in text:
            score += 3
        if "\\begin{document}" in text:
            score += 3
        score += min(path.stat().st_size / 100_000, 3)
        candidates.append((score, path))
    return max(candidates, key=lambda item: item[0])[1] if candidates else tex_files[0]


def _expand_tex_file(path: Path, seen: set[Path]) -> str:
    path = path.resolve()
    if path in seen:
        return ""
    seen.add(path)
    text = _read_tex(path)

    def replace_input(match: re.Match[str]) -> str:
        name = match.group(1).strip()
        child = path.parent / name
        if child.suffix.lower() != ".tex":
            child = child.with_suffix(".tex")
        if not child.exists():
            return ""
        return _expand_tex_file(child, seen)

    return INPUT_RE.sub(replace_input, text)


def _read_tex(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1", errors="ignore")


def _strip_comments(text: str) -> str:
    return "\n".join(re.sub(r"(?<!\\)%.*$", "", line) for line in text.splitlines())


def _document_body(text: str) -> str:
    begin = text.find(r"\begin{document}")
    if begin >= 0:
        text = text[begin + len(r"\begin{document}") :]
    end = text.find(r"\end{document}")
    if end >= 0:
        text = text[:end]
    return text


def _strip_non_text_environments(text: str) -> str:
    for environment in NON_TEXT_ENVIRONMENTS:
        name = re.escape(environment)
        text = re.sub(rf"\\begin\{{{name}\}}.*?\\end\{{{name}\}}", "\n", text, flags=re.DOTALL)
    text = re.sub(r"\\includegraphics(?:\[[^\]]*\])?\{[^{}]*\}", " ", text)
    return text


def _normalize_text_environments(text: str) -> str:
    for environment, label in TEXT_ENVIRONMENT_LABELS.items():
        name = re.escape(environment)
        text = re.sub(rf"\\begin\{{{name}\}}(?:\[[^\]]*\])?", f"\n\n{label}. ", text, flags=re.IGNORECASE)
        text = re.sub(rf"\\end\{{{name}\}}", "\n\n", text, flags=re.IGNORECASE)
    return text


def _collect_events(text: str) -> list[_TexEvent]:
    events: list[_TexEvent] = []
    occupied: list[tuple[int, int]] = []
    for match in ABSTRACT_RE.finditer(text):
        events.append(_TexEvent(match.start(), match.end(), "abstract", match.group("value"), "abstract"))
        occupied.append((match.start(), match.end()))
    for pattern in BLOCK_PATTERNS:
        for match in pattern.finditer(text):
            if any(start <= match.start() < end for start, end in occupied):
                continue
            value = match.group(1)
            events.append(_TexEvent(match.start(), match.end(), "formula", value, "block", _extract_label(value)))
            occupied.append((match.start(), match.end()))
    for pattern in INLINE_PATTERNS:
        for match in pattern.finditer(text):
            if any(start <= match.start() < end for start, end in occupied):
                continue
            value = match.group(1)
            if _inline_math_should_stay_in_text(value):
                continue
            events.append(_TexEvent(match.start(), match.end(), "formula", value, "inline", _extract_label(value)))
    for match in SECTION_RE.finditer(text):
        if any(start <= match.start() < end for start, end in occupied):
            continue
        events.append(_TexEvent(match.start(), match.end(), "section", match.group("title"), match.group("kind")))
    events.sort(key=lambda event: (event.start, 0 if event.kind == "section" else 1))
    return events


def _extract_label(value: str) -> str | None:
    match = re.search(r"\\label\{([^{}]+)\}", value)
    return match.group(1).strip() if match else None


def _clean_tex_formula(value: str) -> str:
    value = value.strip()
    value = re.sub(r"(?<!\\)(?<!\$)\$(?!\$)(.+?)(?<!\\)\$(?!\$)", r"\1", value, flags=re.DOTALL)
    value = re.sub(r"\\label\{[^{}]*\}", "", value)
    value = re.sub(r"\\tag\{([^{}]*)\}", r"\\quad(\1)", value)
    value = re.sub(r"\\notag\b|\\nonumber\b", "", value)
    value = re.sub(r"\\mbox\s*\{([^{}]*)\}", r"\\text{\1}", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _clean_tex_text(value: str) -> str:
    value = _replace_tiny_inline_math(value)
    value = re.sub(r"(?<!\\)(?<!\$)\$(?!\$)(.+?)(?<!\\)\$(?!\$)", r"\1", value, flags=re.DOTALL)
    value = value.replace(r"\\", " ")
    value = re.sub(r"\\(?:label|cite|ref|eqref|pageref)\{[^{}]*\}", " ", value)
    value = re.sub(r"\\(?:emph|textbf|textit|mathrm|mathbf|text)\{([^{}]*)\}", r"\1", value)
    value = re.sub(r"\\(?:thanks|footnote)\{(?:[^{}]|\{[^{}]*\})*\}", " ", value)
    value = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?", " ", value)
    value = _normalize_tex_accents(value)
    value = re.sub(r"[{}]", " ", value)
    value = value.replace("~", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n\s*\n+", "\n\n", value)
    return value.strip()


def _clean_paragraph_text(value: str) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    value = re.sub(r"\s+([,.;:!?])", r"\1", value)
    value = re.sub(r"([(\[{])\s+", r"\1", value)
    value = re.sub(r"\s+([)\]}])", r"\1", value)
    return value.strip()


def _is_meaningful_paragraph(value: str) -> bool:
    text = _clean_paragraph_text(value)
    if not text:
        return False
    if re.fullmatch(r"[\W_]+", text, flags=re.UNICODE):
        return False
    return sum(ch.isalnum() for ch in text) >= 3 or bool(TOKEN_RE.search(text))


def _looks_like_tiny_inline(value: str) -> bool:
    return _inline_math_should_stay_in_text(value)


def _inline_math_should_stay_in_text(value: str) -> bool:
    compact = re.sub(r"\s+", "", _clean_tex_formula(value))
    compact_for_size = re.sub(r"\\(?:mathcal|mathrm|mathbf|mathit|text)\{?([A-Za-z0-9_]+)\}?", r"\1", compact)
    if re.search(r"=|<|>|\\(?:in|frac|sum|lim|begin|int|prod|sqrt|cup|cap|subset|to|le|ge)\b", compact):
        return False
    if re.search(r"\\[A-Za-z]+", compact_for_size):
        return False
    if len(compact_for_size) <= 24 and re.fullmatch(r"[A-Za-z0-9_{}^+\-*/=().,]+", compact_for_size):
        return True
    return False


def _replace_tiny_inline_math(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        latex = _clean_tex_formula(match.group(1))
        if not _inline_math_should_stay_in_text(latex):
            return match.group(0)
        return f" {_inline_latex_to_text(latex)} "

    value = re.sub(r"\\\((.+?)\\\)", replace, value, flags=re.DOTALL)
    value = re.sub(r"(?<!\\)(?<!\$)\$(?!\$)(.+?)(?<!\\)\$(?!\$)", replace, value, flags=re.DOTALL)
    return value


def _inline_latex_to_text(latex: str) -> str:
    value = latex.strip()
    value = re.sub(r"\\mathcal\s*\{([^{}]+)\}", r"\1", value)
    value = re.sub(r"\\mathcal\s+([A-Za-z])", r"\1", value)
    value = re.sub(r"\\(?:mathrm|mathbf|mathit|text)\s*\{([^{}]+)\}", r"\1", value)
    replacements = {
        r"\alpha": "alpha",
        r"\beta": "beta",
        r"\gamma": "gamma",
        r"\lambda": "lambda",
        r"\mu": "mu",
        r"\sigma": "sigma",
        r"\theta": "theta",
        r"\phi": "phi",
        r"\varphi": "varphi",
        r"\omega": "omega",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    value = re.sub(r"\\([A-Za-z]+)", r"\1", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _normalize_tex_accents(value: str) -> str:
    accents = {
        r"\'e": "é",
        r"\'E": "É",
        r'\"o': "ö",
        r'\"O': "Ö",
        r"\`e": "è",
        r"\`E": "È",
    }
    for old, new in accents.items():
        value = value.replace(old, new)
    return value


def _extract_tex_command(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text or "")
    return match.group("value") if match else ""
