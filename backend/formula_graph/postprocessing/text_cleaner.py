from __future__ import annotations

import html
import re


ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
FORMULA_TOKEN_RE = re.compile(r"\[FORMULA_\d{3}\]")


def clean_ocr_text(text: str) -> str:
    value = remove_service_symbols(text)
    value = fix_common_ocr_artifacts(value)
    value = normalize_whitespace(value)
    return value


def remove_service_symbols(text: str) -> str:
    value = "" if text is None else str(text)
    value = html.unescape(value)
    value = value.replace("\ufffd", "")
    value = ZERO_WIDTH_RE.sub("", value)
    value = CONTROL_RE.sub("", value)
    value = re.sub(r"```(?:text|txt|ocr)?", "", value, flags=re.IGNORECASE)
    value = value.replace("```", "")
    value = re.sub(r"</?(?:p|span|div|br|ocr|text)[^>]*>", " ", value, flags=re.IGNORECASE)
    return value


def normalize_whitespace(text: str) -> str:
    protected: list[str] = []

    def protect(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        return f"__FORMULA_TOKEN_{len(protected) - 1}__"

    value = FORMULA_TOKEN_RE.sub(protect, text or "")
    value = re.sub(r"(?<=[A-Za-zА-Яа-яЁё])-\s*(?:\n|\r\n)\s*(?=[A-Za-zА-Яа-яЁё])", "", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    value = value.strip()
    for index, token in enumerate(protected):
        value = value.replace(f"__FORMULA_TOKEN_{index}__", token)
    return value


def fix_common_ocr_artifacts(text: str) -> str:
    value = text or ""
    replacements = {
        "\u00ad": "",
        "\ufb01": "fi",
        "\ufb02": "fl",
        "−": "-",
        "–": "-",
        "—": "-",
        "∗": "*",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    value = _repair_mojibake(value)
    return value


def _repair_mojibake(text: str) -> str:
    if _mojibake_score(text) < 2:
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


def _mojibake_score(text: str) -> int:
    return sum(text.count(marker) for marker in ("Ã", "Â", "â", "Ï", "Î", "Ð", "Ñ"))
