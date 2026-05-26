from __future__ import annotations

import re
from typing import Any

from backend.formula_graph.config import resolve_device
from backend.formula_graph.models import BBox, FormulaBlock, PageImage, TextBlock
from backend.formula_graph.ocr.base import StructureAdapter
from backend.formula_graph.ocr.model_cache import get_cached_model


class PaddleStructureAdapter(StructureAdapter):
    name = "pp_structure_v3"

    def __init__(self, device: str | None = None) -> None:
        self.device = device or resolve_device()

    @property
    def engine(self) -> Any:
        def create_engine() -> Any:
            from paddleocr import PPStructureV3

            return PPStructureV3(
                device=self.device,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=True,
                use_formula_recognition=True,
                use_table_recognition=False,
                use_seal_recognition=False,
                use_chart_recognition=False,
                use_region_detection=False,
                textline_orientation_batch_size=1,
                text_recognition_batch_size=1,
                formula_recognition_batch_size=1,
            )

        return get_cached_model(("pp_structure_v3", self.device), create_engine)

    def parse_pages(self, pages: list[PageImage], progress_callback=None) -> tuple[list[TextBlock], list[FormulaBlock], list[str]]:
        text_blocks: list[TextBlock] = []
        formulas: list[FormulaBlock] = []
        warnings: list[str] = []
        try:
            engine = self.engine
        except Exception as exc:
            message = _short_error(exc)
            if self.device == "gpu":
                cpu_text, cpu_formulas, cpu_warnings = PaddleStructureAdapter(device="cpu").parse_pages(pages, progress_callback=progress_callback)
                return cpu_text, cpu_formulas, [
                    f"PPStructureV3 недоступен на GPU: {message or type(exc).__name__}. Повтор выполнен на CPU."
                ] + cpu_warnings
            return [], [], [f"PPStructureV3 недоступен на CPU: {message or type(exc).__name__}"]

        cpu_fallback: PaddleStructureAdapter | None = None
        total = max(1, len(pages))
        for index, page in enumerate(pages, start=1):
            if cpu_fallback is not None:
                cpu_text, cpu_formulas, cpu_warnings = cpu_fallback.parse_pages([page], progress_callback=None)
                text_blocks.extend(cpu_text)
                formulas.extend(cpu_formulas)
                warnings.extend(cpu_warnings)
                if progress_callback is not None:
                    progress_callback(index, total)
                continue
            try:
                raw_result = _predict(engine, page.image_path)
                payloads = list(_iter_payloads(raw_result))
                text_blocks.extend(_extract_text_blocks(payloads, page, len(text_blocks)))
                formulas.extend(_extract_formulas(payloads, page, len(formulas)))
            except Exception as exc:
                message = _short_error(exc)
                warnings.append(f"PPStructureV3 завершился ошибкой на странице {page.page_number}: {message}")
                if self.device == "gpu" and _is_oom(exc):
                    warnings.append(f"Повторная обработка страницы {page.page_number} на CPU после нехватки памяти GPU.")
                    cpu_fallback = PaddleStructureAdapter(device="cpu")
                    cpu_text, cpu_formulas, cpu_warnings = cpu_fallback.parse_pages([page], progress_callback=None)
                    text_blocks.extend(cpu_text)
                    formulas.extend(cpu_formulas)
                    warnings.extend(cpu_warnings)
            if progress_callback is not None:
                progress_callback(index, total)
        return text_blocks, _filter_false_formulas(formulas), warnings


def _is_oom(exc: Exception) -> bool:
    message = str(exc).lower()
    return "out of memory" in message or "resourceexhausted" in message


def _short_error(exc: Exception) -> str:
    text = " ".join(str(exc).split())
    if "ResourceExhaustedError" in text:
        return text[text.find("ResourceExhaustedError") : text.find("ResourceExhaustedError") + 360]
    return text[:500]


def _predict(engine: Any, image_path: str) -> Any:
    if hasattr(engine, "predict"):
        return engine.predict(input=image_path)
    return engine(image_path)


def _iter_payloads(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_payloads(child)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_payloads(item)
    elif hasattr(value, "json"):
        try:
            yield from _iter_payloads(value.json)
        except Exception:
            return
    elif hasattr(value, "to_dict"):
        try:
            yield from _iter_payloads(value.to_dict())
        except Exception:
            return


def _extract_text_blocks(payloads: list[dict[str, Any]], page: PageImage, offset: int) -> list[TextBlock]:
    blocks: list[TextBlock] = []
    for payload in payloads:
        for key in ("rec_texts", "texts"):
            texts = payload.get(key)
            if isinstance(texts, list):
                scores = _empty_if_none(payload.get("rec_scores"))
                boxes = _empty_if_none(_first_present(payload, "rec_boxes", "boxes"))
                for index, text in enumerate(texts):
                    text = str(text).strip()
                    if not text:
                        continue
                    blocks.append(
                        TextBlock(
                            id=f"p{page.page_number}_struct_{offset + len(blocks) + 1}",
                            page_number=page.page_number,
                            text=text,
                            bbox=_scale_bbox(_box_to_bbox(boxes[index]), page.dpi) if index < len(boxes) else None,
                            source="paddleocr",
                            confidence=float(scores[index]) if index < len(scores) else None,
                        )
                    )
        for key in ("text", "markdown_text", "content"):
            text = payload.get(key)
            if isinstance(text, str) and text.strip() and len(text.strip()) > 2:
                blocks.append(
                    TextBlock(
                        id=f"p{page.page_number}_struct_{offset + len(blocks) + 1}",
                        page_number=page.page_number,
                        text=text.strip(),
                        bbox=_scale_bbox(_box_to_bbox(_first_present(payload, "bbox", "box")), page.dpi),
                        source="paddleocr",
                        confidence=_score(payload),
                    )
                )
    return _dedupe_blocks(blocks)


def _extract_formulas(payloads: list[dict[str, Any]], page: PageImage, offset: int) -> list[FormulaBlock]:
    formulas: list[FormulaBlock] = []
    for payload in payloads:
        label = str(payload.get("label") or payload.get("type") or payload.get("block_label") or "").lower()
        if label == "formula_number":
            continue
        latex = None
        for key in ("latex", "formula", "rec_formula", "formula_text", "content", "text"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                if "formula" in label or "\\" in value or "$" in value:
                    latex = value.strip().strip("$")
                    break
        if not latex:
            continue
        kind = _classify_formula_kind(latex, label)
        formulas.append(
            FormulaBlock(
                id=f"f_{offset + len(formulas) + 1}",
                page_number=page.page_number,
                latex=latex,
                kind=kind,
                bbox=_scale_bbox(_box_to_bbox(_first_present(payload, "bbox", "box", "coordinate", "dt_polys")), page.dpi),
                source="pp_structure_v3",
                confidence=_score(payload),
            )
        )
    return formulas


def _filter_false_formulas(formulas: list[FormulaBlock]) -> list[FormulaBlock]:
    result: list[FormulaBlock] = []
    for formula in formulas:
        latex = _normalize_latex(formula.latex)
        if not _is_usable_formula_latex(latex):
            result.append(
                formula.model_copy(
                    update={
                        "latex": latex,
                        "source": f"{formula.source}_raw",
                        "confidence": min(formula.confidence or 0.45, 0.45),
                        "quality_flags": [*formula.quality_flags, "needs_formula_review"],
                    }
                )
            )
            continue
        result.append(formula.model_copy(update={"latex": latex}))
    return result


def _normalize_latex(latex: str) -> str:
    return " ".join(latex.strip().strip("$").split())


def _is_usable_formula_latex(latex: str) -> bool:
    if len(latex) < 2 or len(latex) > 1600:
        return False
    if re.fullmatch(r"[\W_]+", latex):
        return False

    structural_math = any(
        token in latex
        for token in (
            "\\frac",
            "\\partial",
            "\\sum",
            "\\int",
            "\\begin",
            "\\sqrt",
            "\\lim",
            "\\operatorname",
            "\\mathbb",
            "\\in",
            "\\to",
            "\\cup",
            "\\subset",
            "=",
        )
    )
    if not structural_math:
        return False

    text_wrappers = latex.count("\\mathrm") + latex.count("\\mathit") + latex.count("\\text") + latex.count("\\textsl")
    plain = re.sub(r"\\[A-Za-z]+", " ", latex)
    long_words = re.findall(r"[A-Za-zА-Яа-яЁё]{5,}", plain)
    allowed = {"alpha", "beta", "gamma", "delta", "theta", "sigma", "lambda", "omega", "mathrm", "mathit"}
    suspicious_words = [word for word in long_words if word.lower() not in allowed]
    math_marks = sum(latex.count(token) for token in ("\\frac", "\\partial", "\\sum", "\\int", "\\begin", "=", "_", "^"))

    if text_wrappers and suspicious_words and math_marks < 3:
        return False
    if len(suspicious_words) >= 2 and math_marks < 4:
        return False
    return True


def _classify_formula_kind(latex: str, label: str) -> str:
    if "inline" in label:
        return "inline"
    if any(token in latex for token in ("\\begin", "\\sum", "\\int", "\\lim")):
        return "block"
    if "=" in latex or "\\cup" in latex or "\\subset" in latex:
        return "block"
    if len(latex) > 80:
        return "block"
    return "inline"


def _score(payload: dict[str, Any]) -> float | None:
    for key in ("score", "confidence", "rec_score"):
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _first_present(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None


def _empty_if_none(value: Any) -> Any:
    return [] if value is None else value


def _box_to_bbox(box: Any) -> tuple[float, float, float, float] | None:
    try:
        if box is None:
            return None
        if len(box) == 4 and all(isinstance(value, (int, float)) for value in box):
            x0, y0, x1, y1 = box
            return float(x0), float(y0), float(x1), float(y1)
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        return min(xs), min(ys), max(xs), max(ys)
    except Exception:
        return None


def _scale_bbox(bbox: BBox | None, dpi: int) -> BBox | None:
    if bbox is None:
        return None
    factor = 72 / max(1, dpi)
    x0, y0, x1, y1 = bbox
    return x0 * factor, y0 * factor, x1 * factor, y1 * factor


def _dedupe_blocks(blocks: list[TextBlock]) -> list[TextBlock]:
    seen: set[str] = set()
    result: list[TextBlock] = []
    for block in blocks:
        key = " ".join(block.text.split())
        if key in seen:
            continue
        seen.add(key)
        result.append(block)
    return result
