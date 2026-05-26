from __future__ import annotations

import re

from backend.formula_graph.models import TextBlock
from backend.formula_graph.postprocessing.text_cleaner import clean_ocr_text


REPLACEMENTS = {
    "\u00ad": "",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "−": "-",
    "–": "-",
    "—": "-",
    "∗": "*",
}


def normalize_text_blocks(blocks: list[TextBlock]) -> list[TextBlock]:
    normalized: list[TextBlock] = []
    for block in blocks:
        text = _normalize_text_value(block.text)
        if text:
            lines = [
                line.model_copy(update={"text": _normalize_line_value(line.text)})
                for line in block.lines
                if _normalize_line_value(line.text)
            ]
            normalized.append(block.model_copy(update={"text": text, "source": block.source, "lines": lines}))
    return normalized


def _normalize_text_value(text: str) -> str:
    text = clean_ocr_text(text)
    text = _repair_mojibake(text)
    for old, new in REPLACEMENTS.items():
        text = text.replace(old, new)
    text = re.sub(r"(?<=[A-Za-zА-Яа-яЁё])-\s*(?:\n|\r\n)\s*(?=[A-Za-zА-Яа-яЁё])", "", text)
    text = re.sub(r"(?<=[A-Za-zА-Яа-яЁё])-\s+(?=[A-Za-zА-Яа-яЁё])", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _normalize_line_value(text: str) -> str:
    text = clean_ocr_text(text)
    text = _repair_mojibake(text)
    for old, new in REPLACEMENTS.items():
        text = text.replace(old, new)
    text = re.sub(r"(?<=[A-Za-zА-Яа-яЁё])-\s+(?=[A-Za-zА-Яа-яЁё])", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _repair_mojibake(text: str) -> str:
    if not _looks_mojibake(text):
        return text
    candidates = []
    for encoding in ("latin1", "cp1252"):
        try:
            candidates.append(text.encode(encoding).decode("utf-8"))
        except UnicodeError:
            continue
    if not candidates:
        return text
    repaired = min(candidates, key=_mojibake_score)
    return repaired if _mojibake_score(repaired) < _mojibake_score(text) else text


def _looks_mojibake(text: str) -> bool:
    return _mojibake_score(text) >= 2


def _mojibake_score(text: str) -> int:
    markers = ("Ã", "Â", "â", "Ï", "Î", "Ð", "Ñ")
    return sum(text.count(marker) for marker in markers)
