from __future__ import annotations

import re

from backend.formula_graph.export.graph_ready_export import extract_formula_symbols
from backend.formula_graph.models import Entity, FormulaBlock, Relation, TextBlock


VARIABLE_RE = re.compile(
    r"(?:where|где|let|пусть)\s+([A-Za-zА-Яа-яα-ωΑ-Ω][\wα-ωΑ-Ω]*)\s*(?:is|are|=|-|—|–|означает|является)?\s*([^.;,\n]{2,120})",
    re.IGNORECASE,
)
LATEX_SYMBOL_RE = re.compile(r"\\?[A-Za-zα-ωΑ-Ω](?:_\{?[\w]+\}?|\^\{?[\w]+\}?)*")


def extract_entities(text_blocks: list[TextBlock], formulas: list[FormulaBlock]) -> tuple[list[Entity], list[Relation]]:
    entities: list[Entity] = []
    relations: list[Relation] = []
    seen: set[tuple[str, str]] = set()

    for block in text_blocks:
        for match in VARIABLE_RE.finditer(block.text):
            label = match.group(1).strip()
            definition = match.group(2).strip()
            key = ("variable", label)
            if key in seen:
                continue
            seen.add(key)
            entity = Entity(
                id=f"e_{len(entities) + 1}",
                label=label,
                kind="variable",
                source_block_id=block.id,
                confidence=0.72,
            )
            entities.append(entity)
            definition_entity = Entity(
                id=f"e_{len(entities) + 1}",
                label=definition,
                kind="concept",
                source_block_id=block.id,
                confidence=0.62,
            )
            entities.append(definition_entity)
            relations.append(
                Relation(
                    id=f"r_{len(relations) + 1}",
                    source_id=entity.id,
                    target_id=definition_entity.id,
                    kind="defined_as",
                    evidence=match.group(0),
                    confidence=0.7,
                )
            )

    for formula in formulas:
        latex = formula.normalized_latex or formula.cleaned_latex or formula.latex
        formula_symbols = sorted(set(extract_formula_symbols(latex)))
        for symbol in formula_symbols:
            if len(symbol) > 24:
                continue
            key = ("variable", symbol)
            entity = next((item for item in entities if item.kind == "variable" and item.label == symbol), None)
            if entity is None:
                entity = Entity(
                    id=f"e_{len(entities) + 1}",
                    label=symbol,
                    kind="variable",
                    source_formula_id=formula.id,
                    confidence=0.45,
                )
                entities.append(entity)
            relations.append(
                Relation(
                    id=f"r_{len(relations) + 1}",
                    source_id=formula.id,
                    target_id=entity.id,
                    kind="contains_variable",
                    evidence=formula.latex,
                    confidence=0.6,
                )
            )
    return entities, relations


def bind_formulas_to_context(formulas: list[FormulaBlock], text_blocks: list[TextBlock]) -> list[Relation]:
    relations: list[Relation] = []
    blocks_by_id = {block.id: block for block in text_blocks}
    blocks_by_page: dict[int, list[TextBlock]] = {}
    for block in text_blocks:
        if block.text.strip() and block.source != "formula_token":
            blocks_by_page.setdefault(block.page_number, []).append(block)

    for formula in formulas:
        context_block = blocks_by_id.get(formula.context_block_id or "")
        confidence = 0.78 if context_block else 0.0
        if context_block is None:
            context_block, confidence = _nearest_context_block(formula, blocks_by_page.get(formula.page_number, []))
            if context_block is not None:
                formula.context_block_id = context_block.id

        if context_block is not None:
            relations.append(
                Relation(
                    id=f"ctx_{formula.id}",
                    source_id=formula.id,
                    target_id=context_block.id,
                    kind="has_context",
                    evidence=context_block.text[:300],
                    confidence=confidence,
                )
            )
    return relations


def _nearest_context_block(formula: FormulaBlock, blocks: list[TextBlock]) -> tuple[TextBlock | None, float]:
    candidates = [block for block in blocks if block.id != formula.id]
    if not candidates:
        return None, 0.0
    if formula.bbox is None:
        return candidates[0], 0.45

    scored = []
    for block in candidates:
        if block.bbox is None:
            scored.append((10_000.0, block))
            continue
        scored.append((_context_distance(formula.bbox, block.bbox), block))
    scored.sort(key=lambda item: item[0])
    distance, block = scored[0]
    confidence = 0.64 if distance < 400 else 0.52
    return block, confidence


def _context_distance(formula_bbox, block_bbox) -> float:
    fx0, fy0, fx1, fy1 = formula_bbox
    bx0, by0, bx1, by1 = block_bbox
    formula_center_x = (fx0 + fx1) / 2
    block_center_x = (bx0 + bx1) / 2

    if by1 <= fy0:
        vertical_gap = fy0 - by1
        position_penalty = 0.0
    elif by0 >= fy1:
        vertical_gap = by0 - fy1
        position_penalty = 120.0
    else:
        vertical_gap = abs(((fy0 + fy1) / 2) - ((by0 + by1) / 2))
        position_penalty = 40.0

    horizontal_gap = abs(formula_center_x - block_center_x) * 0.12
    return vertical_gap + horizontal_gap + position_penalty
