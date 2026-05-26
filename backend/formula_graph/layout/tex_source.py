from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path

from backend.formula_graph.models import FormulaBlock
from backend.formula_graph.postprocessing.formulas import repair_formula_latex


BLOCK_ENVIRONMENTS = (
    "equation",
    "align",
    "gather",
    "multline",
    "flalign",
    "eqnarray",
)
BLOCK_PATTERNS = [
    re.compile(r"\\\[(.+?)\\\]", re.DOTALL),
    re.compile(r"(?<!\\)\$\$(.+?)(?<!\\)\$\$", re.DOTALL),
    *[
        re.compile(rf"\\begin\{{{env}\*?\}}(.+?)\\end\{{{env}\*?\}}", re.DOTALL)
        for env in BLOCK_ENVIRONMENTS
    ],
]
INLINE_PATTERNS = [
    re.compile(r"\\\((.+?)\\\)", re.DOTALL),
    re.compile(r"(?<!\\)(?<!\$)\$(?!\$)(.+?)(?<!\\)\$(?!\$)", re.DOTALL),
]
INPUT_RE = re.compile(r"\\(?:input|include)\{([^{}]+)\}")
MACRO_PATTERNS = [
    re.compile(r"\\(?:re)?newcommand\s*\\([A-Za-z]+)\s*(?:\[(\d+)\])?\s*\{((?:[^{}]|\{[^{}]*\})*)\}", re.DOTALL),
    re.compile(r"\\(?:re)?newcommand\s*\{\\([A-Za-z]+)\}\s*(?:\[(\d+)\])?\s*\{((?:[^{}]|\{[^{}]*\})*)\}", re.DOTALL),
    re.compile(r"\\def\\([A-Za-z]+)\s*\{((?:[^{}]|\{[^{}]*\})*)\}", re.DOTALL),
]


def extract_tex_formulas(source_dir: Path) -> tuple[list[FormulaBlock], list[str]]:
    tex_files = sorted(source_dir.rglob("*.tex"))
    if not tex_files:
        return [], ["arXiv source archive contains no .tex files."]
    ordered = _ordered_tex_files(tex_files)
    formulas: list[FormulaBlock] = []
    for path in ordered:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="latin-1", errors="ignore")
        macros = extract_simple_macros(text)
        text = _document_body(text)
        text = apply_simple_macros(text, macros)
        formulas.extend(_extract_from_tex_text(_strip_comments(text), path.name, len(formulas)))
    return _renumber(_repair_tex_formulas(formulas)), []


def align_tex_formulas(
    ocr_formulas: list[FormulaBlock],
    tex_formulas: list[FormulaBlock],
    include_unmatched: bool = False,
) -> list[FormulaBlock]:
    if not tex_formulas:
        return ocr_formulas
    if not ocr_formulas:
        return _renumber(_repair_tex_formulas(tex_formulas))
    aligned: list[FormulaBlock] = []
    used_tex: set[int] = set()
    for formula in ocr_formulas:
        match = _best_tex_match(formula, tex_formulas, used_tex)
        if match is None:
            aligned.append(formula)
            continue
        tex_index, tex_formula = match
        used_tex.add(tex_index)
        aligned.append(
            formula.model_copy(
                update={
                    "latex": tex_formula.latex,
                    "source": "tex_source_aligned",
                    "confidence": 0.99,
                    "raw_latex": formula.latex if formula.latex != tex_formula.latex else formula.raw_latex,
                    "quality_flags": _merge_flags(formula.quality_flags, ["from_tex_source"]),
                }
            )
        )
    if include_unmatched:
        for index, tex_formula in enumerate(tex_formulas):
            if index in used_tex:
                continue
            aligned.append(
                tex_formula.model_copy(
                    update={
                        "id": f"f_{len(aligned) + 1}",
                        "source": "tex_source",
                        "confidence": 0.99,
                        "quality_flags": _merge_flags(tex_formula.quality_flags, ["from_tex_source"]),
                    }
                )
            )
    return _renumber(_repair_tex_formulas(aligned))


def _best_tex_match(
    formula: FormulaBlock,
    tex_formulas: list[FormulaBlock],
    used_tex: set[int],
) -> tuple[int, FormulaBlock] | None:
    current = _normalize_latex_for_match(formula.latex)
    best: tuple[float, int, FormulaBlock] | None = None
    for index, tex_formula in enumerate(tex_formulas):
        if index in used_tex or tex_formula.kind != formula.kind:
            continue
        candidate = _normalize_latex_for_match(tex_formula.latex)
        score = _match_score(current, candidate)
        if best is None or score > best[0]:
            best = (score, index, tex_formula)
    if best is None:
        return None
    threshold = 0.42 if formula.kind == "inline" else 0.28
    if best[0] < threshold:
        return None
    return best[1], best[2]


def _normalize_latex_for_match(latex: str) -> str:
    value = latex.lower()
    replacements = {
        r"\varphi": "phi",
        r"\phi": "phi",
        r"\psi": "psi",
        r"\omega": "omega",
        r"\xi": "xi",
        r"\alpha": "alpha",
        r"\theta": "theta",
        r"\mathbb": "",
        r"\mathbf": "",
        r"\mathrm": "",
        r"\left": "",
        r"\right": "",
        r"\cdots": "...",
        r"\dots": "...",
        r"\cup": "cup",
        r"\cap": "cap",
        r"\in": "in",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    value = re.sub(r"\\[a-zA-Z]+", "", value)
    value = re.sub(r"[^a-z0-9=<>+\-*/_^{}().,]+", "", value)
    return value


def _match_score(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    ratio = SequenceMatcher(None, left, right).ratio()
    left_tokens = set(re.findall(r"[a-z]+|\d+|[=<>+\-*/_^]", left))
    right_tokens = set(re.findall(r"[a-z]+|\d+|[=<>+\-*/_^]", right))
    overlap = len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
    return ratio * 0.65 + overlap * 0.35


def _ordered_tex_files(tex_files: list[Path]) -> list[Path]:
    mains = [path for path in tex_files if _looks_like_main_tex(path)]
    if not mains:
        return tex_files
    main = max(mains, key=lambda path: path.stat().st_size)
    ordered = [main]
    ordered.extend(path for path in tex_files if path != main)
    return ordered


def _looks_like_main_tex(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False
    return "\\documentclass" in text or "\\begin{document}" in text


def _strip_comments(text: str) -> str:
    lines = []
    for line in text.splitlines():
        lines.append(re.sub(r"(?<!\\)%.*$", "", line))
    return "\n".join(lines)


def _document_body(text: str) -> str:
    begin = text.find(r"\begin{document}")
    if begin >= 0:
        text = text[begin + len(r"\begin{document}") :]
    end = text.find(r"\end{document}")
    if end >= 0:
        text = text[:end]
    return text


def extract_simple_macros(text: str) -> dict[str, str]:
    macros: dict[str, str] = {}
    for pattern in MACRO_PATTERNS:
        for match in pattern.finditer(text or ""):
            if pattern.pattern.startswith(r"\\def"):
                name, value = match.group(1), match.group(2)
                arg_count = None
            else:
                name, arg_count, value = match.group(1), match.group(2), match.group(3)
            if arg_count not in {None, "0"}:
                continue
            if name and value:
                macros[name] = value.strip()
    return macros


def apply_simple_macros(text: str, macros: dict[str, str]) -> str:
    for name, value in sorted(macros.items(), key=lambda item: len(item[0]), reverse=True):
        text = re.sub(rf"\\{re.escape(name)}(?![A-Za-z])", lambda _match, replacement=value: replacement, text)
    return text


def _extract_from_tex_text(text: str, filename: str, offset: int) -> list[FormulaBlock]:
    spans: list[tuple[int, int, str, str]] = []
    for pattern in BLOCK_PATTERNS:
        for match in pattern.finditer(text):
            spans.append((match.start(), match.end(), "block", _clean_tex_formula(match.group(1))))
    occupied = [(start, end) for start, end, _, _ in spans]
    for pattern in INLINE_PATTERNS:
        for match in pattern.finditer(text):
            if any(start <= match.start() < end for start, end in occupied):
                continue
            latex = _clean_tex_formula(match.group(1))
            if latex:
                spans.append((match.start(), match.end(), "inline", latex))
    spans.sort(key=lambda item: item[0])
    result: list[FormulaBlock] = []
    for _, _, kind, latex in spans:
        if not latex or _looks_like_tex_noise(latex, kind):
            continue
        result.append(
            FormulaBlock(
                id=f"f_{offset + len(result) + 1}",
                page_number=1,
                latex=latex,
                kind=kind,
                source="tex_source",
                confidence=0.99,
                quality_flags=["from_tex_source", f"tex_file:{filename}"],
            )
        )
    return result


def _clean_tex_formula(value: str) -> str:
    value = value.strip()
    value = re.sub(r"(?<!\\)(?<!\$)\$(?!\$)(.+?)(?<!\\)\$(?!\$)", r"\1", value, flags=re.DOTALL)
    value = re.sub(r"\\label\{[^{}]*\}", "", value)
    value = re.sub(r"\\tag\{([^{}]*)\}", r"\\quad(\1)", value)
    value = re.sub(r"\\notag\b|\\nonumber\b", "", value)
    value = re.sub(r"\\mbox\s*\{([^{}]*)\}", r"\\text{\1}", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _looks_like_tex_noise(latex: str, kind: str) -> bool:
    if len(latex) < 2 or latex.startswith("\\ref") or latex.startswith("\\cite"):
        return True
    if kind == "block":
        return False
    if re.search(r"=|<|>|\\in|\\subset|\\cup|\\cap|\\to|\\le|\\ge|\\frac|\\sum|\\lim|\\begin", latex):
        return False
    compact = re.sub(r"\s+", "", latex)
    if len(compact) <= 8:
        return True
    return False


def _renumber(formulas: list[FormulaBlock]) -> list[FormulaBlock]:
    return [formula.model_copy(update={"id": f"f_{index + 1}"}) for index, formula in enumerate(formulas)]


def _repair_tex_formulas(formulas: list[FormulaBlock]) -> list[FormulaBlock]:
    return [formula.model_copy(update={"latex": repair_formula_latex(formula.latex)}) for formula in formulas]


def _merge_flags(existing: list[str], added: list[str]) -> list[str]:
    result: list[str] = []
    for flag in [*existing, *added]:
        if flag not in result:
            result.append(flag)
    return result
