from __future__ import annotations

import re

from backend.formula_graph.models import FormulaBlock, FormulaRegion


def build_formula_regions(formulas: list[FormulaBlock]) -> list[FormulaRegion]:
    clusters: list[dict[str, object]] = []
    for formula in formulas:
        if formula.bbox is None:
            continue
        cluster = next((item for item in clusters if _belongs_to_cluster(formula, item)), None)
        if cluster is None:
            clusters.append(
                {
                    "bbox": formula.bbox,
                    "members": [formula],
                }
            )
            continue
        cluster["members"].append(formula)  # type: ignore[index]
        cluster["bbox"] = _union_bbox([cluster["bbox"], formula.bbox])  # type: ignore[list-item]

    regions: list[FormulaRegion] = []
    for index, cluster in enumerate(clusters, start=1):
        members: list[FormulaBlock] = list(cluster["members"])  # type: ignore[assignment]
        representative = max(members, key=_formula_sort_key)
        bbox = cluster["bbox"]  # type: ignore[assignment]
        regions.append(
            FormulaRegion(
                id=f"fr_{index}",
                token=f"[FORMULA_{index:03d}]",
                page_number=representative.page_number,
                bbox=bbox,
                kind=representative.kind,
                source=representative.source,
                confidence=representative.confidence,
                formula_keys=[_formula_key(member) for member in members],
                formula_ids=[member.id for member in members],
                latex_keys=[_normalized_latex(member.latex) for member in members],
            )
        )
    return regions


def merge_formula_candidates(*groups: list[FormulaBlock]) -> list[FormulaBlock]:
    merged: list[FormulaBlock] = []
    for group in groups:
        for formula in group:
            duplicate_index = next((index for index, item in enumerate(merged) if _same_formula_region(item, formula)), None)
            if duplicate_index is None:
                merged.append(formula)
                continue
            current = merged[duplicate_index]
            winner = formula if _formula_sort_key(formula) > _formula_sort_key(current) else current
            merged[duplicate_index] = winner
    return merged


def assign_formula_tokens(formulas: list[FormulaBlock], regions: list[FormulaRegion]) -> list[FormulaBlock]:
    region_by_key = {key: region for region in regions for key in region.formula_keys}
    assigned: list[FormulaBlock] = []
    for formula in formulas:
        region = (
            region_by_key.get(_formula_key(formula))
            or _best_region(formula, regions)
            or _best_region_by_latex(formula, regions)
            or _best_unique_page_region(formula, regions)
        )
        if region is None:
            assigned.append(formula)
            continue
        assigned.append(
            formula.model_copy(
                update={
                    "token": region.token,
                    "formula_region_id": region.id,
                }
            )
        )
    return assigned


def consolidate_assigned_formulas(formulas: list[FormulaBlock]) -> list[FormulaBlock]:
    grouped: dict[str, list[FormulaBlock]] = {}
    ungrouped: list[FormulaBlock] = []
    for formula in formulas:
        if formula.token:
            grouped.setdefault(formula.token, []).append(formula)
        else:
            ungrouped.append(formula)

    consolidated: list[FormulaBlock] = []
    for token in sorted(grouped):
        items = grouped[token]
        winner = max(items, key=_representative_formula_key)
        raw_latex = winner.raw_latex
        if raw_latex is None:
            raw_latex = next((item.raw_latex or item.latex for item in items if item is not winner and (item.raw_latex or item.latex)), None)
        borrowed_bbox = winner.bbox
        if borrowed_bbox is None:
            borrowed_bbox = next((item.bbox for item in items if item.bbox is not None), None)
        consolidated.append(
            winner.model_copy(
                update={
                    "quality_flags": list(winner.quality_flags),
                    "raw_latex": raw_latex,
                    "bbox": borrowed_bbox,
                }
            )
        )
    consolidated.extend(ungrouped)
    return consolidated


def reindex_formulas(formulas: list[FormulaBlock]) -> list[FormulaBlock]:
    ordered = sorted(formulas, key=_formula_order_key)
    return [
        formula.model_copy(update={"id": f"f_{index}"})
        for index, formula in enumerate(ordered, start=1)
    ]


def _best_region_by_latex(formula: FormulaBlock, regions: list[FormulaRegion]) -> FormulaRegion | None:
    normalized = _normalized_latex(formula.latex)
    if not normalized:
        return None
    matches = []
    for region in regions:
        if region.page_number != formula.page_number:
            continue
        similarity = max((_latex_overlap(normalized, latex_key) for latex_key in region.latex_keys), default=0.0)
        if similarity >= 0.72:
            matches.append((similarity, _region_priority(region), region))
    if not matches:
        return None
    matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return matches[0][2]


def _best_unique_page_region(formula: FormulaBlock, regions: list[FormulaRegion]) -> FormulaRegion | None:
    if formula.source.endswith("_raw") or formula.bbox is not None:
        return None
    if any(flag in formula.quality_flags for flag in ("needs_formula_review", "contains_prose", "romanized_ocr_noise", "needs_review")):
        return None
    if formula.confidence is not None and formula.confidence < 0.7:
        return None
    same_page = [region for region in regions if region.page_number == formula.page_number]
    if len(same_page) == 1:
        return same_page[0]
    return None


def _belongs_to_cluster(formula: FormulaBlock, cluster: dict[str, object]) -> bool:
    bbox = formula.bbox
    if bbox is None:
        return False
    members: list[FormulaBlock] = cluster["members"]  # type: ignore[assignment]
    sample = members[0]
    cluster_bbox = cluster["bbox"]  # type: ignore[assignment]
    if sample.page_number != formula.page_number:
        return False
    return (
        _same_formula_region(sample, formula)
        or _bbox_iou(cluster_bbox, bbox) >= 0.18
        or _bbox_overlap_ratio(cluster_bbox, bbox) >= 0.45
        or _bbox_contains(cluster_bbox, bbox)
        or _bbox_contains(bbox, cluster_bbox)
    )


def _best_region(formula: FormulaBlock, regions: list[FormulaRegion]) -> FormulaRegion | None:
    if formula.bbox is None:
        return None
    matches = [
        region
        for region in regions
        if region.page_number == formula.page_number
        and (
            _bbox_iou(region.bbox, formula.bbox) >= 0.12
            or _bbox_overlap_ratio(region.bbox, formula.bbox) >= 0.4
            or _bbox_contains(region.bbox, formula.bbox)
            or _bbox_contains(formula.bbox, region.bbox)
        )
    ]
    if not matches:
        return None
    matches.sort(
        key=lambda region: (
            _bbox_overlap_ratio(region.bbox, formula.bbox),
            _bbox_iou(region.bbox, formula.bbox),
            _region_priority(region),
        ),
        reverse=True,
    )
    return matches[0]


def _same_formula_region(left: FormulaBlock, right: FormulaBlock) -> bool:
    if left.page_number != right.page_number or left.bbox is None or right.bbox is None:
        return False
    if _normalized_latex(left.latex) == _normalized_latex(right.latex):
        return True
    return _bbox_iou(left.bbox, right.bbox) >= 0.5 or _bbox_overlap_ratio(left.bbox, right.bbox) >= 0.72


def _formula_key(formula: FormulaBlock) -> str:
    bbox = formula.bbox
    bbox_key = "none"
    if bbox is not None:
        bbox_key = ":".join(str(round(value, 2)) for value in bbox)
    return "|".join(
        [
            str(formula.page_number),
            formula.source,
            formula.kind,
            _normalized_latex(formula.latex),
            bbox_key,
        ]
    )


def _formula_sort_key(formula: FormulaBlock) -> tuple[int, float, int]:
    return _source_rank(formula.source), formula.confidence or 0.0, _math_density(formula.latex)


def _formula_priority(formula: FormulaBlock) -> tuple[int, float]:
    return _source_rank(formula.source), formula.confidence or 0.0


def _representative_formula_key(formula: FormulaBlock) -> tuple[int, int, float, int]:
    severe_penalty = sum(
        1
        for flag in formula.quality_flags
        if flag
        in {
            "contains_prose",
            "romanized_ocr_noise",
            "needs_review",
            "needs_formula_review",
            "raw_ocr_contains_prose",
            "raw_ocr_romanized_ocr_noise",
            "raw_ocr_unbalanced_braces",
            "raw_ocr_very_long_formula",
            "raw_ocr_incomplete_formula",
        }
    )
    mild_penalty = sum(
        1
        for flag in formula.quality_flags
        if flag
        not in {
            "repaired_latex",
            "definition_text_rescued",
            "formula_ocr_kept_fallback",
            "contains_prose",
            "romanized_ocr_noise",
            "needs_review",
            "needs_formula_review",
            "raw_ocr_contains_prose",
            "raw_ocr_romanized_ocr_noise",
            "raw_ocr_unbalanced_braces",
            "raw_ocr_very_long_formula",
            "raw_ocr_incomplete_formula",
        }
    )
    return (
        -severe_penalty,
        _source_rank(formula.source),
        -mild_penalty,
        formula.confidence or 0.0,
        _math_density(formula.latex),
    )


def _region_priority(region: FormulaRegion) -> tuple[int, float]:
    return _source_rank(region.source), region.confidence or 0.0


def _source_rank(source: str) -> int:
    if source == "tex_source":
        return 5
    if source == "pp_formula_net":
        return 4
    if source in {"text_pattern", "text_inline_pattern"}:
        return 3
    if source == "pp_structure_v3":
        return 2
    if source.endswith("_raw"):
        return 1
    return 0


def _normalized_latex(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def _formula_order_key(formula: FormulaBlock) -> tuple[int, float, float, int]:
    bbox = formula.bbox or (10_000.0, 10_000.0, 10_000.0, 10_000.0)
    kind_rank = 0 if formula.kind == "block" else 1
    return formula.page_number, bbox[1], bbox[0], kind_rank


def _math_density(latex: str) -> int:
    return sum(1 for char in latex if char in "=<>_^" or char.isdigit() or char == "\\")


def _latex_overlap(left: str, right: str) -> float:
    left_tokens = set(re.findall(r"[a-z]+|\d+|[=<>+\-*/_^]", left))
    right_tokens = set(re.findall(r"[a-z]+|\d+|[=<>+\-*/_^]", right))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))


def _dedupe_flags(flags) -> list[str]:
    result: list[str] = []
    for flag in flags:
        if flag and flag not in result:
            result.append(flag)
    return result


def _union_bbox(boxes: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _bbox_iou(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> float:
    lx0, ly0, lx1, ly1 = left
    rx0, ry0, rx1, ry1 = right
    ix0 = max(lx0, rx0)
    iy0 = max(ly0, ry0)
    ix1 = min(lx1, rx1)
    iy1 = min(ly1, ry1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    intersection = (ix1 - ix0) * (iy1 - iy0)
    left_area = max(1.0, (lx1 - lx0) * (ly1 - ly0))
    right_area = max(1.0, (rx1 - rx0) * (ry1 - ry0))
    return intersection / (left_area + right_area - intersection)


def _bbox_overlap_ratio(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> float:
    lx0, ly0, lx1, ly1 = left
    rx0, ry0, rx1, ry1 = right
    ix0 = max(lx0, rx0)
    iy0 = max(ly0, ry0)
    ix1 = min(lx1, rx1)
    iy1 = min(ly1, ry1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    intersection = (ix1 - ix0) * (iy1 - iy0)
    return intersection / max(1.0, min((lx1 - lx0) * (ly1 - ly0), (rx1 - rx0) * (ry1 - ry0)))


def _bbox_contains(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> bool:
    lx0, ly0, lx1, ly1 = left
    rx0, ry0, rx1, ry1 = right
    center_x = (rx0 + rx1) / 2
    center_y = (ry0 + ry1) / 2
    return lx0 <= center_x <= lx1 and ly0 <= center_y <= ly1
