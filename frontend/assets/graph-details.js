(function () {
  "use strict";

  function renderDetails(root, explorer, selectedId) {
    const sidebar = root.querySelector("[data-graph-details]");
    if (!sidebar) return;
    const item = explorer.objects.get(selectedId);
    if (!item) {
      sidebar.innerHTML = `<div class="planetEmpty">Выберите узел, метавершину или метаребро.</div>`;
      return;
    }
    const payload = item.item;
    const preview = payload.preview || {};
    const attrs = payload.attributes || {};
    const relatedEdges = explorer.edges.filter((edge) => edge.source === selectedId || edge.target === selectedId).slice(0, 18);
    const breadcrumbs = buildBreadcrumbs(explorer, payload);
    sidebar.innerHTML = `
      <div class="planetDetailHeader">
        <span class="planetTypeBadge ${cssClass(payload.type)}">${escapeHtml(payload.type || item.kind)}</span>
        <strong>${escapeHtml(payload.short_label || payload.label || payload.id)}</strong>
        <small>${escapeHtml(payload.id)}</small>
      </div>
      ${breadcrumbs.length ? `<div class="planetBreadcrumbs">${breadcrumbs.map((crumb) => `<button type="button" data-focus-id="${escapeAttribute(crumb.id)}">${escapeHtml(crumb.label)}</button>`).join("<span>/</span>")}</div>` : ""}
      <div class="planetDetailActions">
        <button type="button" data-planet-action="neighbors">Показать соседей</button>
        <button type="button" data-planet-action="focus-metavertex">Сфокусироваться на метавершине</button>
        <button type="button" data-planet-action="path">Показать путь к документу/секции</button>
        ${payload.type === "formula" ? `<button type="button" data-planet-action="formula-context">Открыть контекст формулы</button>` : ""}
        ${payload.type === "formula" ? `<button type="button" data-planet-action="ast">Показать AST формулы</button>` : ""}
        ${payload.type === "symbol" || payload.type === "variable" ? `<button type="button" data-planet-action="variable-focus">Показать связи переменной</button>` : ""}
        ${payload.type === "metaedge" ? `<button type="button" data-planet-action="metaedge-subgraph">Показать как подграф</button>` : ""}
      </div>
      ${preview.latex ? `<div class="planetLatex" data-latex="${escapeAttribute(preview.latex)}" data-display="true"></div>` : ""}
      ${preview.text ? `<div class="planetPreviewText">${escapeHtml(shortText(preview.text, 900))}</div>` : ""}
      <div class="planetMetrics">
        ${metric("масса", payload.mass)}
        ${metric("ранг", payload.rank)}
        ${metric("глубина", payload.depth)}
        ${metric("важность", payload.importance)}
        ${metric("уровень", payload.visual?.level)}
        ${metric("причина важности", payload.visual?.importanceReason)}
        ${metric("страница", preview.page)}
        ${metric("токен", preview.token)}
      </div>
      ${variableSummary(payload)}
      ${metavertexSummary(payload)}
      ${metaedgeSummary(payload)}
      <details open>
        <summary>Связи</summary>
        <div class="planetRelationList">
          ${relatedEdges.length ? relatedEdges.map((edge) => `<div>${escapeHtml(edge.source)} <b>${escapeHtml(edge.type)}</b> ${escapeHtml(edge.target)}</div>`).join("") : "<div>Нет видимых связей.</div>"}
        </div>
      </details>
      <details>
        <summary>Атрибуты</summary>
        <pre>${escapeHtml(JSON.stringify(attrs, null, 2))}</pre>
      </details>
    `;
    sidebar.querySelectorAll("[data-focus-id]").forEach((button) => {
      button.addEventListener("click", () => {
        explorer.setFocusId(button.dataset.focusId);
      });
    });
    sidebar.querySelectorAll("[data-planet-action]").forEach((button) => {
      button.addEventListener("click", () => {
        const action = button.dataset.planetAction;
        if (action === "neighbors") explorer.focusNeighbors(selectedId);
        if (action === "focus-metavertex") explorer.focusParentMetavertex(selectedId);
        if (action === "path") explorer.focusPath(selectedId);
        if (action === "formula-context") explorer.loadMode?.("formula_context", { formula: selectedId });
        if (action === "ast") explorer.loadMode?.("formula_ast_focus", { formula: selectedId });
        if (action === "variable-focus") explorer.loadMode?.("variable_focus", { variable: payload.attributes?.normalized_symbol || payload.label || selectedId });
        if (action === "metaedge-subgraph") explorer.focusNeighbors(selectedId);
      });
    });
    renderLatex(sidebar);
  }

  function buildBreadcrumbs(explorer, payload) {
    const result = [];
    let current = payload.parent;
    const seen = new Set();
    while (current && !seen.has(current)) {
      seen.add(current);
      const item = explorer.objects.get(current);
      if (!item) break;
      result.unshift({ id: current, label: item.item.short_label || item.item.label || current });
      current = item.item.parent;
    }
    if (payload.id) result.push({ id: payload.id, label: payload.short_label || payload.label || payload.id });
    return result;
  }

  function variableSummary(payload) {
    if (payload.type !== "symbol" && payload.type !== "variable") return "";
    const attrs = payload.attributes || {};
    const formulas = attrs.formula_ids || [];
    const contexts = attrs.context_ids || [];
    const definitions = attrs.possible_definitions || [];
    const sections = attrs.section_ids || [];
    const ambiguity = Math.min(1, Math.max(0, (new Set(definitions.map((item) => String(item.definition_text || item.evidence || "").toLowerCase())).size - 1) * 0.25 + Math.max(0, sections.length - 1) * 0.12));
    return `
      <div class="planetVariableSummary">
        <strong>Переменная</strong>
        <span>формулы: ${formulas.length}</span>
        <span>контексты: ${contexts.length}</span>
        <span>определения: ${definitions.length}</span>
        <span>секции: ${sections.length}</span>
        <span>неоднозначность: ${ambiguity.toFixed(2)}</span>
      </div>
      ${definitions.length ? `<details open><summary>Найденные определения</summary>${definitions.map((item) => `<div class="planetDefinition">${escapeHtml(shortText(item.definition_text || item.evidence || "", 320))}</div>`).join("")}</details>` : ""}
    `;
  }

  function metavertexSummary(payload) {
    if (!String(payload.type || "").includes("metavertex")) return "";
    const metrics = payload.metrics || {};
    return `
      <div class="planetVariableSummary">
        <strong>Метавершина</strong>
        <span>размер: ${(payload.contains || []).length}</span>
        <span>видимых: ${metrics.visible_contains_count ?? 0}</span>
        <span>скрытых: ${metrics.hidden_contains_count ?? 0}</span>
        <span>полная: ${metrics.complete ? "да" : "нет"}</span>
        <span>входов: ${(payload.entry_points || []).length}</span>
        <span>выходов: ${(payload.exit_points || []).length}</span>
      </div>
      ${(payload.contains || []).length ? `<details><summary>Содержимое, первые элементы</summary><div class="planetRelationList">${payload.contains.slice(0, 24).map((id) => `<div>${escapeHtml(id)}</div>`).join("")}</div></details>` : ""}
    `;
  }

  function metaedgeSummary(payload) {
    if (payload.type !== "metaedge") return "";
    const metaedge = payload.attributes || {};
    const visual = metaedge.visual || payload.visual || {};
    return `
      <div class="planetVariableSummary">
        <strong>Метаребро</strong>
        <span>тип: ${escapeHtml(metaedge.type || payload.label || "")}</span>
        <span>источников: ${visual.source_size ?? (metaedge.source_set || []).length}</span>
        <span>целей: ${visual.target_size ?? (metaedge.target_set || []).length}</span>
        <span>посредников: ${visual.mediator_count ?? 0}</span>
        <span>подтверждений: ${visual.evidence_count ?? 0}</span>
        <span>сложность: ${visual.metaedge_complexity ?? ""}</span>
      </div>
      ${metaedgeList("набор источников", metaedge.source_set)}
      ${metaedgeList("набор целей", metaedge.target_set)}
      ${metaedgeList("узлы-посредники", metaedge.mediator_nodes)}
      ${metaedgeList("метавершины-посредники", metaedge.mediator_metavertices)}
    `;
  }

  function metaedgeList(label, values) {
    if (!values?.length) return "";
    return `<details><summary>${escapeHtml(label)}</summary><div class="planetRelationList">${values.slice(0, 40).map((value) => `<div>${escapeHtml(value)}</div>`).join("")}</div></details>`;
  }

  function metric(label, value) {
    if (value === undefined || value === null || value === "") return "";
    return `<span><b>${escapeHtml(label)}</b>${escapeHtml(String(value))}</span>`;
  }

  function renderLatex(root) {
    if (typeof window.renderKatex === "function") {
      window.renderKatex(root);
      return;
    }
    if (!window.katex) return;
    root.querySelectorAll("[data-latex]").forEach((node) => {
      try {
        window.katex.render(node.dataset.latex || "", node, { throwOnError: false, displayMode: node.dataset.display === "true" });
      } catch (_error) {
        node.textContent = node.dataset.latex || "";
      }
    });
  }

  function shortText(value, limit) {
    const text = String(value || "").replace(/\s+/g, " ").trim();
    return text.length <= limit ? text : `${text.slice(0, limit - 3)}...`;
  }

  function cssClass(value) {
    return String(value || "unknown").replace(/[^a-z0-9_-]+/gi, "_");
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function escapeAttribute(value) {
    return escapeHtml(value).replaceAll("`", "&#096;");
  }

  window.GraphDetails = {
    renderDetails,
    renderLatex,
    escapeHtml,
    escapeAttribute,
    shortText,
  };
})();
