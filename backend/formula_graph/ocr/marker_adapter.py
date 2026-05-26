from __future__ import annotations

import re
from html import unescape
from pathlib import Path
from typing import Any

from backend.formula_graph.config import resolve_device
from backend.formula_graph.models import FormulaBlock, TextBlock


class MarkerAdapter:
    name = "marker"
    _models_by_device: dict[str, dict[str, Any]] = {}

    def __init__(self, device: str | None = None) -> None:
        requested = resolve_device(device)
        self.device = "cuda" if requested == "gpu" else "cpu"

    @property
    def models(self) -> dict[str, Any]:
        models = self._models_by_device.get(self.device)
        if models is not None:
            return models
        from marker.models import create_model_dict

        models = create_model_dict(device=self.device)
        self._models_by_device[self.device] = models
        return models

    def parse_document(self, source_path: Path, max_pages: int | None) -> tuple[list[TextBlock], list[FormulaBlock], list[str]]:
        warnings: list[str] = []
        try:
            from marker.config.parser import ConfigParser
            from marker.converters.pdf import PdfConverter
        except Exception as exc:
            return [], [], [f"Marker недоступен: {' '.join(str(exc).split())[:240]}"]

        try:
            config = {"output_format": "json"}
            page_range = _marker_page_range(max_pages)
            if page_range is not None:
                config["page_range"] = page_range
            config_parser = ConfigParser(
                config
            )
            converter = PdfConverter(
                config={**config_parser.generate_config_dict(), "pdftext_workers": 1},
                artifact_dict=self.models,
                processor_list=config_parser.get_processors(),
                renderer=config_parser.get_renderer(),
                llm_service=config_parser.get_llm_service(),
            )
            rendered = converter(str(source_path))
        except Exception as exc:
            return [], [], [f"Разбор через Marker завершился ошибкой: {' '.join(str(exc).split())[:360]}"]

        text_blocks: list[TextBlock] = []
        formulas: list[FormulaBlock] = []
        for page_index, page in enumerate(rendered.children, start=1):
            for child_index, child in enumerate(page.children or [], start=1):
                bbox = _to_bbox(child.bbox)
                html = child.html or ""
                block_type = str(child.block_type)
                if block_type.lower() == "equation":
                    latex_items = _extract_math_items(html)
                    if latex_items:
                        for item_index, latex in enumerate(latex_items, start=1):
                            formulas.append(
                                FormulaBlock(
                                    id=f"f_m_{page_index}_{child_index}_{item_index}",
                                    page_number=page_index,
                                    latex=latex,
                                    kind="block",
                                    bbox=bbox,
                                    source="marker",
                                    confidence=0.95,
                                )
                            )
                    else:
                        plain = _html_to_text(html)
                        if plain:
                            formulas.append(
                                FormulaBlock(
                                    id=f"f_m_{page_index}_{child_index}",
                                    page_number=page_index,
                                    latex=plain,
                                    kind="block",
                                    bbox=bbox,
                                    source="marker",
                                    confidence=0.78,
                                    quality_flags=["marker_equation_without_math_tag"],
                                )
                            )
                    continue

                text = _html_to_text(html)
                if text:
                    text_blocks.append(
                        TextBlock(
                            id=f"p{page_index}_marker_{child_index}",
                            page_number=page_index,
                            text=text,
                            bbox=bbox,
                            source="postprocessed",
                            confidence=0.98,
                        )
                    )
                inline_math = _extract_math_items(html)
                for item_index, latex in enumerate(inline_math, start=1):
                    formulas.append(
                        FormulaBlock(
                            id=f"f_m_{page_index}_{child_index}_{item_index}",
                            page_number=page_index,
                            latex=latex,
                            kind="inline",
                            bbox=bbox,
                            source="marker",
                            confidence=0.9,
                        )
                    )

        return _dedupe_marker_text(text_blocks), _dedupe_marker_formulas(formulas), warnings


def _marker_page_range(max_pages: int | None) -> str | None:
    if max_pages is None or max_pages <= 0:
        return None
    upper = max(0, max_pages - 1)
    return f"0-{upper}"


def _to_bbox(bbox: list[float] | tuple[float, float, float, float] | None):
    if not bbox or len(bbox) != 4:
        return None
    return tuple(float(value) for value in bbox)


def _extract_math_items(html: str) -> list[str]:
    values: list[str] = []
    for match in re.finditer(r"<math\b[^>]*>(.*?)</math>", html, flags=re.IGNORECASE | re.DOTALL):
        value = _cleanup_math(match.group(1))
        if value:
            values.append(value)
    return values


def _cleanup_math(value: str) -> str:
    text = unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = " ".join(text.split())
    return text.strip()


def _html_to_text(html: str) -> str:
    value = re.sub(r"<math\b[^>]*>.*?</math>", " ", html or "", flags=re.IGNORECASE | re.DOTALL)
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"</p>|</h\d>|</li>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n\s+", "\n", value)
    return value.strip()


def _dedupe_marker_text(blocks: list[TextBlock]) -> list[TextBlock]:
    seen: set[tuple[int, str, str]] = set()
    result: list[TextBlock] = []
    for block in blocks:
        key = (
            block.page_number,
            re.sub(r"\s+", " ", block.text).strip().lower(),
            ":".join(str(round(value, 2)) for value in block.bbox) if block.bbox else "none",
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(block)
    return result


def _dedupe_marker_formulas(formulas: list[FormulaBlock]) -> list[FormulaBlock]:
    seen: set[tuple[int, str, str, str]] = set()
    result: list[FormulaBlock] = []
    for formula in formulas:
        key = (
            formula.page_number,
            formula.kind,
            re.sub(r"\s+", "", formula.latex).lower(),
            ":".join(str(round(value, 2)) for value in formula.bbox) if formula.bbox else "none",
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(formula)
    return result
