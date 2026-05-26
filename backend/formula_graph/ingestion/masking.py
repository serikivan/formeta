from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from backend.formula_graph.models import FormulaRegion, PageImage, TextBlock, TextLine


@dataclass
class _FlowItem:
    kind: str
    text: str
    bbox: tuple[float, float, float, float]
    source: str
    confidence: float | None = None


def mask_formula_regions(pages: list[PageImage], regions: list[FormulaRegion], output_dir: Path) -> list[PageImage]:
    if not pages or not regions:
        return pages
    output_dir.mkdir(parents=True, exist_ok=True)
    regions_by_page: dict[int, list[FormulaRegion]] = {}
    for region in regions:
        regions_by_page.setdefault(region.page_number, []).append(region)

    masked_pages: list[PageImage] = []
    for page in pages:
        page_regions = regions_by_page.get(page.page_number, [])
        if not page_regions:
            masked_pages.append(page)
            continue
        target = output_dir / f"{Path(page.image_path).stem}_masked.png"
        _mask_page(Path(page.image_path), target, page_regions, page.dpi)
        masked_pages.append(page.model_copy(update={"image_path": str(target)}))
    return masked_pages


def reconstruct_text_with_formula_tokens(text_blocks: list[TextBlock], regions: list[FormulaRegion]) -> list[TextBlock]:
    if not text_blocks and not regions:
        return []
    regions_by_page: dict[int, list[FormulaRegion]] = {}
    for region in regions:
        regions_by_page.setdefault(region.page_number, []).append(region)
    blocks_by_page: dict[int, list[TextBlock]] = {}
    for block in text_blocks:
        blocks_by_page.setdefault(block.page_number, []).append(block)

    result: list[TextBlock] = []
    pages = sorted(set(blocks_by_page) | set(regions_by_page))
    for page_number in pages:
        page_blocks = blocks_by_page.get(page_number, [])
        page_regions = regions_by_page.get(page_number, [])
        items = _collect_items(page_blocks, page_regions)
        lines = _cluster_lines(items)
        for line_index, line_items in enumerate(lines, start=1):
            bbox = _union_bbox([item.bbox for item in line_items])
            text = _compose_line_text(line_items)
            if not text or bbox is None:
                continue
            source = "formula_token" if all(item.kind == "formula" for item in line_items) else "postprocessed"
            confidence = _average_confidence(line_items)
            line = TextLine(text=text, bbox=bbox)
            result.append(
                TextBlock(
                    id=f"p{page_number}_recon_{line_index}",
                    page_number=page_number,
                    text=text,
                    bbox=bbox,
                    source=source,
                    confidence=confidence,
                    lines=[line],
                )
            )
    return result


def _collect_items(text_blocks: list[TextBlock], regions: list[FormulaRegion]) -> list[_FlowItem]:
    items: list[_FlowItem] = []
    for block in text_blocks:
        if not block.text.strip() or block.bbox is None:
            continue
        items.extend(_collect_text_items(block, regions))
    for region in regions:
        items.append(
            _FlowItem(
                kind="formula",
                text=region.token,
                bbox=region.bbox,
                source="formula_token",
                confidence=region.confidence,
            )
        )
    items.sort(key=lambda item: (_center_y(item.bbox), item.bbox[0]))
    return items


def _collect_text_items(block: TextBlock, regions: list[FormulaRegion]) -> list[_FlowItem]:
    lines = block.lines or [TextLine(text=block.text, bbox=block.bbox, spans=[])]
    items: list[_FlowItem] = []
    for line in lines:
        if not line.text.strip():
            continue
        line_bbox = line.bbox or block.bbox
        if line_bbox is None:
            continue
        line_regions = _overlapping_regions(line_bbox, regions)
        if not line_regions:
            items.append(_text_item(line.text, line_bbox, block))
            continue
        if _should_drop_text_segment(line.text, line_bbox, line_regions):
            continue
        segmented = _split_line_by_inline_regions(line, block, line_regions)
        if not segmented:
            segmented = _split_line_by_inline_text(line, block, line_regions)
        if segmented:
            items.extend(segmented)
            continue
        items.append(_text_item(line.text, line_bbox, block))
    return items


def _split_line_by_inline_regions(line: TextLine, block: TextBlock, regions: list[FormulaRegion]) -> list[_FlowItem]:
    if not line.spans:
        return []
    inline_regions = [region for region in regions if region.kind == "inline"]
    if not inline_regions:
        return []
    segments: list[list] = []
    current: list = []
    for span in line.spans:
        span_text = span.text or ""
        if not span_text:
            continue
        span_bbox = span.bbox
        if span_bbox is not None and any(_bbox_hits_region(span_bbox, region.bbox, 0.18) for region in inline_regions):
            if current:
                segments.append(current)
                current = []
            continue
        current.append(span)
    if current:
        segments.append(current)

    result: list[_FlowItem] = []
    for segment in segments:
        text = "".join(span.text for span in segment)
        bbox = _union_bbox([span.bbox for span in segment if span.bbox is not None]) or line.bbox or block.bbox
        if not text.strip() or bbox is None:
            continue
        result.append(_text_item(text, bbox, block))
    return result


def _split_line_by_inline_text(line: TextLine, block: TextBlock, regions: list[FormulaRegion]) -> list[_FlowItem]:
    line_text = line.text or ""
    line_bbox = line.bbox or block.bbox
    if not line_text.strip() or line_bbox is None:
        return []
    inline_regions = [region for region in regions if region.kind == "inline" and region.latex_keys]
    if not inline_regions:
        return []

    ranges: list[tuple[int, int]] = []
    for region in sorted(inline_regions, key=lambda item: item.bbox[0]):
        match = _find_inline_latex_text_range(line_text, region.latex_keys, ranges)
        if match is not None:
            ranges.append(match)
    ranges = _merge_ranges(sorted(ranges))
    if not ranges:
        return []

    result: list[_FlowItem] = []
    cursor = 0
    for start, end in ranges:
        if start > cursor:
            _append_text_range(result, line_text, cursor, start, line_bbox, block)
        cursor = max(cursor, end)
    if cursor < len(line_text):
        _append_text_range(result, line_text, cursor, len(line_text), line_bbox, block)
    return result


def _find_inline_latex_text_range(
    text: str,
    latex_keys: list[str],
    blocked: list[tuple[int, int]],
) -> tuple[int, int] | None:
    canonical_text, mapping = _canonical_math_with_mapping(text)
    if not canonical_text:
        return None
    for latex_key in sorted(set(latex_keys), key=len, reverse=True):
        canonical_latex, _ = _canonical_math_with_mapping(latex_key)
        if len(canonical_latex) < 3:
            continue
        start = canonical_text.find(canonical_latex)
        while start >= 0:
            end = start + len(canonical_latex)
            original = (mapping[start], mapping[end - 1] + 1)
            if not any(max(original[0], left) < min(original[1], right) for left, right in blocked):
                return original
            start = canonical_text.find(canonical_latex, start + 1)
    return None


def _canonical_math_with_mapping(text: str) -> tuple[str, list[int]]:
    greek = {
        "\u03b1": "alpha",
        "\u03b2": "beta",
        "\u03b3": "gamma",
        "\u03b4": "delta",
        "\u03b8": "theta",
        "\u03bb": "lambda",
        "\u03bc": "mu",
        "\u03c0": "pi",
        "\u03c1": "rho",
        "\u03c3": "sigma",
        "\u03c6": "phi",
        "\u03d5": "phi",
        "\u03c8": "psi",
        "\u03c9": "omega",
        "\u03be": "xi",
    }
    symbols = {
        "\u221e": "infty",
        "\u2208": "in",
        "\u222a": "cup",
        "\u2229": "cap",
        "\u2264": "le",
        "\u2265": "ge",
        "\u2248": "approx",
        "\u2212": "-",
    }
    result: list[str] = []
    mapping: list[int] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\":
            end = index + 1
            while end < len(text) and text[end].isalpha():
                end += 1
            command = text[index + 1 : end].lower()
            if command:
                result.extend(command)
                mapping.extend([index] * len(command))
                index = end
                continue
        replacement = greek.get(char.lower()) or symbols.get(char)
        if replacement:
            result.extend(replacement)
            mapping.extend([index] * len(replacement))
        elif char.isspace() or char in "{}_":
            pass
        else:
            result.append(char.lower())
            mapping.append(index)
        index += 1
    return "".join(result), mapping


def _append_text_range(
    result: list[_FlowItem],
    text: str,
    start: int,
    end: int,
    line_bbox: tuple[float, float, float, float],
    block: TextBlock,
) -> None:
    value = text[start:end].strip()
    if not value:
        return
    bbox = _bbox_for_text_range(line_bbox, len(text), start, end)
    result.append(_text_item(value, bbox, block))


def _bbox_for_text_range(
    bbox: tuple[float, float, float, float],
    text_length: int,
    start: int,
    end: int,
) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = bbox
    width = max(1e-6, x1 - x0)
    length = max(1, text_length)
    return (
        x0 + width * max(0, start) / length,
        y0,
        x0 + width * min(length, end) / length,
        y1,
    )


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not ranges:
        return []
    merged = [ranges[0]]
    for start, end in ranges[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _should_drop_text_segment(text: str, bbox: tuple[float, float, float, float], regions: list[FormulaRegion]) -> bool:
    compact = " ".join(text.split())
    if not compact:
        return True
    for region in regions:
        overlap = _bbox_overlap_ratio(bbox, region.bbox)
        coverage = _bbox_coverage(bbox, region.bbox)
        contains_center = _bbox_center_inside(bbox, region.bbox)
        if region.kind == "block" and (coverage >= 0.34 or contains_center):
            return True
        if region.kind == "inline" and (coverage >= 0.72 or (contains_center and _looks_formula_fragment(compact))):
            return True
    return False


def _text_item(text: str, bbox: tuple[float, float, float, float], block: TextBlock) -> _FlowItem:
    return _FlowItem(
        kind="text",
        text=text.strip(),
        bbox=bbox,
        source=block.source,
        confidence=block.confidence,
    )


def _overlapping_regions(
    bbox: tuple[float, float, float, float],
    regions: list[FormulaRegion],
) -> list[FormulaRegion]:
    return [region for region in regions if _bbox_hits_region(bbox, region.bbox, 0.12)]


def _bbox_hits_region(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
    min_overlap: float,
) -> bool:
    return _bbox_overlap_ratio(left, right) >= min_overlap or _bbox_center_inside(left, right) or _bbox_center_inside(right, left)


def _bbox_overlap_ratio(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    ix0 = max(left[0], right[0])
    iy0 = max(left[1], right[1])
    ix1 = min(left[2], right[2])
    iy1 = min(left[3], right[3])
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    intersection = (ix1 - ix0) * (iy1 - iy0)
    left_area = max(1.0, (left[2] - left[0]) * (left[3] - left[1]))
    right_area = max(1.0, (right[2] - right[0]) * (right[3] - right[1]))
    return intersection / min(left_area, right_area)


def _bbox_coverage(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    ix0 = max(left[0], right[0])
    iy0 = max(left[1], right[1])
    ix1 = min(left[2], right[2])
    iy1 = min(left[3], right[3])
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    intersection = (ix1 - ix0) * (iy1 - iy0)
    left_area = max(1.0, (left[2] - left[0]) * (left[3] - left[1]))
    return intersection / left_area


def _bbox_center_inside(
    inner: tuple[float, float, float, float],
    outer: tuple[float, float, float, float],
) -> bool:
    center_x = (inner[0] + inner[2]) / 2
    center_y = (inner[1] + inner[3]) / 2
    return outer[0] <= center_x <= outer[2] and outer[1] <= center_y <= outer[3]


def _looks_formula_fragment(text: str) -> bool:
    if len(text) <= 2:
        return True
    letters = sum(char.isalpha() for char in text)
    digits = sum(char.isdigit() for char in text)
    math_chars = sum(1 for char in text if char in "=<>+-*/^_()[]{}\\|.,:;")
    return math_chars + digits >= max(1, letters * 0.4)


def _cluster_lines(items: list[_FlowItem]) -> list[list[_FlowItem]]:
    lines: list[list[_FlowItem]] = []
    for item in items:
        line = next((candidate for candidate in lines if _belongs_to_line(item, candidate)), None)
        if line is None:
            lines.append([item])
            continue
        line.append(item)
    for line in lines:
        line.sort(key=lambda item: item.bbox[0])
    lines.sort(key=lambda line: min(item.bbox[1] for item in line))
    return lines


def _belongs_to_line(item: _FlowItem, line: list[_FlowItem]) -> bool:
    line_bbox = _union_bbox([member.bbox for member in line])
    if line_bbox is None:
        return False
    item_height = max(1.0, item.bbox[3] - item.bbox[1])
    line_height = max(1.0, line_bbox[3] - line_bbox[1])
    center_delta = abs(_center_y(item.bbox) - _center_y(line_bbox))
    vertical_overlap = max(0.0, min(item.bbox[3], line_bbox[3]) - max(item.bbox[1], line_bbox[1]))
    min_height = min(item_height, line_height)
    max_height = max(item_height, line_height)
    return center_delta <= min_height * 0.45 or vertical_overlap >= min_height * 0.55 or center_delta <= max_height * 0.3


def _compose_line_text(items: list[_FlowItem]) -> str:
    parts: list[str] = []
    previous: _FlowItem | None = None
    for item in items:
        if not parts:
            parts.append(item.text)
            previous = item
            continue
        gap = item.bbox[0] - (previous.bbox[2] if previous is not None else item.bbox[0])
        glue = _glue(previous, item, gap) if previous is not None else " "
        parts.append(glue + item.text)
        previous = item
    return _normalize_spacing("".join(parts))


def _glue(left: _FlowItem, right: _FlowItem, gap: float) -> str:
    if left.kind == "formula" and right.kind == "formula":
        return " "
    if left.kind == "formula" or right.kind == "formula":
        return " "
    if gap <= 1.5:
        return ""
    if gap <= 8:
        return " "
    return " "


def _normalize_spacing(text: str) -> str:
    value = " ".join(text.split())
    for token in (".", ",", ";", ":", ")", "]", "}", "?", "!"):
        value = value.replace(f" {token}", token)
    for token in ("(", "[", "{"):
        value = value.replace(f"{token} ", token)
    return value.strip()


def _mask_page(source: Path, target: Path, regions: list[FormulaRegion], dpi: int) -> None:
    with Image.open(source) as image:
        canvas = image.convert("RGB")
        draw = ImageDraw.Draw(canvas)
        scale = dpi / 72
        for region in regions:
            x0, y0, x1, y1 = region.bbox
            pad_x = 10 if region.kind == "inline" else 14
            pad_y = 6 if region.kind == "inline" else 10
            box = (
                max(0, int(x0 * scale) - pad_x),
                max(0, int(y0 * scale) - pad_y),
                min(canvas.width, int(x1 * scale) + pad_x),
                min(canvas.height, int(y1 * scale) + pad_y),
            )
            draw.rectangle(box, fill="white")
        canvas.save(target)


def _average_confidence(items: list[_FlowItem]) -> float | None:
    values = [item.confidence for item in items if item.confidence is not None]
    if not values:
        return None
    return sum(values) / len(values)


def _union_bbox(boxes: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float] | None:
    if not boxes:
        return None
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _center_y(bbox: tuple[float, float, float, float]) -> float:
    return (bbox[1] + bbox[3]) / 2
