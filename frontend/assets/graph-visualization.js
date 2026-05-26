(function () {
  "use strict";

  const API_BASE_FALLBACK = window.FG_API_BASE || (["5173", "4175"].includes(window.location.port) ? "http://127.0.0.1:8000" : window.location.origin);
  const MODE_DEFS = [
    ["overview", "Обзор статьи", "Главные разделы, формулы, переменные и контексты без служебных связей."],
    ["metagraph_planetary_overview", "Планетарный метаграф", "Вложенность статьи: документ, разделы, формулы, переменные и контекстные облака."],
    ["formula_semantic_network", "Формулы и переменные", "Семантическая сеть формул, переменных, определений и зависимостей."],
    ["formula_context", "Метавершина формулы", "Внешний уровень метавершины формулы: контекст, определения, обозначения и связи документа."],
    ["variable_focus", "Связи переменной", "Ego-проекция переменной с радиусом 1-3 перехода."],
    ["metaedges_view", "Метаребра", "Многоместные отношения как источник → метаребро → цель с посредниками."],
  ];
  const MODE_DEF_BY_ID = new Map(MODE_DEFS.map((item) => [item[0], item]));
  const MODE_LIMITS = {
    overview: 110,
    metagraph_planetary_overview: 160,
    formula_semantic_network: 190,
    formula_context: 180,
    variable_focus: 190,
    metaedges_view: 180,
    corpus_graph: 560,
  };

  const NODE_COLORS = {
    document: "#23395d",
    section: "#4b6b9a",
    paragraph: "#b7791f",
    formula: "#2463eb",
    symbol: "#069669",
    variable: "#069669",
    context: "#7c3aed",
    definition: "#be185d",
    fragment: "#475569",
    metaedge: "#111827",
    source: "#64748b",
    issue: "#dc2626",
  };

  const EDGE_COLORS = {
    contains: "#94a3b8",
    has_symbol: "#069669",
    has_context: "#7c3aed",
    has_definition: "#be185d",
    depends_on: "#ef4444",
    ast_contains: "#64748b",
    ast_lhs: "#64748b",
    ast_rhs: "#64748b",
    metaedge_source: "#111827",
    metaedge_target: "#111827",
    extracted_from: "#94a3b8",
  };

  const TECHNICAL_TYPES = new Set(["source", "issue", "fragment"]);
  const TECHNICAL_EDGE_TYPES = new Set(["contains", "has_operator", "has_subexpression", "ast_contains", "ast_lhs", "ast_rhs", "metaedge_source", "metaedge_target", "extracted_from"]);
  const explorers = new WeakMap();

  function renderMetagraphVisualization(result, options = {}) {
    const target = options.target || document.querySelector("#visualizationPage");
    if (!target) return;
    renderProjectionWorkspace(result, target, options);
    return;
    cleanup(target);
    const explorer = createExplorer(result, target, options);
    explorers.set(target, explorer);
    explorer.renderShell();
    explorer.loadMode(options.initialMode || "overview", options.initialParams || {});
  }

  function renderProjectionWorkspace(result, target, options = {}) {
    cleanup(target);
    const state = {
      result,
      target,
      apiBase: options.apiBase || API_BASE_FALLBACK,
      mode: "overview",
      formula: "",
      variable: "",
      payload: null,
      abortController: null,
    };
    target.innerHTML = `
      <div class="projectionWorkspace">
        <div class="projectionTopbar">
          <div>
            <strong>Проекции метавершин и метаребер</strong>
            <span>Показаны компактные сценарные схемы без полного служебного слоя.</span>
          </div>
        </div>
        <div class="projectionModeBar">
          ${[
            ["overview", "Обзор документа"],
            ["formula_focus", "Метавершина формулы"],
            ["variable_focus", "Поиск переменной"],
            ["metaedge_lanes", "Метаребра"],
            ["ast_tree", "Структура формулы"],
          ].map(([mode, label]) => `<button type="button" data-projection-mode="${mode}">${label}</button>`).join("")}
        </div>
        <div class="projectionControls">
          <label data-formula-control hidden>Формула <select data-projection-formula></select></label>
          <label data-variable-control hidden>Переменная <input type="search" data-projection-variable placeholder="x, alpha, E" /></label>
        </div>
        <div class="projectionGrid">
          <section class="projectionMain" data-projection-main></section>
          <aside class="projectionDetails" data-projection-details></aside>
        </div>
      </div>
    `;
    target.querySelectorAll("[data-projection-mode]").forEach((button) => {
      button.addEventListener("click", () => loadProjection(button.dataset.projectionMode || "overview"));
    });
    target.querySelector("[data-projection-formula]")?.addEventListener("change", (event) => {
      state.formula = event.target.value;
      loadProjection(state.mode);
    });
    target.querySelector("[data-projection-variable]")?.addEventListener("change", (event) => {
      state.variable = event.target.value.trim();
      loadProjection(state.mode);
    });
    loadProjection("overview");

    async function loadProjection(mode) {
      state.mode = mode;
      target.querySelectorAll("[data-projection-mode]").forEach((button) => button.classList.toggle("active", button.dataset.projectionMode === mode));
      target.querySelector("[data-formula-control]").hidden = !["formula_focus", "ast_tree"].includes(mode);
      target.querySelector("[data-variable-control]").hidden = mode !== "variable_focus";
      const main = target.querySelector("[data-projection-main]");
      main.innerHTML = `<div class="planetLoading">Загрузка проекции...</div>`;
      if (state.abortController) state.abortController.abort();
      state.abortController = new AbortController();
      const url = new URL(`${state.apiBase}/api/results/${encodeURIComponent(result.document_id)}/projection`);
      url.searchParams.set("mode", mode);
      url.searchParams.set("limit", "80");
      if (state.formula) url.searchParams.set("formula", state.formula);
      if (state.variable) url.searchParams.set("variable", state.variable);
      try {
        const response = await fetch(url, { signal: state.abortController.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        state.payload = await response.json();
        syncProjectionSelectors(state.payload);
        renderProjection(state.payload);
      } catch (error) {
        if (error.name === "AbortError") return;
        main.innerHTML = `<div class="planetLoading">Не удалось загрузить проекцию: ${escapeHtml(error.message || "неизвестная ошибка")}</div>`;
      }
    }

    function syncProjectionSelectors(payload) {
      const formulaSelect = target.querySelector("[data-projection-formula]");
      if (formulaSelect && !formulaSelect.options.length) {
        formulaSelect.innerHTML = `<option value="">самая значимая</option>${(payload.available_formulas || []).map((item) => `<option value="${escapeAttribute(item.id)}">${escapeHtml(item.token || item.id)} — ${escapeHtml(compactLabel(item.label || "", 42))}</option>`).join("")}`;
      }
      const variableInput = target.querySelector("[data-projection-variable]");
      if (variableInput && !variableInput.value && (payload.available_variables || []).length) {
        variableInput.placeholder = payload.available_variables.slice(0, 6).join(", ");
      }
    }

    function renderProjection(payload) {
      const main = target.querySelector("[data-projection-main]");
      const details = target.querySelector("[data-projection-details]");
      details.innerHTML = renderProjectionDetails(payload);
      if (payload.layout === "document_map") {
        main.innerHTML = renderDocumentMap(payload);
      } else if (payload.layout === "metaedge_lanes") {
        main.innerHTML = renderMetaedgeLanes(payload);
      } else if (payload.layout === "variable_groups") {
        main.innerHTML = `${renderExplainGraph(payload)}${renderProjectionGroups(payload.groups || [])}`;
      } else if (payload.layout === "formula_explain" || payload.layout === "ast_tree") {
        main.innerHTML = renderExplainGraph(payload);
      } else {
        main.innerHTML = `<div class="planetLoading">${escapeHtml(payload.description || "Нет данных для проекции.")}</div>`;
      }
    }
  }

  function renderDocumentMap(payload) {
    return `
      <div class="projectionIntro"><strong>${escapeHtml(payload.title)}</strong><span>${escapeHtml(payload.description)}</span>${renderHiddenCounts(payload.hidden_counts)}</div>
      <div class="documentMap">
        ${(payload.groups || []).map((group) => `
          <article class="documentSectionCard">
            <div class="documentSectionHeader">
              <strong>${escapeHtml(group.title)}</strong>
              <span>${group.metrics?.formulas || 0} формул · ${group.metrics?.variables || 0} переменных · ${group.metrics?.definitions || 0} определений</span>
            </div>
            <div class="projectionFormulaList">
              ${(group.items || []).map(renderMiniFormula).join("") || `<span class="projectionEmpty">Топ-формулы не найдены.</span>`}
            </div>
          </article>
        `).join("")}
      </div>
    `;
  }

  function renderExplainGraph(payload) {
    const lanes = groupByLane(payload.nodes || []);
    const laneOrder = ["definitions", "variables", "center", "dependencies", "root", "symbols", "operators", "contexts"];
    return `
      <div class="projectionIntro"><strong>${escapeHtml(payload.title)}</strong><span>${escapeHtml(payload.description)}</span>${renderHiddenCounts(payload.hidden_counts)}</div>
      <div class="explainGraph ${cssClass(payload.layout)}">
        ${laneOrder.filter((lane) => lanes.has(lane)).map((lane) => `
          <div class="explainLane">
            <span class="explainLaneTitle">${escapeHtml(translateProjectionLane(lane))}</span>
            ${lanes.get(lane).map((node) => `<div class="explainNode ${cssClass(node.type)}"><strong>${escapeHtml(node.label || node.id)}</strong>${node.latex ? `<code>${escapeHtml(node.latex)}</code>` : ""}</div>`).join("")}
          </div>
        `).join("")}
      </div>
      ${payload.groups ? renderProjectionGroups(payload.groups) : ""}
    `;
  }

  function renderMetaedgeLanes(payload) {
    return `
      <div class="projectionIntro"><strong>${escapeHtml(payload.title)}</strong><span>${escapeHtml(payload.description)}</span>${renderHiddenCounts(payload.hidden_counts)}</div>
      <div class="metaedgeLaneTable">
        <div class="metaedgeLaneHead"><span>SOURCE SET</span><span>METAEDGE</span><span>MEDIATORS</span><span>TARGET SET</span></div>
        ${(payload.rows || []).map((row) => `
          <article class="metaedgeLaneRow">
            <div>${renderIdChips(row.source_set)}</div>
            <div><strong>${escapeHtml(row.type)}</strong><small>${escapeHtml(row.id)}</small></div>
            <div>${renderIdChips(row.mediators)}</div>
            <div>${renderIdChips(row.target_set)}</div>
          </article>
        `).join("") || `<div class="projectionEmpty">Метаребра не найдены.</div>`}
      </div>
    `;
  }

  function renderProjectionGroups(groups) {
    if (!groups?.length) return "";
    return `<div class="projectionGroupList">${groups.map((group) => `
      <article class="projectionGroupCard">
        <strong>${escapeHtml(group.title)}</strong>
        <span>${Object.entries(group.metrics || {}).map(([key, value]) => `${escapeHtml(key)}: ${escapeHtml(value)}`).join(" · ")}</span>
        <div class="projectionFormulaList">${(group.items || []).map(renderMiniFormula).join("")}</div>
      </article>
    `).join("")}</div>`;
  }

  function renderProjectionDetails(payload) {
    const cards = payload.cards || [];
    return `
      <div class="projectionDetailHeader">
        <strong>Что показано</strong>
        <span>${escapeHtml(payload.description || "")}</span>
      </div>
      ${renderHiddenCounts(payload.hidden_counts)}
      ${cards.slice(0, 8).map((card) => `
        <details class="projectionDetailCard" open>
          <summary>${escapeHtml(card.title || card.id)}</summary>
          ${(card.items || []).slice(0, 8).map(renderDetailItem).join("") || `<p class="projectionEmpty">Нет элементов.</p>`}
        </details>
      `).join("")}
    `;
  }

  function renderDetailItem(item) {
    if (!item || typeof item !== "object") return `<p>${escapeHtml(item)}</p>`;
    if (item.latex || item.token) return renderMiniFormula(item);
    if (item.definition_text) return `<p><strong>${escapeHtml(item.symbol || "определение")}</strong>: ${escapeHtml(item.definition_text)}</p>`;
    if (item.type && item.source_id) return `<p><strong>${escapeHtml(item.type)}</strong>: ${escapeHtml(item.source_id)} -> ${escapeHtml(item.target_id)}${item.evidence ? `<br><small>${escapeHtml(item.evidence)}</small>` : ""}</p>`;
    return `<pre>${escapeHtml(JSON.stringify(item, null, 2))}</pre>`;
  }

  function renderMiniFormula(item) {
    return `<div class="projectionMiniFormula"><strong>${escapeHtml(item.token || item.id || "formula")}</strong>${item.latex ? `<code>${escapeHtml(item.latex)}</code>` : ""}${item.plain_text ? `<span>${escapeHtml(item.plain_text)}</span>` : ""}</div>`;
  }

  function renderHiddenCounts(counts = {}) {
    return `<div class="projectionHiddenCounts"><span>скрыто узлов: ${counts.nodes || 0}</span><span>скрыто связей: ${counts.edges || 0}</span></div>`;
  }

  function renderIdChips(values = []) {
    return values.length ? values.map((value) => `<span class="projectionChip">${escapeHtml(value)}</span>`).join("") : `<span class="projectionEmpty">-</span>`;
  }

  function groupByLane(nodes) {
    const map = new Map();
    nodes.forEach((node) => {
      const lane = node.lane || node.type || "items";
      if (!map.has(lane)) map.set(lane, []);
      map.get(lane).push(node);
    });
    return map;
  }

  function translateProjectionLane(lane) {
    return {
      definitions: "Определения / контекст",
      variables: "Переменные",
      center: "Формула",
      dependencies: "Связанные формулы",
      root: "Формула",
      symbols: "Символы",
      operators: "Операторы",
      contexts: "Контексты",
    }[lane] || lane;
  }

  function createExplorer(result, target, options) {
    const state = {
      result,
      target,
      apiBase: options.apiBase || API_BASE_FALLBACK,
      activeCorpus: options.activeCorpus || null,
      compactVariableOnly: Boolean(options.compactVariableOnly),
      mode: options.initialMode || "overview",
      payload: null,
      abortController: null,
      cache: new Map(),
      selectedId: null,
      focusIds: null,
      focusMv: null,
      scale: 1,
      tx: 0,
      ty: 0,
      showMetaedges: false,
      hideTechnical: true,
      showLabels: true,
      topK: MODE_LIMITS[options.initialMode || "overview"] || 140,
      filters: {
        query: "",
        nodeTypes: new Set(),
        edgeTypes: new Set(),
        metavertexTypes: new Set(),
        minMass: 0,
        variableParts: new Set(["formula", "context", "definition", "dependency", "structure", "evidence", "issue"]),
      },
      variableQuery: "",
      formulaQuery: "",
      objects: new Map(),
      edges: [],
    };
    let applyTransform = () => {};

    return {
      renderShell,
      loadMode,
      setFocusId,
      focusNeighbors,
      focusParentMetavertex,
      focusPath,
      loadMode,
      objects: state.objects,
      edges: state.edges,
    };

    function renderShell() {
      target.innerHTML = `
        <div class="planetExplorer graphWorkspacePreset">
          <div class="planetTopbar graphModeTopbar">
            <label class="graphPresetSelect">Пресет
              <select data-preset-select>
                ${MODE_DEFS.map(([mode, label]) => `<option value="${mode}">${escapeHtml(label)}</option>`).join("")}
              </select>
            </label>
            <div class="graphModeSummary">
              <strong data-mode-title>Обзор статьи</strong>
              <span data-mode-description></span>
              <small data-mode-stats></small>
            </div>
            <div class="planetActions graphModeActions">
              ${typeof options.onBack === "function" ? `<button type="button" data-planet-command="back-projection">К проекциям</button>` : ""}
              <button type="button" data-planet-command="fit">Вписать</button>
              <button type="button" data-planet-command="save-image">Сохранить PNG</button>
              <button type="button" data-planet-command="toggle-filters">Скрыть фильтры</button>
              <button type="button" data-planet-command="toggle-details">Скрыть детали</button>
            </div>
          </div>
          <div class="planetWorkspace">
            <aside class="planetFilterPanel">
              <label class="planetSearch">Поиск <input data-planet-search type="search" placeholder="узел, формула, переменная" /></label>
              <div class="planetModeExplain" data-left-mode-description></div>
              <label>Минимальная значимость <input data-mass-filter type="range" min="0" max="80" value="0" /></label>
              <label>Лимит элементов <input data-limit-input type="number" min="40" max="900" step="10" value="140" /></label>
              <label class="graphToggleLine"><input data-label-toggle type="checkbox" checked />Показывать важные подписи</label>
              <label class="graphToggleLine"><input data-advanced-ui-toggle type="checkbox" />Расширенный режим</label>
              <div class="graphAdvancedModePanel" data-advanced-ui hidden>
                <strong>Ручной выбор режима</strong>
                <div class="planetModeBar">
                  ${MODE_DEFS.map(([mode, label, hint]) => `<button type="button" data-planet-mode="${mode}" title="${escapeAttribute(hint)}">${escapeHtml(label)}</button>`).join("")}
                </div>
                <button type="button" data-planet-command="toggle-metaedges">Показать метаребра</button>
              </div>
              <div class="planetVariablePanel" data-variable-panel hidden>
                <strong>Связи переменной</strong>
                <input data-variable-input type="search" placeholder="x, \\alpha, E, p_i" />
                <select data-variable-select></select>
                <label>Радиус <select data-variable-depth><option>1</option><option selected>2</option><option>3</option></select></label>
                <button type="button" data-variable-run>Построить связи</button>
                <div class="planetVariableChecks">
                  ${[
                    ["formula", "формулы"],
                    ["context", "контексты"],
                    ["definition", "только определения"],
                    ["dependency", "зависимости формул"],
                    ["structure", "разделы"],
                  ].map(([id, label]) => `<label><input type="checkbox" data-variable-part="${id}" checked />${label}</label>`).join("")}
                </div>
              </div>
              <div class="planetVariablePanel" data-formula-panel hidden>
                <strong>Контекст формулы</strong>
                <input data-formula-input type="search" placeholder="FORMULA_001, LaTeX fragment" />
                <select data-formula-select></select>
                <button type="button" data-formula-context-run>Показать контекст</button>
                <button type="button" data-formula-run>Открыть AST формулы</button>
              </div>
              <details class="planetFilterGroup"><summary>Быстрые пресеты</summary><div class="planetPresetList">
                <button type="button" data-preset="important">Важное</button>
                <button type="button" data-preset="semantic">Смысловые связи</button>
                <button type="button" data-preset="reset">Сброс</button>
              </div></details>
              <details class="planetFilterGroup"><summary>Расширенные фильтры</summary>
                <strong>Типы объектов</strong><div data-node-filters></div>
                <strong>Типы связей</strong><div data-edge-filters></div>
                <strong>Типы метавершин</strong><div data-mv-filters></div>
              </details>
              <div class="planetLegend" data-planet-legend></div>
            </aside>
            <div class="planetCanvasShell">
              <div class="planetWarning" data-planet-warning hidden></div>
              <div class="planetCanvasWrap" data-canvas-wrap></div>
            </div>
            <aside class="planetDetails" data-graph-details>Выберите узел или связь на графе.</aside>
          </div>
        </div>
      `;
      target.querySelectorAll("[data-preset-select]").forEach((select) => {
        select.addEventListener("change", () => loadMode(select.value));
      });
      target.querySelectorAll("[data-planet-mode]").forEach((button) => {
        button.addEventListener("click", () => loadMode(button.dataset.planetMode));
      });
      target.querySelector("[data-planet-command='back-projection']")?.addEventListener("click", () => options.onBack());
      target.querySelector("[data-planet-search]").addEventListener("input", (event) => {
        state.filters.query = event.target.value.trim().toLowerCase();
        state.focusIds = null;
        draw();
      });
      target.querySelector("[data-mass-filter]").addEventListener("input", (event) => {
        state.filters.minMass = Number(event.target.value || 0);
        draw();
      });
      target.querySelector("[data-limit-input]").addEventListener("change", (event) => {
        state.topK = Math.max(40, Math.min(900, Number(event.target.value || MODE_LIMITS[state.mode] || 140)));
        state.cache.clear();
        loadMode(state.mode, state.mode === "variable_focus" && state.variableQuery ? { variable: state.variableQuery, depth: target.querySelector("[data-variable-depth]").value || "2" } : {});
      });
      target.querySelector("[data-label-toggle]").addEventListener("change", (event) => {
        state.showLabels = event.target.checked;
        draw();
      });
      target.querySelector("[data-advanced-ui-toggle]").addEventListener("change", (event) => {
        target.querySelector("[data-advanced-ui]").hidden = !event.target.checked;
        target.querySelector(".planetExplorer").classList.toggle("advancedMode", event.target.checked);
      });
      target.querySelector("[data-planet-command='fit']").addEventListener("click", () => {
        state.scale = 1;
        state.tx = 0;
        state.ty = 0;
        applyTransform();
      });
      target.querySelector("[data-planet-command='save-image']").addEventListener("click", () => saveCurrentImage());
      target.querySelector("[data-planet-command='toggle-filters']").addEventListener("click", (event) => {
        const hidden = target.querySelector(".planetExplorer").classList.toggle("hideFilters");
        event.currentTarget.textContent = hidden ? "Показать фильтры" : "Скрыть фильтры";
        fitSoon(true);
      });
      target.querySelector("[data-planet-command='toggle-details']").addEventListener("click", (event) => {
        const hidden = target.querySelector(".planetExplorer").classList.toggle("hideDetails");
        event.currentTarget.textContent = hidden ? "Показать детали" : "Скрыть детали";
        fitSoon(true);
      });
      target.querySelector("[data-planet-command='toggle-metaedges']").addEventListener("click", (event) => {
        state.showMetaedges = !state.showMetaedges;
        event.currentTarget.classList.toggle("active", state.showMetaedges);
        draw();
      });
      target.querySelector("[data-variable-run]").addEventListener("click", () => runVariableSearch());
      target.querySelector("[data-formula-context-run]").addEventListener("click", () => runFormulaContext());
      target.querySelector("[data-formula-run]").addEventListener("click", () => runFormulaAst());
      target.querySelector("[data-variable-select]").addEventListener("change", (event) => {
        target.querySelector("[data-variable-input]").value = event.target.value || "";
      });
      target.querySelector("[data-formula-select]").addEventListener("change", (event) => {
        target.querySelector("[data-formula-input]").value = event.target.value || "";
      });
      target.querySelectorAll("[data-preset]").forEach((button) => {
        button.addEventListener("click", () => applyPreset(button.dataset.preset));
      });
      target.querySelectorAll("[data-variable-part]").forEach((input) => {
        input.addEventListener("change", () => {
          state.filters.variableParts = new Set([...target.querySelectorAll("[data-variable-part]:checked")].map((item) => item.dataset.variablePart));
          draw();
        });
      });
      window.addEventListener("resize", () => fitSoon(false));
    }

    function fitSoon(reset = false) {
      window.requestAnimationFrame(() => {
        if (reset) {
          state.scale = 1;
          state.tx = 0;
          state.ty = 0;
        }
        applyTransform();
        window.setTimeout(applyTransform, 0);
      });
    }

    function currentModeParams() {
      if (state.mode === "variable_focus" && state.variableQuery) {
        return { variable: state.variableQuery, depth: target.querySelector("[data-variable-depth]")?.value || "2" };
      }
      if ((state.mode === "formula_context" || state.mode === "formula_ast_focus") && state.formulaQuery) {
        return { formula: state.formulaQuery };
      }
      return {};
    }

    function updateModeSummary() {
      const def = MODE_DEF_BY_ID.get(state.mode) || MODE_DEF_BY_ID.get("overview");
      const title = state.payload?.title || def?.[1] || state.mode;
      const description = state.payload?.description || def?.[2] || "";
      const stats = state.payload?.stats || {};
      const visibleNodes = stats.visibleNodes ?? ((stats.node_count || 0) + (stats.metavertex_count || 0));
      const totalNodes = stats.totalNodes ?? ((stats.original_node_count || 0) + (stats.original_metavertex_count || 0));
      const visibleEdges = stats.visibleEdges ?? ((stats.edge_count || 0) + (stats.metaedge_count || 0));
      const totalEdges = stats.totalEdges ?? ((stats.original_edge_count || 0) + (stats.original_metaedge_count || 0));
      const titleNode = target.querySelector("[data-mode-title]");
      const descriptionNode = target.querySelector("[data-mode-description]");
      const statsNode = target.querySelector("[data-mode-stats]");
      const leftDescription = target.querySelector("[data-left-mode-description]");
      if (titleNode) titleNode.textContent = title;
      if (descriptionNode) descriptionNode.textContent = description;
      if (leftDescription) leftDescription.textContent = description;
      if (statsNode) {
        statsNode.textContent = totalNodes || totalEdges ? `видимо: ${visibleNodes}/${totalNodes} узлов, ${visibleEdges}/${totalEdges} связей` : "";
      }
      target.querySelectorAll("[data-planet-mode]").forEach((button) => button.classList.toggle("active", button.dataset.planetMode === state.mode));
    }

    async function loadMode(mode, params = {}) {
      if (!MODE_DEF_BY_ID.has(mode) && mode !== "corpus_graph") mode = "overview";
      state.mode = mode;
      state.topK = state.topK || MODE_LIMITS[mode] || 140;
      state.selectedId = null;
      state.focusIds = null;
      state.focusMv = null;
      state.scale = 1;
      state.tx = 0;
      state.ty = 0;
      target.querySelectorAll("[data-preset-select]").forEach((select) => {
        if ([...select.options].some((option) => option.value === mode)) select.value = mode;
      });
      const limitInput = target.querySelector("[data-limit-input]");
      if (limitInput) {
        state.topK = MODE_LIMITS[mode] || state.topK;
        limitInput.value = String(state.topK);
      }
      updateModeSummary();
      target.querySelector("[data-variable-panel]").hidden = mode !== "variable_focus";
      target.querySelector("[data-formula-panel]").hidden = mode !== "formula_context" && mode !== "formula_ast_focus";
      state.showMetaedges = mode === "metaedges_view";
      if (mode === "variable_focus" && !params.variable) {
        renderVariableIntro();
        return;
      }
      if ((mode === "formula_context" || mode === "formula_ast_focus") && !params.formula) {
        renderFormulaIntro();
      }
      if (mode === "corpus_graph") {
        await loadCorpusGraph();
        return;
      }
      await loadPayload(mode, params);
    }

    async function loadPayload(mode, params = {}) {
      if (mode === "variable_focus") state.variableQuery = String(params.variable || "").trim().toLowerCase();
      if (mode === "formula_ast_focus" || mode === "formula_context") state.formulaQuery = String(params.formula || "").trim().toLowerCase();
      const requestLimit = Math.max(40, Math.min(900, Number(state.topK || MODE_LIMITS[mode] || 140)));
      const cacheKey = JSON.stringify({ document_id: result.document_id, mode, limit: requestLimit, includeTechnical: !state.hideTechnical, ...params });
      if (state.cache.has(cacheKey)) {
        state.payload = state.cache.get(cacheKey);
        afterPayloadLoaded();
        return;
      }
      if (state.abortController) state.abortController.abort();
      state.abortController = new AbortController();
      target.querySelector("[data-canvas-wrap]").innerHTML = `<div class="planetLoading">Загрузка визуализации...</div>`;
      const url = new URL(`${state.apiBase}/api/results/${encodeURIComponent(result.document_id)}/visualization`);
      url.searchParams.set("mode", mode);
      url.searchParams.set("limit", String(requestLimit));
      if (params.variable) url.searchParams.set("variable", params.variable);
      if (params.formula) url.searchParams.set("formula", params.formula);
      if (params.depth) url.searchParams.set("depth", params.depth);
      url.searchParams.set("include_technical", String(!state.hideTechnical));
      try {
        const response = await fetch(url, { signal: state.abortController.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        state.cache.set(cacheKey, payload);
        state.payload = payload;
        afterPayloadLoaded();
      } catch (error) {
        if (error.name === "AbortError") return;
        target.querySelector("[data-canvas-wrap]").innerHTML = `<div class="planetLoading">Не удалось загрузить визуализацию: ${escapeHtml(error.message || "неизвестная ошибка")}</div>`;
      }
    }

    async function loadCorpusGraph() {
      if (!state.activeCorpus?.corpus_id) {
        target.querySelector("[data-canvas-wrap]").innerHTML = `<div class="planetLoading">Корпус пока не создан. Создайте корпус на странице пакетной обработки.</div>`;
        return;
      }
      const cacheKey = `corpus:${state.activeCorpus.corpus_id}`;
      if (state.cache.has(cacheKey)) {
        state.payload = normalizeCorpusPayload(state.cache.get(cacheKey));
        afterPayloadLoaded();
        return;
      }
      target.querySelector("[data-canvas-wrap]").innerHTML = `<div class="planetLoading">Загрузка корпуса...</div>`;
      try {
        const response = await fetch(`${state.apiBase}/api/corpus/${encodeURIComponent(state.activeCorpus.corpus_id)}/visualization`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        state.cache.set(cacheKey, payload);
        state.payload = normalizeCorpusPayload(payload);
        afterPayloadLoaded();
      } catch (error) {
        target.querySelector("[data-canvas-wrap]").innerHTML = `<div class="planetLoading">Не удалось загрузить корпус: ${escapeHtml(error.message || "неизвестная ошибка")}</div>`;
      }
    }

    function afterPayloadLoaded() {
      populateFilters();
      populateVariableSelect();
      populateFormulaSelect();
      renderLegend();
      updateModeSummary();
      draw();
    }

    function renderVariableIntro() {
      const wrap = target.querySelector("[data-canvas-wrap]");
      wrap.innerHTML = `
        <div class="planetVariableIntro">
          <strong>Связи переменной</strong>
          <p>Введите обозначение или выберите его из списка после первого запроса. Визуализация покажет центральный символ, формулы, контексты, определения, секции и связанные метаребра.</p>
        </div>
      `;
      target.querySelector("[data-graph-details]").innerHTML = "Введите переменную и нажмите «Построить связи».";
    }

    function runVariableSearch() {
      const value = target.querySelector("[data-variable-input]").value.trim() || target.querySelector("[data-variable-select]").value.trim();
      const depth = target.querySelector("[data-variable-depth]").value || "2";
      if (!value) {
        target.querySelector("[data-canvas-wrap]").innerHTML = `<div class="planetLoading">Введите переменную: например x, \\alpha, E или p_i.</div>`;
        return;
      }
      loadPayload("variable_focus", { variable: value, depth });
    }

    function renderFormulaIntro() {
      target.querySelector("[data-graph-details]").innerHTML = "Выберите формулу из списка или введите id/фрагмент LaTeX. Если ничего не выбрано, будет показана самая важная формула.";
    }

    function runFormulaAst() {
      const value = target.querySelector("[data-formula-input]").value.trim() || target.querySelector("[data-formula-select]").value.trim();
      loadPayload("formula_ast_focus", value ? { formula: value } : {});
    }

    function runFormulaContext() {
      const value = target.querySelector("[data-formula-input]").value.trim() || target.querySelector("[data-formula-select]").value.trim();
      loadPayload("formula_context", value ? { formula: value } : {});
    }

    function populateVariableSelect() {
      const select = target.querySelector("[data-variable-select]");
      const variables = state.payload?.available_variables || [];
      if (!select || !variables.length) return;
      select.innerHTML = `<option value="">найденные переменные</option>${variables.map((item) => `<option value="${escapeAttribute(item)}">${escapeHtml(item)}</option>`).join("")}`;
    }

    function populateFormulaSelect() {
      const select = target.querySelector("[data-formula-select]");
      const formulas = state.payload?.available_formulas || [];
      if (!select || !formulas.length) return;
      select.innerHTML = `<option value="">важные формулы</option>${formulas.map((item) => `<option value="${escapeAttribute(item.id)}">${escapeHtml(item.token || item.id)} — ${escapeHtml(item.label || "")}</option>`).join("")}`;
    }

    function applyPreset(preset) {
      if (preset === "important") {
        state.filters.minMass = 12;
        target.querySelector("[data-mass-filter]").value = "12";
      } else if (preset === "semantic") {
        state.filters.edgeTypes = new Set([...state.filters.edgeTypes].filter((type) => !TECHNICAL_EDGE_TYPES.has(type)));
      } else {
        state.filters.minMass = 0;
        target.querySelector("[data-mass-filter]").value = "0";
        state.filters.nodeTypes.clear();
        state.filters.edgeTypes.clear();
        state.filters.metavertexTypes.clear();
        populateFilters();
      }
      draw();
    }

    function populateFilters() {
      const payload = state.payload || {};
      const nodeTypes = unique([...(payload.nodes || []).map((node) => node.type), ...(payload.metavertices || []).map((mv) => mv.type)]);
      const edgeTypes = unique([...(payload.edges || []).map((edge) => edge.type), ...(payload.metaedges || []).map((edge) => edge.type)]);
      const mvTypes = unique((payload.metavertices || []).map((mv) => mv.type));
      syncSet(state.filters.nodeTypes, nodeTypes);
      syncSet(state.filters.edgeTypes, edgeTypes);
      syncSet(state.filters.metavertexTypes, mvTypes);
      renderFilterGroup("[data-node-filters]", nodeTypes, state.filters.nodeTypes, "node");
      renderFilterGroup("[data-edge-filters]", edgeTypes, state.filters.edgeTypes, "edge");
      renderFilterGroup("[data-mv-filters]", mvTypes, state.filters.metavertexTypes, "mv");
    }

    function renderFilterGroup(selector, values, selectedSet, kind) {
      const host = target.querySelector(selector);
      host.innerHTML = values.map((value) => `<label><input type="checkbox" data-filter-kind="${kind}" value="${escapeAttribute(value)}" ${selectedSet.has(value) ? "checked" : ""} />${escapeHtml(value)}</label>`).join("");
      host.querySelectorAll("input").forEach((input) => {
        input.addEventListener("change", () => {
          const set = kind === "node" ? state.filters.nodeTypes : kind === "edge" ? state.filters.edgeTypes : state.filters.metavertexTypes;
          if (input.checked) set.add(input.value);
          else set.delete(input.value);
          draw();
        });
      });
    }

    function draw() {
      const payload = state.payload;
      if (!payload) return;
      const prepared = preparePayload(payload);
      state.objects = prepared.objects;
      state.edges = prepared.edges;

      if (!prepared.nodes.length && !prepared.metavertices.length) {
        renderEmptyPayload(payload);
        return;
      }

      const dense = prepared.nodes.length + prepared.metavertices.length > 120;
      const layout = window.GraphLayout.computeLayout
        ? window.GraphLayout.computeLayout(payload, { ...prepared, compact: state.compactVariableOnly || dense, mode: state.mode })
        : window.GraphLayout.computePlanetaryLayout(payload, { ...prepared, compact: state.compactVariableOnly });
      const wrap = target.querySelector("[data-canvas-wrap]");
      wrap.innerHTML = "";
      const viewBox = contentViewBox(layout, prepared);
      const svg = createSvg("svg", {
        class: "planetCanvas",
        viewBox: `${viewBox.x} ${viewBox.y} ${viewBox.width} ${viewBox.height}`,
        preserveAspectRatio: "xMidYMid meet",
        role: "img",
      });
      svg.innerHTML = `
        <defs>
          <marker id="planetArrow" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z"></path></marker>
        </defs>
      `;
      const viewport = createSvg("g", { class: "planetViewport" });
      svg.appendChild(viewport);
      wrap.appendChild(svg);
      const drawnEdgeCount = drawEdges(viewport, prepared, layout);
      drawMetavertices(viewport, prepared, layout);
      drawNodes(viewport, prepared, layout);
      enablePanZoom(svg, viewport);
      fitSoon(true);
      renderWarning(payload, prepared.edges.length, drawnEdgeCount);
      if (state.selectedId && state.objects.has(state.selectedId)) {
        window.GraphDetails.renderDetails(target, publicApi(), state.selectedId);
      } else {
        target.querySelector("[data-graph-details]").innerHTML = "Выберите узел или связь на графе.";
      }
    }

    function preparePayload(payload) {
      const query = state.filters.query;
      const rawNodes = [...(payload.nodes || [])].filter((node) => state.filters.nodeTypes.has(node.type));
      const rawMvs = [...(payload.metavertices || [])].filter((mv) => state.filters.metavertexTypes.has(mv.type));
      const allowedMvIds = new Set(rawMvs.map((mv) => mv.id));
      let nodes = rawNodes.filter((node) => Number(node.mass || 0) >= state.filters.minMass);
      let metavertices = rawMvs.filter((mv) => Number(mv.mass || 0) >= state.filters.minMass || mv.type === "paper_metavertex");

      if (state.hideTechnical) {
        nodes = nodes.filter((node) => !TECHNICAL_TYPES.has(node.type));
      }
      if (!state.showMetaedges) {
        nodes = nodes.filter((node) => node.type !== "metaedge");
      }
      if (state.mode === "variable_focus") {
        nodes = nodes.filter(variablePartVisible);
        if (state.compactVariableOnly) {
          nodes = compactVariableNodes(nodes, payload.edges || []);
          metavertices = [];
        }
      }
      if (state.focusMv) {
        const contained = collectContained(payload, state.focusMv);
        nodes = nodes.filter((node) => contained.has(node.id));
        metavertices = metavertices.filter((mv) => mv.id === state.focusMv || contained.has(mv.id));
      }

      const objectIds = new Set([...nodes.map((node) => node.id), ...metavertices.map((mv) => mv.id)]);
      let edges = [...(payload.edges || [])].filter((edge) => objectIds.has(edge.source) && objectIds.has(edge.target) && state.filters.edgeTypes.has(edge.type));
      if (!state.showMetaedges) edges = edges.filter((edge) => !String(edge.type).startsWith("metaedge_"));

      if (query) {
        const matched = new Set();
        nodes.forEach((node) => {
          if (objectMatches(node, query)) matched.add(node.id);
        });
        metavertices.forEach((mv) => {
          if (objectMatches(mv, query)) matched.add(mv.id);
        });
        edges.forEach((edge) => {
          if (matched.has(edge.source)) matched.add(edge.target);
          if (matched.has(edge.target)) matched.add(edge.source);
        });
        nodes = nodes.filter((node) => matched.has(node.id));
        metavertices = metavertices.filter((mv) => matched.has(mv.id) || allowedMvIds.has(mv.parent));
        const ids = new Set([...nodes.map((node) => node.id), ...metavertices.map((mv) => mv.id)]);
        edges = edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target));
      }

      if (state.focusIds) {
        nodes = nodes.filter((node) => state.focusIds.has(node.id));
        metavertices = metavertices.filter((mv) => state.focusIds.has(mv.id));
        const ids = new Set([...nodes.map((node) => node.id), ...metavertices.map((mv) => mv.id)]);
        edges = edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target));
      }

      const objects = new Map();
      nodes.forEach((node) => objects.set(node.id, { kind: "node", item: node }));
      metavertices.forEach((mv) => objects.set(mv.id, { kind: "metavertex", item: mv }));
      return { nodes, metavertices, edges, objects };
    }

    function variablePartVisible(node) {
      const parts = state.filters.variableParts;
      if (node.type === "formula") return parts.has("formula");
      if (node.type === "context") return parts.has("context");
      if (node.type === "definition") return parts.has("definition");
      if (node.type === "paragraph" || node.type === "section" || node.type === "document") return parts.has("structure");
      if (node.type === "source" || node.type === "metaedge") return parts.has("evidence");
      if (node.type === "issue") return parts.has("issue");
      return true;
    }

    function compactVariableNodes(nodes, edges) {
      const base = nodes.filter((node) => ["formula", "paragraph", "symbol", "variable"].includes(node.type));
      const query = state.variableQuery;
      const formulas = base.filter((node) => node.type === "formula");
      const matchingFormulaIds = new Set(
        (query ? formulas.filter((node) => objectMatches(node, query)) : formulas).map((node) => node.id)
      );
      if (!matchingFormulaIds.size) {
        formulas.forEach((node) => matchingFormulaIds.add(node.id));
      }
      const relatedParagraphIds = new Set();
      (edges || []).forEach((edge) => {
        if (matchingFormulaIds.has(edge.source)) relatedParagraphIds.add(edge.target);
        if (matchingFormulaIds.has(edge.target)) relatedParagraphIds.add(edge.source);
      });
      return base.filter((node) => {
        if (node.type === "formula") return matchingFormulaIds.has(node.id);
        if (node.type === "paragraph") return relatedParagraphIds.has(node.id);
        return node.type === "symbol" || node.type === "variable";
      });
    }

    function drawMetavertices(viewport, prepared, layout) {
      const layer = createSvg("g", { class: "planetMetavertexLayer" });
      const dense = prepared.nodes.length + prepared.metavertices.length > 60 || layout.compact;
      prepared.metavertices
        .slice()
        .sort((left, right) => (left.depth || 0) - (right.depth || 0))
        .forEach((mv) => {
          const p = layout.metavertices.get(mv.id);
          if (!p) return;
          const rx = dense ? Math.min(48, Math.max(24, p.r * 0.42)) : p.r;
          const ry = dense ? Math.min(30, Math.max(18, p.r * 0.28)) : Math.max(46, p.r * 0.62);
          const group = createSvg("g", {
            class: `planetMetavertex ${cssClass(mv.type)} ${state.selectedId === mv.id ? "selected" : ""}`,
            transform: `translate(${p.x}, ${p.y})`,
            "data-object-id": mv.id,
          });
          group.appendChild(createSvg("ellipse", { rx, ry }));
          group.appendChild(createSvg("text", { class: "planetMvLabel", y: ry + 14, "text-anchor": "middle" }, compactLabel(mv.short_label || mv.label, dense ? 14 : 34)));
          if (!dense) {
            group.appendChild(createSvg("text", { class: "planetMvMeta", y: -Math.max(16, p.r * 0.36), "text-anchor": "middle" }, `${mv.type} | ${mv.metrics?.visible_contains_count ?? mv.contains?.length ?? 0}`));
          }
          attachObjectEvents(group, mv.id);
          enableObjectDrag(group, mv.id, layout, viewport, "metavertex");
          layer.appendChild(group);
        });
      viewport.appendChild(layer);
    }

    function drawEdges(viewport, prepared, layout) {
      const layer = createSvg("g", { class: "planetEdgeLayer" });
      const edges = edgesForRendering(prepared.edges, prepared.nodes.length + prepared.metavertices.length, state);
      edges.forEach((edge) => {
        const source = positionFor(edge.source, layout);
        const target = positionFor(edge.target, layout);
        if (!source || !target) return;
        const active = !state.selectedId || edge.source === state.selectedId || edge.target === state.selectedId;
        const path = createSvg("path", {
          d: window.GraphLayout.edgePath(source, target, String(edge.type).startsWith("metaedge") ? 0.34 : 0.12),
          class: `planetEdge ${cssClass(edge.type)} ${edge.visual?.bundled ? "bundled" : ""} ${active ? "active" : "dimmed"}`,
          stroke: EDGE_COLORS[edge.type] || "#94a3b8",
          "marker-end": edge.directed === false ? "" : "url(#planetArrow)",
          "data-source": edge.source,
          "data-target": edge.target,
        });
        path.appendChild(createSvg("title", {}, `${edge.source} -[${edge.type}]-> ${edge.target}`));
        layer.appendChild(path);
      });
      viewport.appendChild(layer);
      return edges.length;
    }

    function drawNodes(viewport, prepared, layout) {
      const layer = createSvg("g", { class: "planetNodeLayer" });
      prepared.nodes.forEach((node) => {
        const p = layout.nodes.get(node.id);
        if (!p) return;
        const group = createSvg("g", {
          class: `planetNode ${cssClass(node.type)} ${state.selectedId === node.id ? "selected" : ""}`,
          transform: `translate(${p.x}, ${p.y})`,
          tabindex: "0",
          role: "button",
          "data-object-id": node.id,
        });
        appendNodeShape(group, node, p.r);
        if (labelVisible(node, layout)) {
          group.appendChild(createSvg("text", { class: "planetNodeLabel", y: p.r + 14, "text-anchor": "middle" }, compactLabel(node.short_label || node.label, layout.compact ? 12 : 18)));
        }
        if (!layout.compact && node.type === "formula" && node.preview?.latex) {
          group.appendChild(createSvg("text", { class: "planetNodeMeta", y: p.r + 30, "text-anchor": "middle" }, compactLabel(node.preview.latex, 22)));
        }
        group.appendChild(createSvg("title", {}, `${node.type}: ${node.label}`));
        attachObjectEvents(group, node.id);
        enableObjectDrag(group, node.id, layout, viewport, "node");
        layer.appendChild(group);
      });
      viewport.appendChild(layer);
    }

    function appendNodeShape(group, node, radius) {
      const color = NODE_COLORS[node.type] || "#64748b";
      if (node.type === "symbol" || node.type === "variable") {
        group.appendChild(createSvg("polygon", { points: `0,-${radius} ${radius},0 0,${radius} -${radius},0`, fill: color }));
      } else if (node.type === "metaedge") {
        const h = radius * 0.86;
        group.appendChild(createSvg("polygon", { points: `${-radius},0 ${-radius / 2},-${h} ${radius / 2},-${h} ${radius},0 ${radius / 2},${h} ${-radius / 2},${h}`, fill: color }));
      } else if (node.type === "context" || node.type === "definition" || node.type === "paragraph") {
        group.appendChild(createSvg("rect", { x: -radius * 1.35, y: -radius * 0.72, width: radius * 2.7, height: radius * 1.44, rx: 8, fill: color }));
      } else {
        group.appendChild(createSvg("circle", { r: radius, fill: color }));
      }
      if (node.type === "formula") {
        group.appendChild(createSvg("text", { class: "planetFormulaIcon", y: 5, "text-anchor": "middle" }, "ƒ"));
      }
    }

    function labelVisible(node, layout) {
      if (state.selectedId === node.id) return true;
      const totalVisible = (layout.nodes?.size || 0) + (layout.metavertices?.size || 0);
      const priority = Number(node.visual?.labelPriority || node.importance || node.rank || 0);
      if (totalVisible > 180 && state.scale < 1.35) return priority >= 80;
      if (totalVisible > 100 && state.scale < 1.05) return priority >= 55;
      if (!state.showLabels) return Number(node.visual?.labelPriority || 0) >= 80;
      const policy = node.visual?.labelPolicy || "selected_or_zoom_in";
      if (policy === "always" || policy === "visible") return true;
      if (policy === "zoom_out") return true;
      if (policy === "medium_zoom") return !layout.compact || state.scale > 0.8;
      return !layout.compact && state.scale > 1.15;
    }

    function attachObjectEvents(group, id) {
      group.addEventListener("click", (event) => {
        if (group.dataset.suppressClick === "true") {
          event.preventDefault();
          event.stopPropagation();
          group.dataset.suppressClick = "false";
          return;
        }
        selectObject(id);
      });
      group.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          selectObject(id);
        }
      });
      group.addEventListener("mouseenter", () => highlightNeighborhood(id));
      group.addEventListener("mouseleave", () => target.querySelectorAll(".planetDimHover").forEach((item) => item.classList.remove("planetDimHover")));
    }

    function enableObjectDrag(group, id, layout, viewport, kind) {
      let drag = null;
      group.addEventListener("pointerdown", (event) => {
        if (event.button !== 0) return;
        event.stopPropagation();
        const position = kind === "node" ? layout.nodes.get(id) : layout.metavertices.get(id);
        if (!position) return;
        drag = {
          x: event.clientX,
          y: event.clientY,
          startX: position.x,
          startY: position.y,
          position,
          moved: false,
        };
        group.classList.add("dragging");
        group.setPointerCapture?.(event.pointerId);
      });
      group.addEventListener("pointermove", (event) => {
        if (!drag) return;
        const dx = (event.clientX - drag.x) / Math.max(0.1, state.scale);
        const dy = (event.clientY - drag.y) / Math.max(0.1, state.scale);
        if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
        drag.position.x = drag.startX + dx;
        drag.position.y = drag.startY + dy;
        group.setAttribute("transform", `translate(${drag.position.x}, ${drag.position.y})`);
        updateConnectedEdges(viewport, id, layout);
      });
      group.addEventListener("pointerup", (event) => {
        if (!drag) return;
        group.releasePointerCapture?.(event.pointerId);
        group.classList.remove("dragging");
        if (drag.moved) {
          event.preventDefault();
          event.stopPropagation();
          group.dataset.suppressClick = "true";
        }
        drag = null;
      });
      group.addEventListener("pointercancel", () => {
        drag = null;
        group.classList.remove("dragging");
      });
    }

    function updateConnectedEdges(viewport, id, layout) {
      viewport
        .querySelectorAll(`.planetEdge[data-source="${cssEscape(id)}"], .planetEdge[data-target="${cssEscape(id)}"]`)
        .forEach((path) => {
          const source = positionFor(path.dataset.source, layout);
          const target = positionFor(path.dataset.target, layout);
          const isMetaedge = String(path.getAttribute("class") || "").includes("metaedge");
          path.setAttribute("d", window.GraphLayout.edgePath(source, target, isMetaedge ? 0.34 : 0.12));
        });
    }

    function selectObject(id) {
      state.selectedId = id;
      target.querySelectorAll("[data-object-id]").forEach((node) => node.classList.toggle("selected", node.dataset.objectId === id));
      window.GraphDetails.renderDetails(target, publicApi(), id);
    }

    function highlightNeighborhood(id) {
      const ids = neighborSet(id);
      target.querySelectorAll("[data-object-id]").forEach((node) => {
        node.classList.toggle("planetDimHover", !ids.has(node.dataset.objectId));
      });
    }

    function setFocusId(id) {
      state.focusIds = new Set([id]);
      state.focusMv = null;
      draw();
      state.selectedId = id;
      window.GraphDetails.renderDetails(target, publicApi(), id);
    }

    function focusNeighbors(id) {
      state.focusIds = neighborSet(id);
      state.focusMv = null;
      draw();
    }

    function focusParentMetavertex(id) {
      const item = state.objects.get(id);
      if (!item) return;
      state.focusMv = item.item.type?.includes("metavertex") ? id : item.item.parent;
      state.focusIds = null;
      draw();
    }

    function focusPath(id) {
      const ids = new Set([id]);
      let current = state.objects.get(id)?.item?.parent;
      while (current && state.objects.has(current)) {
        ids.add(current);
        current = state.objects.get(current)?.item?.parent;
      }
      state.edges.forEach((edge) => {
        if (ids.has(edge.source)) ids.add(edge.target);
        if (ids.has(edge.target)) ids.add(edge.source);
      });
      state.focusIds = ids;
      state.focusMv = null;
      draw();
    }

    function neighborSet(id) {
      const ids = new Set([id]);
      state.edges.forEach((edge) => {
        if (edge.source === id) ids.add(edge.target);
        if (edge.target === id) ids.add(edge.source);
      });
      const item = state.objects.get(id);
      if (item?.item?.parent) ids.add(item.item.parent);
      return ids;
    }

    function positionFor(id, layout) {
      return layout.nodes.get(id) || layout.metavertices.get(id);
    }

    function collectContained(payload, mvId) {
      const result = new Set([mvId]);
      const mvByParent = new Map();
      (payload.metavertices || []).forEach((mv) => {
        if (mv.parent) {
          if (!mvByParent.has(mv.parent)) mvByParent.set(mv.parent, []);
          mvByParent.get(mv.parent).push(mv.id);
        }
      });
      const stack = [mvId];
      while (stack.length) {
        const current = stack.pop();
        const mv = (payload.metavertices || []).find((item) => item.id === current);
        (mv?.contains || []).forEach((id) => result.add(id));
        (mvByParent.get(current) || []).forEach((child) => {
          result.add(child);
          stack.push(child);
        });
      }
      return result;
    }

    function objectMatches(item, query) {
      return `${item.id} ${item.type} ${item.label} ${item.short_label} ${JSON.stringify(item.preview || {})}`.toLowerCase().includes(query);
    }

    function renderWarning(payload, totalEdges = 0, drawnEdgeCount = totalEdges) {
      const warning = target.querySelector("[data-planet-warning]");
      const stats = payload.stats || {};
      if (!stats.empty_reason && drawnEdgeCount >= totalEdges) {
        warning.hidden = true;
        return;
      }
      const hidden = Number(stats.hiddenNodes ?? 0) + Number(stats.hiddenEdges ?? 0);
      warning.hidden = false;
      const notice = payload.layout?.params?.notice || "Показан обзорный подграф. Используйте поиск, фильтры или раскрытие узла для детализации.";
      const rendered = drawnEdgeCount < totalEdges
        ? ` На холсте показано ${drawnEdgeCount} самых информативных связей из ${totalEdges}; остальные доступны через фильтры, поиск и выбор узла.`
        : "";
      warning.textContent = stats.empty_reason || `${notice}${hidden ? ` Скрыто ${hidden} элементов.` : ""}${rendered}`;
    }

    function renderEmptyPayload(payload) {
      const suggestions = payload.suggestions || [];
      target.querySelector("[data-canvas-wrap]").innerHTML = `
        <div class="planetLoading">
          ${escapeHtml(payload.stats?.empty_reason || "Нет данных для визуализации в этом режиме.")}
          ${suggestions.length ? `<div class="planetSuggestions">Похожие переменные: ${suggestions.map((item) => `<button type="button" data-suggest-variable="${escapeAttribute(item)}">${escapeHtml(item)}</button>`).join("")}</div>` : ""}
        </div>
      `;
      target.querySelectorAll("[data-suggest-variable]").forEach((button) => {
        button.addEventListener("click", () => {
          target.querySelector("[data-variable-input]").value = button.dataset.suggestVariable || "";
          runVariableSearch();
        });
      });
    }

    function renderLegend() {
      const payload = state.payload || {};
      const stats = payload.stats || {};
      target.querySelector("[data-planet-legend]").innerHTML = `
        <strong>Легенда</strong>
        <span>режим: ${escapeHtml(payload.title || payload.canonical_mode || payload.mode || "")}</span>
        <span>раскладка: ${escapeHtml(payload.layout?.type || "")}</span>
        <span>${stats.node_count || 0} узлов</span>
        <span>${stats.metavertex_count || 0} метавершин</span>
        <span>${stats.edge_count || 0} ребер</span>
        <span>${stats.metaedge_count || 0} метаребер</span>
      `;
    }

    function enablePanZoom(svg, viewport) {
      let dragStart = null;
      svg.addEventListener("wheel", (event) => {
        event.preventDefault();
        state.scale = Math.max(0.42, Math.min(2.8, state.scale + (event.deltaY < 0 ? 0.12 : -0.12)));
        applyTransform();
      });
      svg.addEventListener("pointerdown", (event) => {
        if (event.target.closest("[data-object-id]")) return;
        dragStart = { x: event.clientX, y: event.clientY, tx: state.tx, ty: state.ty };
        svg.setPointerCapture(event.pointerId);
      });
      svg.addEventListener("pointermove", (event) => {
        if (!dragStart) return;
        state.tx = dragStart.tx + event.clientX - dragStart.x;
        state.ty = dragStart.ty + event.clientY - dragStart.y;
        applyTransform();
      });
      svg.addEventListener("pointerup", () => {
        dragStart = null;
      });
      function localApply() {
        viewport.setAttribute("transform", `translate(${state.tx} ${state.ty}) scale(${state.scale})`);
      }
      applyTransform = localApply;
    }

    async function saveCurrentImage() {
      const svg = target.querySelector(".planetCanvas");
      if (!svg) return;
      const clone = svg.cloneNode(true);
      clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
      const source = new XMLSerializer().serializeToString(clone);
      const blob = new Blob([source], { type: "image/svg+xml;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const image = new Image();
      image.onload = () => {
        const box = svg.viewBox.baseVal;
        const canvas = document.createElement("canvas");
        canvas.width = Math.max(1, Math.round(box.width || svg.clientWidth || 1200));
        canvas.height = Math.max(1, Math.round(box.height || svg.clientHeight || 800));
        const ctx = canvas.getContext("2d");
        ctx.fillStyle = "#fff8f1";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(image, 0, 0);
        URL.revokeObjectURL(url);
        canvas.toBlob((png) => {
          if (!png) return;
          const link = document.createElement("a");
          link.href = URL.createObjectURL(png);
          link.download = `${state.result?.document_id || "metagraph"}_${state.mode}.png`;
          document.body.appendChild(link);
          link.click();
          URL.revokeObjectURL(link.href);
          link.remove();
        }, "image/png");
      };
      image.src = url;
    }

    function publicApi() {
      return {
        objects: state.objects,
        edges: state.edges,
        setFocusId,
        focusNeighbors,
        focusParentMetavertex,
        focusPath,
        loadMode,
      };
    }
  }

  function normalizeCorpusPayload(payload) {
    const nodes = [];
    const edges = [];
    (payload.elements || []).forEach((element) => {
      const data = element.data || {};
      if (data.source && data.target) {
        edges.push({
          id: data.id,
          source: data.source,
          target: data.target,
          type: data.type || data.label || "related",
          directed: true,
          weight: 1,
          attributes: data.attributes || data,
        });
      } else {
        nodes.push({
          id: data.id,
          type: data.type || "entity",
          label: data.label || data.id,
          short_label: data.label || data.id,
          mass: 1,
          rank: 1,
          depth: 0,
          importance: 0.4,
          attributes: data.attributes || data,
          preview: { latex: data.latex, text: data.text },
        });
      }
    });
    return {
      document_id: payload.corpus_id || "corpus",
      mode: "corpus_graph",
      layout: { type: "planetary_metagraph", version: "1.0", params: { theory: "визуализация.pdf" } },
      nodes,
      metavertices: [],
      edges,
      metaedges: [],
      stats: payload.stats || {},
      legend: payload.legend || {},
    };
  }

  function contentViewBox(layout, prepared) {
    const boxes = [];
    (prepared.nodes || []).forEach((node) => {
      const point = layout.nodes.get(node.id);
      if (!point) return;
      const r = Math.max(26, point.r || 18);
      boxes.push([point.x - r * 2.2, point.y - r * 2.2, point.x + r * 2.2, point.y + r * 2.2]);
    });
    (prepared.metavertices || []).forEach((mv) => {
      const point = layout.metavertices.get(mv.id);
      if (!point) return;
      const r = Math.max(44, Math.min(point.r || 80, 180));
      boxes.push([point.x - r * 1.15, point.y - r * 0.85, point.x + r * 1.15, point.y + r * 0.85]);
    });
    if (!boxes.length) return { x: 0, y: 0, width: layout.width || 1200, height: layout.height || 720 };
    let minX = Math.min(...boxes.map((box) => box[0]));
    let minY = Math.min(...boxes.map((box) => box[1]));
    let maxX = Math.max(...boxes.map((box) => box[2]));
    let maxY = Math.max(...boxes.map((box) => box[3]));
    const pad = 96;
    minX -= pad;
    minY -= pad;
    maxX += pad;
    maxY += pad;
    const width = Math.max(640, maxX - minX);
    const height = Math.max(420, maxY - minY);
    return { x: minX, y: minY, width, height };
  }

  function edgesForRendering(edges, objectCount, explorerState) {
    if (!edges.length || explorerState.selectedId) return edges;
    const capByMode = {
      overview: 90,
      metagraph_planetary_overview: objectCount > 130 ? 120 : 150,
      formula_semantic_network: objectCount > 150 ? 160 : 210,
      formula_context: 150,
      variable_focus: 160,
      metaedges_view: 180,
    };
    const cap = capByMode[explorerState.mode] || 140;
    if (edges.length <= cap) return edges;
    return [...edges].sort((left, right) => edgeRenderPriority(right) - edgeRenderPriority(left)).slice(0, cap);
  }

  function edgeRenderPriority(edge) {
    const typeScore = {
      has_definition: 9,
      defined_as: 9,
      has_context: 8,
      variable_defined_in_context: 8,
      formula_contains_variable: 7,
      has_symbol: 6,
      depends_on: 5,
      metaedge_source: 4,
      metaedge_target: 4,
      contains: 1,
    };
    return (typeScore[edge.type] || 3) + Number(edge.weight || 1);
  }

  function cleanup(target) {
    const previous = explorers.get(target);
    if (previous?.abortController) previous.abortController.abort();
    target.innerHTML = "";
  }

  function createSvg(tag, attrs = {}, text = "") {
    const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.entries(attrs).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") element.setAttribute(key, value);
    });
    if (text) element.textContent = text;
    return element;
  }

  function unique(values) {
    return [...new Set(values.filter(Boolean))].sort();
  }

  function syncSet(set, values) {
    if (!set.size) values.forEach((value) => set.add(value));
    [...set].forEach((value) => {
      if (!values.includes(value)) set.delete(value);
    });
    if (!set.size) values.forEach((value) => set.add(value));
  }

  function compactLabel(value, limit) {
    const text = String(value || "");
    return text.length <= limit ? text : `${text.slice(0, limit - 3)}...`;
  }

  function cssClass(value) {
    return String(value || "unknown").replace(/[^a-z0-9_-]+/gi, "_");
  }

  function cssEscape(value) {
    if (window.CSS?.escape) return window.CSS.escape(value);
    return String(value || "").replace(/["\\]/g, "\\$&");
  }

  function escapeHtml(value) {
    return window.GraphDetails ? window.GraphDetails.escapeHtml(value) : String(value ?? "");
  }

  function escapeAttribute(value) {
    return window.GraphDetails ? window.GraphDetails.escapeAttribute(value) : escapeHtml(value);
  }

  window.GraphVisualization = {
    renderMetagraphVisualization,
  };
})();
