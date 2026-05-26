const API_BASE = window.FG_API_BASE || (["5173", "4175"].includes(window.location.port) ? "http://127.0.0.1:8000" : window.location.origin);
const FORMULA_ADDITIONAL_CHECK_LABEL = "Дополнительная проверка";

const ARXIV_ID_PATTERN = /(?:^|[^A-Za-z0-9])((?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?\/\d{7})(?:v\d+)?)(?=[^A-Za-z0-9]|$)/i;

const state = {
  result: null,
  overlayMode: "smart",
  selectedToken: null,
  variableSearch: null,
  formulaProjectionCache: new Map(),
  pendingFormulaNavigation: null,
  activePage: "home",
  visualizationCache: new Map(),
  deferredRenderDone: new Map(),
  currentJobId: null,
  jobPollTimer: null,
  lastProgress: 0,
  activeBatch: null,
  batchPollTimer: null,
  resultCache: new Map(),
  activeCorpus: null,
  viewMode: "document",
  textRenderSeq: 0,
  progressLog: [],
  historyLoaded: false,
  randomArxivIds: [],
  texSourceMode: false,
};

const PAGE_META = {
  home: ["Главная", "Быстрый старт обработки научных статей и переход к основным рабочим режимам."],
  upload: ["Загрузка документа", "Выберите PDF, изображение или один/несколько arXiv ID."],
  history: ["История запусков", "Ранее обработанные документы из локальной истории и сохранённых результатов."],
  document: ["Результат документа", "Сводка по обработанному документу, источникам данных и найденным предупреждениям."],
  text: ["Читаемый текст", "Восстановленный текст с отрендеренными формулами без служебных токенов."],
  tokens: ["Токены формул", "Текстовые фрагменты и формульные токены, которые связывают документ с метаграфом."],
  formulas: ["Формулы", "Извлеченный LaTeX, качество распознавания и найденные обозначения."],
  variables: ["Переменные и контекст", "Поиск обозначений, определения, области действия и локальные связи."],
  visualization: ["Визуализация", "Единое рабочее поле для метаграфа, контекстов и структуры документа."],
  process: ["Процесс обработки", "Пошаговая диагностика обработки: статусы, источники, тайминги, входы и выходы этапов."],
  metrics: ["Аналитика", "Метрики документа, пакета или корпуса: связность, покрытие контекстом и качество извлечения."],
  reader: ["Размеченный текст", "Токенизированная реконструкция параграфов для проверки связей формул."],
  outputs: ["Артефакты", "JSON-результаты, метаграф, визуализация и индексы переменных."],
  batch: ["Пакетная обработка", "Пакетная обработка, прогресс по файлам и подготовка корпуса из нескольких результатов."],
};

const apiStatus = document.querySelector("#apiStatus");
const uploadForm = document.querySelector("#uploadForm");
const fileInput = document.querySelector("#fileInput");
const fileName = document.querySelector("#fileName");
let submitButton = document.querySelector("#submitButton");
const overlayModal = document.querySelector("#overlayModal");
const overlayModalViewport = document.querySelector("#overlayModalViewport");
const sidebarToggle = document.querySelector("#sidebarToggle");
const sidebarBackdrop = document.querySelector("#sidebarBackdrop");
const historyPanel = document.querySelector("#historyPage");
const randomArxivButton = document.querySelector("#randomArxivButton");
const sidebar = document.querySelector(".sidebar");
const headerDocumentSelector = document.querySelector("#headerDocumentSelector");

function setSidebarOpen(open) {
  document.body.classList.toggle("sidebarOpen", open);
  if (sidebarBackdrop) sidebarBackdrop.hidden = !open;
  if (sidebarToggle) sidebarToggle.setAttribute("aria-label", open ? "Закрыть навигацию" : "Открыть навигацию");
}

sidebarToggle?.addEventListener("click", () => setSidebarOpen(!document.body.classList.contains("sidebarOpen")));
sidebarBackdrop?.addEventListener("click", () => setSidebarOpen(false));
randomArxivButton?.addEventListener("click", () => submitRandomArxivBatch());
document.querySelectorAll("[data-home-action]").forEach((button) => {
  button.addEventListener("click", () => {
    const action = button.dataset.homeAction;
    if (action === "history") {
      activatePage("history");
      return;
    }
    activatePage("upload");
  });
});
const overlayModalMeta = document.querySelector("#overlayModalMeta");

function parseArxivIds(value) {
  return [...new Set(String(value || "")
    .split(/[\s,;]+/)
    .map((item) => item.trim())
    .filter(Boolean))];
}

function extractArxivId(value) {
  const match = String(value || "").match(ARXIV_ID_PATTERN);
  return match ? match[1] : "";
}

function deriveArxivIdsFromFiles(files) {
  return [...new Set((files || []).map((file) => extractArxivId(file?.name)).filter(Boolean))];
}

function looksLikeArxivId(value) {
  return Boolean(extractArxivId(value));
}

function shouldUseTexSourceOnly() {
  if (!document.querySelector("#preferTexSource")?.checked) return false;
  const arxivIds = parseArxivIds(document.querySelector("#arxivId")?.value || "");
  if (arxivIds.length) return true;
  return deriveArxivIdsFromFiles([...(fileInput?.files || [])]).length > 0;
}

function selectedOcrMode() {
  return shouldUseTexSourceOnly() ? "tex_source" : (document.querySelector("#ocrMode")?.value || "standard");
}

function clipboardFiles(event) {
  const items = [...(event.clipboardData?.items || [])];
  const files = [...(event.clipboardData?.files || [])];
  items.forEach((item, index) => {
    if (item.kind !== "file") return;
    const file = item.getAsFile();
    if (!file) return;
    if (file.name) {
      files.push(file);
      return;
    }
    const extension = file.type.includes("png") ? "png" : file.type.includes("jpeg") ? "jpg" : "bin";
    files.push(new File([file], `clipboard_${Date.now()}_${index}.${extension}`, { type: file.type || "application/octet-stream" }));
  });
  return files;
}

document.querySelectorAll("[data-overlay-close], #overlayModalClose").forEach((element) => {
  element.addEventListener("click", closeOverlayModal);
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && overlayModal && !overlayModal.hidden) {
    closeOverlayModal();
  }
});

fileInput.addEventListener("change", () => {
  const files = [...fileInput.files];
  fileName.textContent = files.length > 1 ? `${files.length} документов выбрано` : files[0]?.name || "Выберите PDF, вставьте файл из буфера или укажите arXiv ID";
  const uploadStatus = document.querySelector("#uploadBatchStatus");
  if (uploadStatus && files.length) uploadStatus.innerHTML = "";
});

document.addEventListener("paste", (event) => {
  const files = clipboardFiles(event);
  if (!files.length || !fileInput) return;
  const dataTransfer = new DataTransfer();
  [...fileInput.files].forEach((file) => dataTransfer.items.add(file));
  files.forEach((file) => dataTransfer.items.add(file));
  fileInput.files = dataTransfer.files;
  fileInput.dispatchEvent(new Event("change"));
});

document.querySelectorAll(".pageButton").forEach((button) => {
  button.addEventListener("click", () => {
    if (button.dataset.page === "outputs") {
      openArtifactsModal();
      setSidebarOpen(false);
      document.body.classList.add("sidebarHoverLocked");
      return;
    }
    activatePage(button.dataset.page);
    setSidebarOpen(false);
    document.body.classList.add("sidebarHoverLocked");
  });
});

sidebar?.addEventListener("mouseleave", () => {
  document.body.classList.remove("sidebarHoverLocked");
});

uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const files = [...(fileInput?.files || [])];
  const typedArxivIds = parseArxivIds(document.querySelector("#arxivId").value);
  const inferredArxivIds = typedArxivIds.length ? [] : deriveArxivIdsFromFiles(files);
  const arxivIds = typedArxivIds.length ? typedArxivIds : inferredArxivIds;
  state.texSourceMode = shouldUseTexSourceOnly();
  updateNavAvailability(state.result);
  if (!files[0] && !arxivIds.length) {
    showUploadMessage("Выберите файл или укажите arXiv ID.");
    return;
  }
  if (files.length > 1 || (!files[0] && arxivIds.length > 1)) {
    await submitBatchFromMainForm();
    return;
  }

  const formData = new FormData();
  if (files[0]) formData.append("file", files[0]);
  formData.append("ocr_mode", selectedOcrMode());
  formData.append("device_mode", document.querySelector("#deviceMode").value);
  formData.append("ocr_lang", document.querySelector("#ocrLang").value);
  formData.append("max_pages", document.querySelector("#maxPages").value);
  formData.append("render_dpi", document.querySelector("#renderDpi").value);
  formData.append("arxiv_id", arxivIds[0] || "");
  formData.append("prefer_tex_source", document.querySelector("#preferTexSource").checked ? "true" : "false");

  submitButton.disabled = true;
  showWarnings([]);
  startProgress();
  try {
    const response = await fetchWithTimeout(`${API_BASE}/api/process/submit`, {
      method: "POST",
      body: formData,
    }, 15 * 60 * 1000);
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }
    const payload = await response.json();
    state.currentJobId = payload.job_id;
    await waitForProcessingJob(payload.job_id);
  } catch (error) {
    showUploadMessage(`Ошибка: ${error.message}`);
    showWarnings([`Ошибка: ${error.message}`]);
  } finally {
    stopProgress();
  }
});

async function submitBatchFromMainForm() {
  const files = [...fileInput.files];
  const arxivIds = parseArxivIds(document.querySelector("#arxivId")?.value || "");
  state.randomArxivIds = arxivIds;
  state.texSourceMode = shouldUseTexSourceOnly();
  updateNavAvailability(state.result);
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  if (arxivIds.length) formData.append("arxiv_ids", arxivIds.join("\n"));
  formData.append("ocr_mode", selectedOcrMode());
  formData.append("device_mode", document.querySelector("#deviceMode").value);
  formData.append("ocr_lang", document.querySelector("#ocrLang").value);
  formData.append("max_pages", document.querySelector("#maxPages").value);
  formData.append("render_dpi", document.querySelector("#renderDpi").value);
  formData.append("arxiv_id", arxivIds[0] || "");
  formData.append("prefer_tex_source", document.querySelector("#preferTexSource").checked ? "true" : "false");

  submitButton.disabled = true;
  showWarnings([]);
  startProgress();
  try {
    const response = await fetchWithTimeout(`${API_BASE}/api/process/batch/submit`, { method: "POST", body: formData }, 15 * 60 * 1000);
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }
    const batch = await response.json();
    state.viewMode = "batch";
    state.randomArxivIds = batch.arxiv_ids || [];
    state.activeBatch = batch;
    activatePage("upload");
    renderBatchStatus(batch);
    await waitForBatchJob(batch.batch_id);
  } catch (error) {
    showUploadMessage(`Ошибка пакета: ${error.message}`);
    showWarnings([`Ошибка пакета: ${error.message}`]);
  } finally {
    stopProgress();
  }
}

async function submitRandomArxivBatch() {
  const count = Math.max(1, Math.min(20, Number(document.querySelector("#randomArxivCount")?.value || 3)));
  const commonMaxPages = Number(document.querySelector("#maxPages")?.value || 0);
  const payload = {
    count,
    category: document.querySelector("#randomArxivCategory")?.value || "math",
    device_mode: document.querySelector("#deviceMode")?.value || "auto",
    ocr_lang: document.querySelector("#ocrLang")?.value || "auto",
    max_pages: commonMaxPages > 0 ? commonMaxPages : 20,
    render_dpi: Number(document.querySelector("#renderDpi")?.value || 300),
    prefer_tex_source: Boolean(document.querySelector("#preferTexSource")?.checked),
    russian_only: false,
  };

  randomArxivButton.disabled = true;
  state.randomArxivIds = [];
  state.texSourceMode = Boolean(document.querySelector("#preferTexSource")?.checked);
  updateNavAvailability(state.result);
  showWarnings([]);
  startProgress();
  showUploadMessage(`Подбираю ${count} случайн${count === 1 ? "ую" : "ые"} стать${count === 1 ? "ю" : "и"} arXiv...`);
  try {
    const response = await fetchWithTimeout(`${API_BASE}/api/arxiv/random-process`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }, 60000);
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }
    const batch = await response.json();
    state.viewMode = "batch";
    state.activeBatch = batch;
    activatePage("upload");
    renderBatchStatus(batch);
    await waitForBatchJob(batch.batch_id);
  } catch (error) {
    showUploadMessage(`Ошибка случайной подборки arXiv: ${error.message}`);
    showWarnings([`Ошибка случайной подборки arXiv: ${error.message}`]);
  } finally {
    randomArxivButton.disabled = false;
    stopProgress();
  }
}

function showUploadMessage(message) {
  const target = document.querySelector("#uploadBatchStatus");
  if (target) target.innerHTML = `<div class="batchOverview"><strong>${escapeHtml(message)}</strong></div>`;
}

function showCompletionNotification(title, detail = "") {
  const existing = document.querySelector("#completionNotice");
  existing?.remove();
  const notice = document.createElement("div");
  notice.id = "completionNotice";
  notice.className = "completionNotice";
  notice.innerHTML = `
    <strong>${escapeHtml(title)}</strong>
    ${detail ? `<span>${escapeHtml(detail)}</span>` : ""}
    <button type="button" aria-label="Закрыть уведомление">Закрыть</button>
  `;
  document.body.appendChild(notice);
  notice.querySelector("button")?.addEventListener("click", () => notice.remove());
  window.setTimeout(() => notice.remove(), 9000);
}

async function checkApi() {
  try {
    const response = await fetch(`${API_BASE}/api/health`);
    if (!response.ok) throw new Error("API unavailable");
    const health = await response.json();
    apiStatus.textContent = `API: ${health.status} | устройство: ${health.resolved_device}`;
    apiStatus.classList.add("ok");
  } catch {
    apiStatus.textContent = "API: нет соединения";
    apiStatus.classList.remove("ok");
  }
}

function renderResult(result) {
  state.result = result;
  state.texSourceMode = isTexSourceResult(result);
  if (result?.document_id) state.resultCache.set(result.document_id, result);
  rememberRun(result);
  updateNavAvailability(result);
  state.selectedToken = null;
  state.variableSearch = null;
  state.visualizationCache = new Map();
  state.deferredRenderDone = new Map();
  state.formulaProjectionCache = new Map();
  state.pendingFormulaNavigation = null;
  document.querySelector("#resultStatus")?.closest(".metric")?.setAttribute("hidden", "");
  document.querySelector("#textCount").textContent = (result.text_blocks || []).length;
  document.querySelector("#formulaCount").textContent = (result.formulas || []).length;
  document.querySelector("#tokenCount").textContent = `${getTokenTextBlocks(result).filter((block) => String(block.text || "").includes("[FORMULA_")).length} / ${(result.formula_regions || []).length}`;
  document.querySelector("#graphCount").textContent = `${(result.graph?.nodes || []).length} / ${(result.graph?.edges || []).length}`;
  const metagraph = result.metagraph || { nodes: [], edges: [] };
  document.querySelector("#metagraphCount").textContent = `${metagraph.nodes.length} / ${metagraph.edges.length}`;

  showWarnings(result.warnings || [], result);
  renderText(result);
  renderDocumentPreview(result);
  renderTokenProjection(result);
  renderFormulas(result.formulas || []);
  renderVariableSearch(result);
  renderProcess(result);
  renderMetrics(result);
  renderHeaderDocumentSelector();
  document.querySelector("#visualizationPage").innerHTML = `<div class="graphLoading">Откройте страницу "Визуализация", чтобы загрузить режимы метаграфа и контекста.</div>`;
  document.querySelector("#readerPage").textContent = "Откройте страницу \"Текст и формулы\", чтобы подготовить представление.";
  document.querySelector("#outputsPage").innerHTML = `<div class="graphLoading">Откройте страницу "Артефакты", чтобы загрузить экспортные файлы.</div>`;
  if (state.activePage !== "upload") activatePage(state.activePage);
}

function updateNavAvailability(result = state.result) {
  const hasResult = Boolean(result?.document_id);
  document.body.classList.toggle("hasResult", hasResult);
  document.body.classList.toggle("hasPipeline", hasResult);
  document.body.classList.toggle("texSourceMode", Boolean(state.texSourceMode));
  const hideTokens = Boolean(result?.document_id && !hasFormulaOverlayData(result));
  document.querySelectorAll(".pageButton").forEach((button) => {
    if (button.dataset.page === "tokens") {
      button.hidden = hideTokens;
      button.classList.toggle("forceHidden", hideTokens);
      button.setAttribute("aria-hidden", hideTokens ? "true" : "false");
    }
  });
  if (hideTokens && state.activePage === "tokens") activatePage("text");
}

function startProgress() {
  document.body.classList.add("hasPipeline");
  state.lastProgress = 0;
  state.progressLog = [];
  renderUploadProcessLog();
  if (submitButton) {
    submitButton.disabled = true;
    submitButton.textContent = "Обработка...";
  }
  updateProgress({ progress: 0, stage: "Загрузка задания", detail: "Ожидание ответа сервера...", updated_at: Date.now() / 1000 });
}

function stopProgress() {
  if (state.jobPollTimer) {
    window.clearTimeout(state.jobPollTimer);
    state.jobPollTimer = null;
  }
  if (submitButton) {
    submitButton.disabled = false;
    submitButton.textContent = "Запустить обработку";
  }
}

async function renderText(result) {
  const target = document.querySelector("#textPage");
  target.innerHTML = "";
  const seq = ++state.textRenderSeq;
  try {
    let collected = collectTextForDisplay(result);
    if (collected.source === "missing" && result.document_id) {
      try {
        const [graphReadyResponse, structuredResponse] = await Promise.all([
          fetchWithTimeout(`${API_BASE}/api/results/${encodeURIComponent(result.document_id)}/graph-ready`, {}, 30000),
          fetchWithTimeout(`${API_BASE}/api/results/${encodeURIComponent(result.document_id)}/structured`, {}, 30000),
        ]);
        if (graphReadyResponse.ok) {
          collected = collectTextForDisplay(await graphReadyResponse.json());
        }
        if (collected.source === "missing" && structuredResponse.ok) {
          collected = collectTextForDisplay(await structuredResponse.json());
        }
      } catch {
        collected = { source: "missing", text: "", blocks: [], count: 0 };
      }
    }
    if (seq !== state.textRenderSeq) return;
    if (collected.source === "missing" || !collected.text.trim()) {
      renderMissingTextDiagnostic(target, result);
      return;
    }
    const paragraphs = collected.blocks.length ? buildReadableTextParagraphs(collected.blocks) : [{ text: collected.text }];
    if (!paragraphs.length) {
      renderMissingTextDiagnostic(target, result);
      return;
    }
    target.innerHTML = `
      <div class="textDiagnostics">
        источник: <b>${escapeHtml(formatSourceName(collected.source))}</b> |
        символов: <b>${collected.text.length}</b> |
        блоков/параграфов: <b>${collected.count}</b>
      </div>
      <article class="textPlainFlow">
        ${paragraphs.map((paragraph) => `<p>${renderTokenizedHtml(paragraph.text, { renderFormulas: true })}</p>`).join("")}
      </article>
    `;
    target.querySelectorAll(".tokenChip").forEach((button) => {
      button.addEventListener("click", () => selectToken(button.dataset.token));
    });
    renderKatex(target);
  } catch (error) {
    target.innerHTML = `<div class="graphLoading">Не удалось отобразить текст: ${escapeHtml(error.message || "неизвестная ошибка")}</div>`;
  }
}

function renderMissingTextDiagnostic(target, result) {
  const counts = {
    text_with_tokens: Array.isArray(result?.text_with_tokens) ? result.text_with_tokens.length : typeof result?.text_with_tokens === "string" ? 1 : 0,
    text_blocks: Array.isArray(result?.text_blocks) ? result.text_blocks.length : typeof result?.text_blocks === "string" ? 1 : 0,
    pages: Array.isArray(result?.pages) ? result.pages.length : 0,
    formulas: Array.isArray(result?.formulas) ? result.formulas.length : 0,
  };
  target.innerHTML = `
    <div class="textDiagnostics">
      источник: <b>не найден</b> |
      text_with_tokens: <b>${counts.text_with_tokens}</b> |
      text_blocks: <b>${counts.text_blocks}</b> |
      pages: <b>${counts.pages}</b>
    </div>
    <div class="graphLoading">Текст документа не найден в известных полях результата. Формул найдено: ${counts.formulas}.</div>
  `;
}

function collectTextForDisplay(result) {
  const directTextFields = [
    ["text_with_tokens", result?.text_with_tokens],
    ["structured", result?.text],
    ["raw_text", result?.raw_text],
    ["document_text", result?.document_text],
    ["full_text", result?.full_text],
    ["source_text", result?.source_text],
    ["markdown", result?.markdown],
    ["tex_source", result?.tex_source],
    ["tex_text", result?.tex_text],
  ];
  if (Array.isArray(result?.text_with_tokens) && result.text_with_tokens.length) {
    const blocks = normalizeTextDisplayBlocks(result.text_with_tokens, "text_with_tokens");
    if (blocks.length) return { source: "text_with_tokens", blocks, text: blocks.map(blockText).join("\n\n"), count: blocks.length };
  }
  for (const [source, value] of directTextFields) {
    if (typeof value === "string" && value.trim()) {
      return { source, blocks: [], text: value, count: 1 };
    }
  }
  const sectionParagraphs = Array.isArray(result?.sections)
    ? result.sections.flatMap((section) => section.paragraphs || section.text_blocks || [])
    : [];
  const structured = result?.structured || result?.document || {};
  const paragraphs = structured.paragraphs
    || result?.paragraphs
    || result?.fragments
    || result?.text_fragments
    || sectionParagraphs;
  if (Array.isArray(paragraphs) && paragraphs.length) {
    const blocks = normalizeTextDisplayBlocks(paragraphs, "structured");
    const text = blocks.map(blockText).filter(Boolean).join("\n\n");
    if (text.trim()) return { source: "structured", blocks, text, count: blocks.length };
  }
  const structuredSections = Array.isArray(structured.sections) ? structured.sections : [];
  const nestedParagraphs = structuredSections.flatMap((section) => section.paragraphs || section.text_blocks || section.children || []);
  if (nestedParagraphs.length) {
    const blocks = normalizeTextDisplayBlocks(nestedParagraphs, "structured");
    const text = blocks.map(blockText).filter(Boolean).join("\n\n");
    if (text.trim()) return { source: "structured", blocks, text, count: blocks.length };
  }
  if (Array.isArray(result?.text_blocks) && result.text_blocks.length) {
    const blocks = normalizeTextDisplayBlocks(result.text_blocks, "text_blocks");
    if (blocks.length) return { source: "text_blocks", blocks, text: blocks.map(blockText).join("\n\n"), count: blocks.length };
  }
  const graphNodes = Array.isArray(result?.nodes) ? result.nodes : Array.isArray(result?.graph?.nodes) ? result.graph.nodes : [];
  const textNodes = graphNodes.filter((node) => {
    const type = String(node.type || node.kind || node.node_type || "").toLowerCase();
    return ["paragraph", "text_block", "sentence", "section"].includes(type);
  });
  if (textNodes.length) {
    const blocks = normalizeTextDisplayBlocks(textNodes.map((node) => ({ ...node, ...(node.attributes || {}) })), "graph_text_nodes");
    const text = blocks.map(blockText).filter(Boolean).join("\n\n");
    if (text.trim()) return { source: "graph_text_nodes", blocks, text, count: blocks.length };
  }
  const pages = Array.isArray(result?.pages) ? result.pages : [];
  const pageText = pages.map((page) => page.text_layer || "").filter((text) => text.trim()).join("\n\n");
  if (pageText.trim()) {
    return {
      source: "text_layer",
      blocks: pages.filter((page) => String(page.text_layer || "").trim()).map((page) => ({ id: `page_${page.page_number}`, page_number: page.page_number, text: page.text_layer, source: "text_layer" })),
      text: pageText,
      count: pages.length,
    };
  }
  return { source: "missing", blocks: [], text: "", count: 0 };
}

function normalizeTextDisplayBlocks(items, source) {
  return (items || [])
    .map((item, index) => ({
      id: item.id || `${source}_${index}`,
      page_number: item.page_number || item.page || 1,
      source: item.source || source,
      confidence: item.confidence ?? null,
      text: blockText(item),
    }))
    .filter((block) => block.text.trim());
}

function blockText(block) {
  if (typeof block === "string") return block.trim();
  if (Array.isArray(block)) return block.map(blockText).filter(Boolean).join(" ").trim();
  const direct = block?.text_with_tokens
    ?? block?.text
    ?? block?.content
    ?? block?.value
    ?? block?.raw_text
    ?? block?.source_text
    ?? block?.masked_text
    ?? block?.paragraph_text
    ?? block?.text_layer
    ?? "";
  if (typeof direct === "string" && direct.trim()) return direct.trim();
  if (Array.isArray(direct)) {
    const text = direct.map((item) => (typeof item === "string" ? item : blockText(item))).filter(Boolean).join(" ");
    if (text.trim()) return text.trim();
  }
  if (Array.isArray(block?.lines)) {
    const text = block.lines
      .map((line) => {
        if (typeof line === "string") return line;
        if (typeof line?.text === "string" && line.text.trim()) return line.text;
        if (Array.isArray(line?.spans)) return line.spans.map((span) => span?.text || "").join(" ");
        return "";
      })
      .filter(Boolean)
      .join(" ");
    if (text.trim()) return text.trim();
  }
  if (Array.isArray(block?.spans)) {
    const text = block.spans.map((span) => span?.text || "").filter(Boolean).join(" ");
    if (text.trim()) return text.trim();
  }
  return "";
}

function formatSourceName(source) {
  const names = {
    text_with_tokens: "текст с формульными токенами",
    structured: "структурированный результат",
    raw_text: "исходный текст",
    document_text: "текст документа",
    full_text: "полный текст",
    source_text: "текст источника",
    markdown: "Markdown",
    tex_source: "TeX-источник",
    tex_text: "текст TeX",
    text_blocks: "текстовые блоки",
    graph_text_nodes: "текстовые узлы метаграфа",
    text_layer: "текстовый слой PDF",
    pdf_text_layer: "текстовый слой PDF",
    postprocessed: "после обработки",
    formula_token: "формульный токен",
    pp_formula_net: "распознавание формул",
    pp_structure_v3: "структурный анализ",
    text_inline_pattern: "формула из строки",
    fallback: "резервный вариант",
    graph_ready: "данные для графа",
    missing: "не найден",
  };
  return names[source] || source || "-";
}

function getTokenTextBlocks(result) {
  if (Array.isArray(result?.text_with_tokens) && result.text_with_tokens.length) {
    return normalizeTextDisplayBlocks(result.text_with_tokens, "text_with_tokens");
  }
  if (typeof result?.text_with_tokens === "string" && result.text_with_tokens.trim()) {
    return [
      {
        id: "text_with_tokens",
        page_number: 1,
        source: "graph_ready",
        confidence: null,
        text: result.text_with_tokens,
      },
    ];
  }
  if (Array.isArray(result?.text_blocks) && result.text_blocks.length) {
    return normalizeTextDisplayBlocks(result.text_blocks, "text_blocks");
  }
  if (typeof result?.text_blocks === "string" && result.text_blocks.trim()) {
    return [
      {
        id: "text_blocks",
        page_number: 1,
        source: "text",
        confidence: null,
        text: result.text_blocks,
      },
    ];
  }
  return [];
}

function buildReadableTextParagraphs(blocks) {
  const pages = groupByPage(blocks);
  const paragraphs = [];
  [...pages.entries()].forEach(([pageNumber, pageBlocks]) => {
    const pageText = pageBlocks
      .map(blockText)
      .filter(Boolean)
      .join(" ");
    const chunks = splitIntoReadableParagraphs(pageText);
    chunks.forEach((text, index) => {
      const sources = [...new Set(pageBlocks.map((block) => block.source).filter(Boolean))].join(", ") || "unknown";
      paragraphs.push({
        text,
        meta: `стр. ${pageNumber || "?"} | ${sources} | абзац ${index + 1}/${chunks.length}`,
      });
    });
  });
  return paragraphs;
}

function splitIntoReadableParagraphs(text, maxLength = 900) {
  const normalized = String(text || "")
    .replace(/\s+/g, " ")
    .replace(/\s+([,.;:!?])/g, "$1")
    .replace(/(\[FORMULA_\d+\])/g, " $1 ")
    .replace(/\s+/g, " ")
    .trim();
  if (!normalized) return [];
  const sentences = normalized.match(/[^.!?。！？]+(?:[.!?。！？]+|$)/g) || [normalized];
  const chunks = [];
  let current = "";
  sentences.map((sentence) => sentence.trim()).filter(Boolean).forEach((sentence) => {
    if (current && `${current} ${sentence}`.length > maxLength) {
      chunks.push(current);
      current = sentence;
    } else {
      current = current ? `${current} ${sentence}` : sentence;
    }
  });
  if (current) chunks.push(current);
  return chunks.length ? chunks : [normalized];
}

function renderTokenProjection(result) {
  const blocks = getTokenTextBlocks(result);
  const formulas = result.formulas || [];
  const regions = getFormulaOverlayRegions(result);
  const pages = result.pages || [];
  const target = document.querySelector("#tokensPage");
  target.innerHTML = "";
  if (!hasFormulaOverlayData(result)) {
    target.innerHTML = `<div class="emptyHint">Оверлей недоступен: нет страниц или координат формул в результате обработки.</div>`;
    return;
  }
  if (!blocks.length) {
    target.textContent = "Проекция text_with_tokens пока не сформирована.";
    return;
  }

  const formulasByToken = new Map();
  formulas.forEach((formula) => {
    [formula.token, formula.id, formula.formula_region_id].filter(Boolean).forEach((key) => {
      if (!formulasByToken.has(key)) formulasByToken.set(key, []);
      formulasByToken.get(key).push(formula);
    });
  });

  const displayRegions = buildDisplayRegions(regions, formulas);
  const regionEntries = (displayRegions || []).map((region) => ({
    region,
    formulas: sortFormulaCandidates(formulasByToken.get(region.token) || []),
  }));

  target.innerHTML = `
    <div class="overlayToolbar">
      <div class="overlayToolbarTitle">Оверлей формул</div>
      <div class="overlayToolbarModes">
        ${[
          ["smart", "Умный"],
          ["all", "Все"],
          ["block", "Блочные"],
          ["inline", "Строчные"],
          ["selected", "Выбранный"],
        ]
          .map(
            ([mode, label]) => `
              <button
                type="button"
                class="overlayModeButton${state.overlayMode === mode ? " active" : ""}"
                data-overlay-mode="${mode}"
              >${label}</button>
            `
          )
          .join("")}
      </div>
    </div>
    <div class="pageOverlayGrid" id="pageOverlayGrid"></div>
    <div class="tokenLayout">
      <div id="tokenStream" class="tokenStream"></div>
      <aside id="tokenLegend" class="tokenLegend"></aside>
    </div>
  `;

  target.querySelectorAll("[data-overlay-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      state.overlayMode = button.dataset.overlayMode || "smart";
      renderTokenProjection(result);
    });
  });

  renderPageOverlays(target.querySelector("#pageOverlayGrid"), result.document_id, pages, displayRegions);

  const stream = target.querySelector("#tokenStream");
  const legend = target.querySelector("#tokenLegend");
  const byPage = groupByPage(blocks);
  byPage.forEach(([pageNumber, pageBlocks]) => {
    const section = document.createElement("section");
    section.className = "tokenSection";
    section.innerHTML = `<h3 class="tokenSectionHeader">страница ${pageNumber}</h3>`;
    pageBlocks.forEach((block) => {
      const item = document.createElement("article");
      item.className = "tokenBlock";
      item.innerHTML = `
        <div class="meta">${formatSourceName(block.source)} | уверенность ${formatConfidence(block.confidence)}</div>
        <div class="tokenText">${renderTokenizedHtml(blockText(block))}</div>
      `;
      section.appendChild(item);
    });
    stream.appendChild(section);
  });

  if (!regionEntries.length) {
    const formulaEntries = formulas.filter((formula) => formula.token);
    legend.innerHTML = formulaEntries.length
      ? formulaEntries
          .slice(0, 80)
          .map(
            (formula) => `
              <article class="tokenLegendCard" data-token="${escapeAttribute(formula.token)}">
                <div class="tokenLegendTop">
                  <button type="button" class="tokenChip" data-token="${escapeAttribute(formula.token)}">${escapeHtml(formula.token)}</button>
                  <span class="tokenLegendMeta">${escapeHtml(translateFormulaKind(formula.kind))} | стр. ${formula.page_number || "-"}</span>
                </div>
                <div class="latexRender" data-latex="${escapeAttribute(cleanLatex(formula.latex))}" data-display="${formula.kind === "block"}"></div>
              <div class="meta">${escapeHtml(formatSourceName(formula.source || "-"))} | область на странице не найдена</div>
              </article>
            `
          )
          .join("")
      : `<div class="tokenLegendCard">Формульные регионы с токенами для этого результата не сформированы.</div>`;
  } else {
    regionEntries.forEach(({ region, formulas: tokenFormulas }) => {
      const formula = tokenFormulas[0] || null;
      const card = document.createElement("article");
      card.className = "tokenLegendCard";
      card.dataset.token = region.token;
      card.innerHTML = `
        <div class="tokenLegendTop">
          <button type="button" class="tokenChip" data-token="${escapeAttribute(region.token)}">${escapeHtml(region.token)}</button>
          <span class="tokenLegendMeta">${escapeHtml(translateFormulaKind(region.kind))} | стр. ${region.page_number}</span>
        </div>
        <div class="meta">${escapeHtml(formatSourceName(region.source))} | уверенность ${formatConfidence(region.confidence)}</div>
        ${
          formula
            ? `
              <div class="latexRender" data-latex="${escapeAttribute(cleanLatex(formula.latex))}" data-display="${formula.kind === "block"}"></div>
              <div class="meta">${escapeHtml(formatSourceName(formula.source || "-"))}${formula.formula_region_id ? ` | ${escapeHtml(formula.formula_region_id)}` : ""}</div>
            `
            : `<div class="meta">Нет итоговой формулы, связанной с этим токеном.</div>`
        }
      `;
      legend.appendChild(card);
    });
  }

  target.querySelectorAll(".tokenChip").forEach((button) => {
    button.addEventListener("click", () => selectToken(button.dataset.token));
  });
  target.querySelectorAll(".pageFormulaBox").forEach((button) => {
    button.addEventListener("click", () => selectToken(button.dataset.token));
  });
  renderKatex(target);
}

function renderPageOverlays(target, documentId, pages, regions) {
  if (!pages.length) {
    target.innerHTML = "";
    return;
  }
  target.innerHTML = "";
  const regionsByPage = new Map();
  regions.forEach((region) => {
    const list = regionsByPage.get(region.page_number) || [];
    list.push(region);
    regionsByPage.set(region.page_number, list);
  });
  pages.forEach((page) => {
    const pageRegions = regionsByPage.get(page.page_number) || [];
    const visibleRegions = pageRegions.filter((region) => shouldShowOverlayRegion(region, pageRegions));
    const pageCard = document.createElement("section");
    pageCard.className = "pageCard";
    const pointWidth = (page.width * 72) / Math.max(1, page.dpi);
    const pointHeight = (page.height * 72) / Math.max(1, page.dpi);
    const overlayHtml = visibleRegions
      .map((region) => {
        const bbox = region.display_bbox || region.bbox;
        const left = (bbox[0] / pointWidth) * 100;
        const top = (bbox[1] / pointHeight) * 100;
        const width = ((bbox[2] - bbox[0]) / pointWidth) * 100;
        const height = ((bbox[3] - bbox[1]) / pointHeight) * 100;
        const kind = region.display_kind || region.kind;
        const source = region.display_source || region.source;
        const showLabel = overlayLabelVisible(region, width, height, visibleRegions.length, false);
        return `
          <button
            type="button"
            class="pageFormulaBox ${kind}${showLabel ? "" : " compact"}${region.token === state.selectedToken ? " active" : ""}"
            data-token="${escapeAttribute(region.token)}"
            title="${escapeAttribute(`${region.token} | ${kind} | ${source}`)}"
            style="left:${left}%;top:${top}%;width:${width}%;height:${height}%"
          >
            <span>${escapeHtml(region.token)}</span>
          </button>
        `;
      })
      .join("");
    pageCard.innerHTML = `
      <div class="pageCardTop">
        <strong>стр. ${page.page_number}</strong>
        <span>${visibleRegions.length} / ${pageRegions.length} регионов</span>
      </div>
      <div class="pagePreviewFrame" data-page-number="${page.page_number}" role="button" tabindex="0" aria-label="Открыть страницу ${page.page_number} с оверлеем">
        <img class="pagePreviewImage" src="${escapeAttribute(pagePreviewUrl(documentId, page.image_path))}" alt="страница ${page.page_number}" loading="lazy" />
        <div class="pageOverlayLayer">${overlayHtml}</div>
      </div>
    `;
    target.appendChild(pageCard);
    pageCard.querySelectorAll(".pageFormulaBox").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        selectToken(button.dataset.token);
      });
    });
    const frame = pageCard.querySelector(".pagePreviewFrame");
    frame.addEventListener("click", (event) => {
      if (event.target.closest(".pageFormulaBox")) return;
      openOverlayModal(documentId, page, pageRegions, visibleRegions);
    });
    frame.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      openOverlayModal(documentId, page, pageRegions, visibleRegions);
    });
  });
  return;
}

function renderFormulas(formulas) {
  const target = document.querySelector("#formulasPage");
  target.innerHTML = "";
  const visibleFormulas = (formulas || []).filter((formula) => hasRenderableLatex(formula?.latex));
  if (!visibleFormulas.length) {
    target.textContent = "Формулы не найдены.";
    return;
  }
  if (visibleFormulas.length < (formulas || []).length) {
    const skipped = document.createElement("div");
    skipped.className = "emptyHint";
    skipped.textContent = `Скрыто пустых формульных кандидатов: ${(formulas || []).length - visibleFormulas.length}.`;
    target.appendChild(skipped);
  }
  visibleFormulas.forEach((formula) => {
    const item = document.createElement("article");
    const flags = Array.isArray(formula.quality_flags) ? formula.quality_flags : [];
    const symbols = formulaSymbols(formula);
    const operators = formulaOperators(formula.latex);
    const interpretation = formulaInterpretation(formula, symbols, operators);
    item.className = "formula";
    const flagsHtml = flags.length
      ? `<div class="qualityFlags">${flags.map((flag) => `<span class="qualityFlag">${escapeHtml(flag)}</span>`).join("")}</div>`
      : "";
    const rawHtml = formula.raw_latex
      ? `<strong>Исходный OCR-кандидат</strong><code>${escapeHtml(formula.raw_latex)}</code>`
      : "";
    item.innerHTML = `
      <div class="formulaHeader">
        <div class="meta">${formula.id} | ${translateFormulaKind(formula.kind)} | стр. ${formula.page_number}${formula.token ? ` | ${escapeHtml(formula.token)}` : ""} | ${escapeHtml(formatSourceName(formula.source || "-"))} | уверенность ${formatConfidence(formula.confidence)}</div>
        <div class="formulaHeaderActions">
          <button type="button" class="secondaryInlineButton" data-formula-toggle>${formula.token ? "Раскрыть формулу" : "Раскрыть"}</button>
          ${symbols.length ? `<button type="button" class="secondaryInlineButton" data-open-variable-from-formula="${escapeAttribute(symbols[0])}">К переменной</button>` : ""}
        </div>
      </div>
      <div class="formulaContentGrid">
        <div class="formulaTextPane">
          ${flagsHtml}
          <div class="latexRender" data-latex="${escapeAttribute(cleanLatex(formula.latex))}" data-display="${formula.kind === "block"}"></div>
          ${renderFormulaInterpretation(interpretation)}
          <details class="latexSource">
            <summary>LaTeX, переменные и операторы</summary>
            <strong>Используемый LaTeX</strong>
            <code>${escapeHtml(formula.latex)}</code>
            ${rawHtml}
            ${interpretation.plainText ? `<strong>Читаемая запись</strong><code>${escapeHtml(interpretation.plainText)}</code>` : ""}
            ${symbols.length ? `<strong>Переменные</strong><div class="formulaSymbolList">${symbols.map((symbol) => `<button type="button" data-symbol-search="${escapeAttribute(symbol)}">${escapeHtml(symbol)}</button>`).join("")}</div>` : ""}
            ${operators.length ? `<strong>Операторы</strong><div class="formulaSymbolList">${operators.map((operator) => `<span class="qualityFlag">${escapeHtml(operator)}</span>`).join("")}</div>` : ""}
          </details>
          <div class="formulaContextBox" data-formula-context-host hidden>
            Контекст загружается...
          </div>
        </div>
        <section class="formulaDeepDive" hidden>
          <div class="formulaDeepDiveTop">
            <strong>Метавершина формулы</strong>
            <div class="formulaDeepDiveModes">
              <button type="button" class="secondaryInlineButton active" data-formula-projection-mode="formula_focus">Метаребра и контекст</button>
              <button type="button" class="secondaryInlineButton" data-formula-projection-mode="ast_tree">Структура формулы</button>
            </div>
          </div>
          <div class="formulaProjectionCaption" data-formula-projection-caption></div>
          <div class="formulaProjectionHost" data-formula-projection-host>
            <div class="graphLoading">Загружаю граф формулы...</div>
          </div>
        </section>
      </div>
    `;
    item.dataset.token = formula.token || "";
    item.dataset.formulaId = formula.id;
    target.appendChild(item);
  });
  target.querySelectorAll("[data-symbol-search]").forEach((button) => {
    button.addEventListener("click", () => openVariableSearch(button.dataset.symbolSearch));
  });
  target.querySelectorAll("[data-open-variable-from-formula]").forEach((button) => {
    button.addEventListener("click", () => openVariableSearch(button.dataset.openVariableFromFormula));
  });
  target.querySelectorAll("[data-formula-toggle]").forEach((button) => {
    button.addEventListener("click", async () => {
      const card = button.closest(".formula");
      if (!card) return;
      const expanded = card.querySelector(".formulaDeepDive")?.hidden !== false;
      await setFormulaCardExpanded(card, expanded, card.dataset.activeProjectionMode || "formula_focus");
    });
  });
  target.querySelectorAll("[data-formula-projection-mode]").forEach((button) => {
    button.addEventListener("click", async () => {
      const card = button.closest(".formula");
      if (!card) return;
      await setFormulaCardExpanded(card, true, button.dataset.formulaProjectionMode || "formula_focus");
    });
  });
  renderKatex(target);
  consumePendingFormulaNavigation();
}

async function setFormulaCardExpanded(card, expanded, projectionMode = "formula_focus") {
  const deepDive = card?.querySelector(".formulaDeepDive");
  const toggle = card?.querySelector("[data-formula-toggle]");
  if (!card || !deepDive) return;
  deepDive.hidden = !expanded;
  const contextBox = card.querySelector("[data-formula-context-host]");
  if (contextBox) contextBox.hidden = !expanded;
  card.classList.toggle("expanded", expanded);
  if (toggle) toggle.textContent = expanded ? "Свернуть формулу" : "Раскрыть формулу";
  if (!expanded) return;
  await renderFormulaProjectionSection(card, projectionMode);
}

async function renderFormulaProjectionSection(card, projectionMode = "formula_focus") {
  const formulaId = card?.dataset.formulaId || "";
  const formulaToken = card?.dataset.token || "";
  if (!formulaId) return;
  const contextHost = card.querySelector("[data-formula-context-host]");
  const captionHost = card.querySelector("[data-formula-projection-caption]");
  const projectionHost = card.querySelector("[data-formula-projection-host]");
  card.dataset.activeProjectionMode = projectionMode;
  const requestKey = `${state.result?.document_id || ""}:${formulaId}:${formulaToken}:${projectionMode}:${Date.now()}`;
  card.dataset.formulaProjectionRequest = requestKey;
  card.querySelectorAll("[data-formula-projection-mode]").forEach((button) => {
    button.classList.toggle("active", button.dataset.formulaProjectionMode === projectionMode);
  });
  if (projectionHost) {
    projectionHost.innerHTML = `<div class="graphLoading">Загружаю ${projectionMode === "ast_tree" ? "внутренний граф метавершины" : "метаребра и внешний контекст"}...</div>`;
  }
  try {
    const payload = await loadFormulaProjection(formulaId, projectionMode, formulaToken);
    if (card.dataset.formulaProjectionRequest !== requestKey || card.dataset.formulaId !== formulaId) return;
    if (contextHost) {
      contextHost.innerHTML = renderFormulaContextBox(payload);
      renderKatex(contextHost);
    }
    if (captionHost) {
      captionHost.textContent = payload.description || "";
    }
    if (projectionHost) {
      projectionHost.innerHTML = renderFormulaProjectionGraph(payload);
      bindFormulaProjectionInteractions(projectionHost, payload);
      renderKatex(projectionHost);
    }
  } catch (error) {
    if (projectionHost) {
      projectionHost.innerHTML = `<div class="graphLoading error">Не удалось загрузить граф формулы: ${escapeHtml(error.message)}</div>`;
    }
    if (contextHost) {
      contextHost.textContent = "Данные метавершины формулы недоступны.";
    }
  }
}

function renderFormulaContextBox(payload) {
  const details = payload?.selectedObjectDetails || payload?.selected_object_details || {};
  const definitions = Array.isArray(details.definitions) ? details.definitions : [];
  const formulaMetavertex = details.formula_metavertex || {};
  const metaedges = Array.isArray(details.metaedges) ? details.metaedges : [];
  const internalStructure = details.internal_structure || {};
  return `
    <div class="formulaContextGrid">
      <div>
        <span class="meta">внешний контекст метавершины</span>
        <p>${escapeHtml(details.context || "Контекст не найден.")}</p>
      </div>
      <div>
        <span class="meta">словесная интерпретация</span>
        <p>${escapeHtml(details.plain_text || details.latex || "—")}</p>
      </div>
      <div>
        <span class="meta">метавершина формулы</span>
        <p>${escapeHtml(formulaMetavertex.id || "—")} · контекстов ${Number(formulaMetavertex.context_ids?.length || 0)} · абзацев ${Number(formulaMetavertex.paragraph_ids?.length || 0)} · переменных ${Number(formulaMetavertex.variable_ids?.length || 0)}</p>
      </div>
      <div>
        <span class="meta">внутренний граф</span>
        <p>${escapeHtml(internalStructure.graph_type || "ast_like_expression_graph")} · ролей ${Number(internalStructure.roles?.length || 0)} · метаребер ${metaedges.length}</p>
      </div>
      ${
        definitions.length
          ? `<div class="formulaContextDefinitions"><span class="meta">определения</span><ul>${definitions.map((item) => `<li><strong>${escapeHtml(item.symbol || "")}</strong> ${escapeHtml(item.definition_text || item.evidence || "")}</li>`).join("")}</ul></div>`
          : ""
      }
    </div>
  `;
}

function renderFormulaProjectionGraph(payload) {
  const layout = layoutFormulaProjectionNodes(payload);
  const edges = (payload.edges || []).map((edge) => renderFormulaProjectionEdge(edge, layout.nodeMap)).join("");
  const nodes = layout.nodes.map((node) => renderFormulaProjectionNode(node)).join("");
  return `
    <div class="formulaProjectionToolbar" aria-label="Управление графом формулы">
      <button type="button" data-formula-graph-action="zoom-out">−</button>
      <button type="button" data-formula-graph-action="fit">Вписать</button>
      <button type="button" data-formula-graph-action="zoom-in">+</button>
      <span>Колесо мыши масштабирует, фон сдвигает граф, вершины можно перетаскивать.</span>
    </div>
    <div class="formulaProjectionViewport" data-formula-projection-viewport>
      <svg class="formulaProjectionSvg" viewBox="0 0 ${layout.width} ${layout.height}" role="img" aria-label="${escapeAttribute(payload.title || "Граф формулы")}">
        <defs><marker id="formulaProjectionArrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z"></path></marker></defs>
        <g data-formula-projection-transform>
          ${edges}
          ${nodes}
        </g>
      </svg>
    </div>
  `;
}

function layoutFormulaProjectionNodes(payload) {
  const nodes = (payload.nodes || []).map((node) => ({ ...node }));
  if (payload.layout === "ast_tree") return layoutAstProjectionNodes(nodes);
  return layoutFormulaFocusProjectionNodes(nodes);
}

function layoutAstProjectionNodes(nodes) {
  const width = 840;
  const roleOrder = new Map([
    ["root", { x: 330, y: 28 }],
    ["lhs", { x: 110, y: 140 }],
    ["rhs", { x: 520, y: 140 }],
  ]);
  const dynamicCounters = { operand: 0, operator: 0 };
  const placed = nodes.map((node) => {
    const role = node.astRole || node.details?.ast_role || "operand";
    const fixed = roleOrder.get(role);
    if (fixed) return { ...node, x: fixed.x, y: fixed.y, ...projectionNodeSize(node, 220, 66) };
    if (role === "operator") {
      const index = dynamicCounters.operator++;
      return { ...node, x: 90 + index * 185, y: 370, ...projectionNodeSize(node, 160, 56) };
    }
    const index = dynamicCounters.operand++;
    return { ...node, x: 42 + (index % 3) * 250, y: 250 + Math.floor(index / 3) * 104, ...projectionNodeSize(node, 224, 68) };
  });
  const height = Math.max(470, ...placed.map((node) => node.y + node.h + 30));
  return { width, height, nodes: placed, nodeMap: new Map(placed.map((node) => [node.id, node])) };
}

function layoutFormulaFocusProjectionNodes(nodes) {
  const laneSlots = { top: [], left: [], center: [], right: [], bottom: [] };
  nodes.forEach((node) => (laneSlots[node.lane || "center"] || laneSlots.center).push(node));
  const laneCoords = {
    top: { x: 300, y: 24, dx: 0, dy: 86, w: 220, h: 58 },
    left: { x: 24, y: 138, dx: 0, dy: 86, w: 220, h: 58 },
    center: { x: 300, y: 178, dx: 0, dy: 96, w: 240, h: 64 },
    right: { x: 596, y: 132, dx: 0, dy: 86, w: 220, h: 58 },
    bottom: { x: 300, y: 392, dx: 0, dy: 84, w: 240, h: 56 },
  };
  const placed = [];
  Object.entries(laneSlots).forEach(([lane, list]) => {
    const base = laneCoords[lane] || laneCoords.center;
    list.forEach((node, index) => {
      placed.push({ ...node, x: base.x + base.dx * index, y: base.y + base.dy * index, ...projectionNodeSize(node, base.w, base.h) });
    });
  });
  const height = Math.max(560, ...placed.map((node) => node.y + node.h + 30));
  return { width: 840, height, nodes: placed, nodeMap: new Map(placed.map((node) => [node.id, node])) };
}

function projectionNodeLabel(node) {
  return String(node.label || node.details?.text || node.details?.latex || node.details?.operator || node.id || "");
}

function projectionNodeSize(node, baseW, baseH) {
  const label = projectionNodeLabel(node);
  const lines = Math.max(1, Math.ceil(label.length / Math.max(18, Math.floor(baseW / 9))));
  return { w: baseW, h: Math.min(128, Math.max(baseH, 42 + lines * 18)) };
}

function renderFormulaProjectionEdge(edge, nodeMap) {
  const source = nodeMap.get(edge.source);
  const target = nodeMap.get(edge.target);
  if (!source || !target) return "";
  const x1 = source.x + source.w / 2;
  const y1 = source.y + source.h / 2;
  const x2 = target.x + target.w / 2;
  const y2 = target.y + target.h / 2;
  const midX = (x1 + x2) / 2;
  return `
    <path
      class="formulaProjectionEdge ${escapeAttribute(edge.type || "")}"
      data-source="${escapeAttribute(edge.source || "")}"
      data-target="${escapeAttribute(edge.target || "")}"
      d="M ${x1} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${x2} ${y2}"
      marker-end="url(#formulaProjectionArrow)"
    ></path>
  `;
}

function renderFormulaProjectionNode(node) {
  const detailType = node.kind || node.type || node.details?.type || "context";
  const label = projectionNodeLabel(node);
  const isMath = ["formula", "ast"].includes(detailType) && /[\\_^=+\-/*{}()]/.test(label);
  const labelClass = isMath ? "formulaProjectionNodeLabel formulaProjectionNodeMath latexRender" : "formulaProjectionNodeLabel";
  const labelAttrs = isMath ? ` data-latex="${escapeAttribute(cleanLatex(label))}" data-display="false"` : "";
  return `
    <g class="formulaProjectionNode ${escapeAttribute(detailType)}" transform="translate(${node.x}, ${node.y})" data-node-kind="${escapeAttribute(detailType)}" data-node-id="${escapeAttribute(node.id)}" data-node-x="${node.x}" data-node-y="${node.y}" data-node-w="${node.w}" data-node-h="${node.h}">
      <rect width="${node.w}" height="${node.h}" rx="10"></rect>
      <text x="12" y="22" class="formulaProjectionNodeKind">${escapeHtml(projectionNodeTitle(detailType, node))}</text>
      <foreignObject x="12" y="32" width="${Math.max(60, node.w - 24)}" height="${Math.max(20, node.h - 40)}">
        <div xmlns="http://www.w3.org/1999/xhtml" class="${labelClass}"${labelAttrs}>${escapeHtml(label)}</div>
      </foreignObject>
    </g>
  `;
}

function projectionNodeTitle(kind, node) {
  if (kind === "ast") return String(node.astRole || node.details?.ast_role || "AST").toUpperCase();
  if (kind === "formula") return "Формула";
  if (kind === "variable") return "Переменная";
  if (kind === "context") return "Контекст";
  if (kind === "section") return "Раздел";
  if (kind === "definition") return "Определение";
  return translateGraphKind(kind || "node");
}

function translateGraphKind(kind = "") {
  return {
    node: "Узел",
    metaedge: "Метаребро",
    source: "Источник",
    issue: "Проблема",
    fragment: "Фрагмент",
    entity: "Сущность",
    text: "Текст",
    document: "Документ",
  }[kind] || String(kind).replaceAll("_", " ");
}

function bindFormulaProjectionInteractions(host, payload) {
  bindFormulaProjectionPanZoom(host);
  bindFormulaProjectionNodeDrag(host);
  host.querySelectorAll(".formulaProjectionNode").forEach((nodeElement) => {
    nodeElement.addEventListener("click", () => {
      if (nodeElement.dataset.dragMoved === "true") {
        nodeElement.dataset.dragMoved = "";
        return;
      }
      const nodeId = nodeElement.dataset.nodeId || "";
      const node = (payload.nodes || []).find((item) => item.id === nodeId);
      if (!node) return;
      if (node.kind === "variable") {
        const symbol = node.details?.normalized_symbol || node.details?.symbol || node.label;
        openVariableSearch(symbol);
        return;
      }
      if (node.kind === "formula" && node.id !== payload.selectedObjectDetails?.id) {
        openFormulaDetails({ formulaId: node.id, token: node.details?.token || "", projectionMode: "formula_focus" });
      }
    });
  });
}

function bindFormulaProjectionPanZoom(host) {
  const viewport = host.querySelector("[data-formula-projection-viewport]");
  const transformLayer = host.querySelector("[data-formula-projection-transform]");
  if (!viewport || !transformLayer) return;
  const state = { scale: 1, tx: 0, ty: 0, dragging: false, x: 0, y: 0 };
  const apply = () => {
    transformLayer.setAttribute("transform", `translate(${state.tx} ${state.ty}) scale(${state.scale})`);
  };
  const zoom = (delta) => {
    state.scale = Math.max(0.45, Math.min(2.4, state.scale + delta));
    apply();
  };
  host.querySelector("[data-formula-graph-action='zoom-in']")?.addEventListener("click", () => zoom(0.15));
  host.querySelector("[data-formula-graph-action='zoom-out']")?.addEventListener("click", () => zoom(-0.15));
  host.querySelector("[data-formula-graph-action='fit']")?.addEventListener("click", () => {
    state.scale = 1;
    state.tx = 0;
    state.ty = 0;
    apply();
  });
  viewport.addEventListener("wheel", (event) => {
    event.preventDefault();
    zoom(event.deltaY < 0 ? 0.12 : -0.12);
  }, { passive: false });
  viewport.addEventListener("pointerdown", (event) => {
    if (event.target?.closest?.(".formulaProjectionNode")) return;
    state.dragging = true;
    state.x = event.clientX;
    state.y = event.clientY;
    viewport.setPointerCapture?.(event.pointerId);
    viewport.classList.add("dragging");
  });
  viewport.addEventListener("pointermove", (event) => {
    if (!state.dragging) return;
    const dx = (event.clientX - state.x) / state.scale;
    const dy = (event.clientY - state.y) / state.scale;
    state.x = event.clientX;
    state.y = event.clientY;
    state.tx += dx;
    state.ty += dy;
    apply();
  });
  viewport.addEventListener("pointerup", (event) => {
    state.dragging = false;
    viewport.releasePointerCapture?.(event.pointerId);
    viewport.classList.remove("dragging");
  });
  viewport.addEventListener("pointerleave", () => {
    state.dragging = false;
    viewport.classList.remove("dragging");
  });
  apply();
}

function bindFormulaProjectionNodeDrag(host) {
  const svg = host.querySelector(".formulaProjectionSvg");
  const transformLayer = host.querySelector("[data-formula-projection-transform]");
  if (!svg || !transformLayer) return;
  const pointForEvent = (event) => {
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    const matrix = transformLayer.getScreenCTM();
    return matrix ? point.matrixTransform(matrix.inverse()) : { x: event.clientX, y: event.clientY };
  };
  const rerouteEdges = () => {
    const nodeMap = new Map([...host.querySelectorAll(".formulaProjectionNode")].map((node) => [node.dataset.nodeId, node]));
    host.querySelectorAll(".formulaProjectionEdge").forEach((edge) => {
      const source = nodeMap.get(edge.dataset.source);
      const target = nodeMap.get(edge.dataset.target);
      if (!source || !target) return;
      const sourceCenter = formulaProjectionNodeCenter(source);
      const targetCenter = formulaProjectionNodeCenter(target);
      const midX = (sourceCenter.x + targetCenter.x) / 2;
      edge.setAttribute("d", `M ${sourceCenter.x} ${sourceCenter.y} C ${midX} ${sourceCenter.y}, ${midX} ${targetCenter.y}, ${targetCenter.x} ${targetCenter.y}`);
    });
  };
  host.querySelectorAll(".formulaProjectionNode").forEach((nodeElement) => {
    const drag = { active: false, startPoint: null, startX: 0, startY: 0, pointerId: null, moved: false };
    nodeElement.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      event.stopPropagation();
      drag.active = true;
      drag.pointerId = event.pointerId;
      drag.startPoint = pointForEvent(event);
      drag.startX = Number(nodeElement.dataset.nodeX || 0);
      drag.startY = Number(nodeElement.dataset.nodeY || 0);
      drag.moved = false;
      nodeElement.classList.add("dragging");
      nodeElement.setPointerCapture?.(event.pointerId);
    });
    nodeElement.addEventListener("pointermove", (event) => {
      if (!drag.active || !drag.startPoint) return;
      event.preventDefault();
      event.stopPropagation();
      const point = pointForEvent(event);
      const nextX = drag.startX + point.x - drag.startPoint.x;
      const nextY = drag.startY + point.y - drag.startPoint.y;
      if (Math.abs(nextX - drag.startX) + Math.abs(nextY - drag.startY) > 3) drag.moved = true;
      nodeElement.dataset.nodeX = String(nextX);
      nodeElement.dataset.nodeY = String(nextY);
      nodeElement.dataset.dragMoved = drag.moved ? "true" : "";
      nodeElement.setAttribute("transform", `translate(${nextX}, ${nextY})`);
      rerouteEdges();
    });
    const finish = (event) => {
      if (!drag.active) return;
      event?.stopPropagation?.();
      drag.active = false;
      nodeElement.classList.remove("dragging");
      if (drag.pointerId !== null) nodeElement.releasePointerCapture?.(drag.pointerId);
      drag.pointerId = null;
    };
    nodeElement.addEventListener("pointerup", finish);
    nodeElement.addEventListener("pointercancel", finish);
  });
}

function formulaProjectionNodeCenter(nodeElement) {
  const x = Number(nodeElement.dataset.nodeX || 0);
  const y = Number(nodeElement.dataset.nodeY || 0);
  const w = Number(nodeElement.dataset.nodeW || 0);
  const h = Number(nodeElement.dataset.nodeH || 0);
  return { x: x + w / 2, y: y + h / 2 };
}

function formulaInterpretation(formula, symbols = formulaSymbols(formula), operators = formulaOperators(formula?.latex)) {
  const payload = formula?.formula_interpretation || {};
  const kind = payload.kind || inferFormulaKind(formula?.latex || "", operators);
  const plainText = payload.plain_text || formula?.plain_formula_text || latexReadableFallback(formula?.latex || "");
  const summary = payload.summary_ru || localFormulaSummary(kind, plainText, symbols, payload.definitions || {});
  return {
    kind,
    kindLabel: translateFormulaInterpretationKind(kind),
    plainText,
    summary,
    variables: payload.variables?.length ? payload.variables : symbols,
    definitions: payload.definitions || {},
    contextHint: payload.context_hint || "",
    confidence: payload.confidence,
  };
}

function renderFormulaInterpretation(interpretation) {
  const definitions = Object.entries(interpretation.definitions || {});
  return `
    <section class="formulaInterpretation">
      <div class="formulaInterpretationTop">
        <strong>Словесная интерпретация</strong>
        <span>${escapeHtml(interpretation.kindLabel)}${interpretation.confidence ? ` | уверенность ${formatConfidence(interpretation.confidence)}` : ""}</span>
      </div>
      <p>${escapeHtml(interpretation.summary || "Интерпретация недоступна для этой формулы.")}</p>
      ${
        interpretation.variables?.length
          ? `<div class="formulaVariableChips">${interpretation.variables.slice(0, 24).map((symbol) => `<span>${renderInlineLatexSymbol(symbol)}<code>${escapeHtml(symbol)}</code></span>`).join("")}</div>`
          : ""
      }
      ${
        definitions.length
          ? `<div class="formulaDefinitionList">${definitions.map(([symbol, meaning]) => `<span><b>${renderInlineLatexSymbol(symbol)}</b> — ${escapeHtml(shortText(meaning, 180))}</span>`).join("")}</div>`
          : ""
      }
    </section>
  `;
}

function renderInterpretationText(text, symbols = []) {
  let html = escapeHtml(String(text || ""));
  const replacements = [];
  const candidates = [...new Set((symbols || []).filter(Boolean).flatMap((symbol) => {
    const normalized = String(symbol).trim();
    const latex = latexForSymbol(normalized);
    return [normalized, latex].filter(Boolean);
  }))].sort((a, b) => b.length - a.length);
  candidates.forEach((candidate) => {
    const safeCandidate = escapeHtml(candidate);
    if (!safeCandidate || safeCandidate.length > 60) return;
    const pattern = new RegExp(`(^|[^A-Za-z0-9_\\\\])(${escapeRegExp(safeCandidate)})(?![A-Za-z0-9_])`, "g");
    html = html.replace(pattern, (_match, prefix, value) => {
      const key = `__MATH_PLACEHOLDER_${replacements.length}__`;
      replacements.push([key, renderInlineLatexSymbol(value)]);
      return `${prefix}${key}`;
    });
  });
  replacements.forEach(([key, value]) => {
    html = html.replaceAll(key, value);
  });
  return html;
}

function renderInlineLatexSymbol(symbol) {
  const latex = latexForSymbol(symbol);
  return `<span class="latexRender inlineInterpretationMath" data-latex="${escapeAttribute(cleanLatex(latex))}" data-display="false">${escapeHtml(symbol)}</span>`;
}

function latexForSymbol(symbol) {
  const value = String(symbol || "").trim();
  const greek = {
    alpha: "\\alpha",
    beta: "\\beta",
    gamma: "\\gamma",
    delta: "\\delta",
    epsilon: "\\epsilon",
    varepsilon: "\\varepsilon",
    zeta: "\\zeta",
    eta: "\\eta",
    kappa: "\\kappa",
    lambda: "\\lambda",
    mu: "\\mu",
    nu: "\\nu",
    xi: "\\xi",
    pi: "\\pi",
    rho: "\\rho",
    sigma: "\\sigma",
    tau: "\\tau",
    theta: "\\theta",
    phi: "\\phi",
    varphi: "\\varphi",
    chi: "\\chi",
    psi: "\\psi",
    omega: "\\omega",
    Gamma: "\\Gamma",
    Delta: "\\Delta",
    Theta: "\\Theta",
    Lambda: "\\Lambda",
    Xi: "\\Xi",
    Pi: "\\Pi",
    Sigma: "\\Sigma",
    Phi: "\\Phi",
    Psi: "\\Psi",
    Omega: "\\Omega",
  };
  let latex = greek[value] || value;
  if (latex.startsWith("\\") && greek[latex.slice(1)]) latex = greek[latex.slice(1)];
  latex = latex.replace(/_([A-Za-z0-9]+)/g, "_{$1}");
  latex = latex.replace(/\^([A-Za-z0-9]+)/g, "^{$1}");
  return latex;
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function localFormulaSummary(kind, plainText, symbols, definitions) {
  const pieces = [`Тип: ${translateFormulaInterpretationKind(kind)}.`];
  if (plainText) pieces.push(`Читаемая запись: ${plainText}.`);
  if (symbols.length) pieces.push(`Задействованы переменные: ${symbols.slice(0, 10).join(", ")}.`);
  const defs = Object.entries(definitions || {});
  if (defs.length) pieces.push(`Рядом найдены определения: ${defs.map(([key, value]) => `${key} — ${value}`).join("; ")}.`);
  return pieces.join(" ");
}

function inferFormulaKind(latex, operators = []) {
  const text = String(latex || "");
  if (/\\forall|\\exists|\\in\b|\\notin|\\subset|\\supset|\\cup|\\cap/.test(text)) return "set_or_logic_expression";
  if (/\\to|\\mapsto|\\rightarrow|\\leftarrow|\\Rightarrow|\\Leftrightarrow/.test(text)) return "mapping_or_implication";
  if (/\\sum|\\prod|\\int|\\iint|\\iiint|\\oint|\\lim|\\min|\\max|\\argmin|\\argmax/.test(text)) return "aggregation_or_calculus";
  if (/\\leq?|\\geq?|\\neq?|\\approx|\\sim|\\equiv|[<>]/.test(text)) return "constraint_or_inequality";
  if (text.includes("=")) return "definition_or_equation";
  if (operators.includes("индекс") || operators.includes("степень")) return "mathematical_expression";
  return "mathematical_expression";
}

function translateFormulaInterpretationKind(kind) {
  return {
    aggregation_or_calculus: "суммирование, интеграл или предел",
    constraint_or_inequality: "ограничение или неравенство",
    definition_or_equation: "определение или уравнение",
    set_or_logic_expression: "множества, логика или кванторы",
    mapping_or_implication: "отображение или импликация",
    notation_context: "введение обозначений",
    mathematical_expression: "математическое выражение",
  }[kind] || kind || "математическое выражение";
}

function latexReadableFallback(latex) {
  return latexToReadableText(cleanLatex(latex))
    .replace(/[{}]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function formulaSymbols(formula) {
  const explicit = Array.isArray(formula?.symbols) ? formula.symbols : [];
  const ignoredCommands = /^(\\)?(frac|sum|prod|int|iint|iiint|oint|lim|min|max|argmin|argmax|det|ker|dim|deg|gcd|lcm|mod|bmod|pmod|Pr|Re|Im|sup|inf|limsup|liminf|left|right|begin|end|sin|cos|tan|log|ln|exp|sqrt|cdot|times|div|circ|cdots|dots|ldots|vdots|ddots|quad|qquad|le|leq|ge|geq|ne|neq|approx|sim|equiv|in|notin|subset|subseteq|supset|supseteq|cup|cap|setminus|forall|exists|land|lor|neg|to|mapsto|rightarrow|leftarrow|Rightarrow|Leftrightarrow|partial|nabla|infty|mathbb|mathcal|mathfrak|mathscr|mathrm|mathit|mathbf|text|mbox|operatorname)$/;
  const ignoredWords = new Set(["cases", "matrix", "pmatrix", "bmatrix", "vmatrix", "array", "align", "aligned", "equation", "split", "gather", "gathered", "operator", "operand", "lhs", "rhs", "root", "where", "if", "then", "for", "and", "or"]);
  const isSymbol = (item) => {
    const value = String(item || "");
    return value && !ignoredCommands.test(value) && !ignoredWords.has(value.replace(/^\\/, "").toLowerCase());
  };
  const latex = String(formula?.latex || "");
  const styled = [...latex.matchAll(/\\(?:mathbb|mathcal|mathfrak|mathscr|mathbf|mathit|mathrm)\s*\{\s*([A-Za-z])\s*\}/g)]
    .map((match) => match[0].replace(/\s+/g, ""));
  const maskedLatex = latex.replace(/\\(?:mathbb|mathcal|mathfrak|mathscr|mathbf|mathit|mathrm)\s*\{\s*[A-Za-z]\s*\}/g, " ");
  const inferred = [...maskedLatex.matchAll(/\\[A-Za-z]+|[A-Za-z][A-Za-z0-9_]*/g)]
    .map((match) => match[0])
    .filter(isSymbol);
  return [...new Set([...explicit, ...styled, ...inferred].filter(isSymbol))].slice(0, 32);
}

function formulaOperators(latex) {
  const found = [];
  const text = String(latex || "");
  const patterns = [
    ["\\frac", "дробь"],
    ["\\sqrt", "корень"],
    ["\\sum", "сумма"],
    ["\\prod", "произведение"],
    ["\\int", "интеграл"],
    ["\\iint", "двойной интеграл"],
    ["\\iiint", "тройной интеграл"],
    ["\\oint", "контурный интеграл"],
    ["\\lim", "предел"],
    ["\\min", "минимум"],
    ["\\max", "максимум"],
    ["\\argmin", "arg min"],
    ["\\argmax", "arg max"],
    ["=", "равенство"],
    ["\\ne", "не равно"],
    ["\\neq", "не равно"],
    ["\\approx", "приближенно равно"],
    ["\\sim", "подобно"],
    ["\\equiv", "эквивалентно"],
    ["<", "меньше"],
    [">", "больше"],
    ["\\le", "меньше или равно"],
    ["\\leq", "меньше или равно"],
    ["\\ge", "больше или равно"],
    ["\\geq", "больше или равно"],
    ["+", "сложение"],
    ["-", "вычитание"],
    ["/", "деление"],
    ["\\cdot", "умножение"],
    ["\\times", "умножение"],
    ["\\div", "деление"],
    ["\\circ", "композиция"],
    ["\\cdots", "многоточие"],
    ["\\dots", "многоточие"],
    ["\\ldots", "многоточие"],
    ["^", "степень"],
    ["\\partial", "частная производная"],
    ["\\nabla", "набла"],
    ["\\in", "принадлежит"],
    ["\\notin", "не принадлежит"],
    ["\\subset", "подмножество"],
    ["\\subseteq", "подмножество или равно"],
    ["\\supset", "надмножество"],
    ["\\supseteq", "надмножество или равно"],
    ["\\cup", "объединение"],
    ["\\cap", "пересечение"],
    ["\\setminus", "разность множеств"],
    ["\\forall", "для всех"],
    ["\\exists", "существует"],
    ["\\land", "логическое И"],
    ["\\lor", "логическое ИЛИ"],
    ["\\neg", "отрицание"],
    ["\\to", "отображение"],
    ["\\mapsto", "переходит в"],
    ["\\Rightarrow", "импликация"],
    ["\\Leftrightarrow", "эквивалентность"],
    ["\\sin", "синус"],
    ["\\cos", "косинус"],
    ["\\tan", "тангенс"],
    ["\\log", "логарифм"],
    ["\\ln", "натуральный логарифм"],
    ["\\exp", "экспонента"],
    ["\\det", "детерминант"],
    ["\\ker", "ядро"],
    ["\\operatorname", "именованный оператор"],
  ];
  patterns.forEach(([needle, label]) => {
    if (text.includes(needle)) found.push(label);
  });
  return [...new Set(found)];
}

function latexToReadableText(latex) {
  const commandMap = {
    "\\frac": " дробь ",
    "\\sqrt": " корень ",
    "\\sum": " сумма ",
    "\\prod": " произведение ",
    "\\int": " интеграл ",
    "\\iint": " двойной интеграл ",
    "\\iiint": " тройной интеграл ",
    "\\oint": " контурный интеграл ",
    "\\lim": " предел ",
    "\\min": " минимум ",
    "\\max": " максимум ",
    "\\argmin": " arg min ",
    "\\argmax": " arg max ",
    "\\cdot": " умножить ",
    "\\times": " умножить ",
    "\\div": " разделить ",
    "\\le": " меньше или равно ",
    "\\leq": " меньше или равно ",
    "\\ge": " больше или равно ",
    "\\geq": " больше или равно ",
    "\\ne": " не равно ",
    "\\neq": " не равно ",
    "\\approx": " приблизительно равно ",
    "\\sim": " подобно ",
    "\\equiv": " эквивалентно ",
    "\\in": " принадлежит ",
    "\\notin": " не принадлежит ",
    "\\subset": " подмножество ",
    "\\subseteq": " подмножество или равно ",
    "\\supset": " надмножество ",
    "\\supseteq": " надмножество или равно ",
    "\\cup": " объединение ",
    "\\cap": " пересечение ",
    "\\setminus": " разность ",
    "\\forall": " для всех ",
    "\\exists": " существует ",
    "\\land": " и ",
    "\\lor": " или ",
    "\\neg": " не ",
    "\\to": " переходит в ",
    "\\mapsto": " отображается в ",
    "\\Rightarrow": " следует ",
    "\\Leftrightarrow": " тогда и только тогда ",
    "\\partial": " частная производная ",
    "\\nabla": " набла ",
    "\\infty": " бесконечность ",
  };
  let value = String(latex || "");
  Object.entries(commandMap)
    .sort((a, b) => b[0].length - a[0].length)
    .forEach(([command, label]) => {
      value = value.replaceAll(command, label);
    });
  return value
    .replace(/\^\{?([^{}\s]+)\}?/g, " в степени $1 ")
    .replace(/_\{?([^{}\s]+)\}?/g, " с индексом $1 ")
    .replaceAll("=", " равно ")
    .replaceAll("+", " плюс ")
    .replaceAll("-", " минус ")
    .replaceAll("*", " умножить ")
    .replaceAll("/", " разделить ")
    .replaceAll("<", " меньше ")
    .replaceAll(">", " больше ")
    .replace(/\\([A-Za-z]+)/g, "$1");
}

function translateFormulaKind(kind) {
  if (kind === "inline") return "в строке";
  if (kind === "block") return "блок";
  return kind || "-";
}

function replaceFormulaInState(formula) {
  if (!state.result?.formulas) return;
  const index = state.result.formulas.findIndex((item) => item.id === formula.id);
  if (index >= 0) state.result.formulas[index] = formula;
}

function renderDocumentPreview(result) {
  const target = document.querySelector("#documentPage");
  if (!target) return;
  const pages = result.pages || [];
  if (isTexSourceResult(result) && !pages.length) {
    const arxivIds = arxivIdsFromResult(result);
    target.innerHTML = `
      <section class="texSourceInfo">
        <strong>Документ обработан из TeX-источника</strong>
        <span>Превью страниц и OCR-оверлей не требуются для этого режима.</span>
        ${arxivIds.length ? `
          <div class="arxivLinkList">
            ${arxivIds.map((id) => `
              <a href="https://arxiv.org/abs/${escapeAttribute(id)}" target="_blank" rel="noreferrer">arXiv ${escapeHtml(id)}</a>
              <a href="https://arxiv.org/e-print/${escapeAttribute(id)}" target="_blank" rel="noreferrer">TeX-источник</a>
            `).join("")}
          </div>
        ` : ""}
      </section>
    `;
    return;
  }
  if (pages.length) {
    target.innerHTML = `
      <div class="pageHeader">
        <strong>Превью документа</strong>
        <span>${pages.length} страниц</span>
      </div>
      <div class="pageOverlayGrid">
        ${pages
          .map(
            (page) => `
              <section class="pageCard">
                <div class="pageCardTop"><strong>стр. ${page.page_number}</strong><span>${page.width}x${page.height}, ${page.dpi || "-"} DPI</span></div>
                <div class="pagePreviewFrame" data-doc-preview-page="${page.page_number}" role="button" tabindex="0">
                  <img class="pagePreviewImage" src="${escapeAttribute(pagePreviewUrl(result.document_id, page.image_path))}" alt="страница ${page.page_number}" loading="lazy" />
                </div>
              </section>
            `
          )
          .join("")}
      </div>
    `;
    target.querySelectorAll("[data-doc-preview-page]").forEach((frame) => {
      const page = pages.find((item) => item.page_number === Number(frame.dataset.docPreviewPage));
      frame.addEventListener("click", () => openOverlayModal(result.document_id, page, [], []));
      frame.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          openOverlayModal(result.document_id, page, [], []);
        }
      });
    });
    return;
  }
  const blocks = getTokenTextBlocks(result);
  const text = blocks.map((block) => String(block.text || "").trim()).filter(Boolean).join("\n\n");
  target.innerHTML = `
    <div class="pageHeader">
      <strong>Превью документа</strong>
      <span>TeX/text-источник</span>
    </div>
    <article class="textPlainFlow">${text ? splitIntoReadableParagraphs(text, 1200).map((paragraph) => `<p>${renderTokenizedHtml(paragraph)}</p>`).join("") : "Документ пока не прочитан."}</article>
  `;
}

function arxivIdsFromResult(result) {
  const candidates = [
    result?.filename,
    result?.document_id,
    ...(result?.warnings || []),
    ...(result?.source_files || []),
  ];
  const ids = [];
  candidates.forEach((value) => {
    String(value || "").replace(/(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?\/\d{7})(?:v\d+)?/gi, (match) => {
      ids.push(match);
      return match;
    });
  });
  return [...new Set(ids)];
}

function isTexSourceResult(result) {
  return (result.formulas || []).some((formula) => String(formula.source || "").startsWith("tex_source"))
    || (result.text_blocks || []).some((block) => String(block.source || "").startsWith("tex_source"))
    || String(result.source_type || "") === "tex_source";
}

function hasFormulaOverlayData(result) {
  const pages = result?.pages || [];
  const regions = getFormulaOverlayRegions(result);
  if (!pages.length || !regions.length) return false;
  return regions.some((region) => Array.isArray(region.bbox) && region.bbox.length === 4);
}

function getFormulaOverlayRegions(result) {
  const explicitRegions = (result?.formula_regions || []).filter((region) => Array.isArray(region.bbox) && region.bbox.length === 4);
  if (explicitRegions.length) return explicitRegions;
  return (result?.formulas || [])
    .filter((formula) => Array.isArray(formula.bbox) && formula.bbox.length === 4 && formula.page_number)
    .map((formula, index) => ({
      id: formula.formula_region_id || `formula_overlay_${formula.id || index + 1}`,
      token: formula.token || formula.id || `FORMULA_${String(index + 1).padStart(3, "0")}`,
      page_number: formula.page_number,
      bbox: formula.bbox,
      kind: formula.kind || "unknown",
      source: formula.source || "formula_bbox",
      confidence: formula.confidence ?? null,
      formula_ids: formula.id ? [formula.id] : [],
      formula_keys: [],
      latex_keys: formula.latex ? [formula.latex] : [],
    }));
}

function getRelevantWarnings(warnings, result = state.result) {
  const items = Array.isArray(warnings) ? warnings : [];
  if (!items.length) return [];
  if (!isTexSourceResult(result) || hasFormulaOverlayData(result)) return items;
  return items.filter((warning) => {
    const text = String(warning || "").toLowerCase();
    return !(
      text.includes("render_dpi") ||
      text.includes("dpi") ||
      text.includes("max_pages") ||
      text.includes("capped processing") ||
      text.includes("capped render") ||
      text.includes("ocr") ||
      text.includes("page image") ||
      text.includes("raster") ||
      text.includes("render")
    );
  });
}

function translateWarningText(value) {
  let text = String(value || "");
  const replacements = [
    [/Formula tokens must be unique\./gi, "Формульные токены должны быть уникальными."],
    [/Some formula tokens are not present in text_with_tokens\./gi, "Некоторые формульные токены отсутствуют в тексте с токенами."],
    [/A formula context points to a missing formula\./gi, "Контекст формулы ссылается на отсутствующую формулу."],
    [/A formula context window does not contain its token\./gi, "Окно контекста формулы не содержит ее токен."],
    [/Some relations point to unknown graph-ready objects\./gi, "Некоторые связи ссылаются на неизвестные объекты графа."],
    [/Some objects point to unknown sections\./gi, "Некоторые объекты ссылаются на неизвестные разделы."],
    [/Summary field ([^ ]+) does not match payload\./gi, "Поле сводки $1 не совпадает с данными."],
    [/Some pages do not have an embedded text layer\./gi, "У некоторых страниц нет встроенного текстового слоя."],
    [/Some pages have a poor embedded text layer\./gi, "У некоторых страниц слабый встроенный текстовый слой."],
    [/Some detected formula regions have no recognized LaTeX\./gi, "Для некоторых найденных областей формул нет распознанного LaTeX."],
    [/Formula regions were detected but logical formulas were not built\./gi, "Области формул найдены, но логические формулы не построены."],
    [/provider unavailable/gi, "провайдер недоступен"],
    [/provider exception/gi, "ошибка провайдера"],
    [/manual_on_demand/gi, "ручной запуск"],
    [/no low-confidence items/gi, "нет элементов с низкой уверенностью"],
    [/batch mode/gi, "пакетный режим"],
    [/disabled/gi, "отключено"],
  ];
  replacements.forEach(([pattern, replacement]) => {
    text = text.replace(pattern, replacement);
  });
  return translateStage(text);
}

function renderHeaderDocumentSelector() {
  if (!headerDocumentSelector) return;
  const docs = state.activeBatch?.documents || [];
  const ready = docs.filter((doc) => ["ok", "partial"].includes(doc.status));
  if (ready.length <= 1) {
    headerDocumentSelector.hidden = true;
    headerDocumentSelector.innerHTML = "";
    return;
  }
  headerDocumentSelector.hidden = false;
  headerDocumentSelector.innerHTML = `
    <label>
      <span>Активная статья</span>
      <select id="headerActiveDocumentSelect">
        ${ready.map((doc) => `<option value="${escapeAttribute(doc.document_id)}" ${doc.document_id === state.result?.document_id ? "selected" : ""}>${escapeHtml(doc.filename)}</option>`).join("")}
      </select>
    </label>
  `;
  headerDocumentSelector.querySelector("#headerActiveDocumentSelect")?.addEventListener("change", (event) => openBatchDocument(event.target.value));
}

function historyStorageKey() {
  return "formula_graph_run_history_v1";
}

function readRunHistory() {
  try {
    return JSON.parse(localStorage.getItem(historyStorageKey()) || "[]");
  } catch {
    return [];
  }
}

function writeRunHistory(items) {
  localStorage.setItem(historyStorageKey(), JSON.stringify(items.slice(0, 80)));
}

function rememberRun(result) {
  if (!result?.document_id) return;
  const arxivMatch = String(result.filename || "").match(/(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?\/\d{7})(?:v\d+)?/i);
  const item = {
    document_id: result.document_id,
    title: arxivMatch?.[0] || result.filename || result.document_id,
    filename: result.filename || "",
    status: result.status || "",
    created_at: result.created_at || new Date().toISOString(),
    opened_at: new Date().toISOString(),
  };
  const existing = readRunHistory().filter((entry) => entry.document_id !== result.document_id);
  writeRunHistory([item, ...existing]);
}

async function renderHistoryPage() {
  if (!historyPanel) return;
  const local = readRunHistory();
  renderHistoryItems(local, "История запусков");
  let remote = [];
  try {
    const response = await fetchWithTimeout(`${API_BASE}/api/analytics/documents`, {}, 4000);
    if (response.ok) remote = (await response.json()).documents || [];
  } catch {
    remote = [];
  }
  const byId = new Map();
  remote.forEach((item) => byId.set(item.document_id, { ...item }));
  local.forEach((item) => byId.set(item.document_id, { ...(byId.get(item.document_id) || {}), ...item }));
  const items = [...byId.values()].filter((item) => item.document_id).sort((a, b) => String(b.opened_at || b.created_at || "").localeCompare(String(a.opened_at || a.created_at || "")));
  renderHistoryItems(items, remote.length ? "История запусков" : "История запусков");
}

function renderHistoryItems(items, title) {
  if (!historyPanel) return;
  historyPanel.innerHTML = `
    <div class="historyHeader">
      <strong>${escapeHtml(title)}</strong>
      <button type="button" data-history-refresh>Обновить</button>
    </div>
    <div class="historyList">
      ${items.length ? items.map(renderHistoryItem).join("") : `<div class="emptyHint">История пока пуста.</div>`}
    </div>
  `;
  historyPanel.querySelector("[data-history-refresh]")?.addEventListener("click", () => renderHistoryPage());
  historyPanel.querySelectorAll("[data-history-open]").forEach((button) => {
    button.addEventListener("click", () => openHistoryDocument(button.dataset.historyOpen));
  });
}

function renderHistoryItem(item) {
  const title = item.title || item.filename || item.document_id;
  const created = item.opened_at || item.created_at || "";
  return `
    <button type="button" class="historyItem" data-history-open="${escapeAttribute(item.document_id)}">
      <span>${escapeHtml(title)}</span>
      <small>${escapeHtml(formatDateTime(created))}</small>
    </button>
  `;
}

async function openHistoryDocument(documentId) {
  if (!documentId) return;
  const response = await fetchWithTimeout(`${API_BASE}/api/results/${encodeURIComponent(documentId)}`, {}, 60000);
  if (!response.ok) {
    showUploadMessage(`Не удалось открыть результат ${documentId}`);
    return;
  }
  const result = await response.json();
  renderResult(result);
  activatePage(isTexSourceResult(result) ? "text" : "document");
}

function formatDateTime(value) {
  if (!value) return "дата неизвестна";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
}

function renderVariableSearch(result) {
  const target = document.querySelector("#variablesPage");
  if (!target) return;
  target.innerHTML = `
    <form id="variableSearchForm" class="variableSearchBar">
      <input id="variableSearchInput" type="search" placeholder="lambda, λ, \\\\lambda, x_i" autocomplete="off" />
      <button type="submit">Найти</button>
    </form>
    <div id="variableSearchMeta" class="variableSearchMeta"></div>
    <div id="variableSearchResults" class="variableSearchResults"></div>
  `;

  const form = target.querySelector("#variableSearchForm");
  const input = target.querySelector("#variableSearchInput");
  const meta = target.querySelector("#variableSearchMeta");
  const results = target.querySelector("#variableSearchResults");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const query = input.value.trim();
    if (!query) return;
    meta.textContent = "Поиск...";
    results.innerHTML = "";
    try {
      const url = state.viewMode === "corpus" && state.activeCorpus?.corpus_id
        ? `${API_BASE}/api/corpus/${encodeURIComponent(state.activeCorpus.corpus_id)}/variables/search?q=${encodeURIComponent(query)}`
        : `${API_BASE}/api/results/${encodeURIComponent(result.document_id)}/variables/search?q=${encodeURIComponent(query)}`;
      const response = await fetch(url);
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || `HTTP ${response.status}`);
      }
      const payload = await response.json();
      state.variableSearch = payload;
      renderVariableSearchResults(payload, meta, results);
    } catch (error) {
      meta.textContent = `Ошибка поиска: ${error.message}`;
    }
  });

  if (state.pendingVariableSearch) {
    input.value = state.pendingVariableSearch;
    form.requestSubmit();
    state.pendingVariableSearch = null;
  }
}

function openVariableSearch(symbol) {
  if (!symbol) return;
  state.pendingVariableSearch = symbol;
  activatePage("variables");
  const input = document.querySelector("#variableSearchInput");
  const form = document.querySelector("#variableSearchForm");
  if (input && form) {
    input.value = symbol;
    form.requestSubmit();
    state.pendingVariableSearch = null;
  }
}

function renderVariableSearchResults(payload, meta, results) {
  if (payload.results_by_document) {
    renderCorpusVariableSearchResults(payload, meta, results);
    return;
  }
  const variable = payload.variable;
  meta.textContent = `${payload.query} → ${payload.normalized_query || "-"} | совпадений: ${payload.matches_count}`;
  if (!payload.matches_count || !variable) {
    results.innerHTML = `<article class="variableResultCard">Совпадения не найдены.</article>`;
    return;
  }

  const definitionHtml = (variable.possible_definitions || [])
    .map((item) => `<li>${escapeHtml(item.definition_text || item.evidence || "")}</li>`)
    .join("");

  results.innerHTML = `
    <section class="variableSummaryCard">
      <div>
        <span class="meta">переменная</span>
        <strong>${escapeHtml(variable.normalized_symbol)}</strong>
      </div>
      <div>
        <span class="meta">вхождений</span>
        <strong>${variable.usage_count || 0}</strong>
      </div>
      <div>
        <span class="meta">формул</span>
        <strong>${(variable.formula_ids || []).length}</strong>
      </div>
      ${definitionHtml ? `<ul class="variableDefinitionList">${definitionHtml}</ul>` : ""}
    </section>
    <section class="variableGraphPanel">
      <div class="variableGraphHeader">
        <strong>Связи переменной</strong>
        <div class="variableGraphActions">
          <span>только формулы, где найдена переменная</span>
          <button type="button" data-variable-panel-command="list">Скрыть список</button>
          <button type="button" data-variable-panel-command="details">Скрыть детали</button>
          <button type="button" data-variable-panel-command="expand">Развернуть граф</button>
        </div>
      </div>
      <div class="variableGraphContent">
        <div class="variableFormulaList">
          ${(payload.matches || []).slice(0, 10).map(renderVariableFormulaMini).join("") || `<div class="graphLoading">Формулы для переменной не найдены.</div>`}
        </div>
        <div id="variableNeighborhoodGraph" class="variableNeighborhoodGraph formulaOnlyVariableGraph"></div>
      </div>
    </section>
    ${(payload.matches || []).map(renderVariableMatchCard).join("")}
  `;
  renderVariableFormulaOnlyGraph(payload, results.querySelector("#variableNeighborhoodGraph"));
  bindVariableGraphPanelControls(results);
  renderKatex(results);
  results.querySelectorAll(".tokenChip").forEach((button) => {
    button.addEventListener("click", () => selectToken(button.dataset.token));
  });
  results.querySelectorAll("[data-open-formula-id]").forEach((button) => {
    button.addEventListener("click", () => {
      openFormulaDetails({
        formulaId: button.dataset.openFormulaId || "",
        token: button.dataset.openFormulaToken || "",
        projectionMode: button.dataset.openFormulaMode || "formula_focus",
      });
    });
  });
}

function renderVariableFormulaOnlyGraph(payload, host) {
  if (!host) return;
  const variable = payload.variable;
  const matches = (payload.matches || []).filter((match) => match.formula_id && match.latex);
  if (!variable || !matches.length) {
    host.innerHTML = `<div class="graphLoading">Для этой переменной нет формульных вхождений.</div>`;
    return;
  }
  const unique = [];
  const seen = new Set();
  matches.forEach((match) => {
    const key = match.formula_id || match.token || match.latex;
    if (seen.has(key)) return;
    seen.add(key);
    unique.push(match);
  });
  const items = unique.slice(0, 24);
  const width = 1140;
  const formulaGap = 28;
  const formulaW = 580;
  const nodeHeightFor = (match) => {
    const latexLength = cleanLatex(match.latex || "").length;
    const estimatedLines = Math.max(2, Math.ceil(latexLength / 54));
    return Math.min(180, Math.max(96, 52 + estimatedLines * 24));
  };
  let nextY = 70;
  const nodes = items.map((match) => {
    const h = nodeHeightFor(match);
    const node = {
      match,
      x: 440,
      y: nextY + h / 2,
      h,
    };
    nextY += h + formulaGap;
    return node;
  });
  const height = Math.max(320, nextY + 40);
  const center = { x: 155, y: height / 2 };
  const edges = nodes.map((node) => {
    const x1 = center.x + 60;
    const y1 = center.y;
    const x2 = node.x - 18;
    const y2 = node.y;
    const mx = (x1 + x2) / 2;
    return `<path class="variableFormulaEdge" d="M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}" />`;
  }).join("");
  host.innerHTML = `
    <svg class="variableFormulaSvg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Формулы с переменной ${escapeAttribute(variable.normalized_symbol)}">
      <defs>
        <marker id="variableFormulaArrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z"></path></marker>
      </defs>
      ${edges}
      <g class="variableFormulaRoot" transform="translate(${center.x}, ${center.y})">
        <circle r="58"></circle>
        <foreignObject x="-46" y="-32" width="92" height="44">
          <div xmlns="http://www.w3.org/1999/xhtml" class="variableFormulaRootMath latexRender" data-latex="${escapeAttribute(cleanLatex(variable.normalized_symbol || payload.query || "?"))}" data-display="false"></div>
        </foreignObject>
        <text y="18" text-anchor="middle">${items.length} формул</text>
      </g>
      ${nodes.map(({ match, x, y, h }) => `
        <g class="variableFormulaNode" transform="translate(${x}, ${y})" data-token="${escapeAttribute(match.token || "")}" data-formula-id="${escapeAttribute(match.formula_id || "")}">
          <rect x="0" y="${-h / 2}" width="${formulaW}" height="${h}" rx="10"></rect>
          <text class="variableFormulaToken" x="16" y="${-h / 2 + 25}">${escapeHtml(match.token || match.formula_id || "-")}</text>
          <text class="variableFormulaSection" x="170" y="${-h / 2 + 25}">${escapeHtml(shortText(match.section_title || match.section_id || "", 52))}</text>
          <foreignObject x="14" y="${-h / 2 + 40}" width="${formulaW - 28}" height="${Math.max(44, h - 52)}">
            <div xmlns="http://www.w3.org/1999/xhtml" class="variableFormulaLatex latexRender" data-latex="${escapeAttribute(cleanLatex(match.latex || ""))}" data-display="false"></div>
          </foreignObject>
        </g>
      `).join("")}
    </svg>
    ${unique.length > items.length ? `<div class="meta">Показано ${items.length} из ${unique.length}; уточните поиск или смотрите список ниже.</div>` : ""}
  `;
  host.querySelectorAll(".variableFormulaNode").forEach((node) => {
    node.addEventListener("click", () => {
      openFormulaDetails({
        formulaId: node.dataset.formulaId || "",
        token: node.dataset.token || "",
        projectionMode: "formula_focus",
      });
    });
  });
  renderKatex(host);
}

function bindVariableGraphPanelControls(root) {
  const panel = root.querySelector(".variableGraphPanel");
  if (!panel) return;
  panel.querySelectorAll("[data-variable-panel-command]").forEach((button) => {
    button.addEventListener("click", () => {
      const command = button.dataset.variablePanelCommand;
      if (command === "list") {
        const hidden = panel.classList.toggle("hideVariableList");
        button.textContent = hidden ? "Показать список" : "Скрыть список";
      }
      if (command === "details") {
        const hidden = panel.classList.toggle("hideVariableDetails");
        button.textContent = hidden ? "Показать детали" : "Скрыть детали";
      }
      if (command === "expand") {
        const expanded = panel.classList.toggle("expandVariableGraph");
        button.textContent = expanded ? "Обычный размер" : "Развернуть граф";
      }
      window.dispatchEvent(new Event("resize"));
    });
  });
}

function renderVariableFormulaMini(match) {
  return `
    <article class="variableFormulaMini">
      <div class="variableFormulaMiniTop">
        <div class="meta">${escapeHtml(match.token || "-")} | ${escapeHtml(match.section_title || match.section_id || "раздел не указан")}</div>
        <button
          type="button"
          class="secondaryInlineButton variableFormulaOpenButton"
          data-open-formula-id="${escapeAttribute(match.formula_id || "")}"
          data-open-formula-token="${escapeAttribute(match.token || "")}"
          data-open-formula-mode="formula_focus"
        >К формуле</button>
      </div>
      <div class="latexRender" data-latex="${escapeAttribute(cleanLatex(match.latex || ""))}" data-display="false"></div>
      ${match.window_text || match.context ? `<p>${escapeHtml(shortText(match.window_text || match.context, 220))}</p>` : ""}
    </article>
  `;
}

function renderCorpusVariableSearchResults(payload, meta, results) {
  meta.textContent = `${payload.query} -> ${payload.normalized_query || "-"} | документов: ${payload.documents_count} | вхождений: ${payload.total_occurrences}`;
  if (!payload.documents_count) {
    results.innerHTML = `<article class="variableResultCard">Совпадения по корпусу не найдены.</article>`;
    return;
  }
  results.innerHTML = `
    <section class="variableSummaryCard">
      <div><span class="meta">переменная корпуса</span><strong>${escapeHtml(payload.normalized_query)}</strong></div>
      <div><span class="meta">документов</span><strong>${payload.documents_count}</strong></div>
      <div><span class="meta">вхождений</span><strong>${payload.total_occurrences}</strong></div>
    </section>
    ${(payload.results_by_document || []).map((doc) => `
      <article class="variableResultCard">
        <div class="formulaHeader">
          <strong>${escapeHtml(doc.filename || doc.document_id)}</strong>
          <button type="button" data-open-doc="${escapeAttribute(doc.document_id)}">Открыть документ</button>
        </div>
        <p>область: ${escapeHtml(JSON.stringify(doc.scope || {}))} | уверенность: ${formatConfidence(doc.confidence)}</p>
        ${(doc.definitions || []).length ? `<ul>${doc.definitions.map((item) => `<li>${escapeHtml(item.definition_text || item.evidence || "")}</li>`).join("")}</ul>` : ""}
        ${(doc.formulas || []).slice(0, 8).map((formula) => `<div class="latexRender" data-latex="${escapeAttribute(cleanLatex(formula.latex || ""))}" data-display="true"></div>`).join("")}
      </article>
    `).join("")}
    ${(payload.conflicts || []).length ? `<section class="variableResultCard"><strong>Возможные конфликты</strong>${payload.conflicts.map((item) => `<p>${escapeHtml(item.document_a)}: ${escapeHtml(item.meaning_a)} / ${escapeHtml(item.document_b)}: ${escapeHtml(item.meaning_b)}</p>`).join("")}</section>` : ""}
  `;
  results.querySelectorAll("[data-open-doc]").forEach((button) => button.addEventListener("click", () => openBatchDocument(button.dataset.openDoc)));
  renderKatex(results);
}

function renderVariableMatchCard(match) {
  const definitions = (match.possible_definitions || [])
    .map(
      (item) => `
        <li>
          <strong>${escapeHtml(item.symbol || "")}</strong>
          <span>${escapeHtml(item.definition_text || "")}</span>
          <em>${escapeHtml(item.evidence || "")}</em>
        </li>
      `
    )
    .join("");
  const related = (match.related_variables || []).map((item) => `<span>${escapeHtml(item)}</span>`).join("");
  return `
    <article class="variableResultCard">
      <div class="variableResultTop">
        <button type="button" class="tokenChip" data-token="${escapeAttribute(match.token || "")}">${escapeHtml(match.token || "-")}</button>
        <span>${escapeHtml(match.section_title || match.section_id || "section -")}</span>
        <button
          type="button"
          class="secondaryInlineButton variableFormulaOpenButton"
          data-open-formula-id="${escapeAttribute(match.formula_id || "")}"
          data-open-formula-token="${escapeAttribute(match.token || "")}"
          data-open-formula-mode="formula_focus"
        >К формуле</button>
        <strong>${formatConfidence(match.confidence)}</strong>
      </div>
      <div class="latexRender" data-latex="${escapeAttribute(cleanLatex(match.latex || ""))}" data-display="${match.kind === "display_math"}"></div>
      <details class="latexSource" open>
        <summary>LaTeX и контекст</summary>
        <code>${escapeHtml(match.latex || "")}</code>
        <p>${escapeHtml(match.context_before || "")}</p>
        <p>${escapeHtml(match.context_after || "")}</p>
        <div class="variableWindow">${renderTokenizedHtml(match.window_text || "")}</div>
      </details>
      ${definitions ? `<ul class="variableDefinitionList">${definitions}</ul>` : ""}
      ${related ? `<div class="variableRelated">${related}</div>` : ""}
    </article>
  `;
}

function renderKatex(root) {
  root.querySelectorAll(".latexRender").forEach((element) => {
    const latex = normalizeLatexForKatex(element.dataset.latex || "");
    const displayMode = element.dataset.display === "true";
    if (!latex.trim()) {
      element.textContent = "";
      element.classList.add("latexEmpty");
      element.hidden = true;
      return;
    }
    if (!window.katex) {
      element.textContent = latex;
      element.classList.add("latexError");
      return;
    }
    try {
      window.katex.render(latex, element, {
        displayMode,
        throwOnError: false,
        strict: false,
        trust: false,
        output: "html",
      });
    } catch (error) {
      element.textContent = latex;
      element.classList.add("latexError");
      element.title = error.message;
    }
  });
}

function cleanLatex(value) {
  return String(value)
    .trim()
    .replace(/^(\$\$?)+/, "")
    .replace(/(\$\$?)+$/, "")
    .replace(/^\\\[/, "")
    .replace(/\\\]$/, "")
    .replace(/^\\\(/, "")
    .replace(/\\\)$/, "")
    .trim();
}

function normalizeLatexForKatex(value) {
  let latex = cleanLatex(value)
    .replace(/\\mbox\s*\{([^{}]*)\}/g, "\\text{$1}")
    .replace(/\\begin\{equation\*?\}/g, "")
    .replace(/\\end\{equation\*?\}/g, "")
    .replace(/\\begin\{align\*?\}/g, "\\begin{aligned}")
    .replace(/\\end\{align\*?\}/g, "\\end{aligned}")
    .replace(/\\begin\{eqnarray\*?\}/g, "\\begin{aligned}")
    .replace(/\\end\{eqnarray\*?\}/g, "\\end{aligned}")
    .replace(/\\label\{[^{}]*\}/g, "")
    .trim();

  if (hasUnescapedAlignmentMarker(latex) && !/\\begin\{(?:aligned|array|cases|matrix|pmatrix|bmatrix|vmatrix|Vmatrix|smallmatrix)\}/.test(latex)) {
    latex = latex.replace(/(^|[^\\])&/g, "$1");
  }
  return latex;
}

function hasUnescapedAlignmentMarker(value) {
  return /(^|[^\\])&/.test(String(value || ""));
}

function hasRenderableLatex(value) {
  if (value === null || value === undefined) return false;
  const latex = normalizeLatexForKatex(value).trim();
  return Boolean(latex && latex !== "undefined" && latex !== "null");
}

function renderGraphVisualization(result, selector, mode, detailsId) {
  const target = typeof selector === "string" ? document.querySelector(selector) : selector;
  if (!target) return;
  target.innerHTML = `<div class="graphLoading">Загрузка ${escapeHtml(mode)}...</div>`;
  const cacheKey = `${result.document_id}:${mode}`;
  const cached = state.visualizationCache.get(cacheKey);
  if (cached) {
    renderGraph(cytoscapeElementsToGraph(cached.elements || []), target, detailsId, cached);
    return;
  }
  fetchWithTimeout(
    `${API_BASE}/api/results/${encodeURIComponent(result.document_id)}/visualization?mode=${encodeURIComponent(mode)}`,
    {},
    90 * 1000
  )
    .then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then((payload) => {
      state.visualizationCache.set(cacheKey, payload);
      renderGraph(cytoscapeElementsToGraph(payload.elements || []), target, detailsId, payload);
    })
    .catch((error) => {
      const fallback = mode === "formula_semantic" ? result.graph : result.metagraph;
      if (fallback?.nodes?.length) {
        renderGraph(fallback || { nodes: [], edges: [] }, target, detailsId);
        return;
      }
      target.innerHTML = `<div class="graphLoading">Не удалось загрузить визуализацию: ${escapeHtml(error.message || "неизвестная ошибка")}</div>`;
    });
}

function renderMetagraphVisualization(result) {
  if (window.GraphVisualization?.renderMetagraphVisualization) {
    window.GraphVisualization.renderMetagraphVisualization(result, {
      apiBase: API_BASE,
      activeCorpus: state.activeCorpus,
    });
    return;
  }
  const target = document.querySelector("#visualizationPage");
  if (!target) return;
  const modes = [
    ["graph_view", "Связи", "Обычные вершины и связи: формулы, переменные, контекст."],
    ["metagraph_view", "Метаграф", "Сводный режим по формульно-контекстным метавершинам."],
    ["nested_metagraph", "Вложенный метаграф", "Метавершины как контейнеры, вложенные узлы и метаребра между наборами."],
    ["formula_context_view", "Контекст формул", "Формулы рядом с предложениями, определениями и контекстами."],
    ["variable_neighborhood_view", "Окрестности переменных", "Окрестности переменных и связанные формулы."],
    ["corpus_graph_view", "Корпус", "Общий метаграф нескольких документов и междокументные связи."],
    ["extraction_evidence_view", "Источники извлечения", "Источники извлечения и качество."],
    ["document_structure_view", "Структура документа", "Структура документа: страницы, секции и параграфы."],
  ];
  target.innerHTML = `
    <div class="graphModeBar">
      ${modes
        .map(
          ([mode, label, description], index) => `
            <button type="button" class="graphModeButton${index === 0 ? " active" : ""}" data-graph-mode="${mode}" title="${escapeAttribute(description)}">
              ${label}
            </button>
          `
        )
        .join("")}
    </div>
    <div id="visualizationModeHint" class="modeHint">${escapeHtml(modes[0][2])}</div>
    <div id="metagraphVizHost"></div>
  `;
  const host = target.querySelector("#metagraphVizHost");
  const switchMode = (mode) => {
    const found = modes.find((item) => item[0] === mode);
    const hint = target.querySelector("#visualizationModeHint");
    if (hint) hint.textContent = found?.[2] || "";
    target.querySelectorAll(".graphModeButton").forEach((button) => {
      button.classList.toggle("active", button.dataset.graphMode === mode);
    });
    if (mode === "nested_metagraph") {
      renderNestedMetagraph(result, host);
      return;
    }
    if (mode === "corpus_graph_view") {
      renderCorpusVisualization(host);
      return;
    }
    renderGraphVisualization(result, host, mode, "metagraphDetails");
  };
  target.querySelectorAll(".graphModeButton").forEach((button) => {
    button.addEventListener("click", () => switchMode(button.dataset.graphMode));
  });
  switchMode("graph_view");
}

function cytoscapeElementsToGraph(elements) {
  const nodes = [];
  const edges = [];
  (elements || []).forEach((element) => {
    const data = element.data || {};
    if (data.source && data.target) {
      edges.push({
        id: data.id,
        source: data.source,
        target: data.target,
        label: data.label || data.type || "related",
        payload: data,
      });
      return;
    }
    nodes.push({
      id: data.id,
      label: data.label || data.id,
      kind: data.type || "entity",
      payload: data,
    });
  });
  return { nodes, edges };
}

async function renderNestedMetagraph(result, target) {
  if (!target) return;
  target.innerHTML = `<div class="graphLoading">Загрузка расширенного метаграфа...</div>`;
  try {
    const response = await fetchWithTimeout(`${API_BASE}/api/results/${encodeURIComponent(result.document_id)}/rich-metagraph`, {}, 60000);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    target.innerHTML = renderNestedMetagraphSvg(payload);
    target.querySelectorAll("[data-nested-object]").forEach((item) => {
      item.addEventListener("click", () => {
        const details = target.querySelector("#nestedDetails");
        if (details) details.textContent = item.dataset.nestedObject || "";
      });
    });
  } catch (error) {
    target.innerHTML = `<div class="graphLoading">Не удалось загрузить расширенный метаграф: ${escapeHtml(error.message || "неизвестная ошибка")}</div>`;
  }
}

async function renderCorpusVisualization(target) {
  if (!target) return;
  if (!state.activeCorpus?.corpus_id) {
    target.innerHTML = `<div class="graphLoading">Корпус пока не создан. Откройте страницу "Загрузка", выберите несколько документов и создайте общий граф.</div>`;
    return;
  }
  target.innerHTML = `<div class="graphLoading">Загрузка корпуса...</div>`;
  try {
    const response = await fetchWithTimeout(`${API_BASE}/api/corpus/${encodeURIComponent(state.activeCorpus.corpus_id)}/visualization`, {}, 60000);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    renderGraph(cytoscapeElementsToGraph(payload.elements || []), target, "corpusDetails", payload);
  } catch (error) {
    target.innerHTML = `<div class="graphLoading">Не удалось загрузить корпус: ${escapeHtml(error.message || "неизвестная ошибка")}</div>`;
  }
}

function renderNestedMetagraphSvg(payload) {
  const metavertices = normalizeCollection(payload.metavertices).slice(0, 18);
  const nodes = new Map(normalizeCollection(payload.nodes).map((node) => [node.id, node]));
  const metaedges = normalizeCollection(payload.metaedges).slice(0, 40);
  const width = 1180;
  const cellW = 360;
  const cellH = 250;
  const cols = 3;
  const rows = Math.max(1, Math.ceil(metavertices.length / cols));
  const height = rows * cellH + 80;
  const mvCenters = new Map();
  const nodeToMv = new Map();
  const groups = metavertices
    .map((mv, index) => {
      const col = index % cols;
      const row = Math.floor(index / cols);
      const cx = 190 + col * cellW;
      const cy = 135 + row * cellH;
      mvCenters.set(mv.id, { x: cx, y: cy });
      (mv.contains || []).forEach((id) => nodeToMv.set(id, mv.id));
      const children = (mv.contains || []).slice(0, 10);
      const childMarkup = children
        .map((childId, childIndex) => {
          const angle = (-Math.PI / 2) + (Math.PI * 2 * childIndex) / Math.max(1, children.length);
          const x = cx + Math.cos(angle) * 92;
          const y = cy + Math.sin(angle) * 54;
          const child = nodes.get(childId) || { id: childId, type: "metavertex", label: childId };
          return `
            <g class="nestedNode ${escapeAttribute(graphCategory({ kind: child.type, payload: child }))}" data-nested-object="${escapeAttribute(JSON.stringify(child, null, 2))}">
              <circle cx="${x}" cy="${y}" r="15"></circle>
              <text x="${x}" y="${y + 32}">${escapeHtml(shortText(child.label || child.id, 18))}</text>
            </g>
          `;
        })
        .join("");
      return `
        <g class="nestedMv" data-nested-object="${escapeAttribute(JSON.stringify(mv, null, 2))}">
          <ellipse cx="${cx}" cy="${cy}" rx="155" ry="92"></ellipse>
          <text class="nestedMvTitle" x="${cx}" y="${cy - 74}">${escapeHtml(shortText(mv.label || mv.id, 34))}</text>
          <text class="nestedMvMeta" x="${cx}" y="${cy - 55}">${escapeHtml(mv.type || "метавершина")} | ${(mv.contains || []).length} объектов</text>
          ${childMarkup}
        </g>
      `;
    })
    .join("");
  const edgeMarkup = metaedges
    .map((edge, index) => {
      const sourceMv = firstMappedMv(edge.source_set || [], nodeToMv, mvCenters);
      const targetMv = firstMappedMv(edge.target_set || [], nodeToMv, mvCenters);
      if (!sourceMv || !targetMv || sourceMv.id === targetMv.id) return "";
      const edgePayload = escapeAttribute(JSON.stringify(edge, null, 2));
      return `
        <path class="nestedMetaEdge" data-nested-object="${edgePayload}" d="M ${sourceMv.x} ${sourceMv.y} C ${(sourceMv.x + targetMv.x) / 2} ${sourceMv.y - 80 - index % 5 * 8}, ${(sourceMv.x + targetMv.x) / 2} ${targetMv.y + 80 + index % 5 * 8}, ${targetMv.x} ${targetMv.y}" />
        <text class="nestedEdgeLabel" data-nested-object="${edgePayload}" x="${(sourceMv.x + targetMv.x) / 2}" y="${(sourceMv.y + targetMv.y) / 2 - 10}">${escapeHtml(shortText(edge.type, 28))}</text>
      `;
    })
    .join("");
  return `
    <div class="nestedLayout">
      <div class="nestedCanvasWrap">
        <svg class="nestedCanvas" viewBox="0 0 ${width} ${height}" role="img" aria-label="Вложенный метаграф">
          ${edgeMarkup}
          ${groups}
        </svg>
      </div>
      <pre id="nestedDetails" class="nestedDetails">Выберите метавершину, вложенный узел или метаребро.</pre>
    </div>
  `;
}

function normalizeCollection(value) {
  if (Array.isArray(value)) return value;
  if (value && typeof value === "object") return Object.values(value);
  return [];
}

function firstMappedMv(ids, nodeToMv, mvCenters) {
  for (const id of ids || []) {
    const mvId = nodeToMv.get(id) || (mvCenters.has(id) ? id : null);
    if (mvId && mvCenters.has(mvId)) {
      return { id: mvId, ...mvCenters.get(mvId) };
    }
  }
  return null;
}

function renderGraph(graph, selector = "#visualizationPage", detailsId = "graphDetails", visualizationPayload = null) {
  const target = typeof selector === "string" ? document.querySelector(selector) : selector;
  target.innerHTML = "";
  const nodes = graph.nodes || [];
  const edges = graph.edges || [];
  if (!nodes.length) {
    target.textContent = "Граф пока не построен.";
    return;
  }

  const graphState = {
    query: "",
    filters: new Set(graphCategories(nodes).map((item) => item.id)),
    selectedId: null,
    scale: 1,
    tx: 0,
    ty: 0,
  };
  const view = buildGraphView(nodes, edges, graphState);
  const stats = visualizationPayload?.stats;
  const canvasWidth = graphCanvasWidth(view.nodes.length);
  const canvasHeight = graphCanvasHeight(view.nodes.length);
  target.innerHTML = `
    <div class="graphSummary">
      <strong>${nodes.length} узлов, ${edges.length} связей</strong>
      <span>
        Показано: <b data-graph-visible>${view.nodes.length} / ${view.edges.length}</b>.
        ${stats?.truncated ? `Сжато из ${stats.original_node_count} узлов / ${stats.original_edge_count} связей.` : "Нажмите на узел для деталей."}
      </span>
    </div>
    <div class="graphToolbar">
      <input class="graphSearch" type="search" placeholder="Поиск по узлам" aria-label="Поиск по узлам" />
      <div class="graphFilters">
        ${graphCategories(nodes)
          .map(
            (category) => `
              <label class="graphFilter">
                <input type="checkbox" value="${category.id}" checked />
                <span class="dot ${category.id}"></span>${category.title}
              </label>
            `
          )
          .join("")}
      </div>
      <div class="graphActions">
        <button type="button" data-graph-action="zoom-in">+</button>
        <button type="button" data-graph-action="zoom-out">-</button>
        <button type="button" data-graph-action="fit">Вписать</button>
      </div>
    </div>
    <div class="graphExplorer">
      <div class="graphCanvasWrap"></div>
      <div id="${detailsId}" class="graphDetails">Выберите узел на графе.</div>
    </div>
  `;

  const wrap = target.querySelector(".graphCanvasWrap");
  const svg = createSvg("svg", { viewBox: `0 0 ${canvasWidth} ${canvasHeight}`, class: "graphCanvas", role: "img" });
  const markerId = `arrowHead-${detailsId}`;
  svg.innerHTML = `
    <defs>
      <marker id="${markerId}" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 z"></path>
      </marker>
    </defs>
  `;
  const viewport = createSvg("g", { class: "graphViewport" });
  svg.appendChild(viewport);
  wrap.appendChild(svg);

  const redraw = () => {
    const nextView = buildGraphView(nodes, edges, graphState);
    target.querySelector("[data-graph-visible]").textContent = `${nextView.nodes.length} / ${nextView.edges.length}`;
    if (!graphState.selectedId && nextView.nodes[0]) graphState.selectedId = nextView.nodes[0].id;
    drawGraphViewport(viewport, graph, nextView, graphState, detailsId, markerId, target, canvasWidth, canvasHeight);
    if (graphState.selectedId) selectGraphNode(target, graph, graphState.selectedId, detailsId);
  };

  target.querySelector(".graphSearch").addEventListener("input", (event) => {
    graphState.query = event.target.value.trim().toLowerCase();
    graphState.selectedId = null;
    redraw();
  });
  target.querySelectorAll(".graphFilter input").forEach((input) => {
    input.addEventListener("change", () => {
      graphState.filters = new Set([...target.querySelectorAll(".graphFilter input:checked")].map((item) => item.value));
      graphState.selectedId = null;
      redraw();
    });
  });
  target.querySelectorAll("[data-graph-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const action = button.dataset.graphAction;
      if (action === "zoom-in") graphState.scale = Math.min(2.2, graphState.scale + 0.18);
      if (action === "zoom-out") graphState.scale = Math.max(0.55, graphState.scale - 0.18);
      if (action === "fit") {
        graphState.scale = 1;
        graphState.tx = 0;
        graphState.ty = 0;
      }
      applyGraphTransform(viewport, graphState);
    });
  });
  enableGraphPanZoom(svg, viewport, graphState);
  redraw();
}

function drawGraphViewport(viewport, graph, view, graphState, detailsId, markerId, root, canvasWidth, canvasHeight) {
  viewport.innerHTML = "";
  const activeIds = graphState.selectedId ? graphNeighborIds(graphState.selectedId, view.edges) : new Set();
  const edgeLayer = createSvg("g", { class: "graphEdgeLayer" });
  const nodeLayer = createSvg("g", { class: "graphNodeLayer" });

  view.edges.forEach((edge) => {
    const source = view.positions.get(edge.source);
    const target = view.positions.get(edge.target);
    if (!source || !target) return;
    const active = !graphState.selectedId || activeIds.has(edge.source) || activeIds.has(edge.target);
    const line = createSvg("line", {
      x1: source.x,
      y1: source.y,
      x2: target.x,
      y2: target.y,
      class: `graphEdge ${active ? "active" : "dimmed"}`,
      "marker-end": `url(#${markerId})`,
    });
    line.appendChild(createSvg("title", {}, `${edge.source} -[${edge.label}]-> ${edge.target}`));
    edgeLayer.appendChild(line);
  });

  view.nodes.forEach((node) => {
    const position = view.positions.get(node.id);
    const category = graphCategory(node);
    const isSelected = node.id === graphState.selectedId;
    const active = !graphState.selectedId || isSelected || activeIds.has(node.id);
    const group = createSvg("g", {
      class: `graphNode ${category} ${isSelected ? "selected" : ""} ${active ? "active" : "dimmed"}`,
      tabindex: "0",
      role: "button",
      transform: `translate(${position.x}, ${position.y})`,
      "data-node-id": node.id,
    });
    if (category === "metaedge") {
      const r = graphNodeRadius(node.kind);
      group.appendChild(createSvg("polygon", { points: `0,-${r} ${r},0 0,${r} -${r},0`, class: "metaedgeDiamond" }));
    } else {
      group.appendChild(createSvg("circle", { r: graphNodeRadius(node.kind) }));
    }
    const title = createSvg("text", { y: 1, "text-anchor": "middle", class: "graphNodeTitle" });
    title.textContent = compactLabel(node.label || node.id, graphNodeLabelLimit(node.kind));
    group.appendChild(title);
    const meta = createSvg("text", { y: graphNodeRadius(node.kind) + 14, "text-anchor": "middle", class: "graphNodeMeta" });
    meta.textContent = compactLabel(node.kind, 18);
    group.appendChild(meta);
    group.appendChild(createSvg("title", {}, `${node.kind}: ${node.label}`));
    group.addEventListener("click", () => {
      graphState.selectedId = node.id;
      drawGraphViewport(viewport, graph, view, graphState, detailsId, markerId, root);
      selectGraphNode(root, graph, node.id, detailsId);
    });
    group.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        graphState.selectedId = node.id;
        drawGraphViewport(viewport, graph, view, graphState, detailsId, markerId, root);
        selectGraphNode(root, graph, node.id, detailsId);
      }
    });
    nodeLayer.appendChild(group);
  });

  viewport.appendChild(edgeLayer);
  viewport.appendChild(nodeLayer);
  viewport.setAttribute("data-canvas-width", canvasWidth);
  viewport.setAttribute("data-canvas-height", canvasHeight);
  applyGraphTransform(viewport, graphState);
}

function buildGraphView(nodes, edges, graphState) {
  const query = graphState.query || "";
  const filtered = nodes.filter((node) => graphState.filters.has(graphCategory(node)));
  const filteredIds = new Set(filtered.map((node) => node.id));
  const matchedIds = new Set(
    filtered
      .filter((node) => !query || `${node.id} ${node.kind} ${node.label}`.toLowerCase().includes(query))
      .map((node) => node.id)
  );
  if (query) {
    edges.forEach((edge) => {
      if (matchedIds.has(edge.source) && filteredIds.has(edge.target)) matchedIds.add(edge.target);
      if (matchedIds.has(edge.target) && filteredIds.has(edge.source)) matchedIds.add(edge.source);
    });
  }

  const selected = filtered
    .filter((node) => matchedIds.has(node.id))
    .map((node) => ({ node, score: graphNodeImportance(node, edges) }))
    .sort((left, right) => right.score - left.score)
    .slice(0, query ? 150 : 120)
    .map((item) => item.node);
  const selectedIds = new Set(selected.map((node) => node.id));
  const visibleEdges = edges.filter((edge) => selectedIds.has(edge.source) && selectedIds.has(edge.target)).slice(0, 320);
  return { nodes: selected, edges: visibleEdges, positions: layoutGraph(selected, visibleEdges) };
}

function layoutGraph(nodes, edges) {
  const width = graphCanvasWidth(nodes.length);
  const height = graphCanvasHeight(nodes.length);
  const centerX = width / 2;
  const centerY = height / 2;
  const positions = new Map();
  const velocity = new Map();
  const categories = [...new Set(nodes.map((node) => graphCategory(node)))];
  const lanes = new Map(categories.map((category, index) => [category, index]));
  const rows = Math.max(1, categories.length);
  const grouped = new Map(categories.map((category) => [category, nodes.filter((node) => graphCategory(node) === category)]));
  grouped.forEach((items, category) => {
    const laneIndex = lanes.get(category) || 0;
    const y = ((laneIndex + 1) / (rows + 1)) * height;
    const columnGap = width / (items.length + 1);
    items.forEach((node, index) => {
      const jitter = ((index % 2 === 0 ? 1 : -1) * ((index % 5) + 1) * 6);
      positions.set(node.id, {
        x: columnGap * (index + 1),
        y: Math.max(64, Math.min(height - 64, y + jitter)),
      });
      velocity.set(node.id, { x: 0, y: 0 });
    });
  });

  for (let step = 0; step < 240; step += 1) {
    for (let i = 0; i < nodes.length; i += 1) {
      for (let j = i + 1; j < nodes.length; j += 1) {
        const left = positions.get(nodes[i].id);
        const right = positions.get(nodes[j].id);
        const dx = left.x - right.x || 0.01;
        const dy = left.y - right.y || 0.01;
        const minDistance = graphNodeRadius(nodes[i].kind) + graphNodeRadius(nodes[j].kind) + 30;
        const distance = Math.max(0.01, Math.hypot(dx, dy));
        const distanceSq = Math.max(80, dx * dx + dy * dy);
        const force = 3200 / distanceSq;
        velocity.get(nodes[i].id).x += dx * force;
        velocity.get(nodes[i].id).y += dy * force;
        velocity.get(nodes[j].id).x -= dx * force;
        velocity.get(nodes[j].id).y -= dy * force;
        if (distance < minDistance) {
          const overlap = (minDistance - distance) * 0.085;
          const ox = (dx / distance) * overlap;
          const oy = (dy / distance) * overlap;
          velocity.get(nodes[i].id).x += ox;
          velocity.get(nodes[i].id).y += oy;
          velocity.get(nodes[j].id).x -= ox;
          velocity.get(nodes[j].id).y -= oy;
        }
      }
    }
    edges.forEach((edge) => {
      const source = positions.get(edge.source);
      const target = positions.get(edge.target);
      if (!source || !target) return;
      const dx = target.x - source.x;
      const dy = target.y - source.y;
      const distance = Math.max(1, Math.hypot(dx, dy));
      const desired = 120 + Math.min(40, nodes.length * 0.14);
      const force = (distance - desired) * 0.013;
      const fx = (dx / distance) * force;
      const fy = (dy / distance) * force;
      velocity.get(edge.source).x += fx;
      velocity.get(edge.source).y += fy;
      velocity.get(edge.target).x -= fx;
      velocity.get(edge.target).y -= fy;
    });
    nodes.forEach((node) => {
      const position = positions.get(node.id);
      const speed = velocity.get(node.id);
      const category = graphCategory(node);
      const laneIndex = lanes.get(category) || 0;
      const laneY = ((laneIndex + 1) / (rows + 1)) * height;
      speed.x += (centerX - position.x) * 0.0022;
      speed.y += (laneY - position.y) * 0.012;
      speed.x *= 0.84;
      speed.y *= 0.8;
      const radius = graphNodeRadius(node.kind) + 10;
      position.x = Math.max(radius, Math.min(width - radius, position.x + speed.x));
      position.y = Math.max(radius, Math.min(height - radius, position.y + speed.y));
    });
  }
  resolveNodeCollisions(nodes, positions, width, height);
  return positions;
}

function selectGraphNode(root, graph, nodeId, detailsId = "graphDetails") {
  root.querySelectorAll(".graphNode").forEach((node) => node.classList.toggle("selected", node.dataset.nodeId === nodeId));
  const node = (graph.nodes || []).find((item) => item.id === nodeId);
  if (!node) return;
  const related = (graph.edges || []).filter((edge) => edge.source === nodeId || edge.target === nodeId).slice(0, 18);
  const payload = node.payload || {};
  const latex = payload.latex || payload.attributes?.latex || payload.attributes?.normalized_latex || "";
  const text = payload.text || payload.attributes?.text || payload.attributes?.window_text || "";
  const detail = root.querySelector(`#${detailsId}`);
  detail.innerHTML = `
    <div class="graphDetailTitle">
      <strong>${escapeHtml(node.kind)}</strong>
      <span>${escapeHtml(node.id)}</span>
    </div>
    <div class="graphDetailLabel">${escapeHtml(shortText(node.label, 420))}</div>
    <div class="graphDetailMeta">${graphPayloadSummary(payload)}</div>
    ${graphPayloadBadges(payload)}
    ${latex ? `<div class="latexRender" data-latex="${escapeAttribute(cleanLatex(latex))}" data-display="true"></div>` : ""}
    ${text ? `<div class="graphDetailText">${renderTokenizedHtml(shortText(text, 900))}</div>` : ""}
    <div class="graphRelationList">
      <strong>Связи</strong>
      ${
        related.length
          ? related.map((edge) => `<div>${escapeHtml(edge.source)} -[${escapeHtml(edge.label)}]-> ${escapeHtml(edge.target)}</div>`).join("")
          : "<div>У выбранного узла нет видимых связей.</div>"
      }
    </div>
  `;
  renderKatex(detail);
}

function graphPayloadSummary(payload) {
  const parts = [];
  if (payload.page_number) parts.push(`стр. ${payload.page_number}`);
  if (payload.source) parts.push(`источник ${formatSourceName(payload.source)}`);
  if (payload.type) parts.push(`тип ${payload.type}`);
  if (payload.attributes?.mass) parts.push(`масса ${payload.attributes.mass}`);
  if (payload.confidence !== null && payload.confidence !== undefined) parts.push(`уверенность ${formatConfidence(payload.confidence)}`);
  return parts.length ? escapeHtml(parts.join(" | ")) : "Дополнительные поля доступны на странице выходных JSON.";
}

function graphPayloadBadges(payload) {
  const attrs = payload.attributes || {};
  const flags = Array.isArray(payload.quality_flags) ? payload.quality_flags : Array.isArray(attrs.quality_flags) ? attrs.quality_flags : [];
  const variables = Array.isArray(payload.variables) ? payload.variables.slice(0, 18) : Array.isArray(attrs.variables) ? attrs.variables.slice(0, 18) : [];
  const ids = Array.isArray(payload.formula_ids) ? payload.formula_ids.slice(0, 18) : Array.isArray(attrs.formula_ids) ? attrs.formula_ids.slice(0, 18) : [];
  const symbols = Array.isArray(attrs.symbols) ? attrs.symbols.slice(0, 18) : [];
  const markers = Array.isArray(attrs.definition_markers) ? attrs.definition_markers.slice(0, 18) : [];
  const items = [...flags, ...variables, ...ids, ...symbols, ...markers];
  if (!items.length) return "";
  return `<div class="graphBadges">${items.map((item) => `<span>${escapeHtml(String(item))}</span>`).join("")}</div>`;
}

function graphCategories(nodes) {
  const seen = new Set();
  return nodes
    .map((node) => graphCategory(node))
    .filter((category) => {
      if (seen.has(category)) return false;
      seen.add(category);
      return true;
    })
    .map((category) => ({ id: category, title: graphCategoryTitle(category) }));
}

function graphCategory(node) {
  const kind = String(node.kind || "");
  if (kind === "corpus") return "document";
  if (kind === "meta_document" || kind === "paper" || kind === "paper_metavertex" || kind === "document") return "document";
  if (kind === "text_block" || kind === "meta_section" || kind === "section" || kind.includes("paragraph") || kind.includes("section")) return "text";
  if (kind.includes("formula") || kind === "meta_equation_group") return "formula";
  if (kind.includes("variable") || kind === "symbol") return "variable";
  if (kind.includes("context") || kind === "definition") return "context";
  if (kind === "metaedge") return "metaedge";
  if (kind === "subexpression" || kind === "operator") return "fragment";
  if (kind.includes("quality_issue")) return "issue";
  if (kind.includes("source")) return "source";
  return "entity";
}

function graphCategoryTitle(category) {
  return {
    document: "документ",
    text: "текст/секции",
    formula: "формулы",
    variable: "переменные",
    context: "контексты",
    metaedge: "метаребра",
    fragment: "фрагменты",
    issue: "качество",
    source: "источники",
    entity: "сущности",
  }[category] || category;
}

function graphNodeImportance(node, edges) {
  const degree = edges.filter((edge) => edge.source === node.id || edge.target === node.id).length;
  const categoryBonus = { document: 40, formula: 18, text: 12, variable: 12, context: 10, metaedge: 14, fragment: 2, issue: 12, source: 8, entity: 3 }[graphCategory(node)] || 0;
  return degree * 4 + categoryBonus + (node.payload?.confidence || 0) + Number(node.payload?.attributes?.mass || 0) * 0.05;
}

function graphNeighborIds(nodeId, edges) {
  const result = new Set([nodeId]);
  edges.forEach((edge) => {
    if (edge.source === nodeId) result.add(edge.target);
    if (edge.target === nodeId) result.add(edge.source);
  });
  return result;
}

function applyGraphTransform(viewport, graphState) {
  viewport.setAttribute("transform", `translate(${graphState.tx} ${graphState.ty}) scale(${graphState.scale})`);
}

function enableGraphPanZoom(svg, viewport, graphState) {
  let dragStart = null;
  svg.addEventListener("wheel", (event) => {
    event.preventDefault();
    graphState.scale = Math.max(0.55, Math.min(2.2, graphState.scale + (event.deltaY < 0 ? 0.12 : -0.12)));
    applyGraphTransform(viewport, graphState);
  });
  svg.addEventListener("pointerdown", (event) => {
    if (event.target.closest(".graphNode")) return;
    dragStart = { x: event.clientX, y: event.clientY, tx: graphState.tx, ty: graphState.ty };
    svg.setPointerCapture(event.pointerId);
  });
  svg.addEventListener("pointermove", (event) => {
    if (!dragStart) return;
    graphState.tx = dragStart.tx + (event.clientX - dragStart.x);
    graphState.ty = dragStart.ty + (event.clientY - dragStart.y);
    applyGraphTransform(viewport, graphState);
  });
  svg.addEventListener("pointerup", () => {
    dragStart = null;
  });
}

function createSvg(tag, attributes = {}, text = "") {
  const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
  Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
  if (text) element.textContent = text;
  return element;
}

function graphNodeClass(kind) {
  return graphCategory({ kind });
}

function graphNodeRadius(kind) {
  const category = graphCategory({ kind });
  if (category === "document") return 36;
  if (category === "formula") return 30;
  if (category === "text") return 28;
  if (category === "metaedge") return 24;
  if (category === "fragment") return 20;
  return 24;
}

function graphNodeLabelLimit(kind) {
  const category = graphCategory({ kind });
  if (category === "formula") return 14;
  if (category === "text") return 18;
  return 18;
}

function graphCanvasWidth(nodeCount) {
  return Math.max(980, Math.min(1780, 920 + nodeCount * 5));
}

function graphCanvasHeight(nodeCount) {
  return Math.max(620, Math.min(1120, 560 + nodeCount * 3));
}

function resolveNodeCollisions(nodes, positions, width, height) {
  for (let step = 0; step < 10; step += 1) {
    let moved = false;
    for (let i = 0; i < nodes.length; i += 1) {
      for (let j = i + 1; j < nodes.length; j += 1) {
        const left = positions.get(nodes[i].id);
        const right = positions.get(nodes[j].id);
        const dx = right.x - left.x || 0.01;
        const dy = right.y - left.y || 0.01;
        const distance = Math.max(0.01, Math.hypot(dx, dy));
        const minDistance = graphNodeRadius(nodes[i].kind) + graphNodeRadius(nodes[j].kind) + 18;
        if (distance >= minDistance) continue;
        const shift = (minDistance - distance) / 2;
        const sx = (dx / distance) * shift;
        const sy = (dy / distance) * shift;
        left.x = Math.max(32, Math.min(width - 32, left.x - sx));
        left.y = Math.max(32, Math.min(height - 32, left.y - sy));
        right.x = Math.max(32, Math.min(width - 32, right.x + sx));
        right.y = Math.max(32, Math.min(height - 32, right.y + sy));
        moved = true;
      }
    }
    if (!moved) break;
  }
}

function updateProgress(job) {
  const label = document.querySelector("#progressLabel");
  const value = document.querySelector("#progressValue");
  const fill = document.querySelector("#progressFill");
  const hint = document.querySelector("#progressHint");
  if (!label || !value || !fill || !hint) return;
  const incomingProgress = Math.max(0, Math.min(100, Number(job.progress || 0)));
  const progress = Math.max(state.lastProgress || 0, incomingProgress);
  state.lastProgress = progress;
  const stage = translateStage(job.stage || "Обработка");
  const detail = translateStage(job.detail || "");
  label.textContent = stage;
  value.textContent = `${Math.round(progress)}%`;
  fill.style.width = `${progress}%`;
  const secondsSinceUpdate = Math.max(0, Math.round(Date.now() / 1000 - Number(job.updated_at || 0)));
  hint.textContent = secondsSinceUpdate >= 25
    ? `Последнее обновление ${secondsSinceUpdate} сек. назад. Текущий этап: ${detail || "без деталей"}`
    : (detail || "Сервер выполняет задачу...");
  appendProgressLog(stage, detail, progress);
}

function appendProgressLog(stage, detail, progress) {
  const key = `${Math.round(progress)}:${stage}:${detail}`;
  if (state.progressLog[state.progressLog.length - 1]?.key === key) return;
  state.progressLog.push({ key, stage, detail, progress, at: new Date() });
  state.progressLog = state.progressLog.slice(-12);
  renderUploadProcessLog();
}

function renderUploadProcessLog() {
  const target = document.querySelector("#uploadProcessLog");
  if (!target) return;
  target.innerHTML = (state.progressLog || [])
    .map((item) => `<div><strong>${Math.round(item.progress)}%</strong> ${escapeHtml(item.stage)}${item.detail ? ` <span>${escapeHtml(item.detail)}</span>` : ""}</div>`)
    .join("");
}

function translateStage(value) {
  const text = String(value || "");
  const exact = [
    ["Fetching TeX source", "Загрузка TeX-источника"],
    ["Parsing TeX source", "Разбор TeX-источника"],
    ["Building semantic links", "Построение смысловых связей"],
    ["Preparing structured export", "Подготовка структурированного экспорта"],
    ["Building graph-ready JSON", "Сборка JSON для метаграфа"],
    ["Building metagraph model", "Сборка модели метаграфа"],
    ["Saving JSON exports", "Сохранение JSON-экспортов"],
    ["Saving visualization data", "Сохранение данных визуализации"],
  ];
  let translated = text;
  exact.forEach(([from, to]) => {
    translated = translated.replaceAll(from, to);
  });
  const map = [
    [/Fetching/gi, "Загрузка"],
    [/Parsing/gi, "Разбор"],
    [/Building/gi, "Сборка"],
    [/Preparing/gi, "Подготовка"],
    [/Saving/gi, "Сохранение"],
    [/structured export/gi, "структурированного экспорта"],
    [/semantic links/gi, "смысловых связей"],
    [/TeX source/gi, "TeX-источника"],
    [/pipeline/gi, "обработка"],
    [/batch/gi, "пакет"],
    [/graph-ready/gi, "экспорт для метаграфа"],
    [/rich metagraph/gi, "расширенный метаграф"],
    [/graph build/gi, "построение связей"],
    [/graph/gi, "связи"],
    [/metagraph/gi, "метаграф"],
    [/source/gi, "источник"],
    [/unknown/gi, "неизвестно"],
    [/objects/gi, "объектов"],
    [/candidates/gi, "кандидатов"],
    [/candidate/gi, "кандидат"],
    [/blocks/gi, "блоков"],
    [/block/gi, "блок"],
    [/stage/gi, "этап"],
    [/start/gi, "запуск"],
    [/done/gi, "готово"],
    [/running/gi, "выполняется"],
    [/queued/gi, "в очереди"],
    [/completed/gi, "завершено"],
    [/failed/gi, "ошибка"],
  ];
  return map.reduce((acc, [pattern, replacement]) => acc.replace(pattern, replacement), translated);
}

async function waitForProcessingJob(jobId) {
  const startedAt = Date.now();
  while (true) {
    const response = await fetchWithTimeout(`${API_BASE}/api/process/jobs/${encodeURIComponent(jobId)}`, {}, 30000);
    if (!response.ok) {
      throw new Error(`Не удалось получить статус задачи (${response.status})`);
    }
    const job = await response.json();
    updateProgress(job);
    if (job.status === "completed") {
      const resultResponse = await fetchWithTimeout(`${API_BASE}/api/results/${encodeURIComponent(job.document_id)}`, {}, 120000);
      if (!resultResponse.ok) {
        throw new Error(`Результат готов, но не читается (${resultResponse.status})`);
      }
      state.result = await resultResponse.json();
      renderResult(state.result);
      showUploadMessage(`Обработка завершена: ${state.result.filename || state.result.document_id}.`);
      showCompletionNotification(
        "Обработка завершена",
        `${state.result.filename || state.result.document_id}: ${(state.result.formulas || []).length} формул, ${(state.result.text_blocks || []).length} текстовых блоков`
      );
      return;
    }
    if (job.status === "failed") {
      throw new Error(job.error || "Обработка завершилась с ошибкой");
    }
    if (Date.now() - startedAt > 20 * 60 * 1000) {
      throw new Error("Обработка превысила 20 минут. Похоже, задача зависла или документ слишком тяжелый.");
    }
    await sleep(1200);
  }
}

function compactLabel(value, limit) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  return text.length <= limit ? text : `${text.slice(0, limit - 1)}…`;
}

function renderProcess(result) {
  const target = document.querySelector("#processPage");
  const checks = buildProcessChecks(result);
  const totals = checks.reduce(
    (acc, check) => {
      acc[check.status] = (acc[check.status] || 0) + 1;
      return acc;
    },
    {}
  );

  target.innerHTML = `
    <div class="processSummary">
      <strong>Процесс обработки</strong>
      <span>${checks.length} этапов | предупреждения: ${totals.warning || 0} | ошибки: ${totals.error || 0}</span>
    </div>
    <table class="processTable">
      <thead>
        <tr>
          <th>Этап</th>
          <th>Состояние</th>
          <th>Данные</th>
        </tr>
      </thead>
      <tbody>
        ${checks
          .map(
            (check, index) => `
              <tr class="processRow" tabindex="0" data-process-index="${index}">
                <td>
                  <strong>${escapeHtml(check.id)}</strong>
                  <span>${escapeHtml(check.title)}</span>
                </td>
                <td><span class="processStatusDot ${check.status}" aria-hidden="true"></span></td>
                <td>
                  ${escapeHtml(check.evidence)}
                  <span class="processHint">Нажмите, чтобы посмотреть примеры</span>
                </td>
              </tr>
              <tr class="processDetailRow" id="processDetail-${index}">
                <td colspan="3">
                  <div class="processDetail">
                    <strong>Примеры из результата</strong>
                    ${renderExamples(check.examples)}
                  </div>
                </td>
              </tr>
            `
          )
          .join("")}
      </tbody>
    </table>
  `;

  target.querySelectorAll(".processRow").forEach((row) => {
    const toggle = () => {
      const detail = target.querySelector(`#processDetail-${row.dataset.processIndex}`);
      row.classList.toggle("open");
      detail.classList.toggle("open");
    };
    row.addEventListener("click", toggle);
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        toggle();
      }
    });
  });
}

function buildProcessChecks(result) {
  if (Array.isArray(result.processing_steps) && result.processing_steps.length) {
    const disabledCheckNames = ["l" + "lm", "v" + "lm", "q" + "wen"];
    return result.processing_steps.filter((step) => {
      const text = `${step.stage || ""} ${step.description || ""}`.toLowerCase();
      return !disabledCheckNames.some((name) => text.includes(name));
    }).map((step, index) => ({
      id: step.stage || `stage_${index + 1}`,
      title: translateStage(step.description || step.stage || `Этап ${index + 1}`),
      status: normalizeProcessStatus(step.status),
      evidence: `${step.count ?? "-"} объектов | источник: ${translateStage(step.source || "неизвестно")} | ${formatConfidence(step.duration_sec)} сек.`,
      examples: processStepExamples(step, result),
    }));
  }
  const pages = result.pages || [];
  const textBlocks = result.text_blocks || [];
  const formulas = result.formulas || [];
  const entities = result.entities || [];
  const relations = result.relations || [];
  const graph = result.graph || { nodes: [], edges: [] };
  const warnings = result.warnings || [];

  const textSources = sourceBreakdown(textBlocks);
  const formulaSources = sourceBreakdown(formulas);
  const formulaKinds = kindBreakdown(formulas);
  const contextRelations = relations.filter((relation) => relation.kind === "has_context");
  const semanticRelations = relations.filter((relation) =>
    ["defined_as", "contains_variable", "has_context"].includes(relation.kind)
  );
  const latexReady = formulas.filter((formula) => {
    const latex = String(formula.latex || "");
    return (
      String(formula.source || "").includes("pp_structure") ||
      /\\[A-Za-z]+|[_^=]|\\begin|\\frac/.test(latex)
    );
  });
  const savedAt = result.result_path || `/api/results/${result.document_id}`;
  const hasFormulaClassification = formulas.some((formula) => formula.kind === "inline" || formula.kind === "block");

  return [
    processCheck("upload", "Загрузка документа", Boolean(result.filename && result.document_id), false, `${result.filename || "файл"} | document_id ${result.document_id || "-"}`, [
      `Имя файла: ${result.filename || "-"}`,
      `Идентификатор обработки: ${result.document_id || "-"}`,
      `Дата создания результата: ${result.created_at || "-"}`,
    ]),
    processCheck("prepare_pages", "Подготовка страниц", pages.length > 0, false, `${pages.length} стр.; ${pages[0]?.dpi || "-"} DPI; изображения страниц сохранены`, pages.slice(0, 4).map((page) => `стр. ${page.page_number}: ${page.width}x${page.height}, ${page.dpi} DPI, ${page.image_path}`)),
    processCheck("text_layer", "Извлечение текстового слоя", textBlocks.length > 0, false, `${textBlocks.length} блоков; источники: ${textSources}`, textBlocks.slice(0, 5).map((block) => `стр. ${block.page_number}, ${formatSourceName(block.source)}, уверенность ${formatConfidence(block.confidence)}: ${shortText(block.text, 220)}`)),
    processCheck("formula_detection", "Обнаружение формул", formulas.length > 0, false, `${formulas.length} формул; источники: ${formulaSources || "-"}`, formulas.slice(0, 5).map((formula) => `${formula.id}, стр. ${formula.page_number}, ${formatSourceName(formula.source)}: ${shortText(formula.latex, 220)}`)),
    processCheck("formula_classification", "Классификация строчных и блочных формул", hasFormulaClassification, formulas.length > 0 && !hasFormulaClassification, formulaKinds || "формулы не найдены", formulas.slice(0, 6).map((formula) => `${formula.id}: ${translateFormulaKind(formula.kind)}, стр. ${formula.page_number}`)),
    processCheck("latex_normalization", "Нормализация LaTeX", latexReady.length > 0, formulas.length > 0 && latexReady.length < formulas.length, `${latexReady.length} из ${formulas.length} формул имеют LaTeX-представление`, latexReady.slice(0, 5).map((formula) => `${formula.id}: ${shortText(formula.latex, 260)}`)),
    processCheck("text_normalization", "Нормализация текста", textBlocks.length > 0, warnings.length > 0, warnings.length ? `обработка завершена с предупреждениями: ${warnings.slice(0, 2).map(translateWarningText).join("; ")}` : "нормализация выполнена без предупреждений", warnings.length ? warnings.slice(0, 5).map(translateWarningText) : textBlocks.slice(0, 4).map((block) => shortText(block.text, 220))),
    processCheck("context_linking", "Связывание формул с контекстом", contextRelations.length > 0, formulas.length > 0 && contextRelations.length < formulas.length, `${contextRelations.length} связей has_context для ${formulas.length} формул`, contextRelations.slice(0, 6).map((relation) => `${relation.source_id} -> ${relation.target_id}; подтверждение: ${shortText(relation.evidence, 220)}`)),
    processCheck("entity_extraction", "Извлечение сущностей", entities.length > 0, false, `${entities.length} сущностей: ${kindBreakdown(entities) || "-"}`, entities.slice(0, 8).map((entity) => `${entity.id}: ${entity.kind} "${entity.label}"`)),
    processCheck("semantic_linking", "Формирование семантических связей", semanticRelations.length > 0, false, `${semanticRelations.length} связей: ${kindBreakdown(semanticRelations) || "-"}`, semanticRelations.slice(0, 8).map((relation) => `${relation.source_id} -[${relation.kind}]-> ${relation.target_id}; ${shortText(relation.evidence, 180)}`)),
    processCheck("metagraph_build", "Построение связей и метаграфа", graph.nodes.length > 0 && graph.edges.length > 0, graph.nodes.length > 0 && graph.edges.length === 0, `${graph.nodes.length} узлов / ${graph.edges.length} связей`, [
      ...graph.nodes.slice(0, 4).map((node) => `узел ${node.id}: ${node.kind} "${shortText(node.label, 120)}"`),
      ...graph.edges.slice(0, 4).map((edge) => `связь ${edge.id}: ${edge.source} -[${edge.label}]-> ${edge.target}`),
    ]),
    processCheck("exports", "Генерация экспортов", Boolean(savedAt), false, savedAt, [`JSON результата: ${savedAt}`, `API: /api/results/${result.document_id}`]),
    processCheck("visualization", "Генерация визуализации", Boolean(state.result), false, "доступны страницы: Текст, Формулы, Визуализация, Метрики, Артефакты", ["Визуализация: режимы метаграфа и контекста", "Артефакты: машинные экспорты"]),
  ];
}

function processCheck(id, title, passCondition, warnCondition, evidence, examples = []) {
  return {
    id,
    title,
    status: passCondition ? "ok" : warnCondition ? "warning" : "partial",
    evidence: shortText(evidence, 360),
    examples: examples.length ? examples : ["Для этого пункта нет примеров в текущем результате."],
  };
}

function renderExamples(examples) {
  return `
    <ul class="processExamples">
      ${examples.map((example) => `<li>${escapeHtml(shortText(example, 420))}</li>`).join("")}
    </ul>
  `;
}

function processStepExamples(step, result = state.result) {
  const warnings = (step.warnings || []).map((warning) => `предупреждение: ${translateWarningText(warning)}`);
  const diagnostic = step.diagnostic || step.diagnostic_payload || {};
  const stageExamples = resultProcessExamples(step.stage || "", result, step);
  const items = [
    `описание: ${translateStage(step.description || "-")}`,
    `объектов: ${step.count ?? "-"}`,
    `источник: ${translateStage(step.source || "неизвестно")}`,
    `время: ${formatConfidence(step.duration_sec)} сек.`,
  ];
  if (step.input_example) items.push(`вход: ${JSON.stringify(step.input_example).slice(0, 500)}`);
  if (step.output_example) items.push(`выход: ${JSON.stringify(step.output_example).slice(0, 500)}`);
  if (Object.keys(diagnostic).length) items.push(`диагностика: ${JSON.stringify(diagnostic).slice(0, 500)}`);
  return [...stageExamples, ...items, ...warnings].slice(0, 14);
}

function resultProcessExamples(stage, result, step = {}) {
  const formulas = result?.formulas || [];
  const regions = result?.formula_regions || [];
  const blocks = result?.text_blocks || [];
  const tokenBlocks = result?.text_with_tokens || [];
  const entities = result?.entities || [];
  const relations = result?.relations || [];
  const graph = result?.graph || { nodes: [], edges: [] };
  const metagraph = result?.metagraph || { nodes: [], edges: [] };
  if (stage === "upload") {
    return [`пример: файл "${result?.filename || "-"}" получил document_id ${result?.document_id || "-"}`];
  }
  if (stage === "prepare_pages") {
    return (result?.pages || []).slice(0, 4).map((page) => `пример: стр. ${page.page_number} отрендерена как ${page.width}x${page.height} px при ${page.dpi} DPI`);
  }
  if (stage === "text_layer" || stage === "ocr_fallback") {
    return blocks.slice(0, 5).map((block) => `пример: стр. ${block.page_number}, ${formatSourceName(block.source)}, уверенность ${formatConfidence(block.confidence)} -> "${shortText(block.text, 240)}"`);
  }
  if (stage === "formula_detection") {
    return formulas.slice(0, 6).map((formula) => `пример: ${formula.id} найдено на стр. ${formula.page_number} через ${formatSourceName(formula.source)}${formula.bbox ? `, bbox ${formatBBox(formula.bbox)}` : ""} -> ${shortText(formula.latex, 180)}`);
  }
  if (stage === "formula_classification") {
    return formulas.slice(0, 6).map((formula) => `пример: ${formula.id} классифицирована как "${translateFormulaKind(formula.kind)}": ${formula.kind === "block" ? "отдельная область/выносная формула" : "короткая область внутри строки или текстового блока"}`);
  }
  if (stage === "latex_normalization") {
    return formulas.slice(0, 6).map((formula) => {
      const interpretation = formulaInterpretation(formula);
      return `пример: ${formula.id} нормализована: raw="${shortText(formula.raw_latex || formula.latex, 110)}" -> normalized="${shortText(formula.normalized_latex || formula.cleaned_latex || formula.latex, 110)}"; интерпретация: ${shortText(interpretation.summary, 180)}`;
    });
  }
  if (stage === "formula_masking") {
    return regions.slice(0, 6).map((region) => `пример: ${region.token} на стр. ${region.page_number} замаскирована как ${translateFormulaKind(region.kind)}, bbox ${formatBBox(region.bbox)}, связано формул: ${(region.formula_ids || []).length}`);
  }
  if (stage === "token_reconstruction") {
    return tokenBlocks.slice(0, 5).map((block) => `пример: стр. ${block.page_number}, текст с токенами -> "${shortText(block.text, 260)}"`);
  }
  if (stage === "entity_extraction") {
    return entities.slice(0, 8).map((entity) => `пример: ${entity.id} извлечена как ${entity.kind}: "${entity.label}"${entity.source_formula_id ? ` из ${entity.source_formula_id}` : ""}`);
  }
  if (stage === "context_linking") {
    return relations.slice(0, 8).map((relation) => `пример: ${relation.source_id} -[${relation.kind}]-> ${relation.target_id}; подтверждение: ${shortText(relation.evidence, 220)}`);
  }
  if (stage === "graph_build") {
    return [
      ...graph.nodes.slice(0, 4).map((node) => `пример узла: ${node.id} (${node.kind}) "${shortText(node.label, 120)}"`),
      ...graph.edges.slice(0, 4).map((edge) => `пример связи: ${edge.source} -[${edge.label}]-> ${edge.target}`),
    ];
  }
  if (stage === "metagraph_build") {
    return [
      ...metagraph.nodes.slice(0, 4).map((node) => `пример метавершины/узла: ${node.id} (${node.kind}) "${shortText(node.label, 120)}"`),
      ...metagraph.edges.slice(0, 4).map((edge) => `пример метасвязи: ${edge.source} -[${edge.label}]-> ${edge.target}`),
    ];
  }
  if (stage === "llm_refinement") {
    const outcomes = step.diagnostic?.outcomes || [];
    const candidateIds = step.diagnostic?.candidate_formula_ids || [];
    if (outcomes.length) {
      return outcomes.slice(0, 8).map((item) => `пример: ${item.formula_id} -> ${item.status}, уверенность ${formatConfidence(item.confidence)}, применено=${Boolean(item.applied)}, причина=${shortText(item.reason, 180)}`);
    }
    return candidateIds.slice(0, 8).map((id) => `кандидат для ручного уточнения: ${id}`);
  }
  if (stage === "exports" || stage === "visualization") {
    return [`пример: основной JSON ${result?.result_path || `/api/results/${result?.document_id || "-"}`}`, `пример: визуализация использует ${graph.nodes.length + metagraph.nodes.length} узлов и ${graph.edges.length + metagraph.edges.length} связей`];
  }
  return [];
}

function formatBBox(bbox) {
  if (!Array.isArray(bbox) && !(bbox && typeof bbox.length === "number")) return "-";
  return `[${[...bbox].slice(0, 4).map((value) => Number(value).toFixed(1)).join(", ")}]`;
}

async function renderMetrics(result) {
  const target = document.querySelector("#metricsPage");
  if (!target || !result?.document_id) return;
  target.innerHTML = renderImmediateMetricsHtml(result);
  const metrics = await fetchOptionalJson(`${API_BASE}/api/results/${encodeURIComponent(result.document_id)}/metrics/metagraph`, 120000);
  const aggregate = await fetchOptionalJson(`${API_BASE}/api/analytics/metagraph`, 45000);
  const batchMetrics = state.activeBatch?.batch_id
    ? await fetchOptionalJson(`${API_BASE}/api/process/batch/${encodeURIComponent(state.activeBatch.batch_id)}/metrics`, 45000)
    : null;
  const corpusMetrics = state.activeCorpus?.corpus_id
    ? await fetchOptionalJson(`${API_BASE}/api/corpus/${encodeURIComponent(state.activeCorpus.corpus_id)}/metrics`, 45000)
    : null;
  target.innerHTML = renderMetricsHtml(metrics, aggregate, batchMetrics, corpusMetrics, result);
}

async function fetchOptionalJson(url, timeoutMs) {
  try {
    const response = await fetchWithTimeout(url, {}, timeoutMs);
    if (!response.ok) return null;
    return await response.json();
  } catch (_error) {
    return null;
  }
}

function renderImmediateMetricsHtml(result) {
  return `
    <div class="metricsGrid">
      ${metricCard("Документ", {
        text_blocks: (result.text_blocks || []).length,
        formulas: (result.formulas || []).length,
        warnings: getRelevantWarnings(result.warnings || [], result).length,
      })}
      ${metricCard("Связи", {
        nodes: (result.graph?.nodes || []).length,
        edges: (result.graph?.edges || []).length,
        metagraph_nodes: (result.metagraph?.nodes || []).length,
        metagraph_edges: (result.metagraph?.edges || []).length,
      })}
    </div>
    <div class="graphLoading metricsLoadingInline">Загрузка расширенных метрик...</div>
  `;
}

function renderMetricsHtml(metrics, aggregate, batchMetrics = null, corpusMetrics = null, result = state.result) {
  const fallbackBasic = {
    text_blocks_count: (result?.text_blocks || []).length,
    formula_count: (result?.formulas || []).length,
    graph_nodes: (result?.graph?.nodes || []).length,
    graph_edges: (result?.graph?.edges || []).length,
  };
  const fallbackConnectivity = {
    metagraph_nodes: (result?.metagraph?.nodes || []).length,
    metagraph_edges: (result?.metagraph?.edges || []).length,
  };
  const basic = metrics?.basic || fallbackBasic;
  const formulas = metrics?.formulas || { formula_count: (result?.formulas || []).length };
  const variables = metrics?.variables || {};
  const connectivity = metrics?.connectivity || fallbackConnectivity;
  const metaedges = metrics?.metaedges || {};
  const aggregateInfo = scopedMetricsSummary(aggregate, batchMetrics, corpusMetrics, metrics, result);
  const notice = metrics ? "" : `<div class="metricsNotice">Расширенные метрики еще формируются или сервер не ответил вовремя. Показаны быстрые метрики из текущего результата.</div>`;
  return `
    ${notice}
    <div class="metricsGrid">
      ${metricCard("Базовые", basic)}
      ${metricCard("Связность", {
        connected_components: connectivity.connected_components,
        weakly_connected_components: connectivity.weakly_connected_components,
        isolated_formulas: (connectivity.isolated_formulas || []).length,
        isolated_variables: (connectivity.isolated_variables || []).length,
        orphan_rate: connectivity.orphan_rate,
      })}
      ${metricCard("Формулы", formulas)}
      ${metricCard("Переменные", {
        average_definitions_per_variable: variables.average_definitions_per_variable,
        variables_with_definition_ratio: variables.variables_with_definition_ratio,
        ambiguous_variables: (variables.ambiguous_variables || []).length,
      })}
      ${metricCard("Метаребра", metaedges)}
      ${metricCard("Документы", {
        documents_count: aggregateInfo.documents_count,
        average_formula_context_coverage: aggregateInfo.average_formula_context_coverage,
        average_variable_definition_coverage: aggregateInfo.average_variable_definition_coverage,
      })}
      ${batchMetrics ? metricCard("Пакет", {
        status: batchMetrics.status,
        documents: (batchMetrics.documents || []).length,
        formula_count: batchMetrics.totals?.formula_count,
        variable_count: batchMetrics.totals?.variable_count,
        warnings_count: batchMetrics.totals?.warnings_count,
        processing_time: batchMetrics.totals?.processing_time,
      }) : ""}
      ${corpusMetrics ? metricCard("Корпус", corpusMetrics) : ""}
    </div>
  `;
}

function scopedMetricsSummary(aggregate, batchMetrics, corpusMetrics, metrics, result) {
  if (corpusMetrics) {
    return {
      documents_count: corpusMetrics.total_documents ?? 0,
      average_formula_context_coverage: corpusMetrics.average_formula_context_coverage,
      average_variable_definition_coverage: corpusMetrics.average_variable_definition_coverage,
    };
  }
  if (batchMetrics) {
    const documents = batchMetrics.documents || [];
    const withMetrics = documents.filter((item) => typeof item.formula_count === "number");
    return {
      documents_count: documents.length,
      average_formula_context_coverage: aggregate?.average_formula_context_coverage,
      average_variable_definition_coverage: aggregate?.average_variable_definition_coverage,
      formula_count: batchMetrics.totals?.formula_count,
      variable_count: batchMetrics.totals?.variable_count,
      warnings_count: batchMetrics.totals?.warnings_count,
      processed_documents: withMetrics.length,
    };
  }
  return {
    documents_count: result?.document_id ? 1 : 0,
    average_formula_context_coverage: metrics?.formulas?.formula_context_coverage,
    average_variable_definition_coverage: metrics?.variables?.variables_with_definition_ratio,
  };
}

async function renderCorpusMetrics() {
  if (!state.result) return;
  await renderMetrics(state.result);
}

function metricCard(title, payload) {
  const rows = Object.entries(payload || {}).slice(0, 12);
  return `
    <section class="metricPanel">
      <h3>${escapeHtml(title)}</h3>
      ${rows.map(([key, value]) => {
        const description = metricDescription(key);
        return `<div><span title="${escapeAttribute(description)}">${escapeHtml(formatMetricKey(key))}</span><strong>${escapeHtml(formatMetricValue(value))}</strong></div>`;
      }).join("")}
    </section>
  `;
}

function formatMetricKey(key) {
  const map = {
    status: "статус",
    documents: "документы",
    documents_count: "документы",
    formula_count: "формулы",
    formulas: "формулы",
    variable_count: "переменные",
    variables: "переменные",
    warnings_count: "предупреждения",
    warnings: "предупреждения",
    processing_time: "время обработки",
    text_blocks: "текстовые блоки",
    text_blocks_count: "текстовые блоки",
    nodes: "узлы",
    edges: "связи",
    graph_nodes: "узлы графа",
    graph_edges: "связи графа",
    metagraph_nodes: "узлы метаграфа",
    metagraph_edges: "связи метаграфа",
    connected_components: "компоненты связности",
    weakly_connected_components: "слабые компоненты",
    isolated_formulas: "изолированные формулы",
    isolated_variables: "изолированные переменные",
    orphan_rate: "доля изолированных",
    average_definitions_per_variable: "среднее число определений",
    variables_with_definition_ratio: "доля переменных с определением",
    ambiguous_variables: "неоднозначные переменные",
    average_formula_context_coverage: "покрытие контекстами формул",
    average_variable_definition_coverage: "покрытие определениями переменных",
    processed_documents: "обработано документов",
  };
  return map[key] || String(key).replaceAll("_", " ");
}

function metricDescription(key) {
  const map = {
    status: "Текущий статус обработки выбранного пакета, корпуса или документа.",
    documents: "Количество документов в активном пакете или наборе.",
    documents_count: "Количество документов в текущем контексте аналитики: 1 для открытого документа, размер пакета или размер корпуса.",
    processed_documents: "Сколько документов из текущего пакета уже имеют рассчитанные метрики.",
    formula_count: "Количество формул, попавших в графовую модель.",
    formulas: "Количество формул в текущем результате обработки.",
    variable_count: "Количество переменных, извлеченных из формул и контекста.",
    variables: "Количество переменных в текущем результате обработки.",
    warnings_count: "Количество предупреждений качества или обработки.",
    warnings: "Количество актуальных предупреждений для документа.",
    processing_time: "Суммарное время обработки в секундах.",
    text_blocks: "Количество распознанных текстовых блоков.",
    text_blocks_count: "Количество текстовых блоков в структурированном документе.",
    nodes: "Количество вершин в обычном графе связей.",
    edges: "Количество ребер в обычном графе связей.",
    graph_nodes: "Количество вершин в базовом графе документа.",
    graph_edges: "Количество ребер в базовом графе документа.",
    metagraph_nodes: "Количество узлов в метаграфе.",
    metagraph_edges: "Количество связей в метаграфе.",
    node_count: "Количество узлов расширенного метаграфа.",
    edge_count: "Количество связей расширенного метаграфа.",
    metavertex_count: "Количество метавершин, объединяющих связанные объекты.",
    metaedge_count: "Количество метаребер, описывающих многоместные отношения.",
    paragraph_count: "Количество параграфов в графовой модели.",
    context_count: "Количество контекстных окон вокруг формул.",
    definition_count: "Количество найденных определений переменных.",
    connected_components: "Количество компонент связности в неориентированном представлении графа.",
    weakly_connected_components: "Количество слабых компонент связности в ориентированном графе.",
    isolated_formulas: "Формулы без связей с другими объектами графа.",
    isolated_variables: "Переменные без связей с формулами или определениями.",
    orphan_rate: "Доля полностью изолированных узлов среди всех узлов.",
    average_variables_per_formula: "Среднее число переменных, связанных с одной формулой.",
    formulas_with_context_ratio: "Доля формул, у которых найден текстовый контекст.",
    formulas_without_context_count: "Количество формул без найденного контекстного окна.",
    formula_context_coverage: "Доля формул, покрытых контекстом.",
    formula_dependency_count: "Количество зависимостей между формулами.",
    formulas_with_metavertex_semantics_ratio: "Доля формул с семантикой метавершины.",
    average_internal_role_count: "Среднее число внутренних ролей в структуре формулы.",
    average_definitions_per_variable: "Среднее число определений на одну переменную.",
    variables_with_definition_ratio: "Доля переменных, для которых найдено определение.",
    ambiguous_variables: "Количество переменных с несколькими возможными определениями.",
    average_formula_context_coverage: "Среднее покрытие формул контекстом в текущем наборе документов.",
    average_variable_definition_coverage: "Средняя доля переменных с определениями в текущем наборе документов.",
    metaedge_count_by_type: "Распределение метаребер по типам.",
    average_source_set_size: "Средний размер множества источников в метаребре.",
    average_target_set_size: "Средний размер множества целей в метаребре.",
    average_evidence_count: "Среднее количество свидетельств, поддерживающих метаребро.",
    average_confidence_by_type: "Средняя уверенность по типам метаребер.",
    semantic_metaedge_count_by_relation: "Количество семантических метаребер по типам отношений.",
  };
  return map[key] || `Метрика "${formatMetricKey(key)}" из текущего результата.`;
}

function formatMetricValue(value) {
  if (Array.isArray(value)) return String(value.length);
  if (value && typeof value === "object") return shortText(JSON.stringify(value), 160);
  return translateMetricValue(value ?? "-");
}

function translateMetricValue(value) {
  const text = String(value);
  const map = {
    ok: "готово",
    partial: "частично",
    error: "ошибка",
    running: "выполняется",
    queued: "в очереди",
    completed: "завершено",
    failed: "ошибка",
    unknown: "неизвестно",
  };
  return map[text] || text;
}

function renderOutputsPage(result) {
  const target = document.querySelector("#outputsPage");
  if (!target || !result?.document_id) return;
  target.innerHTML = `
    <div class="emptyHint">
      Артефакты теперь открываются отдельным окном из нижней кнопки сайдбара.
      <button type="button" id="openArtifactsModalInline">Открыть артефакты</button>
    </div>
  `;
  target.querySelector("#openArtifactsModalInline")?.addEventListener("click", () => openArtifactsModal());
}

function artifactOutputs(result) {
  if (!result?.document_id) return [];
  const id = encodeURIComponent(result.document_id);
  return [
    { id: "result", label: "Основной результат JSON", path: `/api/results/${id}`, filename: "result.json", selected: true },
    { id: "structured", label: "Структурированный JSON", path: `/api/results/${id}/structured`, filename: "structured.json", selected: true },
    { id: "graph_ready", label: "JSON для метаграфа", path: `/api/results/${id}/graph-ready`, filename: "graph_ready.json", selected: true },
    { id: "rich_metagraph", label: "Расширенный метаграф JSON", path: `/api/results/${id}/rich-metagraph`, filename: "rich_metagraph.json", selected: true },
    { id: "visualization", label: "Визуализация JSON", path: `/api/results/${id}/visualization?mode=metagraph_planetary_overview`, filename: "visualization.json", selected: true },
    { id: "metrics", label: "Метрики метаграфа JSON", path: `/api/results/${id}/metrics/metagraph`, filename: "metagraph_metrics.json", selected: true },
    { id: "analytics", label: "Сводная аналитика JSON", path: "/api/analytics/metagraph", filename: "analytics_metagraph.json", selected: false },
  ];
}

function openArtifactsModal() {
  if (!state.result?.document_id) {
    window.alert("Сначала обработайте документ, затем скачайте артефакты.");
    return;
  }
  const modal = ensureArtifactsModal();
  const outputs = artifactOutputs(state.result);
  modal.querySelector("[data-artifact-list]").innerHTML = outputs.map((item) => `
    <label class="artifactChoice">
      <input type="checkbox" value="${escapeAttribute(item.id)}" ${item.selected ? "checked" : ""} />
      <span>
        <strong>${escapeHtml(item.label)}</strong>
        <small>${escapeHtml(item.filename)}</small>
      </span>
    </label>
  `).join("");
  modal.querySelector("[data-artifact-status]").textContent = "";
  modal.hidden = false;
  document.body.classList.add("modalOpen");
}

function ensureArtifactsModal() {
  let modal = document.querySelector("#artifactsModal");
  if (modal) return modal;
  modal = document.createElement("div");
  modal.id = "artifactsModal";
  modal.className = "artifactsModal";
  modal.hidden = true;
  modal.innerHTML = `
    <div class="artifactsModalBackdrop" data-artifacts-close></div>
    <div class="artifactsModalDialog" role="dialog" aria-modal="true" aria-labelledby="artifactsModalTitle">
      <div class="artifactsModalTop">
        <div>
          <strong id="artifactsModalTitle">Артефакты результата</strong>
          <div class="artifactsModalMeta">Выберите файлы и скачайте их одним ZIP-архивом.</div>
        </div>
        <button type="button" class="artifactsModalClose" data-artifacts-close>Закрыть</button>
      </div>
      <div class="artifactSelectActions">
        <button type="button" data-artifacts-select="all">Выбрать все</button>
        <button type="button" data-artifacts-select="none">Снять выбор</button>
      </div>
      <div class="artifactChoiceList" data-artifact-list></div>
      <div class="artifactsModalFooter">
        <span data-artifact-status></span>
        <button type="button" data-artifacts-download>Скачать выбранные ZIP</button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);
  modal.querySelectorAll("[data-artifacts-close]").forEach((node) => node.addEventListener("click", () => closeArtifactsModal()));
  modal.querySelector("[data-artifacts-select='all']").addEventListener("click", () => {
    modal.querySelectorAll("[data-artifact-list] input").forEach((input) => {
      input.checked = true;
    });
  });
  modal.querySelector("[data-artifacts-select='none']").addEventListener("click", () => {
    modal.querySelectorAll("[data-artifact-list] input").forEach((input) => {
      input.checked = false;
    });
  });
  modal.querySelector("[data-artifacts-download]").addEventListener("click", () => {
    const selectedIds = new Set([...modal.querySelectorAll("[data-artifact-list] input:checked")].map((input) => input.value));
    const selected = artifactOutputs(state.result).filter((item) => selectedIds.has(item.id));
    downloadArtifactsJsonBundle(selected, state.result?.document_id, modal);
  });
  return modal;
}

function closeArtifactsModal() {
  const modal = document.querySelector("#artifactsModal");
  if (modal) modal.hidden = true;
  document.body.classList.remove("modalOpen");
}

async function downloadArtifactsJsonBundle(outputs, documentId, modal = null) {
  const status = modal?.querySelector("[data-artifact-status]");
  const button = modal?.querySelector("[data-artifacts-download]");
  if (!outputs.length) {
    if (status) status.textContent = "Выберите хотя бы один файл.";
    return;
  }
  if (button) button.disabled = true;
  if (status) status.textContent = "Подготовка архива...";
  const files = [];
  for (const item of outputs) {
    try {
      const response = await fetchWithTimeout(`${API_BASE}${item.path}`, {}, 120000);
      if (!response.ok) continue;
      const text = await response.text();
      files.push({ name: item.filename || `${safeFileName(item.label)}.json`, content: prettyJsonText(text) });
      if (status) status.textContent = `Добавлено файлов: ${files.length}`;
    } catch (_error) {
      // Один тяжелый артефакт не должен блокировать скачивание остальных.
    }
  }
  if (!files.length) {
    if (status) status.textContent = "Не удалось получить выбранные файлы.";
    if (button) button.disabled = false;
    return;
  }
  downloadBlob(createZip(files), `${safeFileName(documentId || "artifacts")}_artifacts.zip`);
  if (status) status.textContent = `Скачивание начато. Файлов в архиве: ${files.length}.`;
  if (button) button.disabled = false;
}

function prettyJsonText(text) {
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch (_error) {
    return text;
  }
}

function safeFileName(value) {
  return String(value || "artifact").toLowerCase().replace(/[^a-z0-9а-яё_-]+/gi, "_").replace(/^_+|_+$/g, "") || "artifact";
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1500);
}

function createZip(files) {
  const encoder = new TextEncoder();
  const chunks = [];
  const central = [];
  let offset = 0;
  files.forEach((file) => {
    const nameBytes = encoder.encode(file.name);
    const data = encoder.encode(file.content);
    const crc = crc32(data);
    const local = zipHeader(0x04034b50, [
      [2, 20], [2, 0x0800], [2, 0], [2, 0], [2, 0],
      [4, crc], [4, data.length], [4, data.length],
      [2, nameBytes.length], [2, 0],
    ]);
    chunks.push(local, nameBytes, data);
    central.push({ file, nameBytes, data, crc, offset });
    offset += local.length + nameBytes.length + data.length;
  });
  let centralSize = 0;
  central.forEach((entry) => {
    const header = zipHeader(0x02014b50, [
      [2, 20], [2, 20], [2, 0x0800], [2, 0], [2, 0], [2, 0],
      [4, entry.crc], [4, entry.data.length], [4, entry.data.length],
      [2, entry.nameBytes.length], [2, 0], [2, 0], [2, 0], [2, 0],
      [4, 0], [4, entry.offset],
    ]);
    chunks.push(header, entry.nameBytes);
    centralSize += header.length + entry.nameBytes.length;
  });
  chunks.push(zipHeader(0x06054b50, [
    [2, 0], [2, 0], [2, files.length], [2, files.length],
    [4, centralSize], [4, offset], [2, 0],
  ]));
  return new Blob(chunks, { type: "application/zip" });
}

function zipHeader(signature, fields) {
  const size = 4 + fields.reduce((sum, [bytes]) => sum + bytes, 0);
  const buffer = new ArrayBuffer(size);
  const view = new DataView(buffer);
  view.setUint32(0, signature, true);
  let offset = 4;
  fields.forEach(([bytes, value]) => {
    if (bytes === 2) view.setUint16(offset, value, true);
    if (bytes === 4) view.setUint32(offset, value >>> 0, true);
    offset += bytes;
  });
  return new Uint8Array(buffer);
}

function crc32(data) {
  let crc = -1;
  for (let i = 0; i < data.length; i += 1) {
    crc = (crc >>> 8) ^ CRC32_TABLE[(crc ^ data[i]) & 0xff];
  }
  return (crc ^ -1) >>> 0;
}

const CRC32_TABLE = (() => {
  const table = [];
  for (let i = 0; i < 256; i += 1) {
    let c = i;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table.push(c >>> 0);
  }
  return table;
})();

function renderBatchPage() {
  const target = document.querySelector("#batchPage");
  if (!target) return;
  if (target.dataset.ready === "1") {
    if (state.activeBatch) renderBatchStatus(state.activeBatch);
    return;
  }
  target.dataset.ready = "1";
  target.innerHTML = `
    <section class="batchPanel">
      <h2>Пакетная обработка</h2>
      <p>Выберите несколько PDF/изображений или укажите несколько arXiv ID на вкладке загрузки. Сервер создаст пакет и обработает документы последовательно.</p>
      <input id="batchFileInput" type="file" accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp" multiple />
      <button id="batchStartButton" type="button">Запустить пакетную обработку</button>
      <button id="createCorpusButton" type="button" disabled>Создать корпус</button>
      <div class="batchHint">После обработки можно выбрать документ или создать общий корпус для междокументного поиска.</div>
      <div id="batchResults" class="batchResults"></div>
      <div id="corpusPanel" class="batchResults"></div>
    </section>
  `;
  target.querySelector("#batchStartButton").addEventListener("click", async () => {
    const files = [...target.querySelector("#batchFileInput").files];
    const results = target.querySelector("#batchResults");
    if (!files.length) {
      results.innerHTML = `<div class="graphLoading">Выберите файлы для обработки.</div>`;
      return;
    }
    try {
      const formData = new FormData();
      files.forEach((file) => formData.append("files", file));
      formData.append("ocr_mode", selectedOcrMode());
      formData.append("device_mode", document.querySelector("#deviceMode").value);
      formData.append("ocr_lang", document.querySelector("#ocrLang").value);
      formData.append("max_pages", document.querySelector("#maxPages").value);
      formData.append("render_dpi", document.querySelector("#renderDpi").value);
      const arxivIds = parseArxivIds(document.querySelector("#arxivId")?.value || "");
      if (arxivIds.length) formData.append("arxiv_ids", arxivIds.join("\n"));
      formData.append("arxiv_id", arxivIds[0] || "");
      formData.append("prefer_tex_source", document.querySelector("#preferTexSource").checked ? "true" : "false");
      const response = await fetchWithTimeout(`${API_BASE}/api/process/batch/submit`, { method: "POST", body: formData }, 15 * 60 * 1000);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      state.activeBatch = await response.json();
      state.viewMode = "batch";
      await waitForBatchJob(state.activeBatch.batch_id);
    } catch (error) {
      results.innerHTML = `<div class="graphLoading">Ошибка пакетной обработки: ${escapeHtml(error.message || "неизвестная ошибка")}</div>`;
    }
  });
  target.querySelector("#createCorpusButton").addEventListener("click", () => createCorpusFromBatch());
}

function batchStatusTarget() {
  return document.querySelector("#uploadBatchStatus") || document.querySelector("#batchResults");
}

async function waitForBatchJob(batchId) {
  const startedAt = Date.now();
  while (true) {
    const response = await fetchWithTimeout(`${API_BASE}/api/process/batch/${encodeURIComponent(batchId)}`, {}, 30000);
    if (!response.ok) throw new Error(`Не удалось получить статус пакета (${response.status})`);
    const batch = await response.json();
    state.activeBatch = batch;
    renderBatchStatus(batch);
    updateProgress({ progress: batch.progress || 0, stage: "Пакетная обработка", detail: `${batch.completed_documents}/${batch.total_documents} обработано`, updated_at: batch.updated_at });
    if (["ok", "partial", "error"].includes(batch.status) && batch.completed_documents + batch.failed_documents >= batch.total_documents) {
      await loadBatchResults(batch.batch_id);
      return batch;
    }
    if (Date.now() - startedAt > 30 * 60 * 1000) throw new Error("Пакетная обработка превысила 30 минут.");
    await sleep(1400);
  }
}

function renderBatchStatus(batch) {
  const target = batchStatusTarget();
  if (!target) return;
  renderHeaderDocumentSelector();
  const arxivIds = arxivIdsFromBatch(batch);
  target.innerHTML = `
    <div class="batchOverview">
      <strong>Пакет ${escapeHtml(batch.batch_id)}</strong>
      <span>${batch.completed_documents}/${batch.total_documents} обработано | ошибок: ${batch.failed_documents}</span>
      ${arxivIds.length ? `<div class="arxivLinkList">${arxivIds.map((id) => `<a href="https://arxiv.org/abs/${escapeAttribute(id)}" target="_blank" rel="noreferrer">arXiv ${escapeHtml(id)}</a>`).join("")}</div>` : ""}
    </div>
    ${(batch.documents || []).map((doc) => `
      <button type="button" class="batchDocCard" data-document-id="${escapeAttribute(doc.document_id)}" ${["ok", "partial"].includes(doc.status) ? "" : "disabled"}>
        <strong>${escapeHtml(doc.filename)}</strong>
        <span>${Math.round(doc.progress || 0)}% | ${escapeHtml(translateStage(doc.current_stage || ""))}</span>
        ${(doc.warnings || []).length ? `<small>${escapeHtml((doc.warnings || []).slice(0, 2).join("; "))}</small>` : ""}
      </button>
    `).join("")}
    <button id="createCorpusButton" type="button" ${!(batch.documents || []).some((doc) => ["ok", "partial"].includes(doc.status)) ? "disabled" : ""}>Создать корпус</button>
    <div id="corpusPanel" class="batchResults"></div>
  `;
  target.querySelectorAll(".batchDocCard").forEach((button) => {
    button.addEventListener("click", () => openBatchDocument(button.dataset.documentId));
  });
  const corpusButton = document.querySelector("#createCorpusButton");
  if (corpusButton) {
    corpusButton.disabled = !(batch.documents || []).some((doc) => ["ok", "partial"].includes(doc.status));
    corpusButton.addEventListener("click", () => createCorpusFromBatch());
  }
}

function arxivIdsFromBatch(batch) {
  const fromState = state.randomArxivIds || [];
  const fromDocs = (batch?.documents || []).flatMap((doc) => arxivIdsFromResult(doc));
  return [...new Set([...fromState, ...fromDocs])];
}

async function loadBatchResults(batchId) {
  const response = await fetchWithTimeout(`${API_BASE}/api/process/batch/${encodeURIComponent(batchId)}/results`, {}, 60000);
  if (!response.ok) return;
  const payload = await response.json();
  (payload.results || []).forEach((result) => state.resultCache.set(result.document_id, result));
  const first = (payload.results || [])[0];
  if (first) renderResult(first);
  activatePage("upload");
  renderBatchStatus(state.activeBatch);
  showCompletionNotification(
    "Пакетная обработка завершена",
    `${(payload.results || []).length} результатов загружено`
  );
}

async function openBatchDocument(documentId) {
  if (!documentId) return;
  let result = state.resultCache.get(documentId);
  if (!result) {
    const response = await fetchWithTimeout(`${API_BASE}/api/results/${encodeURIComponent(documentId)}`, {}, 60000);
    if (!response.ok) return;
    result = await response.json();
    state.resultCache.set(documentId, result);
  }
  state.viewMode = "document";
  renderResult(result);
  activatePage(isTexSourceResult(result) ? "text" : "document");
}

async function createCorpusFromBatch() {
  if (!state.activeBatch?.batch_id) return;
  const target = document.querySelector("#corpusPanel");
  if (target) target.innerHTML = `<div class="graphLoading">Создание корпуса...</div>`;
  const buttons = document.querySelectorAll("#createCorpusButton");
  buttons.forEach((button) => {
    button.disabled = true;
    button.textContent = "Корпус создается...";
  });
  try {
    const response = await fetchWithTimeout(`${API_BASE}/api/corpus/create`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ batch_id: state.activeBatch.batch_id, name: `Корпус ${state.activeBatch.batch_id}` }),
    }, 60000);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.activeCorpus = await response.json();
    state.viewMode = "corpus";
    if (target) {
      target.innerHTML = `
        <div class="batchOverview">
          <strong>Корпус ${escapeHtml(state.activeCorpus.corpus_id)}</strong>
          <span>${(state.activeCorpus.documents || []).length} документов</span>
          <button type="button" id="openCorpusViz">Открыть визуализацию корпуса</button>
          <button type="button" id="downloadCorpusBundle">Скачать корпус ZIP</button>
        </div>
      `;
      target.querySelector("#openCorpusViz")?.addEventListener("click", () => {
        activatePage("visualization");
        renderMetagraphVisualization(state.result || {}, {
          activeCorpus: state.activeCorpus,
          initialMode: "corpus_graph",
        });
      });
      target.querySelector("#downloadCorpusBundle")?.addEventListener("click", () => downloadCorpusBundle(state.activeCorpus));
    }
  } catch (error) {
    if (target) target.innerHTML = `<div class="graphLoading">Не удалось создать корпус: ${escapeHtml(error.message || "неизвестная ошибка")}</div>`;
  } finally {
    buttons.forEach((button) => {
      button.disabled = false;
      button.textContent = "Создать корпус";
    });
  }
}

async function downloadCorpusBundle(corpus) {
  if (!corpus?.corpus_id) return;
  const corpusId = corpus.corpus_id;
  const outputs = [
    { path: `/api/corpus/${encodeURIComponent(corpusId)}`, filename: "corpus.json" },
    { path: `/api/corpus/${encodeURIComponent(corpusId)}/graph`, filename: "graph.json" },
    { path: `/api/corpus/${encodeURIComponent(corpusId)}/metagraph`, filename: "metagraph.json" },
    { path: `/api/corpus/${encodeURIComponent(corpusId)}/metrics`, filename: "metrics.json" },
    { path: `/api/corpus/${encodeURIComponent(corpusId)}/visualization`, filename: "visualization.json" },
  ];
  const files = [];
  for (const output of outputs) {
    const response = await fetchWithTimeout(`${API_BASE}${output.path}`, {}, 45000);
    if (!response.ok) throw new Error(`Не удалось скачать ${output.filename}: HTTP ${response.status}`);
    files.push({ name: output.filename, content: JSON.stringify(await response.json(), null, 2) });
  }
  downloadBlob(createZip(files), `${safeFileName(corpusId)}_corpus.zip`);
}

function sourceBreakdown(items) {
  return countBreakdown(items, "source");
}

function kindBreakdown(items) {
  return countBreakdown(items, "kind");
}

function countBreakdown(items, field) {
  const counts = items.reduce((acc, item) => {
    const key = item[field] || "-";
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
  return Object.entries(counts)
    .map(([key, value]) => `${field === "source" ? formatSourceName(key) : field === "kind" ? translateFormulaKind(key) : key}: ${value}`)
    .join(", ");
}

function statusText(status) {
  if (status === "ok") return "готово";
  if (status === "partial") return "частично";
  if (status === "skipped") return "пропущено";
  if (status === "disabled") return "отключено";
  if (status === "warning") return "предупреждение";
  if (status === "error") return "ошибка";
  if (status === "running") return "выполняется";
  if (status === "queued") return "в очереди";
  return "неизвестно";
}

function normalizeProcessStatus(status) {
  return ["ok", "partial", "skipped", "warning", "error", "disabled"].includes(status) ? status : "partial";
}

function renderTokenizedHtml(text, options = {}) {
  const renderFormulas = options.renderFormulas !== false;
  const formulaByToken = formulaTokenMap(state.result?.formulas || []);
  return escapeHtml(String(text || ""))
    .replace(/\[FORMULA_\d+\]/g, (token) => {
      if (!renderFormulas) {
        return `<button type="button" class="tokenChip" data-token="${escapeAttribute(token)}">${escapeHtml(token)}</button>`;
      }
      const formula = formulaByToken.get(token);
      if (!hasRenderableLatex(formula?.latex)) {
        return "";
      }
      return `<button type="button" class="tokenChip formulaInlineChip" data-token="${escapeAttribute(token)}" title="${escapeAttribute(token)}"><span class="latexRender" data-latex="${escapeAttribute(cleanLatex(formula.latex))}" data-display="false">${escapeHtml(token)}</span></button>`;
    })
    .replaceAll("\n", "<br>");
}

function formulaTokenMap(formulas) {
  const map = new Map();
  (formulas || []).forEach((formula) => {
    if (formula.token) {
      map.set(formula.token, formula);
      if (!String(formula.token).startsWith("[")) map.set(`[${formula.token}]`, formula);
    }
    const idText = String(formula.id || "");
    const match = idText.match(/(\d{1,4})$/);
    if (match) {
      map.set(`[FORMULA_${match[1].padStart(3, "0")}]`, formula);
    }
  });
  return map;
}

function formulaById(formulaId) {
  return (state.result?.formulas || []).find((formula) => formula.id === formulaId) || null;
}

function formulaByToken(token) {
  if (!token) return null;
  return formulaTokenMap(state.result?.formulas || []).get(token) || null;
}

function findFormulaCard(formulaId, token) {
  if (formulaId) {
    const direct = document.querySelector(`#formulasPage .formula[data-formula-id="${cssEscape(formulaId)}"]`);
    if (direct) return direct;
  }
  if (token) {
    return document.querySelector(`#formulasPage .formula[data-token="${cssEscape(token)}"]`);
  }
  return null;
}

function formulaProjectionCacheKey(documentId, formulaId, token, mode) {
  return `${documentId}:${formulaId || token}:${mode}`;
}

async function loadFormulaProjection(formulaId, mode = "formula_focus", token = "") {
  if (!state.result?.document_id || (!formulaId && !token)) throw new Error("Формула не выбрана.");
  const cacheKey = formulaProjectionCacheKey(state.result.document_id, formulaId, token, mode);
  if (state.formulaProjectionCache.has(cacheKey)) {
    return state.formulaProjectionCache.get(cacheKey);
  }
  const formulaQuery = token || formulaId;
  const url = `${API_BASE}/api/results/${encodeURIComponent(state.result.document_id)}/projection?mode=${encodeURIComponent(mode)}&formula=${encodeURIComponent(formulaQuery)}`;
  const response = await fetchWithTimeout(url, {}, 30000);
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }
  const payload = await response.json();
  state.formulaProjectionCache.set(cacheKey, payload);
  return payload;
}

function openFormulaDetails({ formulaId = "", token = "", projectionMode = "formula_focus" } = {}) {
  const formula = formulaById(formulaId) || formulaByToken(token);
  if (!formula) return;
  state.pendingFormulaNavigation = { formulaId: formula.id, token: formula.token || token || "", projectionMode };
  activatePage("formulas");
  const card = findFormulaCard(formula.id, formula.token || token || "");
  if (!card) return;
  selectToken(formula.token || token || "");
  card.scrollIntoView({ behavior: "smooth", block: "center" });
  setFormulaCardExpanded(card, true, projectionMode);
}

function consumePendingFormulaNavigation() {
  const pending = state.pendingFormulaNavigation;
  if (!pending) return;
  const card = findFormulaCard(pending.formulaId, pending.token);
  if (!card) return;
  state.pendingFormulaNavigation = null;
  if (pending.token) selectToken(pending.token);
  setFormulaCardExpanded(card, true, pending.projectionMode || "formula_focus");
  card.scrollIntoView({ behavior: "smooth", block: "center" });
}

function selectToken(token) {
  state.selectedToken = token;
  document.querySelectorAll(".tokenChip").forEach((chip) => chip.classList.toggle("active", chip.dataset.token === token));
  document.querySelectorAll(".tokenLegendCard").forEach((card) => card.classList.toggle("active", card.dataset.token === token));
  document.querySelectorAll(".pageFormulaBox").forEach((box) => box.classList.toggle("active", box.dataset.token === token));
  const activeCard = document.querySelector(`.tokenLegendCard[data-token="${cssEscape(token)}"]`);
  if (activeCard) {
    activeCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  rerenderOverlay();
  focusFormulaByToken(token);
  focusJsonByToken(token);
}

function focusFormulaByToken(token) {
  let firstMatch = null;
  document.querySelectorAll("#formulasPage .formula").forEach((card) => {
    const match = card.dataset.token === token;
    card.classList.toggle("focus", match);
    if (match && !firstMatch) firstMatch = card;
  });
  if (firstMatch && document.querySelector("#formulasPage").classList.contains("active")) {
    firstMatch.scrollIntoView({ behavior: "smooth", block: "center" });
  }
}

function activatePage(pageName) {
  if (pageName === "tokens" && state.result?.document_id && !hasFormulaOverlayData(state.result)) {
    pageName = "text";
  }
  state.activePage = pageName;
  document.body.dataset.page = pageName;
  window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  document.querySelector(".shell")?.scrollTo?.({ top: 0, left: 0, behavior: "auto" });
  const [title, subtitle] = PAGE_META[pageName] || PAGE_META.upload;
  const titleNode = document.querySelector("#pageTitle");
  const subtitleNode = document.querySelector("#pageSubtitle");
  if (titleNode) titleNode.textContent = title;
  if (subtitleNode) subtitleNode.textContent = subtitle;
  document.querySelectorAll(".pageButton").forEach((item) => item.classList.toggle("active", item.dataset.page === pageName));
  document.querySelectorAll(".pageView").forEach((item) => item.classList.toggle("active", item.id === `${pageName}Page`));
  syncVisualizationLayoutHeight();
  if (pageName === "text" && state.result) {
    renderText(state.result);
  }
  renderDeferredPage(pageName);
}

function syncVisualizationLayoutHeight() {
  const page = document.querySelector("#visualizationPage");
  if (!page || !page.classList.contains("active")) return;
  const rect = page.getBoundingClientRect();
  const available = Math.max(520, Math.floor(window.innerHeight - rect.top - 16));
  document.documentElement.style.setProperty("--visualization-page-height", `${available}px`);
}

window.addEventListener("resize", syncVisualizationLayoutHeight);

function renderDeferredPage(pageName) {
  if (pageName === "history") {
    renderHistoryPage();
    return;
  }
  if (pageName === "batch") {
    renderBatchPage();
    return;
  }
  if (!state.result) return;
  const currentDoc = state.result.document_id;
  const cacheKey = `${currentDoc}:${pageName}`;
  if (state.deferredRenderDone.get(cacheKey)) return;
  if (pageName === "visualization") {
    if (window.ProjectionVisualization?.render) {
      window.ProjectionVisualization.render(state.result, { target: document.querySelector("#visualizationPage") });
    } else {
      const target = document.querySelector("#visualizationPage");
      if (target) {
        target.innerHTML = `
          <div class="graphLoading error">
            React Flow визуализация не загрузилась. Обновите страницу без кэша; старый renderer больше не используется как демонстрационный fallback.
          </div>
        `;
      }
    }
    state.deferredRenderDone.set(cacheKey, true);
    return;
  }
  if (pageName === "metrics") {
    renderMetrics(state.result);
    state.deferredRenderDone.set(cacheKey, true);
    return;
  }
  if (pageName === "reader") {
    const target = document.querySelector("#readerPage");
    renderJsonTokenFormulaView(state.result, target);
    state.deferredRenderDone.set(cacheKey, true);
    return;
  }
  if (pageName === "outputs") {
    renderOutputsPage(state.result);
    state.deferredRenderDone.set(cacheKey, true);
    return;
  }
}

function focusJsonByToken(token) {
  document.querySelectorAll(".jsonFormulaCard").forEach((card) => card.classList.toggle("focus", card.dataset.token === token));
  document.querySelectorAll(".jsonParagraph").forEach((paragraph) => {
    const hasToken = Boolean(token) && paragraph.textContent.includes(token);
    paragraph.classList.toggle("focus", hasToken);
  });
}

function focusJsonFormula(token) {
  const card = document.querySelector(`.jsonFormulaCard[data-token="${cssEscape(token)}"]`);
  if (card) card.scrollIntoView({ behavior: "smooth", block: "center" });
}

function focusJsonParagraph(paragraphId) {
  if (!paragraphId) return;
  const paragraph = document.querySelector(`.jsonParagraph[data-paragraph-id="${cssEscape(paragraphId)}"]`);
  if (paragraph) paragraph.scrollIntoView({ behavior: "smooth", block: "center" });
}

function renderJsonTokenFormulaView(result, target) {
  const blocks = getTokenTextBlocks(result);
  const paragraphs = buildJsonReadableParagraphs(blocks);
  const paragraphByToken = new Map();
  paragraphs.forEach((paragraph) => {
    paragraph.tokens.forEach((token) => paragraphByToken.set(token, paragraph.id));
  });
  const formulas = [...(result.formulas || [])].sort((left, right) => String(left.token || "").localeCompare(String(right.token || "")));
  target.innerHTML = `
    <div class="jsonViewer">
      <section class="jsonTextFlow">
        <div class="jsonViewerHeader">
          <strong>Размеченный текст</strong>
          <span>${paragraphs.length} параграфов</span>
        </div>
        ${paragraphs.length ? paragraphs.map(renderJsonParagraph).join("") : `<div class="emptyHint">Размеченный текст не найден.</div>`}
      </section>
      <aside class="jsonFormulaRail">
        <div class="jsonViewerHeader">
          <strong>Формулы</strong>
          <span>${formulas.length} токенов</span>
        </div>
        ${formulas.length ? formulas.map((formula) => renderJsonFormulaCard(formula, paragraphByToken.get(formula.token || ""))).join("") : `<div class="emptyHint">Формулы не найдены.</div>`}
      </aside>
    </div>
  `;
  target.querySelectorAll(".tokenChip").forEach((button) => {
    button.addEventListener("click", () => {
      selectToken(button.dataset.token);
      focusJsonFormula(button.dataset.token);
    });
  });
  target.querySelectorAll(".jsonFormulaCard").forEach((card) => {
    card.addEventListener("click", () => {
      selectToken(card.dataset.token);
      focusJsonParagraph(card.dataset.paragraphId);
    });
  });
  target.querySelectorAll("[data-open-json-formula]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      openFormulaDetails({
        formulaId: button.dataset.formulaId || "",
        token: button.dataset.token || "",
        projectionMode: "formula_focus",
      });
    });
  });
  renderKatex(target);
}

function buildJsonReadableParagraphs(blocks) {
  const text = blocks
    .map((block) => String(block.text || "").trim())
    .filter(Boolean)
    .join(" ")
    .replace(/\s+/g, " ")
    .replace(/\s+([,.;:!?])/g, "$1")
    .replace(/(\[FORMULA_\d+\])/g, " $1 ")
    .replace(/\s+/g, " ")
    .trim();
  return splitIntoReadableParagraphs(text, 1100).map((paragraph, index) => ({
    id: `jsonParagraph_${index + 1}`,
    order: index + 1,
    text: paragraph,
    tokens: [...paragraph.matchAll(/\[FORMULA_\d+\]/g)].map((match) => match[0]),
  }));
}

function renderJsonParagraph(paragraph) {
  return `
    <article class="jsonParagraph" id="${escapeAttribute(paragraph.id)}" data-paragraph-id="${escapeAttribute(paragraph.id)}">
      <div class="meta">параграф ${paragraph.order}${paragraph.tokens.length ? ` | ${paragraph.tokens.map(escapeHtml).join(", ")}` : ""}</div>
      <div class="textReadable">${renderTokenizedHtml(paragraph.text, { renderFormulas: false })}</div>
    </article>
  `;
}

function renderJsonFormulaCard(formula, paragraphId) {
  const display = formula.kind === "block" || formula.kind === "display_math";
  const interpretation = formulaInterpretation(formula, formula.symbols || [], formulaOperators(formula.latex || ""));
  return `
    <article class="jsonFormulaCard" id="jsonFormula_${escapeAttribute(formula.token || formula.id)}" data-token="${escapeAttribute(formula.token || "")}" data-paragraph-id="${escapeAttribute(paragraphId || "")}" tabindex="0">
      <div class="jsonFormulaTop">
        <button type="button" class="tokenChip" data-token="${escapeAttribute(formula.token || "")}">${escapeHtml(formula.token || "-")}</button>
        <span>${escapeHtml(formula.kind || "unknown")}</span>
        <button
          type="button"
          class="secondaryInlineButton variableFormulaOpenButton"
          data-open-json-formula
          data-formula-id="${escapeAttribute(formula.id || "")}"
          data-token="${escapeAttribute(formula.token || "")}"
        >
          К формуле и графу
        </button>
      </div>
      <div class="latexRender" data-latex="${escapeAttribute(cleanLatex(formula.latex || ""))}" data-display="${display}"></div>
      <div class="jsonFormulaInterpretation">${escapeHtml(interpretation.summary)}</div>
      <code>${escapeHtml(formula.latex || "")}</code>
      ${(formula.symbols || []).length ? `<div class="jsonFormulaSymbols">переменные: ${formula.symbols.map(escapeHtml).join(", ")}</div>` : ""}
    </article>
  `;
}

function buildJsonTabPayload(result) {
  const tokenBlocks = getTokenTextBlocks(result);
  const textWithTokens = tokenBlocks
    .map((block) => String(block.text || "").trim())
    .filter(Boolean)
    .join("\n\n");
  const formulas = (result.formulas || []).map((formula) => ({
    id: formula.id,
    token: formula.token,
    latex: formula.latex,
    kind: formula.kind,
    source: formula.source,
    symbols: formula.symbols || [],
    quality_flags: formula.quality_flags || [],
    plain_formula_text: formula.plain_formula_text || "",
    formula_interpretation: formula.formula_interpretation || {},
    interpretation: formula.interpretation || "",
  }));
  const formulasById = new Map(formulas.map((formula) => [formula.id, formula]));
  const contexts = buildFormulaContextsForJson(result, textWithTokens, formulasById);
  const variables = buildVariablesForJson(result, formulas);
  return {
    document_id: result.document_id,
    filename: result.filename,
    status: result.status,
    text_with_tokens: textWithTokens,
    formulas,
    formula_contexts: contexts,
    variables,
    summary: {
      text_blocks_count: (result.text_blocks || []).length,
      formulas_count: formulas.length,
      variables_count: variables.length,
      contexts_count: contexts.length,
      warnings_count: (result.warnings || []).length,
    },
    warnings: result.warnings || [],
  };
}

function buildFormulaContextsForJson(result, textWithTokens, formulasById) {
  const relationContexts = new Map();
  (result.relations || [])
    .filter((relation) => relation.kind === "has_context" || relation.label === "context")
    .forEach((relation) => {
      if (!relation.source_id && !relation.source) return;
      relationContexts.set(relation.source_id || relation.source, relation);
    });
  return (result.formulas || []).map((formula) => {
    const formulaId = formula.id;
    const context = relationContexts.get(formulaId);
    const token = formula.token || "";
    const windowText = extractTokenWindow(textWithTokens, token);
    return {
      formula_id: formulaId,
      token,
      latex: formulasById.get(formulaId)?.latex || formula.latex || "",
      context_before: context?.payload?.context_before || "",
      context_after: context?.payload?.context_after || "",
      window_text: context?.payload?.window_text || context?.evidence || windowText,
    };
  });
}

function buildVariablesForJson(result, formulas) {
  const bySymbol = new Map();
  formulas.forEach((formula) => {
    (formula.symbols || []).forEach((symbol) => {
      if (!symbol) return;
      if (!bySymbol.has(symbol)) {
        bySymbol.set(symbol, { symbol, formula_tokens: [], formula_ids: [] });
      }
      const item = bySymbol.get(symbol);
      if (formula.token && !item.formula_tokens.includes(formula.token)) item.formula_tokens.push(formula.token);
      if (formula.id && !item.formula_ids.includes(formula.id)) item.formula_ids.push(formula.id);
    });
  });
  (result.entities || [])
    .filter((entity) => entity.type === "symbol" || entity.kind === "variable")
    .forEach((entity) => {
      const symbol = entity.normalized_value || entity.value || entity.label;
      if (!symbol) return;
      if (!bySymbol.has(symbol)) bySymbol.set(symbol, { symbol, formula_tokens: [], formula_ids: [] });
      const formulaId = entity.formula_id || entity.source_formula_id;
      if (formulaId && !bySymbol.get(symbol).formula_ids.includes(formulaId)) {
        bySymbol.get(symbol).formula_ids.push(formulaId);
      }
    });
  return [...bySymbol.values()].sort((left, right) => left.symbol.localeCompare(right.symbol));
}

function extractTokenWindow(text, token, radius = 260) {
  if (!text || !token) return "";
  const index = text.indexOf(token);
  if (index < 0) return "";
  const start = Math.max(0, index - radius);
  const end = Math.min(text.length, index + token.length + radius);
  return text.slice(start, end).replace(/\s+/g, " ").trim();
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 60000) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(new Error("timeout")), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("Превышено время ожидания. Сервер занят или документ слишком тяжелый.");
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function pagePreviewUrl(documentId, imagePath) {
  const normalized = String(imagePath || "").replaceAll("\\", "/");
  const artifactPath = normalized.split("/").slice(-1)[0];
  return `${API_BASE}/api/artifacts/${encodeURIComponent(documentId)}/${encodeURIComponent(artifactPath)}`;
}

function openOverlayModal(documentId, page, pageRegions, visibleRegions) {
  if (!overlayModal || !overlayModalViewport || !overlayModalMeta || !page) return;
  const regions = visibleRegions?.length ? visibleRegions : pageRegions || [];
  overlayModalMeta.textContent = `стр. ${page.page_number} | показано ${regions.length} / всего ${pageRegions.length} регионов`;
  overlayModalViewport.innerHTML = renderOverlayPreviewMarkup(documentId, page, regions);
  overlayModal.hidden = false;
  document.body.classList.add("modalOpen");
  overlayModal.querySelectorAll(".pageFormulaBox").forEach((button) => {
    button.addEventListener("click", () => selectToken(button.dataset.token));
  });
}

function closeOverlayModal() {
  if (!overlayModal || overlayModal.hidden) return;
  overlayModal.hidden = true;
  document.body.classList.remove("modalOpen");
  if (overlayModalViewport) overlayModalViewport.innerHTML = "";
}

function renderOverlayPreviewMarkup(documentId, page, regions) {
  const pointWidth = (page.width * 72) / Math.max(1, page.dpi);
  const pointHeight = (page.height * 72) / Math.max(1, page.dpi);
  const overlayHtml = (regions || [])
    .map((region) => {
      const bbox = region.display_bbox || region.bbox;
      const left = (bbox[0] / pointWidth) * 100;
      const top = (bbox[1] / pointHeight) * 100;
      const width = ((bbox[2] - bbox[0]) / pointWidth) * 100;
      const height = ((bbox[3] - bbox[1]) / pointHeight) * 100;
      const kind = region.display_kind || region.kind;
      const source = region.display_source || region.source;
      const showLabel = overlayLabelVisible(region, width, height, regions.length, true);
      return `
        <button
          type="button"
          class="pageFormulaBox ${kind}${showLabel ? "" : " compact"}${region.token === state.selectedToken ? " active" : ""}"
          data-token="${escapeAttribute(region.token)}"
          title="${escapeAttribute(`${region.token} | ${kind} | ${source}`)}"
          style="left:${left}%;top:${top}%;width:${width}%;height:${height}%"
        >
          <span>${escapeHtml(region.token)}</span>
        </button>
      `;
    })
    .join("");
  return `
    <div class="pagePreviewFrame pagePreviewFrameLarge">
      <img class="pagePreviewImage" src="${escapeAttribute(pagePreviewUrl(documentId, page.image_path))}" alt="страница ${page.page_number}" />
      <div class="pageOverlayLayer">${overlayHtml}</div>
    </div>
  `;
}

function cssEscape(value) {
  if (window.CSS && typeof window.CSS.escape === "function") {
    return window.CSS.escape(value);
  }
  return String(value).replace(/["\\]/g, "\\$&");
}

function groupByPage(blocks) {
  const pages = new Map();
  blocks.forEach((block) => {
    const list = pages.get(block.page_number) || [];
    list.push(block);
    pages.set(block.page_number, list);
  });
  return [...pages.entries()].sort((left, right) => left[0] - right[0]);
}

function rerenderOverlay() {
  if (!state.result) return;
  const target = document.querySelector("#pageOverlayGrid");
  if (!target) return;
  renderPageOverlays(
    target,
    state.result.document_id,
    state.result.pages || [],
    buildDisplayRegions(getFormulaOverlayRegions(state.result), state.result.formulas || [])
  );
  if (overlayModal && !overlayModal.hidden) {
    const pageNumber = Number((overlayModalMeta?.textContent || "").match(/(?:page|стр\.)\s+(\d+)/)?.[1] || 0);
    const page = (state.result.pages || []).find((item) => item.page_number === pageNumber);
    if (page) {
      const displayRegions = buildDisplayRegions(getFormulaOverlayRegions(state.result), state.result.formulas || []);
      const pageRegions = displayRegions.filter((region) => region.page_number === pageNumber);
      const visibleRegions = pageRegions.filter((region) => shouldShowOverlayRegion(region, pageRegions));
      openOverlayModal(state.result.document_id, page, pageRegions, visibleRegions);
    }
  }
}

function buildDisplayRegions(regions, formulas) {
  const formulasById = new Map((formulas || []).map((formula) => [formula.id, formula]));
  return (regions || []).map((region) => {
    const linked = (region.formula_ids || []).map((id) => formulasById.get(id)).filter(Boolean);
    const preferred = pickPreferredOverlayFormula(linked.filter((formula) => Array.isArray(formula.bbox) && formula.bbox.length === 4));
    return {
      ...region,
      display_bbox: preferred?.bbox || region.bbox,
      display_kind: preferred?.kind || region.kind,
      display_source: preferred?.source || region.source,
    };
  });
}

function pickPreferredOverlayFormula(formulas) {
  if (!formulas.length) return null;
  return [...formulas].sort((left, right) => {
    const leftPriority = overlayFormulaPriority(left);
    const rightPriority = overlayFormulaPriority(right);
    if (rightPriority !== leftPriority) return rightPriority - leftPriority;
    return bboxArea(left.bbox) - bboxArea(right.bbox);
  })[0];
}

function overlayFormulaPriority(formula) {
  const source = String(formula.source || "");
  let score = formula.kind === "block" ? 3 : 1;
  if (source.includes("tex")) score += 5;
  if (source.includes("pp_formula_net")) score += 4;
  if (source.includes("pp_structure")) score += 3;
  if (source.includes("text_inline_pattern")) score -= 1;
  return score + (formula.confidence || 0);
}

function bboxArea(bbox) {
  if (!Array.isArray(bbox) || bbox.length !== 4) return Number.MAX_SAFE_INTEGER;
  return Math.max(0, bbox[2] - bbox[0]) * Math.max(0, bbox[3] - bbox[1]);
}

function shouldShowOverlayRegion(region, pageRegions) {
  const mode = state.overlayMode || "smart";
  const kind = region.display_kind || region.kind;
  if (mode === "all") return true;
  if (mode === "block") return kind === "block";
  if (mode === "inline") return kind === "inline";
  if (mode === "selected") return Boolean(state.selectedToken) && region.token === state.selectedToken;

  const densePage = pageRegions.length > 6;
  if (state.selectedToken && region.token === state.selectedToken) return true;
  if (kind === "block") return true;
  return !densePage;
}

function overlayLabelVisible(region, width, height, visibleCount, largePreview) {
  if (region.token === state.selectedToken) return true;
  if (!largePreview && visibleCount > 3) return false;
  if (largePreview && visibleCount > 12) return false;
  const area = width * height;
  if (largePreview) return width >= 7 && height >= 1.4;
  return area >= 90 && width >= 12 && height >= 2.2;
}

function sortFormulaCandidates(formulas) {
  return [...formulas].sort((left, right) => {
    const leftScore = (left.confidence || 0) + (String(left.source || "").includes("tex") ? 2 : 0) + (String(left.source || "").includes("pp_formula_net") ? 1 : 0);
    const rightScore = (right.confidence || 0) + (String(right.source || "").includes("tex") ? 2 : 0) + (String(right.source || "").includes("pp_formula_net") ? 1 : 0);
    return rightScore - leftScore;
  });
}

function shortText(value, limit) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  return text.length <= limit ? text : `${text.slice(0, limit - 3)}...`;
}

function showWarnings(warnings, result = state.result) {
  const target = document.querySelector("#warnings");
  const relevantWarnings = getRelevantWarnings(warnings, result);
  if (!relevantWarnings.length) {
    target.classList.remove("active");
    target.hidden = true;
    target.textContent = "";
    return;
  }
  target.classList.add("active");
  target.hidden = false;
  const hasOcrWarnings = relevantWarnings.some((warning) => /ocr|dpi|render|max_pages|page/i.test(String(warning)));
  target.innerHTML = `
    <div class="warningsTop">
      <strong>${hasOcrWarnings ? "OCR-предупреждения" : "Предупреждения обработки"}</strong>
      <button type="button" class="warningsClose" aria-label="Скрыть предупреждения">Скрыть</button>
    </div>
    <div class="warningsList">
      ${relevantWarnings.map((warning) => `<div>${escapeHtml(shortText(translateWarningText(warning), 520))}</div>`).join("")}
    </div>
  `;
  target.querySelector(".warningsClose")?.addEventListener("click", () => {
    target.classList.remove("active");
    target.hidden = true;
  });
}

function formatConfidence(value) {
  return value === null || value === undefined ? "-" : Number(value).toFixed(2);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttribute(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}

document.body.dataset.page = state.activePage;
checkApi();
setInterval(checkApi, 10000);

