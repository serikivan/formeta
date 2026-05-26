from __future__ import annotations

import csv
import shutil
import subprocess
from collections import defaultdict
from io import StringIO

from backend.formula_graph.models import BBox, PageImage, TextBlock
from backend.formula_graph.ocr.base import OCRAdapter


class TesseractOCRAdapter(OCRAdapter):
    name = "tesseract"

    def __init__(self, lang: str = "ru") -> None:
        self.lang = lang

    def recognize_pages(self, pages: list[PageImage], progress_callback=None) -> tuple[list[TextBlock], list[str]]:
        executable = shutil.which("tesseract")
        if executable is None:
            return [], ["Tesseract executable was not found in PATH."]

        blocks: list[TextBlock] = []
        warnings: list[str] = []
        total = max(1, len(pages))
        for index, page in enumerate(pages, start=1):
            try:
                tsv = _run_tesseract(executable, page.image_path, _lang_arg(self.lang))
                blocks.extend(_parse_tsv(tsv, page, len(blocks)))
            except Exception as exc:
                warnings.append(f"Tesseract завершился ошибкой на странице {page.page_number}: {' '.join(str(exc).split())[:500]}")
            if progress_callback is not None:
                progress_callback(index, total)
        return blocks, warnings


def _run_tesseract(executable: str, image_path: str, lang: str) -> str:
    completed = subprocess.run(
        [executable, image_path, "stdout", "-l", lang, "--psm", "6", "--oem", "1", "tsv"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.stdout


def _lang_arg(lang: str) -> str:
    if lang == "ru":
        return "rus+eng"
    return "eng"


def _parse_tsv(tsv: str, page: PageImage, offset: int) -> list[TextBlock]:
    reader = csv.DictReader(StringIO(tsv), delimiter="\t")
    grouped: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in reader:
        text = (row.get("text") or "").strip()
        if not text:
            continue
        try:
            conf = float(row.get("conf") or -1)
        except ValueError:
            conf = -1
        if conf < 0:
            continue
        key = (row.get("block_num") or "0", row.get("par_num") or "0", row.get("line_num") or "0")
        grouped[key].append(row)

    blocks: list[TextBlock] = []
    for rows in grouped.values():
        words = [(row.get("text") or "").strip() for row in rows if (row.get("text") or "").strip()]
        if not words:
            continue
        confs = []
        boxes = []
        for row in rows:
            try:
                left = float(row.get("left") or 0)
                top = float(row.get("top") or 0)
                width = float(row.get("width") or 0)
                height = float(row.get("height") or 0)
                confs.append(float(row.get("conf") or 0))
                boxes.append((left, top, left + width, top + height))
            except ValueError:
                continue
        if not boxes:
            bbox = None
            confidence = None
        else:
            bbox = (
                min(box[0] for box in boxes),
                min(box[1] for box in boxes),
                max(box[2] for box in boxes),
                max(box[3] for box in boxes),
            )
            confidence = sum(confs) / len(confs) / 100 if confs else None
        blocks.append(
            TextBlock(
                id=f"p{page.page_number}_tes_{offset + len(blocks) + 1}",
                page_number=page.page_number,
                text=" ".join(words),
                bbox=_scale_bbox(bbox, page.dpi),
                source="tesseract",
                confidence=confidence,
            )
        )
    return blocks


def _scale_bbox(bbox: BBox | None, dpi: int) -> BBox | None:
    if bbox is None:
        return None
    factor = 72 / max(1, dpi)
    x0, y0, x1, y1 = bbox
    return x0 * factor, y0 * factor, x1 * factor, y1 * factor
