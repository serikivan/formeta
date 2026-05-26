from __future__ import annotations

import shutil
import re
from datetime import datetime
from pathlib import Path

import fitz
from PIL import Image

from backend.formula_graph.config import settings
from backend.formula_graph.models import PageImage, TextBlock, TextLine, TextSpan


SUPPORTED_IMAGES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


def persist_upload(source_path: Path, original_name: str) -> tuple[str, Path]:
    document_id = build_document_id(original_name)
    safe_suffix = Path(original_name).suffix.lower()
    target = _unique_path(settings.input_dir / f"{document_id}{safe_suffix}")
    shutil.copyfile(source_path, target)
    return target.stem, target


def build_document_id(original_name: str, processed_at: datetime | None = None) -> str:
    processed_at = processed_at or datetime.now()
    path = Path(original_name or "document")
    stem = path.stem or "document"
    suffix = path.suffix.lower().lstrip(".") or "unknown"
    safe_stem = re.sub(r"[^A-Za-z0-9А-Яа-я_.-]+", "_", stem, flags=re.IGNORECASE).strip("._-")
    safe_stem = safe_stem[:80] or "document"
    timestamp = processed_at.strftime("%Y%m%d_%H%M%S")
    return f"{safe_stem}_{timestamp}_{suffix}"


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Could not allocate unique path for {path}")


def render_document(path: Path, document_id: str, dpi: int, max_pages: int | None, progress_callback=None) -> tuple[list[PageImage], list[TextBlock]]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _render_pdf(path, document_id, dpi, max_pages, progress_callback=progress_callback)
    if suffix in SUPPORTED_IMAGES:
        return _load_image(path, document_id, dpi, progress_callback=progress_callback)
    raise ValueError(f"Unsupported file type: {suffix}")


def _render_pdf(path: Path, document_id: str, dpi: int, max_pages: int | None, progress_callback=None) -> tuple[list[PageImage], list[TextBlock]]:
    output_dir = settings.processed_dir / document_id
    output_dir.mkdir(parents=True, exist_ok=True)
    pages: list[PageImage] = []
    text_blocks: list[TextBlock] = []

    with fitz.open(path) as doc:
        page_count = len(doc) if max_pages is None or max_pages <= 0 else min(len(doc), max_pages)
        for index in range(page_count):
            page = doc[index]
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            image_path = output_dir / f"page_{index + 1:04d}.png"
            pix.save(image_path)

            text_layer = page.get_text("text").strip()
            pages.append(
                PageImage(
                    page_number=index + 1,
                    image_path=str(image_path),
                    width=pix.width,
                    height=pix.height,
                    dpi=dpi,
                    text_layer=text_layer,
                )
            )

            text_dict = page.get_text("dict")
            block_index = 0
            for block in text_dict.get("blocks", []):
                if block.get("type") != 0:
                    continue
                lines = []
                line_items: list[TextLine] = []
                for line in block.get("lines", []):
                    span_items = [
                        TextSpan(
                            text=span.get("text", ""),
                            bbox=tuple(span.get("bbox", (0, 0, 0, 0))),
                            font=span.get("font"),
                            size=span.get("size"),
                        )
                        for span in line.get("spans", [])
                        if span.get("text", "")
                    ]
                    line_text = "".join(span.text for span in span_items).strip()
                    if line_text:
                        lines.append(line_text)
                        line_items.append(
                            TextLine(
                                text=line_text,
                                bbox=tuple(line.get("bbox", (0, 0, 0, 0))),
                                spans=span_items,
                            )
                        )
                block_text = "\n".join(lines).strip()
                if not block_text:
                    continue
                block_index += 1
                text_blocks.append(
                    TextBlock(
                        id=f"p{index + 1}_tl_{block_index}",
                        page_number=index + 1,
                        text=block_text,
                        bbox=tuple(block.get("bbox", (0, 0, 0, 0))),
                        source="pdf_text_layer",
                        confidence=1.0,
                        lines=line_items,
                    )
                )
            if progress_callback is not None:
                progress_callback(index + 1, page_count)
    return pages, text_blocks


def _load_image(path: Path, document_id: str, dpi: int, progress_callback=None) -> tuple[list[PageImage], list[TextBlock]]:
    output_dir = settings.processed_dir / document_id
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"page_0001{path.suffix.lower()}"
    shutil.copyfile(path, target)
    with Image.open(target) as image:
        width, height = image.size
    return [
        PageImage(
            page_number=1,
            image_path=str(target),
            width=width,
            height=height,
            dpi=dpi,
        )
    ], []
