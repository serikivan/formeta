import React, { memo, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import ReactFlow, {
  Background,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlowProvider,
  useReactFlow,
  useEdgesState,
  useNodesState,
} from "reactflow";
import "reactflow/dist/style.css";
import "./visualization-app.css";

const API_BASE = window.FG_API_BASE || (["5173", "4175"].includes(window.location.port) ? "http://127.0.0.1:8000" : window.location.origin);

const MODES = [
  ["overview", "Обзор"],
  ["formula_focus", "Контекст формулы"],
  ["variable_focus", "Поиск переменной"],
  ["metaedge_lanes", "Метаребра"],
  ["ast_tree", "Структура формулы"],
];

const NODE_TYPES = {
  formulaNode: memo(NodeCard),
  variableNode: memo(NodeCard),
  definitionNode: memo(NodeCard),
  contextNode: memo(NodeCard),
  sectionNode: memo(NodeCard),
  metaedgeNode: memo(NodeCard),
  astNode: memo(NodeCard),
};

function VisualizationRoot({ result }) {
  const [mode, setMode] = useState("overview");
  const [formula, setFormula] = useState("");
  const [variable, setVariable] = useState("");
  const [payload, setPayload] = useState(null);
  const [selectedDetails, setSelectedDetails] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!result?.document_id) return;
    const controller = new AbortController();
    const url = new URL(`${API_BASE}/api/results/${encodeURIComponent(result.document_id)}/projection`);
    url.searchParams.set("mode", mode);
    url.searchParams.set("limit", "80");
    if (formula && ["formula_focus", "ast_tree"].includes(mode)) url.searchParams.set("formula", formula);
    if (variable && mode === "variable_focus") url.searchParams.set("variable", variable);
    setLoading(true);
    setError("");
    fetch(url, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((data) => {
        setPayload(data);
        setSelectedDetails(data.selectedObjectDetails || data.selected_object_details || null);
      })
      .catch((err) => {
        if (err.name !== "AbortError") setError(err.message || "Не удалось загрузить проекцию");
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [result?.document_id, mode, formula, variable]);

  return (
    <ReactFlowProvider>
      <div className="rfProjection">
        <header className="rfProjectionTop">
          <div>
            <strong>Объяснимая визуализация</strong>
            <span>Компактные смысловые проекции метаграфа без полного служебного слоя.</span>
          </div>
        </header>

        <div className="rfProjectionModes">
          {MODES.map(([id, label]) => (
            <button key={id} type="button" className={mode === id ? "active" : ""} onClick={() => setMode(id)}>
              {label}
            </button>
          ))}
        </div>

        <div className="rfProjectionControls">
          {["formula_focus", "ast_tree"].includes(mode) && (
            <label>
              Формула
              <select value={formula} onChange={(event) => setFormula(event.target.value)}>
                <option value="">самая значимая</option>
                {(payload?.available_formulas || []).map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.token || item.id} · {item.label}
                  </option>
                ))}
              </select>
            </label>
          )}
          {mode === "variable_focus" && (
            <label>
              Переменная
              <input
                value={variable}
                onChange={(event) => setVariable(event.target.value)}
                placeholder={(payload?.available_variables || []).slice(0, 6).join(", ") || "x, alpha, omega"}
              />
            </label>
          )}
          <HiddenCounters counts={payload?.hiddenCounts || payload?.hidden_counts} />
        </div>

        <main className="rfProjectionBody">
          <section className="rfProjectionCanvas">
            {loading && <div className="rfProjectionLoading">Загрузка проекции...</div>}
            {error && <div className="rfProjectionLoading error">{error}</div>}
            {!loading && !error && payload && (
              <ProjectionFlow payload={payload} onSelectDetails={setSelectedDetails} />
            )}
          </section>
          <DetailsSidebar details={selectedDetails} payload={payload} />
        </main>
      </div>
    </ReactFlowProvider>
  );
}

function ProjectionFlow({ payload, onSelectDetails }) {
  const { nodes: initialNodes, edges: initialEdges } = useMemo(() => buildFlowElements(payload), [payload]);
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  useEffect(() => {
    setNodes(initialNodes);
    setEdges(initialEdges);
    onSelectDetails(payload.selectedObjectDetails || payload.selected_object_details || initialNodes[0]?.data?.details || null);
  }, [initialEdges, initialNodes, onSelectDetails, payload, setEdges, setNodes]);

  return (
    <ReactFlow
      key={`${payload.mode}:${payload.layout}`}
      nodes={nodes}
      edges={edges}
      nodeTypes={NODE_TYPES}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onNodeClick={(_, node) => onSelectDetails(node.data?.details || node.data)}
      onEdgeClick={(_, edge) => onSelectDetails(edge.data?.details || edge.data)}
      fitView
      fitViewOptions={{ padding: 0.2, maxZoom: 1.1 }}
      minZoom={0.35}
      maxZoom={1.8}
      nodesDraggable
      nodesConnectable={false}
      elementsSelectable
      proOptions={{ hideAttribution: true }}
    >
      <Background gap={24} size={1} color="#eadbc8" />
      <FlowControls />
      <MiniMap zoomable pannable nodeStrokeWidth={2} />
    </ReactFlow>
  );
}

function FlowControls() {
  const { fitView, zoomIn, zoomOut } = useReactFlow();

  return (
    <div className="rfFlowControls" aria-label="Управление масштабом">
      <button type="button" title="Приблизить" aria-label="Приблизить" onClick={() => zoomIn({ duration: 160 })}>
        +
      </button>
      <button type="button" title="Отдалить" aria-label="Отдалить" onClick={() => zoomOut({ duration: 160 })}>
        -
      </button>
      <button
        type="button"
        title="Показать всё"
        aria-label="Показать всё"
        onClick={() => fitView({ padding: 0.2, maxZoom: 1.1, duration: 160 })}
      >
        все
      </button>
    </div>
  );
}

function buildFlowElements(payload) {
  const nodes = payload.nodes || [];
  const edges = payload.edges || [];
  const positionedNodes = layoutNodes(payload.layout, nodes, payload.groups || []);
  return {
    nodes: positionedNodes.map((node) => ({
      id: node.id,
      type: nodeTypeFor(node),
      position: node.position,
      sourcePosition: sourcePositionFor(node),
      targetPosition: targetPositionFor(node),
      data: {
        label: node.label,
        kind: node.kind || node.type,
        details: node.details || node,
        chip: node.chip,
        compact: node.compact,
        astRole: node.astRole,
      },
      draggable: true,
    })),
    edges: edges
      .filter((edge) => positionedNodes.some((node) => node.id === edge.source) && positionedNodes.some((node) => node.id === edge.target))
      .map((edge, index, visibleEdges) => {
        const siblingEdges = visibleEdges.filter((item) => sameEdgePair(item, edge));
        const siblingIndex = siblingEdges.findIndex((item) => (item.id || `${item.source}-${item.target}-${item.type}`) === (edge.id || `${edge.source}-${edge.target}-${edge.type}`));
        const route = routeForEdge(edge, siblingIndex, siblingEdges.length);
        return {
          id: edge.id || `${edge.source}-${edge.target}-${edge.type}`,
          source: edge.source,
          target: edge.target,
          label: route.label,
          type: route.type,
          markerEnd: route.markerEnd ? { type: MarkerType.ArrowClosed, width: 12, height: 12 } : undefined,
          className: `rfEdge rfEdge-${cssSafe(edge.type)} ${route.className}`,
          data: { details: edge.details || edge },
          style: route.style,
          pathOptions: route.pathOptions,
          labelShowBg: true,
          labelBgPadding: [4, 2],
          labelBgBorderRadius: 4,
          labelBgStyle: { fill: "#fffdf9", fillOpacity: 0.88 },
          interactionWidth: 18,
        };
      }),
  };
}

function sourcePositionFor(node) {
  if (node.kind === "section") return Position.Right;
  if (node.kind === "definition") return Position.Bottom;
  if (node.lane === "center") return Position.Right;
  return Position.Bottom;
}

function targetPositionFor(node) {
  if (node.kind === "variable") return Position.Top;
  if (node.kind === "section") return Position.Left;
  if (node.lane === "bottom") return Position.Top;
  if (node.lane === "right") return Position.Left;
  return Position.Left;
}

function sameEdgePair(left, right) {
  return left.source === right.source && left.target === right.target;
}

function routeForEdge(edge, siblingIndex = 0, siblingCount = 1) {
  const type = String(edge.type || "");
  const structural = ["section_contains_formula", "section_definitions", "in_section"].includes(type);
  const variable = ["uses_variable", "appears_in"].includes(type);
  const dependency = ["depends_on", "formula_dependency", "formula_references_formula"].includes(type);
  const ast = type.startsWith("ast_");
  const offset = siblingCount > 1 ? 14 + siblingIndex * 10 : 8;
  if (structural) {
    return {
      label: "",
      type: "step",
      markerEnd: false,
      className: "rfEdge-structural",
      style: { strokeWidth: 1.15, opacity: 0.46 },
      pathOptions: { offset },
    };
  }
  if (variable) {
    return {
      label: "",
      type: "smoothstep",
      markerEnd: true,
      className: "rfEdge-variable",
      style: { strokeWidth: 1.6, opacity: 0.78 },
      pathOptions: { offset: offset + 8, borderRadius: 14 },
    };
  }
  if (ast) {
    return {
      label: shortEdgeLabel(type),
      type: "step",
      markerEnd: true,
      className: "rfEdge-ast",
      style: { strokeWidth: 1.2, opacity: 0.58 },
      pathOptions: { offset },
    };
  }
  return {
    label: shortEdgeLabel(type),
    type: "smoothstep",
    markerEnd: true,
    className: dependency ? "rfEdge-dependency" : "rfEdge-semantic",
    style: { strokeWidth: dependency ? 2.1 : 1.7, opacity: dependency ? 0.9 : 0.76 },
    pathOptions: { offset: offset + 16, borderRadius: 18 },
  };
}

function layoutNodes(layout, nodes, groups) {
  if (layout === "section_lanes") return layoutSectionLanes(nodes, groups);
  if (layout === "formula_focus") return layoutFormulaFocus(nodes);
  if (layout === "variable_ego") return layoutVariableEgo(nodes, groups);
  if (layout === "metaedge_lanes") return layoutMetaedgeLanes(nodes);
  if (layout === "ast_tree") return layoutAstTree(nodes);
  return nodes.map((node, index) => ({ ...node, position: { x: (index % 6) * 170, y: Math.floor(index / 6) * 110 } }));
}

function layoutSectionLanes(nodes, groups) {
  const result = [];
  const groupOrder = groups.slice(0, 5).map((group) => group.id);
  const groupIndex = new Map(groupOrder.map((id, index) => [id, index]));
  const rowHeight = 220;
  groupOrder.forEach((groupId) => {
    const row = groupIndex.get(groupId) ?? 0;
    const rowNodes = nodes.filter((node) => (node.groupId || node.lane || groupOrder[0] || "document") === groupId);
    const section = rowNodes.find((node) => node.kind === "section");
    if (section) result.push({ ...section, position: { x: 24, y: 50 + row * rowHeight } });
    rowNodes
      .filter((node) => node.kind === "formula")
      .forEach((node, index) => result.push({ ...node, position: { x: 170 + index * 134, y: 28 + row * rowHeight } }));
    rowNodes
      .filter((node) => node.kind === "variable" || node.kind === "symbol")
      .forEach((node, index) => result.push({ ...node, position: { x: 170 + index * 116, y: 118 + row * rowHeight } }));
    rowNodes
      .filter((node) => node.kind === "definition")
      .forEach((node, index) => result.push({ ...node, position: { x: 170 + index * 130, y: 168 + row * rowHeight } }));
  });
  nodes.forEach((node, index) => {
    if (result.some((item) => item.id === node.id)) return;
    const lane = node.groupId || node.lane || groupOrder[0] || "document";
    const row = groupIndex.get(lane) ?? 0;
    result.push({ ...node, position: { x: 170 + (index % 8) * 124, y: 70 + row * rowHeight + Math.floor(index / 8) * 72 } });
  });
  return result;
}

function layoutFormulaFocus(nodes) {
  const buckets = bucketByLane(nodes);
  return [
    ...placeLane(buckets.top, 430, 20, 160, 0),
    ...placeLane(buckets.left, 40, 170, 0, 94),
    ...placeLane(buckets.center, 430, 220, 0, 0),
    ...placeLane(buckets.right, 760, 150, 0, 96),
    ...placeLane(buckets.bottom, 260, 430, 126, 0),
  ];
}

function layoutVariableEgo(nodes, groups) {
  const result = [];
  const center = nodes.filter((node) => node.lane === "center");
  result.push(...placeLane(center, 430, 230, 0, 0));
  const definitions = nodes.filter((node) => node.lane === "definitions");
  result.push(...placeLane(definitions, 40, 120, 0, 92));
  const sectionIds = groups.map((group) => group.id);
  const columns = Math.max(1, Math.min(3, sectionIds.length || 1));
  sectionIds.forEach((sectionId, groupIndex) => {
    const x = 720 + (groupIndex % columns) * 190;
    const y = 40 + Math.floor(groupIndex / columns) * 260;
    const groupNodes = nodes.filter((node) => node.lane === sectionId);
    result.push(...placeLane(groupNodes, x, y, 0, 86));
  });
  nodes
    .filter((node) => !result.some((item) => item.id === node.id))
    .forEach((node, index) => result.push({ ...node, position: { x: 250 + (index % 5) * 140, y: 520 + Math.floor(index / 5) * 90 } }));
  return result;
}

function layoutMetaedgeLanes(nodes) {
  const xByLane = { source: 40, metaedge: 360, mediator: 640, target: 920 };
  const counters = new Map();
  return nodes.map((node) => {
    const lane = node.lane || "metaedge";
    const row = Number(node.row || 1) - 1;
    const key = `${lane}:${row}`;
    const offset = counters.get(key) || 0;
    counters.set(key, offset + 1);
    return {
      ...node,
      position: { x: xByLane[lane] ?? 360, y: 40 + row * 180 + offset * 48 },
    };
  });
}

function layoutAstTree(nodes) {
  const roleOrder = { root: [430, 30, 0], lhs: [260, 170, 0], rhs: [600, 170, 0], operand: [160, 320, 145], operator: [260, 470, 135] };
  const counters = new Map();
  return nodes.map((node) => {
    const role = node.astRole || "operand";
    const [x, y, step] = roleOrder[role] || roleOrder.operand;
    const index = counters.get(role) || 0;
    counters.set(role, index + 1);
    return { ...node, position: { x: x + index * step, y } };
  });
}

function placeLane(items = [], x, y, dx, dy) {
  return items.map((node, index) => ({ ...node, position: { x: x + index * dx, y: y + index * dy } }));
}

function bucketByLane(nodes) {
  return nodes.reduce((acc, node) => {
    const lane = node.lane || "center";
    acc[lane] = acc[lane] || [];
    acc[lane].push(node);
    return acc;
  }, {});
}

function NodeCard({ data }) {
  return (
    <div className={`rfNode rfNode-${cssSafe(data.kind)} ${data.chip ? "chip" : ""} ${data.compact ? "compact" : ""}`}>
      <Handle type="target" position={Position.Top} className="rfHandle" />
      <Handle type="target" position={Position.Left} className="rfHandle" />
      <span>{nodeKindLabel(data.kind, data.astRole)}</span>
      <strong>{data.label || nodeKindLabel(data.kind)}</strong>
      <Handle type="source" position={Position.Right} className="rfHandle" />
      <Handle type="source" position={Position.Bottom} className="rfHandle" />
    </div>
  );
}

function DetailsSidebar({ details, payload }) {
  return (
    <aside className="rfDetails">
      <div className="rfDetailsHeader">
        <strong>Детали</strong>
        <span>{payload?.title || "Выберите объект на схеме"}</span>
      </div>
      {!details ? (
        <p className="rfMuted">Выберите узел или связь.</p>
      ) : (
        <div className="rfDetailsBody">
          <Field label="ID" value={details.id} />
          <Field label="Тип" value={translateKind(details.type || details.kind)} />
          <Field label="LaTeX" value={details.latex} pre />
          <Field label="Текст" value={details.text || details.context || details.plain_text} pre />
          <Field label="Обозначение" value={details.symbol || details.normalized_symbol} />
          <Field label="Источник" value={translateSource(details.source)} />
          <Field label="Уверенность" value={details.confidence} />
          <Field label="Связанные объекты" value={[...(details.formula_ids || []), ...(details.context_ids || []), ...(details.section_ids || [])].join(", ")} pre />
          <Field label="Атрибуты" value={details.attributes || details.definitions || details} json />
        </div>
      )}
    </aside>
  );
}

function Field({ label, value, pre = false, json = false }) {
  if (value === undefined || value === null || value === "") return null;
  const rendered = json ? JSON.stringify(value, null, 2) : String(value);
  return (
    <div className="rfDetailField">
      <span>{label}</span>
      {pre || json ? <pre>{rendered}</pre> : <strong>{rendered}</strong>}
    </div>
  );
}

function HiddenCounters({ counts = {} }) {
  return (
    <div className="rfHiddenCounters">
      <span>скрыто узлов: {counts.nodes || 0}</span>
      <span>скрыто связей: {counts.edges || 0}</span>
    </div>
  );
}

function nodeTypeFor(node) {
  const kind = node.kind || node.type;
  if (kind === "formula") return "formulaNode";
  if (kind === "variable") return "variableNode";
  if (kind === "definition") return "definitionNode";
  if (kind === "context") return "contextNode";
  if (kind === "section") return "sectionNode";
  if (kind === "metaedge") return "metaedgeNode";
  if (kind === "ast") return "astNode";
  return "contextNode";
}

function nodeKindLabel(kind, astRole) {
  if (kind === "ast" && astRole) return translateAstRole(astRole);
  return {
    formula: "Формула",
    variable: "Переменная",
    definition: "Определение",
    context: "Контекст",
    section: "Раздел",
    metaedge: "Метаребро",
    ast: "AST",
  }[kind] || "Узел";
}

function shortEdgeLabel(type = "") {
  const labels = {
    has_context: "контекст",
    has_definition: "определение",
    defines: "задает",
    uses_variable: "переменная",
    appears_in: "входит в",
    depends_on: "зависит от",
    formula_dependency: "зависимость",
    formula_references_formula: "ссылка",
    section_contains_formula: "",
    section_definitions: "",
    in_section: "",
    ast_lhs: "левая часть",
    ast_rhs: "правая часть",
    ast_operand: "операнд",
    ast_operator: "оператор",
    ast_argument: "аргумент",
    metaedge_source: "источник",
    metaedge_target: "цель",
  };
  return labels[type] ?? String(type).replace(/^formula_/, "").replaceAll("_", " ");
}

function translateKind(kind = "") {
  return nodeKindLabel(kind);
}

function translateSource(source = "") {
  if (!source) return "";
  return {
    tex_source: "TeX-источник",
    tex_source_aligned: "TeX-источник",
    pdf_text_layer: "текстовый слой PDF",
    pp_structure_v3: "структурный анализ",
    pp_formula_net: "распознавание формул",
    text_pattern: "текстовый шаблон",
    text_inline_pattern: "строчная формула",
    rule_based: "правила",
  }[source] || source;
}

function translateAstRole(role = "") {
  return {
    root: "корень",
    lhs: "левая часть",
    rhs: "правая часть",
    operand: "операнд",
    operator: "оператор",
  }[role] || role;
}

function cssSafe(value = "") {
  return String(value).replace(/[^a-z0-9_-]+/gi, "_");
}

function renderProjectionVisualization(result, options = {}) {
  const target = options.target || document.querySelector("#visualizationPage");
  if (!target) return;
  target.innerHTML = "";
  const root = createRoot(target);
  root.render(<VisualizationRoot result={result} />);
}

window.ProjectionVisualization = {
  render: renderProjectionVisualization,
};
