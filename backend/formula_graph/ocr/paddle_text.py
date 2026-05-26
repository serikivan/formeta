from __future__ import annotations

from functools import cached_property
from typing import Any

from backend.formula_graph.config import resolve_device, settings
from backend.formula_graph.models import BBox, PageImage, TextBlock
from backend.formula_graph.ocr.base import OCRAdapter
from backend.formula_graph.ocr.model_cache import get_cached_model


class PaddleOCRAdapter(OCRAdapter):
    name = "paddleocr"

    def __init__(self, device: str | None = None, lang: str | None = None) -> None:
        self.device = resolve_device(device)
        self.lang = lang or settings.ocr_lang

    @cached_property
    def engine(self) -> Any:
        ocr_version = "PP-OCRv5" if self.lang in {"ch", "chinese_cht", "en", "japan"} else "PP-OCRv3"

        def create_engine() -> Any:
            from paddleocr import PaddleOCR

            try:
                return PaddleOCR(
                    lang=self.lang,
                    ocr_version=ocr_version,
                    device=self.device,
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=True,
                    textline_orientation_batch_size=1,
                    text_recognition_batch_size=1,
                )
            except TypeError:
                return PaddleOCR(
                    lang=self.lang,
                    ocr_version=ocr_version,
                    use_angle_cls=True,
                    show_log=False,
                    use_gpu=self.device == "gpu",
                )

        return get_cached_model(("paddleocr", self.device, self.lang, ocr_version), create_engine)

    def recognize_pages(self, pages: list[PageImage], progress_callback=None) -> tuple[list[TextBlock], list[str]]:
        blocks: list[TextBlock] = []
        warnings: list[str] = []
        try:
            engine = self.engine
        except Exception as exc:
            return [], [f"PaddleOCR недоступен: {exc}"]

        total = max(1, len(pages))
        for index, page in enumerate(pages, start=1):
            try:
                raw_result = _predict(engine, page.image_path)
                page_blocks = _parse_result(raw_result, page)
                blocks.extend(page_blocks)
            except Exception as exc:
                warnings.append(f"PaddleOCR завершился ошибкой на странице {page.page_number}: {exc}")
            if progress_callback is not None:
                progress_callback(index, total)
        return blocks, warnings


def _predict(engine: Any, image_path: str) -> Any:
    if hasattr(engine, "predict"):
        return engine.predict(input=image_path)
    return engine.ocr(image_path, cls=True)


def _parse_result(raw_result: Any, page: PageImage) -> list[TextBlock]:
    blocks: list[TextBlock] = []

    if isinstance(raw_result, list):
        for item in raw_result:
            if isinstance(item, dict):
                texts = _empty_if_none(_first_present(item, "rec_texts", "texts"))
                scores = _empty_if_none(_first_present(item, "rec_scores", "scores"))
                boxes = _empty_if_none(_first_present(item, "rec_boxes", "dt_polys", "boxes"))
                for index, text in enumerate(texts):
                    if not str(text).strip():
                        continue
                    blocks.append(
                        TextBlock(
                            id=f"p{page.page_number}_ocr_{len(blocks) + 1}",
                            page_number=page.page_number,
                            text=str(text).strip(),
                            bbox=_scale_bbox(_box_to_bbox(boxes[index]), page.dpi) if index < len(boxes) else None,
                            source="paddleocr",
                            confidence=float(scores[index]) if index < len(scores) else None,
                        )
                    )
            elif isinstance(item, list):
                _parse_legacy_lines(item, page, blocks)
    return blocks


def _parse_legacy_lines(lines: list[Any], page: PageImage, blocks: list[TextBlock]) -> None:
    for line in lines:
        if not isinstance(line, (list, tuple)) or len(line) < 2:
            continue
        box = line[0]
        payload = line[1]
        if isinstance(payload, (list, tuple)) and payload:
            text = str(payload[0]).strip()
            score = float(payload[1]) if len(payload) > 1 else None
        else:
            text = str(payload).strip()
            score = None
        if not text:
            continue
        blocks.append(
            TextBlock(
                id=f"p{page.page_number}_ocr_{len(blocks) + 1}",
                page_number=page.page_number,
                text=text,
                bbox=_scale_bbox(_box_to_bbox(box), page.dpi),
                source="paddleocr",
                confidence=score,
            )
        )


def _box_to_bbox(box: Any) -> tuple[float, float, float, float] | None:
    try:
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


def _first_present(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None


def _empty_if_none(value: Any) -> Any:
    return [] if value is None else value
