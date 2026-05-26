from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path
from typing import Any


SEMANTIC_VISUALIZATION_MODES = {
    "graph_view",
    "metagraph_view",
    "formula_context_view",
    "variable_neighborhood_view",
    "extraction_evidence_view",
    "document_structure_view",
    "document_structure",
    "formula_semantic",
    "metagraph_overview",
    "metagraph_fragments",
}


def export_semantic_visualization(
    graph_input: dict[str, Any],
    metagraph: dict[str, Any],
    *,
    mode: str = "metagraph_overview",
    limit: int = 220,
    variable_filter: str | None = None,
    relation_filter: str | None = None,
) -> dict[str, Any]:
    mode = mode if mode in SEMANTIC_VISUALIZATION_MODES else "metagraph_overview"
    mode = {
        "graph_view": "formula_semantic",
        "metagraph_view": "metagraph_overview",
        "formula_context_view": "metagraph_fragments",
        "variable_neighborhood_view": "formula_semantic",
        "extraction_evidence_view": "metagraph_fragments",
        "document_structure_view": "document_structure",
    }.get(mode, mode)
    if mode in {"metagraph_overview", "metagraph_fragments"}:
        nodes, edges = _metagraph_elements(metagraph, variable_filter=variable_filter, relation_filter=relation_filter, limit=limit)
    elif mode == "formula_semantic":
        nodes, edges = _formula_semantic_elements(metagraph, limit=limit)
    else:
        nodes, edges = _graph_elements(graph_input, allowed={"document", "page", "paragraph", "formula"}, limit=limit)
    elements = [{"data": node} for node in nodes] + [{"data": edge} for edge in edges]
    return {
        "mode": mode,
        "elements": elements,
        "stats": {
            "original_node_count": len(metagraph.get("nodes", [])) + len(metagraph.get("meta_nodes", [])),
            "original_edge_count": len(metagraph.get("edges", [])) + len(metagraph.get("meta_edges", [])),
            "node_count": len(nodes),
            "edge_count": len(edges),
            "total_element_count": len(elements),
            "truncated": len(nodes) >= limit,
            "node_types": dict(Counter(node.get("type") for node in nodes)),
        },
    }


def generate_graph_view(
    graph_input: dict[str, Any],
    output_html: Path,
    include_pages: bool = True,
    include_paragraphs: bool = True,
    include_contexts: bool = True,
    include_variables: bool = True,
) -> None:
    allowed = {"document", "formula", "term"}
    if include_pages:
        allowed.add("page")
    if include_paragraphs:
        allowed.add("paragraph")
    if include_contexts:
        allowed.add("context")
    if include_variables:
        allowed.add("variable")
    nodes, edges = _graph_elements(graph_input, allowed=allowed, limit=450)
    _write_html(output_html, "Graph View", nodes, edges)


def generate_formula_graph_view(graph_input: dict[str, Any], output_html: Path) -> None:
    nodes, edges = _graph_elements(graph_input, allowed={"formula", "variable", "context", "term"}, limit=450)
    _write_html(output_html, "Formula Graph View", nodes, edges)


def generate_metagraph_view(
    metagraph: dict[str, Any],
    output_html: Path,
    relation_filter: str | None = None,
    variable_filter: str | None = None,
) -> None:
    nodes, edges = _metagraph_elements(metagraph, variable_filter=variable_filter, relation_filter=relation_filter, limit=450)
    _write_html(output_html, "Metagraph View", nodes, edges)


def generate_variable_metagraph_view(
    variable_name: str,
    metagraph: dict[str, Any],
    variable_index: dict[str, Any],
    output_html: Path,
) -> None:
    generate_metagraph_view(metagraph, output_html, variable_filter=variable_name)


def generate_variable_focus_view(
    variable_name: str,
    graph_input: dict[str, Any],
    metagraph: dict[str, Any],
    variable_index: dict[str, Any],
    output_html: Path,
) -> None:
    normalized = _normalize_variable_label(variable_name)
    entry = variable_index.get(normalized, {})
    ids = set(entry.get("formulas", [])) | set(entry.get("contexts", [])) | {entry.get("variable_node")}
    meta_ids = set(entry.get("meta_nodes", []))
    for meta_edge in metagraph.get("meta_edges", []):
        if meta_edge.get("variable") == normalized and (meta_edge.get("source") in meta_ids or meta_edge.get("target") in meta_ids):
            meta_ids.add(meta_edge.get("source"))
            meta_ids.add(meta_edge.get("target"))
    nodes = [_display_node(node) for node in graph_input.get("nodes", []) if node.get("id") in ids]
    nodes.extend(_display_meta_node(node) for node in metagraph.get("meta_nodes", []) if node.get("id") in meta_ids)
    visible = {node["id"] for node in nodes}
    edges = [
        _display_edge(edge)
        for edge in graph_input.get("edges", [])
        if edge.get("source") in visible and edge.get("target") in visible
    ]
    edges.extend(
        _display_meta_edge(edge)
        for edge in metagraph.get("meta_edges", [])
        if edge.get("source") in visible and edge.get("target") in visible
        and edge.get("relation") in {"shared_variable", "definition_usage", "possible_semantic_dependency", "shares_variable", "definition_to_usage"}
    )
    _write_html(output_html, f"Variable Focus: {normalized}", nodes, edges)


def generate_demo_dashboard(metadata: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    files = metadata.get("generated_files", [])
    links = "\n".join(f'<li><a href="{html.escape(str(name))}">{html.escape(str(name))}</a></li>' for name in files)
    stats = "\n".join(
        f"<li>{html.escape(str(key))}: {html.escape(str(value))}</li>"
        for key, value in metadata.items()
        if key != "generated_files" and not isinstance(value, (dict, list))
    )
    (output_dir / "demo_dashboard.html").write_text(
        f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <title>Metagraph Demo Dashboard</title>
  <style>
    body {{ margin: 0; font-family: Arial, sans-serif; background: #f7f3ea; color: #172033; }}
    main {{ max-width: 980px; margin: 0 auto; padding: 32px; }}
    section {{ margin: 24px 0; }}
    a {{ color: #1d4ed8; }}
  </style>
</head>
<body>
  <main>
    <h1>Metagraph Demo Dashboard</h1>
    <section><h2>Statistics</h2><ul>{stats}</ul></section>
    <section><h2>Visualizations</h2><ul>{links}</ul></section>
  </main>
</body>
</html>
""",
        encoding="utf-8",
    )


def _graph_elements(graph_input: dict[str, Any], allowed: set[str], limit: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = [
        _display_node(node)
        for node in graph_input.get("nodes", [])
        if node.get("type") in allowed
    ][:limit]
    node_ids = {node["id"] for node in nodes}
    edges = [
        _display_edge(edge)
        for edge in graph_input.get("edges", [])
        if edge.get("source") in node_ids and edge.get("target") in node_ids
    ][: limit * 2]
    return nodes, edges


def _formula_semantic_elements(metagraph: dict[str, Any], limit: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    allowed = {"formula", "variable", "context", "term", "paragraph"}
    return _graph_elements({"nodes": metagraph.get("nodes", []), "edges": metagraph.get("edges", [])}, allowed=allowed, limit=limit)


def _metagraph_elements(
    metagraph: dict[str, Any],
    *,
    variable_filter: str | None,
    relation_filter: str | None,
    limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    variable_filter = _normalize_variable_label(variable_filter)
    meta_nodes = metagraph.get("meta_nodes", [])
    meta_edges = metagraph.get("meta_edges", [])
    if variable_filter:
        related = {
            node["id"]
            for node in meta_nodes
            if variable_filter in {_normalize_variable_label(item) for item in node.get("variable_names", [])}
        }
        for edge in meta_edges:
            if edge.get("variable") == variable_filter and (edge.get("source") in related or edge.get("target") in related):
                related.add(edge.get("source"))
                related.add(edge.get("target"))
        meta_nodes = [node for node in meta_nodes if node.get("id") in related]
    if relation_filter:
        meta_edges = [edge for edge in meta_edges if edge.get("relation") == relation_filter]
    node_ids = {node.get("id") for node in meta_nodes}
    meta_edges = [edge for edge in meta_edges if edge.get("source") in node_ids and edge.get("target") in node_ids]
    nodes = [_display_meta_node(node) for node in meta_nodes[:limit]]
    visible = {node["id"] for node in nodes}
    edges = [_display_meta_edge(edge) for edge in meta_edges if edge.get("source") in visible and edge.get("target") in visible][: limit * 2]
    return nodes, edges


def _display_node(node: dict[str, Any]) -> dict[str, Any]:
    node_type = node.get("type", "unknown")
    label = node.get("id", "")
    if node_type == "variable":
        label = node.get("value", label)
    elif node_type == "document":
        label = "Document"
    elif node_type == "page":
        label = f"Page {node.get('page', '?')}"
    data = {
        "id": node.get("id"),
        "label": label,
        "type": node_type,
        "attributes": node,
        "text": node.get("value") or node.get("sentence") or node.get("latex"),
    }
    if node_type == "formula":
        data["latex"] = node.get("latex", "")
    return data


def _display_meta_node(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": node.get("id"),
        "label": node.get("id"),
        "type": "meta_node",
        "attributes": node,
        "text": node.get("sentence", ""),
        "latex": node.get("latex", ""),
    }


def _display_edge(edge: dict[str, Any]) -> dict[str, Any]:
    relation = edge.get("relation", "")
    suffix = f"({edge.get('variable')})" if edge.get("variable") else ""
    return {
        "id": f"{edge.get('source')}->{edge.get('target')}:{relation}:{edge.get('variable', '')}",
        "source": edge.get("source"),
        "target": edge.get("target"),
        "label": f"{relation}{suffix}",
        "type": relation,
        "attributes": edge,
    }


def _display_meta_edge(edge: dict[str, Any]) -> dict[str, Any]:
    return _display_edge(edge)


def _write_html(output_html: Path, title: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    output_html.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False)
    escaped_title = html.escape(title)
    description = html.escape(_view_description(title))
    template = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <title>__TITLE__</title>
  <style>
    body {{ margin: 0; font-family: Georgia, 'Times New Roman', serif; background: #f7f3ea; color: #172033; }}
    header {{ padding: 16px 24px; border-bottom: 1px solid #d9cdb9; background: #fffaf0; display: grid; gap: 8px; }}
    header p {{ margin: 0; max-width: 920px; color: #475569; }}
    .controls {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: end; font-family: Arial, sans-serif; }}
    .controls label {{ display: grid; gap: 4px; font-size: 12px; color: #475569; }}
    .controls input, .controls select {{ min-width: 140px; padding: 7px 9px; border: 1px solid #cbd5e1; border-radius: 8px; background: white; }}
    .controls button {{ padding: 8px 12px; border: 1px solid #0f172a; border-radius: 8px; background: #0f172a; color: white; cursor: pointer; }}
    .legend {{ display: flex; flex-wrap: wrap; gap: 8px; font-family: Arial, sans-serif; font-size: 12px; }}
    .legend span {{ display: inline-flex; align-items: center; gap: 5px; padding: 4px 8px; border: 1px solid #e2e8f0; border-radius: 999px; background: white; }}
    .swatch {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
    #canvas {{ width: 100vw; height: calc(100vh - 156px); min-height: 520px; }}
    .node {{ cursor: pointer; }}
    .edge {{ stroke: #90a0b8; stroke-width: 1.4; opacity: .8; }}
    .label {{ font: 12px sans-serif; fill: #172033; text-anchor: middle; pointer-events: none; }}
    #tip {{ position: fixed; right: 16px; top: 176px; width: 360px; max-height: 68vh; overflow: auto; background: white; border: 1px solid #d5dceb; border-radius: 12px; padding: 14px; box-shadow: 0 14px 40px #0002; white-space: pre-wrap; font-family: Consolas, monospace; font-size: 12px; }}
  </style>
</head>
<body>
  <header>
    <strong>__TITLE__</strong><span id="stats"></span>
    <p>__DESCRIPTION__</p>
    <div class="controls">
      <label>Node type <select id="nodeTypeFilter"><option value="">all</option></select></label>
      <label>Edge type <select id="edgeTypeFilter"><option value="">all</option></select></label>
      <label>Variable/text <input id="textFilter" placeholder="m, lambda, context..." /></label>
      <label>Node limit <input id="limitFilter" type="number" min="20" max="900" value="450" /></label>
      <button id="resetFilters" type="button">Reset</button>
    </div>
    <div id="legend" class="legend"></div>
  </header>
  <svg id="canvas"></svg>
  <aside id="tip">Click a node to inspect it.</aside>
  <script>
    const payload = __PAYLOAD__;
    const svg = document.querySelector('#canvas');
    const tip = document.querySelector('#tip');
    const stats = document.querySelector('#stats');
    const nodeTypeFilter = document.querySelector('#nodeTypeFilter');
    const edgeTypeFilter = document.querySelector('#edgeTypeFilter');
    const textFilter = document.querySelector('#textFilter');
    const limitFilter = document.querySelector('#limitFilter');
    const colors = { document:'#111827', page:'#64748b', paragraph:'#f59e0b', formula:'#2563eb', variable:'#16a34a', context:'#9333ea', term:'#dc2626', meta_node:'#0f172a' };
    const nodeTypes = [...new Set(payload.nodes.map(node => node.type).filter(Boolean))].sort();
    const edgeTypes = [...new Set(payload.edges.map(edge => edge.type).filter(Boolean))].sort();
    for (const type of nodeTypes) nodeTypeFilter.append(new Option(type, type));
    for (const type of edgeTypes) edgeTypeFilter.append(new Option(type, type));
    document.querySelector('#legend').innerHTML = nodeTypes.map(type => `<span><i class="swatch" style="background:${colors[type] || '#64748b'}"></i>${type}</span>`).join('');
    document.querySelector('#resetFilters').addEventListener('click', () => {
      nodeTypeFilter.value = '';
      edgeTypeFilter.value = '';
      textFilter.value = '';
      limitFilter.value = '450';
      render();
    });
    [nodeTypeFilter, edgeTypeFilter, textFilter, limitFilter].forEach(control => control.addEventListener('input', render));

    function matchesText(node, needle) {
      if (!needle) return true;
      const attrs = node.attributes || {};
      const text = `${node.id || ''} ${node.label || ''} ${node.text || ''} ${node.latex || ''} ${JSON.stringify(attrs)}`.toLowerCase();
      return text.includes(needle);
    }

    function render() {
      svg.innerHTML = '';
      const selectedNodeType = nodeTypeFilter.value;
      const selectedEdgeType = edgeTypeFilter.value;
      const needle = textFilter.value.trim().toLowerCase();
      const limit = Math.max(20, Math.min(Number(limitFilter.value || 450), 900));
      const nodes = payload.nodes
        .filter(node => (!selectedNodeType || node.type === selectedNodeType) && matchesText(node, needle))
        .slice(0, limit);
      const visible = new Set(nodes.map(node => node.id));
      const edges = payload.edges
        .filter(edge => visible.has(edge.source) && visible.has(edge.target))
        .filter(edge => !selectedEdgeType || edge.type === selectedEdgeType)
        .slice(0, limit * 2);
      stats.textContent = `: ${nodes.length}/${payload.nodes.length} nodes, ${edges.length}/${payload.edges.length} edges`;
      const width = window.innerWidth, height = Math.max(520, window.innerHeight - 156);
      svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
      const cx = width / 2, cy = height / 2;
      const radius = Math.max(160, Math.min(width, height) * .36);
      const positions = new Map();
      nodes.forEach((node, i) => {
        const angle = -Math.PI / 2 + (Math.PI * 2 * i / Math.max(1, nodes.length));
        positions.set(node.id, { x: cx + Math.cos(angle) * radius, y: cy + Math.sin(angle) * radius });
      });
      edges.forEach(edge => {
        const a = positions.get(edge.source), b = positions.get(edge.target);
        if (!a || !b) return;
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.setAttribute('x1', a.x); line.setAttribute('y1', a.y); line.setAttribute('x2', b.x); line.setAttribute('y2', b.y);
        line.setAttribute('class', 'edge');
        line.addEventListener('click', () => tip.textContent = JSON.stringify(edge.attributes || edge, null, 2));
        svg.appendChild(line);
      });
      nodes.forEach(node => {
        const p = positions.get(node.id);
        const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        group.setAttribute('class', 'node');
        const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        circle.setAttribute('cx', p.x); circle.setAttribute('cy', p.y); circle.setAttribute('r', node.type === 'meta_node' ? 26 : 20);
        circle.setAttribute('fill', colors[node.type] || '#64748b');
        circle.setAttribute('stroke', 'white'); circle.setAttribute('stroke-width', '3');
        const title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
        title.textContent = node.attributes?.interpretation || node.attributes?.plain_formula_text || node.text || node.latex || node.label || node.id;
        const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        label.setAttribute('x', p.x); label.setAttribute('y', p.y + 38); label.setAttribute('class', 'label');
        label.textContent = String(node.label || node.id).slice(0, 28);
        group.appendChild(title); group.appendChild(circle); group.appendChild(label);
        group.addEventListener('click', () => tip.textContent = JSON.stringify(node.attributes || node, null, 2));
        svg.appendChild(group);
      });
    }
    render();
  </script>
</body>
</html>
"""
    output_html.write_text(
        template.replace("{{", "{").replace("}}", "}").replace("__TITLE__", escaped_title).replace("__DESCRIPTION__", description).replace("__PAYLOAD__", payload),
        encoding="utf-8",
    )


def _view_description(title: str) -> str:
    if "Variable" in title:
        return "Фокусная визуализация выбранной переменной: формулы, мета-вершины, контексты, определения и связи через эту переменную."
    if "Formula Graph" in title:
        return "Упрощенный граф формул: formula, variable, context и term без страниц и абзацев."
    if "Metagraph" in title:
        return "Метаграф смысловых единиц formula_context_unit и связей sequence, shared_variable, definition_usage, possible_semantic_dependency."
    return "Полный базовый граф документа: document, page, paragraph, formula, variable, context и term."


def _normalize_variable_label(value: str | None) -> str:
    return str(value or "").strip().lstrip("\\")
