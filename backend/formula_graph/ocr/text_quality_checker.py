from __future__ import annotations

from typing import Any


def assess_text_layer_quality(document_structure: Any) -> dict[str, Any]:
    blocks = _extract_blocks(document_structure)
    text = "\n".join(str(block.get("text") or block.get("normalized_text") or "") for block in blocks)
    char_count = len(text.strip())
    replacement_count = text.count("\ufffd")
    control_count = sum(1 for char in text if ord(char) < 32 and char not in "\n\r\t")
    letters = sum(1 for char in text if char.isalpha())
    whitespace_ratio = (sum(1 for char in text if char.isspace()) / max(1, len(text))) if text else 1.0
    warnings: list[str] = []

    if char_count == 0:
        warnings.append("text_layer_missing")
    if replacement_count:
        warnings.append("replacement_symbols_present")
    if control_count:
        warnings.append("control_symbols_present")
    if char_count > 0 and letters / max(1, char_count) < 0.2:
        warnings.append("low_letter_ratio")
    if whitespace_ratio > 0.65:
        warnings.append("excessive_whitespace")

    if char_count == 0:
        quality = "missing"
        allow_ocr_fallback = True
        score = 0.0
    else:
        score = max(0.0, 1.0 - 0.18 * len(warnings))
        quality = "good" if score >= 0.7 and char_count >= 80 else "poor"
        allow_ocr_fallback = quality != "good"

    return {
        "quality": quality,
        "score": round(score, 2),
        "char_count": char_count,
        "warnings": warnings,
        "allow_ocr_fallback": allow_ocr_fallback,
    }


def _extract_blocks(document_structure: Any) -> list[dict[str, Any]]:
    if document_structure is None:
        return []
    if isinstance(document_structure, dict):
        blocks = document_structure.get("text_blocks") or document_structure.get("blocks") or []
    else:
        blocks = getattr(document_structure, "text_blocks", None) or getattr(document_structure, "blocks", None) or []
    result: list[dict[str, Any]] = []
    for block in blocks:
        if isinstance(block, dict):
            result.append(block)
        else:
            result.append({"text": getattr(block, "text", ""), "normalized_text": getattr(block, "normalized_text", "")})
    return result
