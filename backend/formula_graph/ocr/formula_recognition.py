from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image

from backend.formula_graph.config import resolve_device, settings
from backend.formula_graph.models import FormulaBlock, PageImage, TextBlock
from backend.formula_graph.ocr.formula_image_preprocessor import preprocess_formula_crop
from backend.formula_graph.ocr.model_cache import get_cached_model
from backend.formula_graph.postprocessing.latex_cleaner import clean_latex, latex_to_plain_text, normalize_latex
from backend.formula_graph.postprocessing.formulas import repair_formula_latex, validate_formula_latex


class FormulaRecognitionAdapter:
    name = "pp_formula_net"

    def __init__(self, device: str | None = None) -> None:
        self.device = resolve_device(device)

    @property
    def engine(self) -> Any:
        def create_engine() -> Any:
            from paddleocr import FormulaRecognition

            return FormulaRecognition(model_name="PP-FormulaNet_plus-L", device=self.device)

        return get_cached_model(("formula_recognition", self.device, "PP-FormulaNet_plus-L"), create_engine)

    def refine(
        self,
        pages: list[PageImage],
        formulas: list[FormulaBlock],
        text_blocks: list[TextBlock],
        progress_callback=None,
    ) -> tuple[list[FormulaBlock], list[str]]:
        warnings: list[str] = []
        page_map = {page.page_number: page for page in pages}
        refined: list[FormulaBlock] = []
        try:
            engine = self.engine
        except Exception as exc:
            return formulas, [f"Распознавание формул недоступно: {_short_error(exc)}"]

        with tempfile.TemporaryDirectory(prefix="formula_crops_") as temp_dir:
            temp_path = Path(temp_dir)
            total = max(1, len(formulas))
            threshold = float(settings.formula_ocr_refine_confidence_threshold or 0.86)
            candidate_indices = [
                index
                for index, formula in enumerate(formulas)
                if _needs_neural_refinement(formula, page_map, threshold)
            ]
            selected_indices = set(_select_refinement_candidates(formulas, candidate_indices))
            skipped_by_budget = len(candidate_indices) - len(selected_indices)
            if skipped_by_budget > 0:
                warnings.append(
                    "Нейросетевое уточнение формул ограничено "
                    f"{len(selected_indices)} из {len(candidate_indices)} кандидатами; "
                    f"{skipped_by_budget} низкоприоритетных областей оставлены как есть."
                )
            prepared = _prepare_refinement_crops(
                pages=page_map,
                formulas=formulas,
                selected_indices=selected_indices,
                text_blocks=text_blocks,
                temp_path=temp_path,
            )
            for item in prepared.values():
                warnings.extend(item.get("warnings", []))
            for index, formula in enumerate(formulas, start=1):
                detail_prefix = _formula_progress_label(formula)
                if formula.source == "tex_source":
                    refined.append(formula)
                    _emit_refinement_progress(progress_callback, index, total, f"{detail_prefix}: TeX-источник, OCR не нужен")
                    continue
                if formula.bbox is None:
                    refined.append(formula)
                    _emit_refinement_progress(progress_callback, index, total, f"{detail_prefix}: нет области на странице")
                    continue
                if (formula.confidence or 0.0) >= threshold:
                    refined.append(formula)
                    _emit_refinement_progress(progress_callback, index, total, f"{detail_prefix}: уверенность достаточная")
                    continue
                zero_index = index - 1
                if zero_index not in selected_indices:
                    refined.append(
                        formula.model_copy(
                            update={
                                "quality_flags": [*formula.quality_flags, "formula_ocr_budget_skipped"],
                            }
                        )
                    )
                    _emit_refinement_progress(progress_callback, index, total, f"{detail_prefix}: пропущено по лимиту уточнения")
                    continue
                prepared_crop = prepared.get(zero_index)
                if not prepared_crop or not prepared_crop.get("crop_for_recognition"):
                    refined.append(formula)
                    _emit_refinement_progress(progress_callback, index, total, f"{detail_prefix}: кроп не подготовлен")
                    continue
                crop_for_recognition = Path(prepared_crop["crop_for_recognition"])
                try:
                    latex = _recognize_formula(engine, crop_for_recognition)
                except Exception as exc:
                    warnings.append(f"Распознавание формулы {formula.id} завершилось ошибкой: {_short_error(exc)}")
                    refined.append(
                        formula.model_copy(
                            update={
                                "quality_flags": [*formula.quality_flags, "formula_ocr_failed"],
                            }
                        )
                    )
                    _emit_refinement_progress(progress_callback, index, total, f"{detail_prefix}: OCR завершился ошибкой")
                    continue
                latex = _salvage_math_segment(latex) or latex
                latex = _restore_missing_left_hand_side(latex, formula.latex)
                if _is_better_latex(latex, formula.latex):
                    latex_fields = _latex_variant_fields(latex)
                    refined.append(
                        formula.model_copy(
                            update={
                                "latex": latex,
                                "raw_latex": latex or formula.raw_latex,
                                **latex_fields,
                                "source": "pp_formula_net",
                                "confidence": 0.82,
                            }
                        )
                    )
                    outcome = f"{detail_prefix}: OCR улучшил LaTeX -> {_short_latex(latex)}"
                else:
                    candidate_flags = validate_formula_latex(latex)
                    raw_flags = [f"raw_ocr_{flag}" for flag in candidate_flags if flag != "needs_review"]
                    latex_fields = _latex_variant_fields(formula.latex)
                    refined.append(
                        formula.model_copy(
                            update={
                                "raw_latex": latex or None,
                                **latex_fields,
                                "quality_flags": [*formula.quality_flags, "formula_ocr_kept_fallback", *raw_flags],
                            }
                        )
                    )
                    outcome = f"{detail_prefix}: оставлен исходный LaTeX, OCR-кандидат слабее"
                _emit_refinement_progress(progress_callback, index, total, outcome)
        return refined, warnings


def _needs_neural_refinement(formula: FormulaBlock, page_map: dict[int, PageImage], threshold: float) -> bool:
    return (
        formula.source != "tex_source"
        and formula.bbox is not None
        and formula.page_number in page_map
        and (formula.confidence or 0.0) < threshold
    )


def _select_refinement_candidates(formulas: list[FormulaBlock], candidate_indices: list[int]) -> list[int]:
    limit = int(settings.formula_ocr_max_refine_candidates or 0)
    if limit <= 0 or len(candidate_indices) <= limit:
        return candidate_indices
    return sorted(
        sorted(candidate_indices, key=lambda index: _refinement_priority(formulas[index]), reverse=True)[:limit]
    )


def _refinement_priority(formula: FormulaBlock) -> float:
    priority = 1.0 - float(formula.confidence or 0.0)
    if formula.kind == "block":
        priority += 0.35
    if formula.quality_flags:
        priority += 0.25
    if formula.source in {"pp_structure", "pp_formula_net"}:
        priority += 0.15
    if formula.bbox is not None:
        x0, y0, x1, y1 = formula.bbox
        area = max(0.0, x1 - x0) * max(0.0, y1 - y0)
        priority += min(0.25, area / 18000.0)
    return priority


def _prepare_refinement_crops(
    *,
    pages: dict[int, PageImage],
    formulas: list[FormulaBlock],
    selected_indices: set[int],
    text_blocks: list[TextBlock],
    temp_path: Path,
) -> dict[int, dict[str, Any]]:
    if not selected_indices:
        return {}

    def prepare(index: int) -> tuple[int, dict[str, Any]]:
        formula = formulas[index]
        page = pages.get(formula.page_number)
        if page is None:
            return index, {"crop_for_recognition": None, "warnings": []}
        crop = _crop_formula(page, formula, text_blocks, temp_path)
        if crop is None:
            return index, {"crop_for_recognition": None, "warnings": []}
        preprocessing = preprocess_formula_crop(crop)
        warnings = [str(item) for item in preprocessing.get("warnings", [])]
        return index, {
            "crop_for_recognition": str(preprocessing.get("preprocessed_crop_path") or crop),
            "warnings": warnings,
        }

    workers = max(1, int(settings.formula_ocr_parallel_preprocess_workers or 1))
    if workers <= 1 or len(selected_indices) <= 1:
        return dict(prepare(index) for index in sorted(selected_indices))

    prepared: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=min(workers, len(selected_indices))) as executor:
        futures = [executor.submit(prepare, index) for index in sorted(selected_indices)]
        for future in as_completed(futures):
            index, item = future.result()
            prepared[index] = item
    return prepared


def _emit_refinement_progress(progress_callback, index: int, total: int, detail: str) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(index, total, detail)
    except TypeError:
        progress_callback(index, total)


def _formula_progress_label(formula: FormulaBlock) -> str:
    token = formula.token or formula.id
    return f"{token}, стр. {formula.page_number}"


def _short_latex(latex: str, limit: int = 120) -> str:
    value = " ".join(str(latex or "").split())
    return value if len(value) <= limit else value[: limit - 3] + "..."


def _crop_formula(page: PageImage, formula: FormulaBlock, text_blocks: list[TextBlock], temp_dir: Path) -> Path | None:
    page_path = Path(page.image_path)
    if not page_path.exists() or formula.bbox is None:
        return None
    x0, y0, x1, y1 = _expanded_bbox(formula, text_blocks)
    scale = page.dpi / 72
    with Image.open(page_path) as image:
        bbox_height = max(0.0, y1 - y0)
        if bbox_height <= 24:
            pad_x = 8
            pad_y = 4
        else:
            pad_x = 18
            pad_y = 10
        box = (
            max(0, int(x0 * scale) - pad_x),
            max(0, int(y0 * scale) - pad_y),
            min(image.width, int(x1 * scale) + pad_x),
            min(image.height, int(y1 * scale) + pad_y),
        )
        if box[2] - box[0] < 24 or box[3] - box[1] < 12:
            return None
        crop = image.crop(box)
        target = temp_dir / f"{formula.id}.png"
        crop.save(target)
        return target


def _expanded_bbox(formula: FormulaBlock, text_blocks: list[TextBlock]) -> tuple[float, float, float, float]:
    assert formula.bbox is not None
    x0, y0, x1, y1 = _tight_math_bbox(formula, text_blocks) or formula.bbox
    for text, bbox in _iter_page_lines(text_blocks, formula.page_number):
        if bbox is None:
            continue
        if not _nearby_math_fragment((x0, y0, x1, y1), bbox, text):
            continue
        bx0, by0, bx1, by1 = bbox
        x0, y0, x1, y1 = min(x0, bx0), min(y0, by0), max(x1, bx1), max(y1, by1)
    return x0, y0, x1, y1


def _tight_math_bbox(formula: FormulaBlock, text_blocks: list[TextBlock]) -> tuple[float, float, float, float] | None:
    if formula.bbox is None:
        return None
    candidates: list[tuple[float, float, float, float]] = []
    for block in text_blocks:
        if block.page_number != formula.page_number or not block.lines:
            continue
        for line in block.lines:
            if line.bbox is None or not _bbox_overlaps(line.bbox, formula.bbox):
                continue
            for span in line.spans:
                if span.bbox is None or not _looks_math_span(span.text, span.font):
                    continue
                if _bbox_overlaps(span.bbox, formula.bbox) or _bbox_contains(formula.bbox, span.bbox):
                    candidates.append(span.bbox)
    if not candidates:
        return None
    union = _union_bbox(candidates)
    if union is None:
        return None
    original_area = _bbox_area(formula.bbox)
    union_area = _bbox_area(union)
    if union_area <= 0 or original_area <= 0:
        return None
    return union if union_area <= original_area * 0.9 else None


def _iter_page_lines(text_blocks: list[TextBlock], page_number: int):
    for block in text_blocks:
        if block.page_number != page_number:
            continue
        if block.lines:
            for line in block.lines:
                if line.text.strip():
                    yield line.text, line.bbox
        elif block.bbox is not None:
            yield block.text, block.bbox


def _nearby_math_fragment(formula_bbox, block_bbox, text: str) -> bool:
    fx0, fy0, fx1, fy1 = formula_bbox
    bx0, by0, bx1, by1 = block_bbox
    if (bx1 - bx0) > 520 and len(" ".join(text.split())) > 120:
        return False
    vertical_gap = max(0.0, max(fy0 - by1, by0 - fy1))
    horizontal_overlap = max(0.0, min(fx1, bx1) - max(fx0, bx0))
    horizontal_gap = max(0.0, max(fx0 - bx1, bx0 - fx1))
    near_center = abs(((fx0 + fx1) / 2) - ((bx0 + bx1) / 2)) < 120
    same_line_continuation = vertical_gap <= 4 and horizontal_gap <= 90
    same_display_stack = vertical_gap <= 7 and (horizontal_overlap > 0 or near_center)
    return (same_display_stack or same_line_continuation) and _looks_math_fragment(text)


def _looks_math_fragment(text: str) -> bool:
    compact = " ".join(text.split())
    if not compact or len(compact) > 180:
        return False
    math_chars = sum(1 for char in compact if char in "=<>+-*/^_{}()[]|,.:;∑∫√∞→←∈∪∩≤≥◦·" or "\u0370" <= char <= "\u03ff")
    letters = sum(char.isalpha() for char in compact)
    return math_chars >= 2 and math_chars >= max(2, letters * 0.18)


def _looks_math_span(text: str | None, font: str | None) -> bool:
    value = " ".join((text or "").split())
    if not value:
        return False
    font_name = (font or "").lower()
    if any(marker in font_name for marker in ("cmmi", "cmsy", "cmex", "msbm", "math", "symbol")):
        return True
    if re.search(r"[=<>_^/\\(){}\[\]\-+*]|[\u0370-\u03ff]", value):
        return True
    if len(value) <= 4 and re.fullmatch(r"[A-Za-z0-9]+", value):
        return True
    return False


def _bbox_overlaps(left, right) -> bool:
    lx0, ly0, lx1, ly1 = left
    rx0, ry0, rx1, ry1 = right
    return min(lx1, rx1) > max(lx0, rx0) and min(ly1, ry1) > max(ly0, ry0)


def _bbox_contains(left, right) -> bool:
    lx0, ly0, lx1, ly1 = left
    rx0, ry0, rx1, ry1 = right
    return lx0 <= rx0 and ly0 <= ry0 and lx1 >= rx1 and ly1 >= ry1


def _bbox_area(box) -> float:
    x0, y0, x1, y1 = box
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def _union_bbox(boxes: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float] | None:
    if not boxes:
        return None
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _recognize_formula(engine: Any, crop_path: Path) -> str:
    if hasattr(engine, "predict"):
        raw = engine.predict(input=str(crop_path))
    else:
        raw = engine(str(crop_path))
    latex = _extract_latex(raw)
    return _cleanup_formula_latex(latex)


def _extract_latex(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("rec_formula", "formula", "latex"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                return item.strip()
        for item in value.values():
            latex = _extract_latex(item)
            if latex:
                return latex
    elif isinstance(value, list):
        for item in value:
            latex = _extract_latex(item)
            if latex:
                return latex
    elif hasattr(value, "json"):
        try:
            return _extract_latex(value.json)
        except Exception:
            return ""
    return ""


def _cleanup_formula_latex(latex: str) -> str:
    return repair_formula_latex(clean_latex(latex))


def _latex_variant_fields(latex: str) -> dict[str, str]:
    cleaned = clean_latex(latex)
    normalized = normalize_latex(cleaned)
    return {
        "cleaned_latex": cleaned,
        "normalized_latex": normalized,
        "plain_formula_text": latex_to_plain_text(normalized),
    }


def _salvage_math_segment(latex: str) -> str | None:
    flags = validate_formula_latex(latex)
    if "contains_prose" not in flags and "very_long_formula" not in flags:
        return None
    value = re.sub(r"\\begin\{(?:array|aligned|gathered)\}\{[^{}]*\}", "", latex)
    value = re.sub(r"\\end\{(?:array|aligned|gathered)\}", "", value)
    rows = re.split(r"\\\\+", value)
    candidates: list[str] = []
    for row in rows:
        cleaned = _cleanup_ocr_row(row)
        if not cleaned or len(cleaned) < 4:
            continue
        row_flags = validate_formula_latex(cleaned)
        if any(flag in row_flags for flag in ("contains_prose", "weird_unicode", "unbalanced_braces")):
            continue
        if not any(token in cleaned for token in ("=", "\\frac", "\\sum", "\\lim", "\\cup", "\\cap", "_", "^")):
            continue
        candidates.append(cleaned)
    if not candidates:
        return None
    return max(candidates, key=_latex_score)


def _cleanup_ocr_row(row: str) -> str:
    value = row.strip()
    value = value.replace("&", " ")
    value = re.sub(r"\\(?:quad|qquad|;|,|!|:)\s*", " ", value)
    value = re.sub(r"\{\s*\}", " ", value)
    value = re.sub(r"^\s*\{+", "", value)
    value = re.sub(r"\}+\s*$", "", value)
    value = re.sub(r"^\s*\{(.+)\}\s*$", r"\1", value)
    value = re.sub(r"\s+", " ", value)
    return repair_formula_latex(value)


def _restore_missing_left_hand_side(candidate: str, current: str) -> str:
    match = re.match(r"^\s*([A-Za-z](?:_\{?[\w]+\}?)?)\s*=", current)
    if not match:
        return candidate
    if re.match(r"^n\s*=\\sum", candidate):
        return f"{match.group(1)}{candidate[candidate.find('='):]}"
    if not candidate.startswith("="):
        return candidate
    return f"{match.group(1)}{candidate}"


def _is_better_latex(candidate: str, current: str) -> bool:
    if not candidate or len(candidate) < 4:
        return False
    candidate_flags = validate_formula_latex(candidate)
    current_flags = validate_formula_latex(current)
    if any(
        flag in candidate_flags
        for flag in (
            "contains_prose",
            "weird_unicode",
            "unbalanced_braces",
            "unbalanced_delimiters",
            "incomplete_formula",
            "very_long_formula",
            "sum_missing_lower_bound",
            "romanized_ocr_noise",
            "weak_math_signal",
        )
    ):
        return False
    strong = any(token in candidate for token in ("\\frac", "\\lim", "\\sum", "\\int", "\\begin", "_", "^", "="))
    if not strong:
        return False
    if candidate.count("\\therefore") > 1:
        return False
    current_score = _latex_score(current)
    candidate_score = _latex_score(candidate)
    candidate_math = _math_command_count(candidate)
    current_math = _math_command_count(current)
    current_is_degraded = any(
        flag in current_flags
        for flag in (
            "contains_prose",
            "weird_unicode",
            "unbalanced_braces",
            "unbalanced_delimiters",
            "incomplete_formula",
            "sum_missing_lower_bound",
            "romanized_ocr_noise",
            "weak_math_signal",
        )
    )
    # Do not replace a decent formula with a more "OCR-ish" reconstruction full of
    # boxed Latin letters or simplified text commands.
    if candidate.count(r"\mathrm{") >= max(3, current.count(r"\mathrm{") + 2) and candidate_math <= current_math:
        return False
    if not current_is_degraded:
        return candidate_score >= current_score + 2 and candidate_math + 3 >= current_math
    return candidate_score >= current_score - 1 and len(candidate_flags) <= len(current_flags) + 1


def _has_prose_latex(latex: str) -> bool:
    if any(marker in latex for marker in ("é–", "閉", "�")):
        return True
    compact = re.sub(r"[^A-Za-z]", "", latex).lower()
    prose_tokens = (
        "if",
        "thus",
        "proof",
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
        "recall",
    )
    if any(token in compact for token in prose_tokens):
        return True
    spaced_text_commands = len(re.findall(r"\\(?:mathit|mathrm|text|mathbf)\{[^{}]*[A-Za-z](?:\s+[A-Za-z]){3,}", latex))
    math_marks = sum(latex.count(token) for token in ("\\frac", "\\sum", "\\int", "\\lim", "=", "_", "^"))
    return spaced_text_commands >= 1 and math_marks < 5


def _latex_score(latex: str) -> int:
    score = 0
    score += 4 * sum(latex.count(token) for token in ("\\frac", "\\lim", "\\sum", "\\int", "\\sqrt"))
    score += 3 * latex.count("\\cdots")
    score += 2 * sum(latex.count(token) for token in ("_", "^", "\\to", "\\infty", "\\circ", "\\cdot", "\\cup", "\\cap"))
    score += latex.count("=")
    score -= 3 * latex.count("\\therefore")
    score -= 4 * len(re.findall(r"_\{[^{}]+\}\s*-\s*\d", latex))
    score -= len(re.findall(r"[A-Za-z]{8,}", latex))
    return score


def _math_command_count(latex: str) -> int:
    return sum(
        latex.count(token)
        for token in (
            "\\frac",
            "\\lim",
            "\\sum",
            "\\int",
            "\\sqrt",
            "\\partial",
            "\\alpha",
            "\\beta",
            "\\gamma",
            "\\delta",
            "\\rho",
            "\\phi",
            "\\psi",
            "\\mu",
            "\\nu",
            "\\Delta",
            "=",
            "_",
            "^",
        )
    )


def _short_error(exc: Exception) -> str:
    return " ".join(str(exc).split())[:400]
