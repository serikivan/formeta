from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from backend.formula_graph.export.graph_ready_export import GraphReadyDocument
from backend.formula_graph.graph.metagraph_model import Edge, MetaEdge, MetaVertex, Metagraph, Node
from backend.formula_graph.models import GraphEdge, GraphNode, KnowledgeGraph


def build_metagraph_from_graph_ready(doc: GraphReadyDocument) -> Metagraph:
    metagraph = Metagraph()
    paper_id = "paper_1"
    paper_mv = MetaVertex(
        id="paper_metavertex_1",
        type="paper_metavertex",
        label=doc.document_structure.title or doc.filename or doc.document_id,
        contains=[paper_id],
        entry_points=[paper_id],
        exit_points=[paper_id],
        attributes={
            "document_id": doc.document_id,
            "source_type": doc.source_type,
            "status": doc.status,
            "nesting_depth": 0,
        },
    )
    metagraph.add_metavertex(paper_mv)
    metagraph.add_node(
        Node(
            id=paper_id,
            type="paper",
            label=doc.document_structure.title or doc.filename or doc.document_id,
            attributes={"document_id": doc.document_id, "filename": doc.filename},
        )
    )
    metagraph.ensure_contains_edge(paper_mv.id, paper_id)

    section_mvs = _add_sections(metagraph, paper_mv, doc)
    block_mvs = _add_text_blocks(metagraph, paper_mv, section_mvs, doc)
    formula_mvs = _add_formulas(metagraph, paper_mv, section_mvs, block_mvs, doc)
    context_mvs = _add_contexts(metagraph, paper_mv, section_mvs, block_mvs, formula_mvs, doc)
    _add_variables(metagraph, formula_mvs, context_mvs, doc)
    _add_graph_ready_relations(metagraph, doc)
    _add_formula_dependencies(metagraph, doc)
    _add_extraction_evidence_edges(metagraph, formula_mvs, doc)
    _add_paragraph_formula_context_edges(metagraph, doc)
    _add_quality_and_source_metavertices(metagraph, paper_mv, doc)
    compute_node_masses(metagraph)
    metagraph.metrics = _basic_metagraph_metrics(metagraph)
    metagraph.provenance = {"document_id": doc.document_id, "source_type": doc.source_type, "evidence_count": _evidence_count(metagraph)}
    return metagraph


def metagraph_to_knowledge_graph(metagraph: Metagraph) -> KnowledgeGraph:
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    for metavertex in metagraph.metavertices.values():
        nodes.append(
            GraphNode(
                id=metavertex.id,
                label=metavertex.label,
                kind=metavertex.type,
                payload={
                    "metagraph_object": "metavertex",
                    "contains": metavertex.contains,
                    "entry_points": metavertex.entry_points,
                    "exit_points": metavertex.exit_points,
                    "attributes": metavertex.attributes,
                },
            )
        )
    for node in metagraph.nodes.values():
        nodes.append(GraphNode(id=node.id, label=node.label, kind=node.type, payload={"attributes": node.attributes}))
    for edge in metagraph.edges.values():
        edges.append(
            GraphEdge(
                id=edge.id,
                source=edge.source,
                target=edge.target,
                label=edge.type,
                payload={"directed": edge.directed, "attributes": edge.attributes},
            )
        )
    for metaedge in metagraph.metaedges.values():
        node_id = metaedge.id
        nodes.append(
            GraphNode(
                id=node_id,
                label=metaedge.type,
                kind="metaedge",
                payload={
                    "source_set": metaedge.source_set,
                    "target_set": metaedge.target_set,
                    "mediator_nodes": metaedge.mediator_nodes,
                    "mediator_metavertices": metaedge.mediator_metavertices,
                    "contains": metaedge.contains,
                    "attributes": metaedge.attributes,
                },
            )
        )
        for source in metaedge.source_set:
            if source in metagraph.nodes or source in metagraph.metavertices:
                edges.append(GraphEdge(id=f"{metaedge.id}:source:{source}", source=source, target=node_id, label="metaedge_source"))
        for target in metaedge.target_set:
            if target in metagraph.nodes or target in metagraph.metavertices:
                edges.append(GraphEdge(id=f"{metaedge.id}:target:{target}", source=node_id, target=target, label="metaedge_target"))
    return KnowledgeGraph(nodes=_dedupe_graph_nodes(nodes), edges=_dedupe_graph_edges(edges))


def save_metagraph(metagraph: Metagraph, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(metagraph.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def compute_node_masses(metagraph: Metagraph) -> None:
    degrees = Counter()
    for edge in metagraph.edges.values():
        degrees[edge.source] += 1
        degrees[edge.target] += 1
    for node in metagraph.nodes.values():
        base = 1.0 + degrees[node.id]
        if node.type == "formula":
            base += 1.5 * len(node.attributes.get("symbols", []))
            base += 2.0 * int(bool(node.attributes.get("context_id")))
        elif node.type == "symbol":
            base += 2.0 * len(node.attributes.get("formula_ids", []))
            base += 2.0 * int(bool(node.attributes.get("possible_definitions")))
        elif node.type in {"section", "paragraph", "context"}:
            base += 0.5 * len(str(node.label))
        node.attributes["mass"] = round(min(base, 80.0), 4)

    unresolved = set(metagraph.metavertices)
    while unresolved:
        progressed = False
        for mv_id in list(unresolved):
            metavertex = metagraph.metavertices[mv_id]
            masses: list[float] = []
            ready = True
            for child in metavertex.contains:
                if child in metagraph.nodes:
                    masses.append(float(metagraph.nodes[child].attributes.get("mass", 1.0)))
                elif child in metagraph.metavertices:
                    child_mass = metagraph.metavertices[child].attributes.get("mass")
                    if child_mass is None:
                        ready = False
                        break
                    masses.append(float(child_mass))
            if ready:
                metavertex.attributes["mass"] = round(sum(masses) or 1.0, 4)
                unresolved.remove(mv_id)
                progressed = True
        if not progressed:
            for mv_id in unresolved:
                metagraph.metavertices[mv_id].attributes.setdefault("mass", 1.0)
            break


def _add_sections(metagraph: Metagraph, paper_mv: MetaVertex, doc: GraphReadyDocument) -> dict[str, str]:
    result: dict[str, str] = {}
    sections = doc.document_structure.sections or []
    if not sections:
        section_id = "sec_document"
        sections = [
            type(
                "FallbackSection",
                (),
                {
                    "id": section_id,
                    "title": "Document",
                    "level": 1,
                    "order": 1,
                    "parent_id": None,
                    "text_block_ids": [block.id for block in doc.text_blocks],
                    "formula_tokens": [formula.token for formula in doc.formulas],
                },
            )()
        ]
    for section in sections:
        node_id = section.id
        mv_id = f"{section.id}_mv"
        metagraph.add_node(
            Node(
                id=node_id,
                type="section",
                label=section.title or section.id,
                attributes={
                    "level": section.level,
                    "order": section.order,
                    "parent_id": section.parent_id,
                    "text_block_ids": section.text_block_ids,
                    "formula_tokens": section.formula_tokens,
                },
            )
        )
        metagraph.add_metavertex(
            MetaVertex(
                id=mv_id,
                type="section_metavertex",
                label=section.title or section.id,
                contains=[node_id],
                entry_points=[node_id],
                exit_points=[node_id],
                attributes={"section_id": section.id, "level": section.level, "nesting_depth": 1},
            )
        )
        metagraph.ensure_contains_edge(mv_id, node_id)
        parent_mv = result.get(section.parent_id or "") or paper_mv.id
        _append_unique(metagraph.metavertices[parent_mv].contains, mv_id)
        metagraph.ensure_contains_edge(parent_mv, mv_id)
        result[section.id] = mv_id
    return result


def _add_text_blocks(
    metagraph: Metagraph,
    paper_mv: MetaVertex,
    section_mvs: dict[str, str],
    doc: GraphReadyDocument,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for block in doc.text_blocks:
        node = Node(
            id=block.id,
            type="paragraph" if block.type in {"paragraph", "unknown"} else block.type,
            label=_short(block.text_with_tokens or block.text, 120),
            attributes=block.model_dump(),
        )
        metagraph.add_node(node)
        mv_id = f"{block.id}_mv"
        metagraph.add_metavertex(
            MetaVertex(
                id=mv_id,
                type="paragraph_metavertex",
                label=block.id,
                contains=[block.id],
                entry_points=[block.id],
                exit_points=[block.id],
                attributes={"section_id": block.section_id, "order": block.order, "nesting_depth": 2},
            )
        )
        metagraph.ensure_contains_edge(mv_id, block.id)
        parent_mv = section_mvs.get(block.section_id or "") or paper_mv.id
        _append_unique(metagraph.metavertices[parent_mv].contains, mv_id)
        metagraph.ensure_contains_edge(parent_mv, mv_id)
        result[block.id] = mv_id
    return result


def _add_formulas(
    metagraph: Metagraph,
    paper_mv: MetaVertex,
    section_mvs: dict[str, str],
    block_mvs: dict[str, str],
    doc: GraphReadyDocument,
) -> dict[str, str]:
    result: dict[str, str] = {}
    token_to_blocks = _token_to_blocks(doc)
    for formula in doc.formulas:
        attrs = formula.model_dump()
        attrs["context_id"] = next((ctx.id for ctx in doc.formula_contexts if ctx.formula_id == formula.id), None)
        attrs["semantic_object"] = "formula_metavertex"
        metagraph.add_node(Node(id=formula.id, type="formula", label=formula.latex or formula.token, attributes=attrs))
        mv_id = f"{formula.id}_mv"
        metagraph.add_metavertex(
            MetaVertex(
                id=mv_id,
                type="formula_metavertex",
                label=formula.token,
                contains=[formula.id],
                entry_points=[formula.id],
                exit_points=[formula.id],
                attributes={
                    "formula_id": formula.id,
                    "token": formula.token,
                    "nesting_depth": 3,
                    "semantic_type": "formula_metavertex",
                    "inner_expression_object": "ast_like_expression_graph",
                    "outer_document_object": "document_formula_object",
                    "internal_roles": list(getattr(formula.meta_semantics, "internal_roles", []) or []),
                    "context_ids": list(getattr(formula.meta_semantics, "context_ids", []) or []),
                    "paragraph_ids": list(getattr(formula.meta_semantics, "paragraph_ids", []) or []),
                    "variable_ids": list(getattr(formula.meta_semantics, "variable_ids", []) or []),
                },
            )
        )
        metagraph.ensure_contains_edge(mv_id, formula.id)
        parent_mv = None
        for block_id in token_to_blocks.get(formula.token, []):
            parent_mv = block_mvs.get(block_id)
            if parent_mv:
                break
        parent_mv = parent_mv or section_mvs.get(formula.section_id or "") or paper_mv.id
        _append_unique(metagraph.metavertices[parent_mv].contains, mv_id)
        _append_unique(metagraph.metavertices[parent_mv].exit_points, mv_id)
        metagraph.ensure_contains_edge(parent_mv, mv_id)
        _attach_formula_fragments(metagraph, metagraph.metavertices[mv_id], formula.id, formula.normalized_latex or formula.latex)
        for operator_index, operator in enumerate(formula.operators, start=1):
            operator_id = f"{formula.id}:operator:{operator_index}:{_safe_id(operator)}"
            metagraph.add_node(Node(id=operator_id, type="operator", label=operator, attributes={"formula_id": formula.id}))
            _append_unique(metagraph.metavertices[mv_id].contains, operator_id)
            _append_unique(metagraph.metavertices[mv_id].exit_points, operator_id)
            metagraph.ensure_contains_edge(mv_id, operator_id)
            metagraph.add_edge(Edge(id=f"has_operator:{formula.id}->{operator_id}", source=formula.id, target=operator_id, type="has_operator"))
        result[formula.id] = mv_id
    return result


def _add_contexts(
    metagraph: Metagraph,
    paper_mv: MetaVertex,
    section_mvs: dict[str, str],
    block_mvs: dict[str, str],
    formula_mvs: dict[str, str],
    doc: GraphReadyDocument,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for context in doc.formula_contexts:
        metagraph.add_node(
            Node(
                id=context.id,
                type="context",
                label=_short(context.window_text, 120),
                attributes=context.model_dump(),
            )
        )
        mv_id = f"{context.id}_mv"
        contains = [context.id]
        definition_ids: list[str] = []
        for index, definition in enumerate(context.possible_definitions, start=1):
            definition_id = f"definition:{context.id}:{index}"
            definition_ids.append(definition_id)
            metagraph.add_node(
                Node(
                    id=definition_id,
                    type="definition",
                    label=definition.definition_text,
                    attributes={**definition.model_dump(), "context_id": context.id},
                )
            )
            contains.append(definition_id)
            metagraph.add_edge(
                Edge(
                    id=f"has_definition:{context.id}->{definition_id}",
                    source=context.id,
                    target=definition_id,
                    type="has_definition",
                    attributes={"symbol": definition.symbol, "confidence": definition.confidence},
                )
            )
        metagraph.add_metavertex(
            MetaVertex(
                id=mv_id,
                type="definition_context_metavertex",
                label=f"context_{context.formula_id}",
                contains=contains,
                entry_points=[context.id],
                exit_points=definition_ids or [context.id],
                attributes={
                    "formula_id": context.formula_id,
                    "section_id": context.section_id,
                    "nearest_text_block_ids": context.nearest_text_block_ids,
                    "definition_markers": context.definition_markers,
                    "nesting_depth": 3,
                },
            )
        )
        for child in contains:
            metagraph.ensure_contains_edge(mv_id, child)
        parent_mv = next((block_mvs[item] for item in context.nearest_text_block_ids if item in block_mvs), None)
        parent_mv = parent_mv or section_mvs.get(context.section_id or "") or paper_mv.id
        _append_unique(metagraph.metavertices[parent_mv].contains, mv_id)
        metagraph.ensure_contains_edge(parent_mv, mv_id)
        formula_mv = formula_mvs.get(context.formula_id)
        contains_edges = [f"has_context:{context.formula_id}->{context.id}"]
        metagraph.add_edge(Edge(id=contains_edges[0], source=context.formula_id, target=context.id, type="has_context"))
        if formula_mv:
            _append_unique(metagraph.metavertices[formula_mv].contains, mv_id)
            metagraph.ensure_contains_edge(formula_mv, mv_id)
        metagraph.add_metaedge(
            MetaEdge(
                id=f"meta:formula_context:{context.formula_id}:{context.id}",
                type="definition_context",
                source_set=[context.formula_id],
                target_set=[context.id, *definition_ids],
                mediator_nodes=[context.id],
                mediator_metavertices=[mv_id],
                contains=contains_edges,
                attributes={
                    "markers": context.definition_markers,
                    "mentioned_symbols": context.mentioned_symbols,
                    "evidence": [item.model_dump() for item in context.possible_definitions],
                    "scope": "paragraph" if context.nearest_text_block_ids else "document",
                    "confidence": max([item.confidence for item in context.possible_definitions] or [0.55]),
                },
            )
        )
        result[context.id] = mv_id
    return result


def _add_variables(
    metagraph: Metagraph,
    formula_mvs: dict[str, str],
    context_mvs: dict[str, str],
    doc: GraphReadyDocument,
) -> None:
    for variable in doc.variables:
        symbol_id = f"symbol:{_safe_id(variable.normalized_symbol)}"
        metagraph.add_node(
            Node(
                id=symbol_id,
                type="symbol",
                label=variable.normalized_symbol,
                attributes=variable.model_dump(),
            )
        )
        for formula_id in variable.formula_ids:
            formula_mv = formula_mvs.get(formula_id)
            if formula_mv:
                _append_unique(metagraph.metavertices[formula_mv].contains, symbol_id)
                _append_unique(metagraph.metavertices[formula_mv].exit_points, symbol_id)
                metagraph.ensure_contains_edge(formula_mv, symbol_id)
            metagraph.add_edge(
                Edge(
                    id=f"has_symbol:{formula_id}->{symbol_id}",
                    source=formula_id,
                    target=symbol_id,
                    type="has_symbol",
                    attributes={"variable_id": variable.id},
                )
            )
        for context_id in variable.context_ids:
            context_mv = context_mvs.get(context_id)
            if context_mv:
                _append_unique(metagraph.metavertices[context_mv].contains, symbol_id)
                _append_unique(metagraph.metavertices[context_mv].exit_points, symbol_id)
                metagraph.ensure_contains_edge(context_mv, symbol_id)
                metagraph.add_metaedge(
                    MetaEdge(
                        id=f"meta:notation_scope:{symbol_id}:{context_id}",
                        type="notation_scope",
                        source_set=[symbol_id],
                        target_set=[context_id, *variable.formula_ids],
                        mediator_metavertices=[context_mv],
                        attributes={
                            "scope_level": "section" if variable.section_ids else "paragraph",
                            "section_ids": variable.section_ids,
                            "evidence": variable.possible_definitions,
                            "confidence": 0.78 if variable.possible_definitions else 0.55,
                        },
                    )
                )


def _add_graph_ready_relations(metagraph: Metagraph, doc: GraphReadyDocument) -> None:
    variable_to_symbol = {variable.id: f"symbol:{_safe_id(variable.normalized_symbol)}" for variable in doc.variables}
    id_map = {**variable_to_symbol}
    object_ids = set(metagraph.nodes) | set(metagraph.metavertices)
    for relation in doc.relations:
        source = id_map.get(relation.source_id, relation.source_id)
        target = id_map.get(relation.target_id, relation.target_id)
        if source not in object_ids or target not in object_ids:
            continue
        edge_id = f"graph_ready:{relation.id}"
        metagraph.add_edge(
            Edge(
                id=edge_id,
                source=source,
                target=target,
                type=relation.type,
                attributes={"evidence": relation.evidence, "confidence": relation.confidence},
            )
        )


def _add_formula_dependencies(metagraph: Metagraph, doc: GraphReadyDocument) -> None:
    formulas = sorted(doc.formulas, key=lambda item: item.order)
    formula_symbols = {formula.id: set(formula.symbols) for formula in formulas}
    formula_sections = {formula.id: formula.section_id for formula in formulas}
    for index, formula in enumerate(formulas):
        current_symbols = formula_symbols.get(formula.id, set())
        if not current_symbols:
            continue
        targets: list[str] = []
        shared_by_target: dict[str, list[str]] = {}
        for previous in reversed(formulas[:index]):
            if formula_sections.get(previous.id) != formula_sections.get(formula.id):
                continue
            shared = sorted(current_symbols.intersection(formula_symbols.get(previous.id, set())))
            if not shared:
                continue
            targets.append(previous.id)
            shared_by_target[previous.id] = shared
            metagraph.add_edge(
                Edge(
                    id=f"depends_on:{formula.id}->{previous.id}",
                    source=formula.id,
                    target=previous.id,
                    type="depends_on",
                    attributes={"shared_symbols": shared},
                )
            )
            if len(targets) >= 3:
                break
        if targets:
            metagraph.add_metaedge(
                MetaEdge(
                    id=f"meta:formula_dependency:{formula.id}",
                    type="formula_dependency",
                    source_set=[formula.id],
                    target_set=targets,
                    mediator_nodes=[f"symbol:{_safe_id(symbol)}" for values in shared_by_target.values() for symbol in values],
                    contains=[f"depends_on:{formula.id}->{target}" for target in targets],
                    attributes={
                        "section_id": formula.section_id,
                        "shared_symbols_by_target": shared_by_target,
                        "dependency_type": "shared_variable",
                        "confidence": 0.62,
                    },
                )
            )


def _add_extraction_evidence_edges(metagraph: Metagraph, formula_mvs: dict[str, str], doc: GraphReadyDocument) -> None:
    for formula in doc.formulas:
        source_id = f"source:{_safe_id(formula.source)}"
        if source_id not in metagraph.nodes:
            metagraph.add_node(Node(id=source_id, type="source", label=formula.source, attributes={"formula_count": 0}))
        issue_ids: list[str] = []
        for flag in formula.quality_flags:
            issue_id = f"issue:{_safe_id(flag)}"
            issue_ids.append(issue_id)
            if issue_id not in metagraph.nodes:
                metagraph.add_node(Node(id=issue_id, type="quality_issue", label=flag, attributes={"formula_ids": [], "count": 0}))
        edge_id = f"extracted_from:{formula.id}->{source_id}"
        metagraph.add_edge(
            Edge(
                id=edge_id,
                source=formula.id,
                target=source_id,
                type="extracted_from",
                attributes={"confidence": formula.confidence, "quality_flags": formula.quality_flags},
            )
        )
        metagraph.add_metaedge(
            MetaEdge(
                id=f"meta:extraction_evidence:{formula.id}",
                type="extraction_evidence",
                source_set=[formula.id],
                target_set=[source_id, *issue_ids],
                mediator_metavertices=[formula_mvs.get(formula.id, "")],
                contains=[edge_id],
                attributes={
                    "source": formula.source,
                    "confidence": formula.confidence,
                    "quality_flags": formula.quality_flags,
                    "evidence": [{"source": formula.source, "token": formula.token, "confidence": None}],
                },
            )
        )


def _add_paragraph_formula_context_edges(metagraph: Metagraph, doc: GraphReadyDocument) -> None:
    context_by_formula = {ctx.formula_id: ctx for ctx in doc.formula_contexts}
    context_by_id = {ctx.id: ctx for ctx in doc.formula_contexts}
    for paragraph in getattr(doc, "paragraphs", []):
        if not paragraph.formula_ids:
            continue
        context_ids = [context_by_formula[formula_id].id for formula_id in paragraph.formula_ids if formula_id in context_by_formula]
        definition_ids = [
            f"definition:{context_id}:{index}"
            for context_id in context_ids
            for index, _definition in enumerate(context_by_id.get(context_id).possible_definitions if context_id in context_by_id else [], start=1)
        ]
        metagraph.add_metaedge(
            MetaEdge(
                id=f"meta:paragraph_formula_context:{paragraph.id}",
                type="paragraph_formula_context",
                source_set=[paragraph.id],
                target_set=[*paragraph.formula_ids, *context_ids, *definition_ids],
                mediator_nodes=context_ids,
                attributes={
                    "formula_tokens": paragraph.formula_tokens,
                    "sentence_ids": paragraph.sentence_ids,
                    "evidence": paragraph.text[:500],
                    "confidence": 0.7 if context_ids else 0.5,
                },
            )
        )


def _add_quality_and_source_metavertices(metagraph: Metagraph, paper_mv: MetaVertex, doc: GraphReadyDocument) -> None:
    for source, count in Counter(formula.source for formula in doc.formulas).items():
        source_id = f"source:{_safe_id(source)}"
        metagraph.add_node(Node(id=source_id, type="source", label=source, attributes={"formula_count": count}))
        _append_unique(paper_mv.contains, source_id)
        metagraph.ensure_contains_edge(paper_mv.id, source_id)
    quality_flags: dict[str, list[str]] = {}
    for formula in doc.formulas:
        for flag in formula.quality_flags:
            quality_flags.setdefault(flag, []).append(formula.id)
    for flag, formula_ids in quality_flags.items():
        issue_id = f"issue:{_safe_id(flag)}"
        metagraph.add_node(Node(id=issue_id, type="quality_issue", label=flag, attributes={"formula_ids": formula_ids, "count": len(formula_ids)}))
        _append_unique(paper_mv.contains, issue_id)
        metagraph.ensure_contains_edge(paper_mv.id, issue_id)


def _attach_formula_fragments(metagraph: Metagraph, formula_mv: MetaVertex, formula_id: str, latex: str) -> None:
    latex = " ".join((latex or "").split())
    if not latex:
        return

    def make_fragment(value: str, role: str, index: int, parent_id: str | None = None) -> str:
        fragment_id = f"{formula_id}:fragment:{index}:{role}"
        metagraph.add_node(Node(id=fragment_id, type="subexpression", label=value, attributes={"formula_id": formula_id, "ast_role": role}))
        _append_unique(formula_mv.contains, fragment_id)
        _append_unique(formula_mv.exit_points, fragment_id)
        metagraph.ensure_contains_edge(formula_mv.id, fragment_id)
        if parent_id:
            metagraph.add_edge(Edge(id=f"ast_contains:{parent_id}->{fragment_id}", source=parent_id, target=fragment_id, type="ast_contains"))
        return fragment_id

    root_id = make_fragment(latex, "root", 1)
    metagraph.add_edge(Edge(id=f"ast_root:{formula_id}->{root_id}", source=formula_id, target=root_id, type="has_subexpression"))
    parts = _split_top_level(latex, "=")
    if len(parts) == 2:
        lhs_id = make_fragment(parts[0], "lhs", 2, root_id)
        rhs_id = make_fragment(parts[1], "rhs", 3, root_id)
        metagraph.add_edge(Edge(id=f"ast_lhs:{root_id}->{lhs_id}", source=root_id, target=lhs_id, type="ast_lhs"))
        metagraph.add_edge(Edge(id=f"ast_rhs:{root_id}->{rhs_id}", source=root_id, target=rhs_id, type="ast_rhs"))


def _split_top_level(text: str, operator: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for char in text:
        if char in "({[":
            depth += 1
        elif char in ")}]":
            depth = max(0, depth - 1)
        if char == operator and depth == 0:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
            continue
        current.append(char)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def _token_to_blocks(doc: GraphReadyDocument) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for block in doc.text_blocks:
        for token in block.formula_tokens:
            result.setdefault(token, []).append(block.id)
    return result


def _basic_metagraph_metrics(metagraph: Metagraph) -> dict[str, int | float | dict[str, int]]:
    node_types = Counter(node.type for node in metagraph.nodes.values())
    edge_types = Counter(edge.type for edge in metagraph.edges.values())
    metaedge_types = Counter(edge.type for edge in metagraph.metaedges.values())
    return {
        "node_count": len(metagraph.nodes),
        "edge_count": len(metagraph.edges),
        "metavertex_count": len(metagraph.metavertices),
        "metaedge_count": len(metagraph.metaedges),
        "formula_count": node_types.get("formula", 0),
        "variable_count": node_types.get("symbol", 0),
        "paragraph_count": node_types.get("paragraph", 0),
        "definition_count": node_types.get("definition", 0),
        "node_count_by_type": dict(sorted(node_types.items())),
        "edge_count_by_type": dict(sorted(edge_types.items())),
        "metaedge_count_by_type": dict(sorted(metaedge_types.items())),
    }


def _evidence_count(metagraph: Metagraph) -> int:
    count = 0
    for metaedge in metagraph.metaedges.values():
        evidence = metaedge.attributes.get("evidence")
        if isinstance(evidence, list):
            count += len(evidence)
        elif evidence:
            count += 1
    return count


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _safe_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", str(value).strip("\\"))
    return safe.strip("_") or "item"


def _short(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _dedupe_graph_nodes(nodes: list[GraphNode]) -> list[GraphNode]:
    seen: set[str] = set()
    result: list[GraphNode] = []
    for node in nodes:
        if node.id in seen:
            continue
        seen.add(node.id)
        result.append(node)
    return result


def _dedupe_graph_edges(edges: list[GraphEdge]) -> list[GraphEdge]:
    seen: set[str] = set()
    result: list[GraphEdge] = []
    for edge in edges:
        if edge.id in seen:
            continue
        seen.add(edge.id)
        result.append(edge)
    return result
