(function () {
  "use strict";

  const TYPE_RADIUS = {
    document: 34,
    section: 26,
    paragraph: 22,
    formula: 28,
    symbol: 18,
    context: 24,
    definition: 22,
    fragment: 14,
    metaedge: 20,
    source: 16,
    issue: 16,
  };

  function computePlanetaryLayout(payload, options = {}) {
    /*
     * Идея раскладки основана на планетарной модели визуализации метаграфов из визуализация.pdf:
     * метавершины рассматриваются как системы, вложенные узлы - как связанные тела, а масса влияет
     * на размер и силу группировки.
     */
    const nodes = options.nodes || payload.nodes || [];
    const metavertices = options.metavertices || payload.metavertices || [];
    const count = nodes.length + metavertices.length;
    const compactInput = Boolean(options.compact);
    const width = compactInput
      ? Math.max(760, Math.min(1500, 660 + count * 4))
      : Math.max(920, Math.min(2100, 820 + count * 4.2));
    const height = compactInput
      ? Math.max(520, Math.min(1100, 480 + count * 2.8))
      : Math.max(600, Math.min(1500, 560 + count * 2.6));
    const center = { x: width / 2, y: height / 2 };
    const nodeById = new Map(nodes.map((node) => [node.id, node]));
    const mvById = new Map(metavertices.map((mv) => [mv.id, mv]));
    const childrenByParent = new Map();
    nodes.forEach((node) => {
      if (node.parent) push(childrenByParent, node.parent, node.id);
    });
    metavertices.forEach((mv) => {
      if (mv.parent) push(childrenByParent, mv.parent, mv.id);
    });

    const roots = metavertices.filter((mv) => !mv.parent || !mvById.has(mv.parent));
    const mvLayout = new Map();
    const nodeLayout = new Map();
    const compact = compactInput || count > 360;

    if (roots.length) {
      roots.forEach((root, index) => {
        const radius = metavertexRadius(root, count);
        const position = roots.length === 1 ? center : orbitPoint(center, Math.min(width, height) * 0.22, index, roots.length);
        placeMetavertex(root, position, radius, 0);
      });
    }

    const looseNodes = nodes.filter((node) => !node.parent || !mvLayout.has(node.parent));
    placeNodesInOrbit(looseNodes, center, Math.min(width, height) * 0.34, nodeLayout, compact);
    avoidGlobalCollisions(nodes, metavertices, nodeLayout, mvLayout, width, height);

    return { width, height, compact, nodes: nodeLayout, metavertices: mvLayout };

    function placeMetavertex(mv, position, radius, depth) {
      if (mvLayout.has(mv.id)) return;
      mvLayout.set(mv.id, { ...position, r: radius, depth });
      const children = (childrenByParent.get(mv.id) || []).filter((id) => nodeById.has(id) || mvById.has(id));
      const childMvs = children.map((id) => mvById.get(id)).filter(Boolean);
      const childNodes = children.map((id) => nodeById.get(id)).filter(Boolean);

      const childMvRing = Math.max(72, radius * 0.55);
      childMvs.forEach((child, index) => {
        const childRadius = Math.min(radius * 0.45, metavertexRadius(child, count));
        const point = orbitPoint(position, childMvRing, index, childMvs.length, depth * 0.47);
        const clamped = clampInside(point, position, Math.max(20, radius - childRadius - 24));
        placeMetavertex(child, clamped, childRadius, depth + 1);
      });

      const nodeRing = Math.max(34, radius * (childMvs.length ? 0.34 : 0.48));
      placeNodesInOrbit(childNodes, position, nodeRing, nodeLayout, compact, radius - 18);
    }
  }

  function computeLayout(payload, options = {}) {
    const type = payload?.layout?.type || "planetary_metagraph";
    if (type === "document_tree") return computeTreeLayout(payload, options);
    if (type === "formula_ast_tree") return computeTreeLayout(payload, { ...options, ast: true });
    if (type === "formula_context_ego") return computeConcentricLayout(payload, { ...options, centerType: "formula" });
    if (type === "variable_ego") return computeConcentricLayout(payload, options);
    if (type === "metaedge_bipartite") return computeLaneLayout(payload, options);
    if (type === "semantic_network") return computeSemanticLayout(payload, options);
    return computeSemanticLayout(payload, { ...options, compact: true });
  }

  function computeTreeLayout(payload, options = {}) {
    const nodes = options.nodes || payload.nodes || [];
    const metavertices = options.metavertices || payload.metavertices || [];
    const items = [...metavertices, ...nodes];
    const count = Math.max(1, items.length);
    const nodeLayout = new Map();
    const mvLayout = new Map();
    const levels = new Map();
    items.forEach((item) => {
      const level = Number(item.layout?.level ?? item.visual?.level ?? item.depth ?? 0);
      if (!levels.has(level)) levels.set(level, []);
      levels.get(level).push(item);
    });
    const cell = options.ast ? 118 : 146;
    const maxRow = Math.max(1, ...[...levels.values()].map((row) => row.length));
    const maxLevel = Math.max(0, ...levels.keys());
    const width = Math.max(1180, Math.min(18000, Math.max(maxRow * cell + 180, 760 + count * 24)));
    const height = Math.max(640, Math.min(8000, Math.max(220 + (maxLevel + 1) * (options.ast ? 130 : 150), 420 + count * 22)));
    [...levels.keys()].sort((a, b) => a - b).forEach((level) => {
      const row = levels.get(level).sort((a, b) => (b.rank || 0) - (a.rank || 0));
      row.forEach((item, index) => {
        const x = Math.max(90, cell / 2) + index * cell;
        const y = 96 + level * (options.ast ? 130 : 150);
        const target = item.type?.endsWith("metavertex") ? mvLayout : nodeLayout;
        target.set(item.id, { x, y, r: item.type?.endsWith("metavertex") ? metavertexRadius(item, count) * 0.42 : nodeRadius(item, Boolean(options.compact)) });
      });
    });
    return { width, height, compact: Boolean(options.compact) || count > 260, nodes: nodeLayout, metavertices: mvLayout };
  }

  function computeConcentricLayout(payload, options = {}) {
    const nodes = options.nodes || payload.nodes || [];
    const metavertices = options.metavertices || payload.metavertices || [];
    const count = nodes.length + metavertices.length;
    const cellW = 168;
    const cellH = 92;
    const nodeLayout = new Map();
    const mvLayout = new Map();
    const centerNode =
      options.centerType === "formula"
        ? nodes.find((node) => node.type === "formula") || nodes[0]
        : nodes.find((node) => node.type === "symbol" || node.type === "variable") || nodes[0];
    const groups = [
      centerNode ? [centerNode] : [],
      nodes.filter((node) => node !== centerNode && node.type === "formula"),
      nodes.filter((node) => ["context", "definition"].includes(node.type)),
      [...metavertices, ...nodes.filter((node) => ["section", "paragraph", "document"].includes(node.type))],
      nodes.filter((node) => !["formula", "context", "definition", "section", "paragraph", "document", "symbol", "variable"].includes(node.type)),
    ];
    const grids = groups.map((group, index) => gridBlock(group.length, index === 0 ? 180 : cellW, cellH, index === 0 ? 1 : 4));
    const width = Math.max(1180, grids.reduce((sum, grid) => sum + Math.max(220, grid.width) + 90, 80));
    const height = Math.max(680, Math.max(...grids.map((grid) => grid.height), 0) + 180);
    let cursorX = 90;
    groups.forEach((group, groupIndex) => {
      const grid = grids[groupIndex];
      const groupWidth = Math.max(220, grid.width);
      const startX = cursorX + (groupWidth - grid.width) / 2;
      const startY = groupIndex === 0 ? height / 2 - cellH / 2 : 95;
      group.forEach((item, index) => {
        const point = gridPoint(startX, startY, index, grid, groupIndex === 0 ? 180 : cellW, cellH);
        const target = item.type?.endsWith("metavertex") ? mvLayout : nodeLayout;
        target.set(item.id, { ...point, r: item.type?.endsWith("metavertex") ? Math.min(34, metavertexRadius(item, count) * 0.18) : nodeRadius(item, true) });
      });
      cursorX += groupWidth + 90;
    });
    return { width, height, compact: true, nodes: nodeLayout, metavertices: mvLayout };
  }

  function computeLaneLayout(payload, options = {}) {
    const nodes = options.nodes || payload.nodes || [];
    const metavertices = options.metavertices || payload.metavertices || [];
    const items = [...metavertices, ...nodes];
    const count = Math.max(1, items.length);
    const cellW = 142;
    const cellH = 78;
    const lanes = {
      source: [],
      metaedge: [],
      mediator: [],
      target: [],
      endpoint: [],
    };
    items.forEach((item) => {
      const lane = item.type === "metaedge" ? "metaedge" : item.type === "context" || item.type === "definition" ? "mediator" : item.type?.endsWith("metavertex") ? "endpoint" : "target";
      lanes[lane].push(item);
    });
    const laneOrder = ["endpoint", "metaedge", "mediator", "target"];
    const laneGrids = laneOrder.map((lane) => [lane, gridBlock((lanes[lane] || []).length, cellW, cellH, 10)]);
    const width = Math.max(1180, laneGrids.reduce((sum, [, grid]) => sum + Math.max(220, grid.width) + 120, 80));
    const height = Math.max(700, Math.max(...laneGrids.map(([, grid]) => grid.height), 0) + 180);
    const nodeLayout = new Map();
    const mvLayout = new Map();
    let cursorX = 80;
    laneGrids.forEach(([lane, grid]) => {
      const laneItems = lanes[lane] || [];
      const laneWidth = Math.max(220, grid.width);
      const startX = cursorX + (laneWidth - grid.width) / 2;
      const startY = 95;
      laneItems.forEach((item, index) => {
        const point = gridPoint(startX, startY, index, grid, cellW, cellH);
        const target = item.type?.endsWith("metavertex") ? mvLayout : nodeLayout;
        target.set(item.id, { ...point, r: item.type?.endsWith("metavertex") ? metavertexRadius(item, count) * 0.28 : nodeRadius(item, true) });
      });
      cursorX += laneWidth + 120;
    });
    return { width, height, compact: true, nodes: nodeLayout, metavertices: mvLayout };
  }

  function computeSemanticLayout(payload, options = {}) {
    const nodes = options.nodes || payload.nodes || [];
    const metavertices = options.metavertices || payload.metavertices || [];
    const count = nodes.length + metavertices.length;
    const cellW = 138;
    const cellH = 82;
    const nodeLayout = new Map();
    const mvLayout = new Map();
    const groups = [
      nodes.filter((node) => node.type === "formula"),
      nodes.filter((node) => node.type === "symbol" || node.type === "variable"),
      nodes.filter((node) => node.type === "context" || node.type === "definition"),
      metavertices,
      nodes.filter((node) => !["formula", "symbol", "variable", "context", "definition"].includes(node.type)),
    ];
    const grids = groups.map((group) => gridBlock(group.length, cellW, cellH));
    const width = Math.max(1180, grids.reduce((sum, grid) => sum + Math.max(240, grid.width) + 90, 80));
    const height = Math.max(720, Math.max(...grids.map((grid) => grid.height), 0) + 180);
    let cursorX = 80;
    groups.forEach((group, groupIndex) => {
      const grid = grids[groupIndex];
      const groupWidth = Math.max(240, grid.width);
      const startX = cursorX + (groupWidth - grid.width) / 2;
      const startY = 95;
      group.sort((a, b) => (b.rank || 0) - (a.rank || 0)).forEach((item, index) => {
        const point = gridPoint(startX, startY, index, grid, cellW, cellH);
        const target = item.type?.endsWith("metavertex") ? mvLayout : nodeLayout;
        target.set(item.id, { ...point, r: item.type?.endsWith("metavertex") ? metavertexRadius(item, count) * 0.28 : nodeRadius(item, true) });
      });
      cursorX += groupWidth + 90;
    });
    return { width, height, compact: Boolean(options.compact) || count > 320, nodes: nodeLayout, metavertices: mvLayout };
  }

  function placeNodesInOrbit(nodes, center, ring, target, compact, maxDistance = null) {
    if (!nodes.length) return;
    const byPriority = [...nodes].sort((left, right) => (right.importance || right.rank || 0) - (left.importance || left.rank || 0));
    if (nodes.length > 18) {
      const cellW = compact ? 110 : 128;
      const cellH = compact ? 68 : 78;
      const grid = gridBlock(nodes.length, cellW, cellH);
      const startX = center.x - grid.width / 2;
      const startY = center.y - grid.height / 2;
      byPriority.forEach((node, index) => {
        target.set(node.id, { ...gridPoint(startX, startY, index, grid, cellW, cellH), r: nodeRadius(node, compact) });
      });
      return;
    }
    byPriority.forEach((node, index) => {
      const radius = nodeRadius(node, compact);
      const shell = Math.floor(index / 14);
      const shellIndex = index % 14;
      const shellSize = Math.min(14, byPriority.length - shell * 14);
      const innerRing = Math.max(30, ring - shell * (compact ? 44 : 56));
      const point = orbitPoint(center, innerRing, shellIndex, shellSize, shell * 0.41);
      const clamped = maxDistance ? clampInside(point, center, Math.max(radius + 8, maxDistance - radius)) : point;
      target.set(node.id, { ...clamped, r: radius });
    });
    avoidLocalCollisions(byPriority, center, target, maxDistance || ring + 80);
  }

  function avoidLocalCollisions(nodes, center, positions, maxDistance) {
    for (let step = 0; step < 22; step += 1) {
      for (let i = 0; i < nodes.length; i += 1) {
        for (let j = i + 1; j < nodes.length; j += 1) {
          const a = positions.get(nodes[i].id);
          const b = positions.get(nodes[j].id);
          if (!a || !b) continue;
          const dx = b.x - a.x || 0.01;
          const dy = b.y - a.y || 0.01;
          const distance = Math.max(0.01, Math.hypot(dx, dy));
          const minDistance = a.r + b.r + 12;
          if (distance >= minDistance) continue;
          const pushBy = (minDistance - distance) / 2;
          const sx = (dx / distance) * pushBy;
          const sy = (dy / distance) * pushBy;
          a.x -= sx;
          a.y -= sy;
          b.x += sx;
          b.y += sy;
          Object.assign(a, clampInside(a, center, maxDistance));
          Object.assign(b, clampInside(b, center, maxDistance));
        }
      }
    }
  }

  function avoidGlobalCollisions(nodes, metavertices, nodeLayout, mvLayout, width, height) {
    const items = [
      ...nodes.map((node) => ({ id: node.id, type: "node", r: nodeLayout.get(node.id)?.r || 18 })),
      ...metavertices.map((mv) => ({ id: mv.id, type: "mv", r: Math.min(70, (mvLayout.get(mv.id)?.r || 80) * 0.28) })),
    ];
    const pos = (item) => item.type === "node" ? nodeLayout.get(item.id) : mvLayout.get(item.id);
    for (let step = 0; step < 8; step += 1) {
      for (let i = 0; i < items.length; i += 1) {
        for (let j = i + 1; j < items.length; j += 1) {
          const a = pos(items[i]);
          const b = pos(items[j]);
          if (!a || !b) continue;
          const dx = b.x - a.x || 0.01;
          const dy = b.y - a.y || 0.01;
          const distance = Math.max(0.01, Math.hypot(dx, dy));
          const minDistance = Math.min(130, items[i].r + items[j].r + 10);
          if (distance >= minDistance) continue;
          const shift = (minDistance - distance) * 0.18;
          const sx = (dx / distance) * shift;
          const sy = (dy / distance) * shift;
          b.x = clamp(b.x + sx, 28, width - 28);
          b.y = clamp(b.y + sy, 28, height - 28);
        }
      }
    }
  }

  function edgePath(source, target, bend = 0.18) {
    if (!source || !target) return "";
    const mx = (source.x + target.x) / 2;
    const my = (source.y + target.y) / 2;
    const dx = target.x - source.x;
    const dy = target.y - source.y;
    const length = Math.max(1, Math.hypot(dx, dy));
    const nx = -dy / length;
    const ny = dx / length;
    const offset = Math.min(120, length * bend);
    return `M ${source.x} ${source.y} Q ${mx + nx * offset} ${my + ny * offset} ${target.x} ${target.y}`;
  }

  function nodeRadius(node, compact = false) {
    const base = TYPE_RADIUS[node.type] || 18;
    const mass = Math.max(1, Number(node.mass || 1));
    return Math.min(compact ? 26 : 42, base + Math.log1p(mass) * 2.2);
  }

  function metavertexRadius(mv, count = 0) {
    const mass = Math.max(1, Number(mv.mass || 1));
    const contains = Math.max(1, Number(mv.metrics?.visible_contains_count || mv.contains?.length || 1));
    const typeBonus = mv.type === "paper_metavertex" ? 72 : mv.type === "section_metavertex" ? 52 : mv.type === "paragraph_metavertex" ? 36 : 28;
    const compactFactor = count > 420 ? 0.82 : 1;
    return Math.max(70, Math.min(330, (typeBonus + Math.sqrt(mass) * 7 + Math.sqrt(contains) * 18) * compactFactor));
  }

  function gridBlock(count, cellW, cellH, maxCols = null) {
    const safeCount = Math.max(1, count);
    const cols = Math.max(1, Math.min(maxCols || safeCount, Math.ceil(Math.sqrt(safeCount * 1.35))));
    const rows = Math.ceil(safeCount / cols);
    return { cols, rows, width: cols * cellW, height: rows * cellH };
  }

  function gridPoint(startX, startY, index, grid, cellW, cellH) {
    const col = index % grid.cols;
    const row = Math.floor(index / grid.cols);
    return { x: startX + col * cellW + cellW / 2, y: startY + row * cellH + cellH / 2 };
  }

  function orbitPoint(center, radius, index, total, phase = 0) {
    const angle = -Math.PI / 2 + phase + (Math.PI * 2 * index) / Math.max(1, total);
    return { x: center.x + Math.cos(angle) * radius, y: center.y + Math.sin(angle) * radius };
  }

  function clampInside(point, center, radius) {
    const dx = point.x - center.x;
    const dy = point.y - center.y;
    const distance = Math.max(0.01, Math.hypot(dx, dy));
    if (distance <= radius) return { x: point.x, y: point.y };
    return { x: center.x + (dx / distance) * radius, y: center.y + (dy / distance) * radius };
  }

  function push(map, key, value) {
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(value);
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  window.GraphLayout = {
    computeLayout,
    computePlanetaryLayout,
    edgePath,
    nodeRadius,
    metavertexRadius,
  };
})();
