from __future__ import annotations

import re
from collections import Counter, defaultdict

from backend.formula_graph.models import Entity, FormulaBlock, GraphEdge, GraphNode, KnowledgeGraph, Relation, TextBlock


LATEX_COMMAND_SYMBOLS = {
    "alpha",
    "beta",
    "gamma",
    "delta",
    "epsilon",
    "varepsilon",
    "zeta",
    "eta",
    "theta",
    "vartheta",
    "iota",
    "kappa",
    "lambda",
    "mu",
    "nu",
    "xi",
    "pi",
    "rho",
    "sigma",
    "tau",
    "upsilon",
    "phi",
    "varphi",
    "chi",
    "psi",
    "omega",
    "Gamma",
    "Delta",
    "Theta",
    "Lambda",
    "Xi",
    "Pi",
    "Sigma",
    "Phi",
    "Psi",
    "Omega",
}
IGNORED_COMMANDS = {
    "begin",
    "end",
    "left",
    "right",
    "frac",
    "sum",
    "int",
    "lim",
    "max",
    "min",
    "text",
    "mathrm",
    "mathbf",
    "mathbb",
    "mathcal",
    "operatorname",
    "quad",
    "qquad",
    "cdot",
    "times",
    "partial",
    "nabla",
}


def build_metagraph(
    document_id: str,
    text_blocks: list[TextBlock],
    formulas: list[FormulaBlock],
    entities: list[Entity],
    relations: list[Relation],
) -> KnowledgeGraph:
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    edge_index = 1

    def add_edge(source: str, target: str, label: str, **payload) -> None:
        nonlocal edge_index
        edges.append(GraphEdge(id=f"me_{edge_index}", source=source, target=target, label=label, payload=payload))
        edge_index += 1

    nodes.append(
        GraphNode(
            id="meta_document",
            label=document_id,
            kind="meta_document",
            payload={
                "document_id": document_id,
                "text_blocks": len(text_blocks),
                "formulas": len(formulas),
                "entities": len(entities),
                "relations": len(relations),
            },
        )
    )

    sections = _collect_sections(text_blocks)
    if not sections:
        sections = [("sec_document", "Document", [])]
    for section_id, title, evidence_blocks in sections:
        section_node = f"meta_{section_id}"
        section_formulas = [formula for formula in formulas if (formula.section_id or "sec_document") == section_id]
        if section_id == "sec_document":
            section_formulas = [formula for formula in formulas if not formula.section_id]
        section_text = [block for block in text_blocks if (block.section_id or "sec_document") == section_id]
        variables = _variables_for_formulas(section_formulas)

        nodes.append(
            GraphNode(
                id=section_node,
                label=title,
                kind="meta_section",
                payload={
                    "section_id": section_id,
                    "evidence_blocks": [block.id for block in evidence_blocks],
                    "text_blocks": len(section_text),
                    "formulas": len(section_formulas),
                    "variables": len(variables),
                },
            )
        )
        add_edge("meta_document", section_node, "contains_section", confidence=0.99)

        eq_group_id = f"meta_eqgrp_{section_id}"
        nodes.append(
            GraphNode(
                id=eq_group_id,
                label=f"Equations: {title}",
                kind="meta_equation_group",
                payload={
                    "section_id": section_id,
                    "formula_ids": [formula.id for formula in section_formulas],
                    "formula_count": len(section_formulas),
                    "block_formulas": sum(1 for formula in section_formulas if formula.kind == "block"),
                    "inline_formulas": sum(1 for formula in section_formulas if formula.kind == "inline"),
                },
            )
        )
        add_edge(section_node, eq_group_id, "contains_equation_group", confidence=0.95)

        var_set_id = f"meta_varset_{section_id}"
        nodes.append(
            GraphNode(
                id=var_set_id,
                label=f"Variables: {title}",
                kind="meta_variable_set",
                payload={"section_id": section_id, "variables": sorted(variables)},
            )
        )
        add_edge(eq_group_id, var_set_id, "uses_variable_set", confidence=0.82)

        for formula in section_formulas[:80]:
            formula_node = f"meta_formula_{formula.id}"
            nodes.append(
                GraphNode(
                    id=formula_node,
                    label=_short_formula(formula.latex),
                    kind=f"meta_formula_{formula.kind}",
                    payload={
                        "formula_id": formula.id,
                        "source": formula.source,
                        "confidence": formula.confidence,
                        "quality_flags": formula.quality_flags,
                        "token": formula.token,
                        "label": formula.label,
                    },
                )
            )
            add_edge(eq_group_id, formula_node, "groups_formula", confidence=formula.confidence or 0.8)
            for symbol in sorted(_extract_formula_variables(formula.latex))[:24]:
                variable_node = f"meta_var_{_safe_id(symbol)}"
                if not any(node.id == variable_node for node in nodes):
                    nodes.append(GraphNode(id=variable_node, label=symbol, kind="meta_variable", payload={"symbol": symbol}))
                add_edge(formula_node, variable_node, "uses_variable", confidence=0.72)

    for source, count in Counter(formula.source for formula in formulas).items():
        source_id = f"meta_source_{_safe_id(source)}"
        nodes.append(
            GraphNode(
                id=source_id,
                label=source,
                kind="meta_source_reliability",
                payload={
                    "source": source,
                    "formula_count": count,
                    "confidence": _source_confidence(source),
                },
            )
        )
        add_edge("meta_document", source_id, "has_formula_source", confidence=_source_confidence(source))

    issue_counts: dict[str, list[str]] = defaultdict(list)
    for formula in formulas:
        for flag in formula.quality_flags:
            if flag.startswith("tex_file:") or flag == "from_tex_source":
                continue
            issue_counts[flag].append(formula.id)
    for flag, formula_ids in issue_counts.items():
        issue_id = f"meta_issue_{_safe_id(flag)}"
        nodes.append(
            GraphNode(
                id=issue_id,
                label=flag,
                kind="meta_quality_issue",
                payload={"flag": flag, "formula_ids": formula_ids, "count": len(formula_ids)},
            )
        )
        add_edge("meta_document", issue_id, "has_quality_issue", confidence=0.9)

    return KnowledgeGraph(nodes=_dedupe_nodes(nodes), edges=edges)


def _collect_sections(text_blocks: list[TextBlock]) -> list[tuple[str, str, list[TextBlock]]]:
    sections = []
    for block in text_blocks:
        if block.role == "section" and block.section_id:
            sections.append((block.section_id, block.text, [block]))
    return sections


def _variables_for_formulas(formulas: list[FormulaBlock]) -> set[str]:
    variables: set[str] = set()
    for formula in formulas:
        variables.update(_extract_formula_variables(formula.latex))
    return variables


def _extract_formula_variables(latex: str) -> set[str]:
    variables = set()
    for command in re.findall(r"\\([A-Za-z]+)", latex):
        if command in LATEX_COMMAND_SYMBOLS:
            variables.add("\\" + command)
        elif command not in IGNORED_COMMANDS and len(command) <= 16:
            variables.add(command)
    for symbol in re.findall(r"(?<!\\)\b[A-Za-z](?:_\{?[A-Za-z0-9]+\}?|\^\{?[A-Za-z0-9]+\}?)*", latex):
        variables.add(symbol)
    return {symbol for symbol in variables if len(symbol) <= 32}


def _source_confidence(source: str) -> float:
    if "tex" in source:
        return 0.99
    if "marker" in source:
        return 0.9
    if "pp_formula_net" in source:
        return 0.78
    if "pp_structure" in source:
        return 0.7
    return 0.55


def _safe_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip("\\"))
    return safe.strip("_") or "item"


def _short_formula(value: str, limit: int = 90) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1] + "..."


def _dedupe_nodes(nodes: list[GraphNode]) -> list[GraphNode]:
    seen: set[str] = set()
    result: list[GraphNode] = []
    for node in nodes:
        if node.id in seen:
            continue
        seen.add(node.id)
        result.append(node)
    return result
