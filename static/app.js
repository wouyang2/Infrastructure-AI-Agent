const form = document.querySelector("#inspection-form");
const runButton = document.querySelector("#run-button");
const operationsShell = document.querySelector("#operations-shell");
const statusPill = document.querySelector("#status-pill");
const runRail = document.querySelector(".run-rail");
const dropZone = document.querySelector("#drop-zone");
const mediaUpload = document.querySelector("#media-upload");
const uploadStatus = document.querySelector("#upload-status");
const uploadPreview = document.querySelector("#upload-preview");
const videoUploadPreview = document.querySelector("#video-upload-preview");
const refreshCasesButton = document.querySelector("#refresh-cases-button");
const clearQueueButton = document.querySelector("#clear-queue-button");
const progressPanel = document.querySelector("#progress-panel");
const inspectionQueue = document.querySelector("#inspection-queue");
const inspectionHistory = document.querySelector("#inspection-history");
const queueCount = document.querySelector("#queue-count");
const historyCount = document.querySelector("#history-count");
const runSearch = document.querySelector("#run-search");
const runStatusFilter = document.querySelector("#run-status-filter");
const railSections = [...document.querySelectorAll("[data-rail-section]")];
const railSectionToggles = [...document.querySelectorAll("[data-toggle-section]")];
const sidebarToggleButton = document.querySelector("#sidebar-toggle-button");

const caseTitle = document.querySelector("#case-title");
const caseLocation = document.querySelector("#case-location");
const metricSeverity = document.querySelector("#metric-severity");
const metricRepair = document.querySelector("#metric-repair");
const metricSchedule = document.querySelector("#metric-schedule");
const metricRisk = document.querySelector("#metric-risk");
const observationCount = document.querySelector("#observation-count");
const citationCount = document.querySelector("#citation-count");
const overviewObservations = document.querySelector("#overview-observations");
const overviewRag = document.querySelector("#overview-rag");
const overviewMedia = document.querySelector("#overview-media");
const decisionSummary = document.querySelector("#decision-summary");
const observationsBlock = document.querySelector("#observations");
const contextBlock = document.querySelector("#context");
const planBlock = document.querySelector("#plan");
const scheduleBlock = document.querySelector("#schedule");
const formalReport = document.querySelector("#formal-report");
const eventStream = document.querySelector("#event-stream");
const reviewSummary = document.querySelector("#review-summary");
const reviewNotes = document.querySelector("#review-notes");

const openDrawerButton = document.querySelector("#open-drawer-button");
const closeDrawerButton = document.querySelector("#close-drawer-button");
const cancelInspectionButton = document.querySelector("#cancel-inspection-button");
const inspectionDrawer = document.querySelector("#inspection-drawer");
const drawerOverlay = document.querySelector("#drawer-overlay");
const exportButtons = [
  document.querySelector("#export-report-button"),
  document.querySelector("#report-export-button"),
].filter(Boolean);

let latestInspectionPayload = null;
let selectedRunId = null;
let focusedRunId = null;
let selectedCaseDetail = null;
let latestCases = [];
let activeTab = "overview";
let selectionRequest = 0;
const progressPollTimers = new Map();
const activeProgress = new Map();
const railSectionStorageKey = "infra_agent_collapsed_rail_sections";
const sidebarCollapsedStorageKey = "infra_agent_sidebar_collapsed";

const routeStages = ["intake", "evidence", "severity", "retrieval", "planning", "scheduling", "report"];
const stageAliases = {
  maintenance: "planning",
  maintenance_planning: "planning",
  schedule_context: "scheduling",
  persistence: "report",
  completed: "report",
};

const savedApiKey = localStorage.getItem("infra_agent_api_key");
if (savedApiKey && form.elements.api_key) {
  form.elements.api_key.value = savedApiKey;
}

const collapsedRailSections = new Set(
  JSON.parse(localStorage.getItem(railSectionStorageKey) || "[]"),
);
let sidebarCollapsed = localStorage.getItem(sidebarCollapsedStorageKey) === "true";

function requestHeaders(json = false) {
  const headers = {};
  if (json) headers["Content-Type"] = "application/json";
  const apiKey = form.elements.api_key?.value.trim();
  if (apiKey) {
    headers["X-API-Key"] = apiKey;
    localStorage.setItem("infra_agent_api_key", apiKey);
  }
  return headers;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function sentenceCase(value) {
  const text = String(value ?? "-").replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function formatDateTime(value) {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value).slice(0, 19).replace("T", " ");
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(parsed);
}

function formatWindow(schedule) {
  if (!schedule?.recommended_window) return "Monitoring only";
  const start = formatDateTime(schedule.recommended_window.start);
  const end = formatDateTime(schedule.recommended_window.end);
  return `${start} – ${end}`;
}

function makeRunId() {
  if (crypto.randomUUID) return crypto.randomUUID().replaceAll("-", "");
  return `run_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function item(title, body, variant = "") {
  return `<div class="item ${escapeHtml(variant)}"><strong>${escapeHtml(title)}</strong><p>${escapeHtml(body)}</p></div>`;
}

function renderList(element, rows, emptyText) {
  if (!rows.length) {
    element.className = "list-block muted";
    element.textContent = emptyText;
    return;
  }
  element.className = "list-block";
  element.innerHTML = rows.join("");
}

function setStatus(label, state) {
  statusPill.textContent = label;
  statusPill.className = `status-pill ${state}`;
}

function setExportEnabled(enabled) {
  exportButtons.forEach((button) => {
    button.disabled = !enabled;
  });
}

function setSidebarCollapsed(collapsed) {
  sidebarCollapsed = collapsed;
  operationsShell.classList.toggle("sidebar-collapsed", collapsed);
  runRail.classList.toggle("collapsed", collapsed);
  sidebarToggleButton.setAttribute("aria-expanded", String(!collapsed));
  sidebarToggleButton.title = collapsed ? "Expand sidebar" : "Collapse sidebar";
  localStorage.setItem(sidebarCollapsedStorageKey, String(collapsed));
}

function setRailSectionCollapsed(sectionName, collapsed) {
  const section = railSections.find((node) => node.dataset.railSection === sectionName);
  const toggle = railSectionToggles.find((node) => node.dataset.toggleSection === sectionName);
  if (!section || !toggle) return;
  section.classList.toggle("collapsed", collapsed);
  toggle.setAttribute("aria-expanded", String(!collapsed));
  if (collapsed) collapsedRailSections.add(sectionName);
  else collapsedRailSections.delete(sectionName);
  localStorage.setItem(railSectionStorageKey, JSON.stringify([...collapsedRailSections]));
}

function applyRailSectionState() {
  railSections.forEach((section) => {
    setRailSectionCollapsed(
      section.dataset.railSection,
      collapsedRailSections.has(section.dataset.railSection),
    );
  });
}

function showTab(tabName, focus = false) {
  activeTab = tabName;
  document.querySelectorAll("[data-tab]").forEach((button) => {
    const selected = button.dataset.tab === tabName;
    button.setAttribute("aria-selected", String(selected));
    if (selected && focus) button.focus();
  });
  document.querySelectorAll("[data-view]").forEach((panel) => {
    const selected = panel.dataset.view === tabName;
    panel.hidden = !selected;
    panel.classList.toggle("active", selected);
  });
}

function openDrawer() {
  clearMediaSelection();
  drawerOverlay.hidden = false;
  inspectionDrawer.classList.add("open");
  inspectionDrawer.setAttribute("aria-hidden", "false");
  document.body.classList.add("drawer-open");
  closeDrawerButton.focus();
}

function closeDrawer() {
  inspectionDrawer.classList.remove("open");
  inspectionDrawer.setAttribute("aria-hidden", "true");
  drawerOverlay.hidden = true;
  document.body.classList.remove("drawer-open");
  openDrawerButton.focus();
}

function formPayload() {
  const data = new FormData(form);
  const imagePath = String(data.get("image_path") || "").trim();
  const videoPath = String(data.get("video_path") || "").trim();
  const latitude = data.get("latitude");
  const longitude = data.get("longitude");
  return {
    asset_id: data.get("asset_id"),
    asset_type: "bridge",
    asset_name: data.get("asset_name"),
    location: data.get("location"),
    latitude: latitude === "" ? null : Number(latitude),
    longitude: longitude === "" ? null : Number(longitude),
    criticality: data.get("criticality"),
    notes: data.get("notes"),
    image_paths: imagePath ? [imagePath] : [],
    video_paths: videoPath ? [videoPath] : [],
    require_media: true,
    image_analyzer: data.get("image_analyzer"),
    embedding_backend: data.get("embedding_backend"),
    video_sampler: data.get("video_sampler"),
    video_frame_interval: Number(data.get("video_frame_interval") || 4.6),
    video_max_frames: Number(data.get("video_max_frames") || 3),
    planning_mode: data.get("planning_mode"),
    scheduling_mode: data.get("scheduling_mode"),
    schedule_context_mode: data.get("schedule_context_mode"),
    event_provider: data.get("event_provider"),
    report_mode: data.get("report_mode"),
    rag_backend: "chroma",
    knowledge_corpus: "merged",
    llm_failure_mode: "fallback",
  };
}

function hasUploadedMedia() {
  return Boolean(form.elements.image_path.value.trim() || form.elements.video_path.value.trim());
}

function clearMediaSelection() {
  form.elements.image_path.value = "";
  form.elements.video_path.value = "";
  mediaUpload.value = "";
  uploadPreview.hidden = true;
  uploadPreview.src = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==";
  videoUploadPreview.hidden = true;
  videoUploadPreview.removeAttribute("src");
  uploadStatus.textContent = "Image or video required; the file type selects the analysis path.";
}

function validateMediaSelection() {
  if (hasUploadedMedia()) return true;
  uploadStatus.textContent = "Choose an inspection image or video before running the inspection.";
  dropZone.classList.add("field-error");
  dropZone.scrollIntoView({ behavior: "smooth", block: "center" });
  return false;
}

async function uploadImage(file) {
  dropZone.classList.remove("field-error");
  uploadStatus.textContent = `Uploading ${file.name}...`;
  const uploadBody = new FormData();
  uploadBody.append("file", file, file.name);
  const response = await fetch("/uploads/images/multipart", {
    method: "POST",
    headers: requestHeaders(false),
    body: uploadBody,
  });
  if (!response.ok) throw new Error(await response.text());
  const payload = await response.json();
  form.elements.image_path.value = payload.file_path;
  form.elements.video_path.value = "";
  if (form.elements.image_analyzer.value === "metadata") form.elements.image_analyzer.value = "roboflow";
  uploadPreview.src = payload.preview_url;
  uploadPreview.hidden = false;
  videoUploadPreview.hidden = true;
  videoUploadPreview.removeAttribute("src");
  uploadStatus.textContent = `${file.name} uploaded. ${sentenceCase(form.elements.image_analyzer.value)} analysis selected.`;
}

async function uploadVideo(file) {
  dropZone.classList.remove("field-error");
  uploadStatus.textContent = `Uploading ${file.name}...`;
  const uploadBody = new FormData();
  uploadBody.append("file", file, file.name);
  const response = await fetch("/uploads/videos/multipart", {
    method: "POST",
    headers: requestHeaders(false),
    body: uploadBody,
  });
  if (!response.ok) throw new Error(await response.text());
  const payload = await response.json();
  form.elements.image_path.value = "";
  form.elements.video_path.value = payload.file_path;
  form.elements.video_sampler.value = "opencv";
  uploadPreview.hidden = true;
  videoUploadPreview.src = payload.preview_url;
  videoUploadPreview.hidden = false;
  uploadStatus.textContent = `${file.name} uploaded. OpenCV frame sampling selected.`;
}

async function uploadMedia(file) {
  if (!file) return;
  try {
    if (file.type.startsWith("image/")) await uploadImage(file);
    else if (file.type.startsWith("video/")) await uploadVideo(file);
    else throw new Error("Choose a JPG, PNG, WEBP, MP4, MOV, AVI, or MKV file.");
  } catch (error) {
    uploadStatus.textContent = error.message;
  }
}

function isTerminalStatus(status) {
  return status === "completed" || status === "failed" || status === "canceled";
}

function normalizedStage(stage) {
  return stageAliases[stage] || stage || "intake";
}

function renderWorkflowRoute(progress = null, fallbackStatus = null) {
  const routeItems = [...document.querySelectorAll("#workflow-route li")];
  const status = progress?.status || fallbackStatus || "queued";
  const currentStage = normalizedStage(progress?.current_stage || "intake");
  const currentIndex = Math.max(0, routeStages.indexOf(currentStage));
  const eventByStage = new Map();
  for (const event of progress?.events || []) eventByStage.set(normalizedStage(event.stage), event);

  routeItems.forEach((node, index) => {
    node.className = "";
    const stage = node.dataset.stage;
    const small = node.querySelector("small");
    if (status === "completed") {
      node.classList.add("complete");
      small.textContent = "Complete";
      return;
    }
    if (index < currentIndex) {
      node.classList.add("complete");
      small.textContent = "Complete";
      return;
    }
    if (index === currentIndex) {
      node.classList.add(status === "failed" || status === "canceled" ? "failed" : "current");
      small.textContent = status === "failed" || status === "canceled"
        ? sentenceCase(status)
        : sentenceCase(eventByStage.get(stage)?.status || "Active");
      return;
    }
    small.textContent = "Waiting";
  });
}

function renderProgress(progress) {
  const events = progress.events || [];
  const recentEvents = events.slice(-4).reverse();
  const runtimeLine = progress.job_status_message
    ? `<div class="progress-runtime"><strong>${escapeHtml((progress.job_backend || "job").toUpperCase())} · ${escapeHtml(progress.job_status || "unknown")}</strong><span>${escapeHtml(progress.job_status_message)}</span>${progress.job_last_heartbeat ? `<span>Heartbeat ${escapeHtml(formatDateTime(progress.job_last_heartbeat))}</span>` : ""}</div>`
    : "";
  progressPanel.innerHTML = `
    <div class="progress-head"><div><h3>Live Progress</h3><strong>${escapeHtml(sentenceCase(progress.current_stage))}: ${escapeHtml(progress.message)}</strong></div><span>${escapeHtml(progress.percent)}%</span></div>
    <div class="progress-track"><div class="progress-fill" style="width:${Math.max(0, Math.min(100, Number(progress.percent || 0)))}%"></div></div>
    ${runtimeLine}
    <div class="progress-events">${recentEvents.map((event) => `<div><strong>${escapeHtml(sentenceCase(event.stage))}</strong><span>${escapeHtml(event.message)}</span></div>`).join("")}</div>
  `;
  renderWorkflowRoute(progress);
  setStatus(
    progress.status === "failed" ? "Failed" : progress.status === "completed" ? "Complete" : progress.status === "canceled" ? "Canceled" : sentenceCase(progress.status),
    progress.status === "failed" ? "error" : progress.status === "completed" ? "done" : progress.status === "canceled" ? "idle" : "running",
  );
}

function renderProgressPlaceholder(message, status = "queued") {
  progressPanel.innerHTML = `<div class="progress-head"><div><h3>Live Progress</h3><strong>${escapeHtml(message)}</strong></div><span>0%</span></div><div class="progress-track"><div class="progress-fill" style="width:0%"></div></div>`;
  renderWorkflowRoute(null, status);
}

function renderPersistedProgress(caseDetail) {
  const completed = caseDetail.status === "completed";
  const failed = caseDetail.status === "failed";
  const canceled = caseDetail.status === "canceled";
  const percent = completed || canceled ? 100 : 0;
  const message = completed
    ? `Completed ${formatDateTime(caseDetail.completed_at)}`
    : failed
      ? caseDetail.error || "The workflow stopped before completion."
      : canceled
        ? caseDetail.error || "Inspection canceled by operator."
        : "Waiting for live worker progress.";
  progressPanel.innerHTML = `<div class="progress-head"><div><h3>Live Progress</h3><strong>${escapeHtml(message)}</strong></div><span>${percent}%</span></div><div class="progress-track"><div class="progress-fill ${completed ? "done" : failed ? "failed" : canceled ? "canceled" : ""}" style="width:${percent}%"></div></div>`;
  renderWorkflowRoute(null, caseDetail.status);
}

function queueRowStatus(item) {
  const status = activeProgress.get(item.run_id)?.status || item.status || "queued";
  if (status === "canceled") return "canceled";
  if (status === "failed") return "failed";
  if (status === "completed") return "completed";
  return "running";
}

function queueRowMeta(item) {
  const progress = activeProgress.get(item.run_id);
  if (progress) return `${sentenceCase(progress.current_stage)} · ${progress.message}`;
  return `${sentenceCase(item.status)} · ${formatDateTime(item.completed_at || item.created_at)}`;
}

function queueRowPercent(item) {
  const progress = activeProgress.get(item.run_id);
  if (progress) return `${Math.max(0, Math.min(100, Number(progress.percent || 0)))}%`;
  return item.status === "completed" ? "100%" : item.status === "failed" ? "Failed" : item.status === "canceled" ? "Canceled" : "Queued";
}

function allRunRows() {
  const rowsByRunId = new Map(latestCases.map((item) => [item.run_id, item]));
  for (const [runId, progress] of activeProgress.entries()) {
    if (!rowsByRunId.has(runId)) {
      rowsByRunId.set(runId, {
        run_id: runId,
        case_id: null,
        asset_name: "Queued inspection",
        location: "Awaiting persisted case",
        status: progress.status,
        created_at: progress.started_at,
      });
    }
  }
  return [...rowsByRunId.values()].sort((left, right) => {
    const leftActive = isTerminalStatus(activeProgress.get(left.run_id)?.status || left.status) ? 1 : 0;
    const rightActive = isTerminalStatus(activeProgress.get(right.run_id)?.status || right.status) ? 1 : 0;
    if (leftActive !== rightActive) return leftActive - rightActive;
    return String(right.created_at || "").localeCompare(String(left.created_at || ""));
  });
}

function rowMatchesCurrentFilter(item) {
  const query = runSearch.value.trim().toLowerCase();
  const filter = runStatusFilter.value;
  const status = activeProgress.get(item.run_id)?.status || item.status || "queued";
  const matchesStatus = filter === "all"
    || (filter === "active" && !isTerminalStatus(status))
    || (filter === "completed" && status === "completed")
    || (filter === "failed" && status === "failed")
    || (filter === "canceled" && status === "canceled");
  const haystack = `${item.asset_name || ""} ${item.asset_id || ""} ${item.case_id || ""} ${item.run_id}`.toLowerCase();
  return matchesStatus && (!query || haystack.includes(query));
}

function renderRunRows(container, rows, emptyText, { showCancel = false } = {}) {
  if (!rows.length) {
    container.className = container.classList.contains("history-list")
      ? "inspection-queue history-list muted"
      : "inspection-queue muted";
    container.textContent = emptyText;
    return;
  }

  container.className = container.classList.contains("history-list")
    ? "inspection-queue history-list"
    : "inspection-queue";
  container.innerHTML = rows.map((entry) => `
    <div class="queue-row ${queueRowStatus(entry)} ${entry.run_id === focusedRunId ? "selected" : ""}" data-run-id="${escapeHtml(entry.run_id)}">
      <button type="button" class="queue-row-main" data-select-run-id="${escapeHtml(entry.run_id)}">
        <span><strong>${escapeHtml(entry.asset_name || entry.case_id || "Inspection")}</strong><span class="queue-row-meta">${escapeHtml(entry.case_id || entry.run_id.slice(-12))} · ${escapeHtml(queueRowMeta(entry))}</span></span>
        <span class="queue-row-state">${escapeHtml(queueRowPercent(entry))}</span>
      </button>
      ${showCancel ? `<button type="button" class="queue-cancel-button" data-cancel-run-id="${escapeHtml(entry.run_id)}" title="Cancel inspection">Cancel</button>` : ""}
    </div>
  `).join("");

  container.querySelectorAll("[data-select-run-id]").forEach((button) => {
    button.addEventListener("click", () => selectRun(button.dataset.selectRunId));
  });
  container.querySelectorAll("[data-cancel-run-id]").forEach((button) => {
    button.addEventListener("click", () => cancelRun(button.dataset.cancelRunId));
  });
}

function renderInspectionQueue() {
  const allRows = allRunRows();
  const activeRows = allRows.filter((item) => !isTerminalStatus(activeProgress.get(item.run_id)?.status || item.status));
  const historyRows = allRows.filter((item) => isTerminalStatus(activeProgress.get(item.run_id)?.status || item.status));
  const filteredActiveRows = activeRows.filter(rowMatchesCurrentFilter);
  const filteredHistoryRows = historyRows.filter(rowMatchesCurrentFilter);
  queueCount.textContent = activeRows.length ? `${activeRows.length} active` : "No active inspections";
  historyCount.textContent = `${historyRows.length} historical inspection${historyRows.length === 1 ? "" : "s"}`;
  clearQueueButton.disabled = activeRows.length === 0;

  renderRunRows(
    inspectionQueue,
    filteredActiveRows,
    activeRows.length ? "The current filters match zero active runs." : "Start a new inspection to create the first active run.",
    { showCancel: true },
  );
  renderRunRows(
    inspectionHistory,
    filteredHistoryRows,
    historyRows.length ? "The current filters match zero historical runs." : "Completed, failed, and canceled inspections will appear here.",
  );
}

function activeRunIds() {
  return allRunRows()
    .filter((item) => !isTerminalStatus(activeProgress.get(item.run_id)?.status || item.status))
    .map((item) => item.run_id);
}

function renderCaseHeader(caseDetail) {
  caseTitle.textContent = caseDetail.asset_name || "Inspection run";
  caseLocation.textContent = `${caseDetail.case_id || caseDetail.run_id} · ${caseDetail.location || "Location unavailable"} · ${sentenceCase(caseDetail.asset_type || "bridge")} · ${sentenceCase(caseDetail.criticality || "unknown")} criticality`;
  const state = caseDetail.status === "failed" ? "error" : caseDetail.status === "completed" ? "done" : "running";
  setStatus(sentenceCase(caseDetail.status), caseDetail.status === "canceled" ? "idle" : state);
}

function clearResultData(message = "This run has not produced a report yet.") {
  latestInspectionPayload = null;
  setExportEnabled(false);
  metricSeverity.textContent = "-";
  metricRepair.textContent = "-";
  metricSchedule.textContent = "-";
  metricRisk.textContent = "-";
  observationCount.textContent = "0";
  citationCount.textContent = "0";
  [overviewObservations, overviewRag, decisionSummary].forEach((element) => {
    element.className = "list-block muted";
    element.textContent = message;
  });
  overviewMedia.className = "media-gallery muted";
  overviewMedia.textContent = message;
  observationsBlock.className = "table-wrap muted";
  observationsBlock.textContent = message;
  contextBlock.className = "rag-layout muted";
  contextBlock.textContent = message;
  planBlock.className = "plan-layout muted";
  planBlock.textContent = message;
  scheduleBlock.className = "schedule-layout muted";
  scheduleBlock.textContent = message;
  formalReport.innerHTML = `<div class="empty-state">${escapeHtml(message)}</div>`;
}

function confidenceCell(confidence) {
  const percent = Math.round(Number(confidence || 0) * 100);
  return `<div class="confidence-bar"><span><i style="width:${percent}%"></i></span><strong>${percent}%</strong></div>`;
}

function renderObservations(observations) {
  observationCount.textContent = String(observations.length);
  renderList(
    overviewObservations,
    observations.slice(0, 4).map((observation) => item(
      `${sentenceCase(observation.defect_type)} · ${Math.round(observation.confidence * 100)}%`,
      `${observation.location_on_asset || "Location not specified"} — ${observation.description}`,
    )),
    "The workflow produced zero observations.",
  );
  if (!observations.length) {
    observationsBlock.className = "table-wrap muted";
    observationsBlock.textContent = "The workflow produced zero observations.";
    return;
  }
  observationsBlock.className = "table-wrap";
  observationsBlock.innerHTML = `
    <table class="data-table"><thead><tr><th>ID</th><th>Defect</th><th>Location</th><th>Source</th><th>Confidence</th><th>Description</th></tr></thead>
    <tbody>${observations.map((observation) => `<tr><td>${escapeHtml(observation.observation_id)}</td><td><strong>${escapeHtml(sentenceCase(observation.defect_type))}</strong></td><td>${escapeHtml(observation.location_on_asset || "-")}</td><td>${escapeHtml(sentenceCase(observation.source_modality))}<br><small>${escapeHtml(observation.source_id)}</small></td><td>${confidenceCell(observation.confidence)}</td><td>${escapeHtml(observation.description)}</td></tr>`).join("")}</tbody></table>
  `;
}

function sourceList(title, sources, emptyText, formatter) {
  return `<section class="result-block"><h4>${escapeHtml(title)}</h4><ul class="source-list">${sources.length ? sources.map(formatter).join("") : `<li>${escapeHtml(emptyText)}</li>`}</ul></section>`;
}

function renderRag(report) {
  const citations = report.severity.citations || [];
  const precedents = report.maintenance_plan.historical_precedents || [];
  const scheduleContext = report.schedule?.context_summary || [];
  citationCount.textContent = String(citations.length + precedents.length);
  renderList(
    overviewRag,
    [
      ...citations.slice(0, 2).map((citation) => item(citation.document_id, citation.title)),
      ...precedents.slice(0, 2).map((precedent) => item(precedent.document_id, precedent.title)),
    ],
    "The retriever returned zero guidance or repair precedents.",
  );
  contextBlock.className = "rag-layout";
  contextBlock.innerHTML = [
    sourceList("Standards & guidance", citations, "The retrieval threshold excluded all standards.", (citation) => `<li><span class="source-score">${Number(citation.score || 0).toFixed(2)}</span><strong>${escapeHtml(citation.title)}</strong><span>${escapeHtml(citation.document_id)} · ${escapeHtml(sentenceCase(citation.source_type))}</span><span>${escapeHtml(citation.excerpt || "")}</span></li>`),
    sourceList("Historical repair precedents", precedents, "The retriever found zero similar repairs.", (precedent) => `<li><strong>${escapeHtml(precedent.title)}</strong><span>${escapeHtml(precedent.document_id)} · ${escapeHtml(precedent.repair_method || "Method unavailable")}</span><span>${escapeHtml(precedent.outcome || "Outcome unavailable")} · ${escapeHtml(precedent.actual_duration_hours)} hours</span></li>`),
    `<section class="result-block full"><h4>Scheduling context</h4><ul class="context-list">${scheduleContext.length ? scheduleContext.map((line) => `<li>${escapeHtml(line)}</li>`).join("") : "<li>Scheduling context was not required.</li>"}</ul></section>`,
  ].join("");
}

function renderPlan(plan) {
  const tasks = plan.tasks || [];
  planBlock.className = "plan-layout";
  planBlock.innerHTML = `
    <section class="result-block full"><h4>Recommended action</h4><p>${escapeHtml(plan.recommended_action)}</p><div class="detail-grid"><div><span>Estimated duration</span><strong>${escapeHtml(plan.estimated_duration_hours)} hours</strong></div><div><span>Task count</span><strong>${tasks.length}</strong></div></div></section>
    <section class="result-block"><h4>Work sequence</h4><ul class="task-list">${tasks.length ? tasks.map((task) => `<li><strong>${escapeHtml(task.name)} <span class="source-score">${escapeHtml(task.estimated_hours)}h</span></strong><span>${escapeHtml(task.description)}</span>${task.dependencies?.length ? `<span>Depends on ${escapeHtml(task.dependencies.join(", "))}</span>` : ""}</li>`).join("") : "<li>The plan contains zero repair tasks.</li>"}</ul></section>
    <section class="result-block"><h4>Resources</h4><div class="detail-grid"><div><span>Materials</span><strong>${escapeHtml((plan.materials || []).join(", ") || "None")}</strong></div><div><span>Equipment</span><strong>${escapeHtml((plan.equipment || []).join(", ") || "None")}</strong></div><div><span>Permits</span><strong>${escapeHtml((plan.permits || []).join(", ") || "None")}</strong></div><div><span>Precedents used</span><strong>${(plan.historical_precedents || []).length}</strong></div></div></section>
    <section class="result-block full"><h4>Execution risks</h4><ul class="risk-list">${(plan.risks || []).length ? plan.risks.map((risk) => `<li>${escapeHtml(risk)}</li>`).join("") : "<li>The plan contains zero listed risks.</li>"}</ul></section>
  `;
}

function renderSchedule(schedule) {
  scheduleBlock.className = "schedule-layout";
  if (!schedule) {
    scheduleBlock.innerHTML = `<section class="result-block full"><h4>Monitoring path</h4><p>This case requires monitoring instead of a repair window. Continue the follow-up inspection plan.</p></section>`;
    return;
  }
  scheduleBlock.innerHTML = `
    <section class="result-block full"><h4>Recommended window</h4><div class="detail-grid"><div><span>Start</span><strong>${escapeHtml(formatDateTime(schedule.recommended_window.start))}</strong></div><div><span>End</span><strong>${escapeHtml(formatDateTime(schedule.recommended_window.end))}</strong></div><div><span>Disruption score</span><strong>${escapeHtml(schedule.disruption_score)}</strong></div><div><span>Context risk</span><strong>${escapeHtml(schedule.context_risk_score)}</strong></div></div></section>
    <section class="result-block"><h4>Constraints satisfied</h4><ul class="context-list">${(schedule.constraints_satisfied || []).map((line) => `<li>${escapeHtml(line)}</li>`).join("") || "<li>The scheduler listed zero constraints.</li>"}</ul></section>
    <section class="result-block"><h4>Tradeoffs</h4><ul class="risk-list">${(schedule.tradeoffs || []).map((line) => `<li>${escapeHtml(line)}</li>`).join("") || "<li>The scheduler listed zero tradeoffs.</li>"}</ul></section>
    <section class="result-block full"><h4>Weather, traffic & events</h4><ul class="context-list">${(schedule.context_summary || []).map((line) => `<li>${escapeHtml(line)}</li>`).join("") || "<li>External context was unavailable for this case.</li>"}</ul></section>
  `;
}

function stripMarkdownSyntax(text) {
  return String(text ?? "")
    .replace(/```[\s\S]*?```/g, "")
    .split("\n")
    .map((line) => line.replace(/^\s{0,3}#{1,6}\s+/g, "").replace(/^\s*[-*]\s+/g, "").replace(/^\s*\d+\.\s+/g, "").replace(/\*\*(.*?)\*\*/g, "$1").replace(/__(.*?)__/g, "$1").replace(/`([^`]+)`/g, "$1").trim())
    .filter((line) => line && !/^[-=_]{3,}$/.test(line))
    .join("\n");
}

function renderNarrative(text) {
  const cleaned = stripMarkdownSyntax(text);
  return cleaned.split(/\n{2,}/).map((paragraph) => paragraph.replace(/\n/g, " ").trim()).filter(Boolean).map((paragraph) => `<p>${escapeHtml(paragraph)}</p>`).join("");
}

function renderRows(rows) {
  return rows.map((row) => `<tr>${row.map((cell) => `<td>${escapeHtml(cell)}</td>`).join("")}</tr>`).join("");
}

function mediaRowsFromPayload(payload) {
  const fromDetail = Array.isArray(payload.media) ? payload.media : [];
  if (fromDetail.length) return fromDetail;
  const request = payload.request || {};
  return [
    ...(request.image_paths || []).map((filePath) => ({
      media_type: "image",
      file_path: filePath,
      preview_url: `/${filePath}`,
      original_filename: filePath.split("/").pop(),
      scan_status: "unknown",
    })),
    ...(request.video_paths || []).map((filePath) => ({
      media_type: "video",
      file_path: filePath,
      preview_url: `/${filePath}`,
      original_filename: filePath.split("/").pop(),
      scan_status: "unknown",
    })),
  ];
}

function renderMediaCard(media, mode = "overview") {
  const isImage = media.media_type === "image";
  const label = `${sentenceCase(media.media_type || "media")} · ${media.original_filename || media.file_path || "Uploaded file"}`;
  const previewUrl = media.preview_url || (media.file_path ? `/${media.file_path}` : "");
  const meta = [
    media.storage_backend ? `${sentenceCase(media.storage_backend)} storage` : "",
    media.size_bytes ? `${Math.round(media.size_bytes / 1024)} KB` : "",
    media.scan_status ? `scan: ${sentenceCase(media.scan_status)}` : "",
  ].filter(Boolean).join(" · ");
  const mediaElement = isImage
    ? `<img src="${escapeHtml(previewUrl)}" alt="${escapeHtml(label)}" />`
    : `<video src="${escapeHtml(previewUrl)}" controls muted preload="metadata"></video>`;
  return `
    <figure class="media-card ${escapeHtml(mode)}">
      ${mediaElement}
      <figcaption><strong>${escapeHtml(label)}</strong>${meta ? `<span>${escapeHtml(meta)}</span>` : ""}</figcaption>
    </figure>
  `;
}

function renderMediaGallery(payload) {
  const media = mediaRowsFromPayload(payload);
  if (!media.length) {
    overviewMedia.className = "media-gallery muted";
    overviewMedia.textContent = "No uploaded image or video is linked to this case.";
    return "";
  }
  overviewMedia.className = "media-gallery";
  overviewMedia.innerHTML = media.slice(0, 4).map((row) => renderMediaCard(row)).join("");
  return `<section class="report-section"><h4>Visual Evidence</h4><div class="report-media-grid">${media.map((row) => renderMediaCard(row, "report")).join("")}</div></section>`;
}

function renderFormalReport(payload) {
  const report = payload.report;
  const schedule = report.schedule;
  const plan = report.maintenance_plan;
  const citations = report.severity.citations || [];
  const observations = report.observations || [];
  const tasks = plan.tasks || [];
  const precedents = plan.historical_precedents || [];
  const visualEvidenceSection = renderMediaGallery(payload);
  formalReport.innerHTML = `
    <div class="report-title-block"><h2>Infrastructure Inspection Report</h2><p><strong>${escapeHtml(report.case.asset.name)}</strong> · ${escapeHtml(report.case.asset.location)} · ${escapeHtml(report.case.case_id)}</p><div class="report-meta"><div><span>Severity</span><strong>${escapeHtml(sentenceCase(report.severity.severity))}</strong></div><div><span>Urgency</span><strong>${escapeHtml(sentenceCase(report.severity.urgency))}</strong></div><div><span>Repair</span><strong>${report.severity.repair_required ? "Required" : "Monitor"}</strong></div><div><span>Schedule</span><strong>${escapeHtml(formatWindow(schedule))}</strong></div></div></div>
    <section class="report-section"><h4>Executive Summary</h4><div class="report-two-column"><div class="report-callout"><span class="report-section-label">Recommended action</span>${escapeHtml(plan.recommended_action)}</div><div class="report-callout"><span class="report-section-label">Estimated duration</span>${escapeHtml(plan.estimated_duration_hours)} hours</div></div><p>${escapeHtml(report.severity.rationale)}</p></section>
    ${visualEvidenceSection}
    ${payload.rendered_report ? `<section class="report-section"><h4>Supervisor Narrative</h4><div class="report-narrative">${renderNarrative(payload.rendered_report)}</div></section>` : ""}
    <section class="report-section"><h4>Observed Conditions</h4><table class="report-table"><thead><tr><th>ID</th><th>Defect</th><th>Source</th><th>Confidence</th><th>Description</th></tr></thead><tbody>${renderRows(observations.map((observation) => [observation.observation_id, sentenceCase(observation.defect_type), observation.source_modality, `${Math.round(observation.confidence * 100)}%`, observation.description]))}</tbody></table></section>
    <section class="report-section"><h4>Guidance and Precedents</h4><div class="report-two-column"><div><span class="report-section-label">Retrieved guidance</span><ul class="report-list">${citations.length ? citations.map((citation) => `<li>${escapeHtml(citation.title)} [${escapeHtml(citation.document_id)}]</li>`).join("") : "<li>The retrieval threshold excluded all standards.</li>"}</ul></div><div><span class="report-section-label">Historical repairs</span><ul class="report-list">${precedents.length ? precedents.map((precedent) => `<li>${escapeHtml(precedent.title)} [${escapeHtml(precedent.document_id)}]</li>`).join("") : "<li>The retriever found zero similar repairs.</li>"}</ul></div></div></section>
    <section class="report-section"><h4>Maintenance Plan</h4><table class="report-table"><thead><tr><th>Task</th><th>Description</th><th>Hours</th></tr></thead><tbody>${renderRows(tasks.map((task) => [task.name, task.description, task.estimated_hours]))}</tbody></table><div class="report-two-column report-section"><div><span class="report-section-label">Materials</span><p>${escapeHtml((plan.materials || []).join(", ") || "None listed")}</p></div><div><span class="report-section-label">Equipment</span><p>${escapeHtml((plan.equipment || []).join(", ") || "None listed")}</p></div></div><span class="report-section-label">Risks</span><ul class="report-list">${(plan.risks || []).map((risk) => `<li>${escapeHtml(risk)}</li>`).join("") || "<li>None listed.</li>"}</ul></section>
    <section class="report-section"><h4>Repair Schedule</h4>${schedule ? `<div class="report-meta"><div><span>Window</span><strong>${escapeHtml(formatWindow(schedule))}</strong></div><div><span>Disruption</span><strong>${escapeHtml(schedule.disruption_score)}</strong></div><div><span>Context risk</span><strong>${escapeHtml(schedule.context_risk_score)}</strong></div><div><span>Total score</span><strong>${escapeHtml(schedule.total_score)}</strong></div></div><div class="report-two-column report-section"><div><span class="report-section-label">Context</span><ul class="report-list">${(schedule.context_summary || []).map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul></div><div><span class="report-section-label">Tradeoffs</span><ul class="report-list">${(schedule.tradeoffs || []).map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul></div></div>` : "<p>This case follows a monitoring plan instead of a repair window.</p>"}</section>
  `;
}

function renderReviewSummary(caseDetail) {
  selectedRunId = caseDetail.run_id;
  reviewNotes.value = caseDetail.reviewer_notes || "";
  renderList(reviewSummary, [
    item("Case", `${caseDetail.case_id || "Pending"} · ${sentenceCase(caseDetail.status)}`),
    item("Review state", `${sentenceCase(caseDetail.review_status)}${caseDetail.reviewed_by ? ` by ${caseDetail.reviewed_by}` : ""}`),
    item("Workflow trace", caseDetail.workflow_trace_id || "Workflow trace unavailable"),
  ], "Select a saved case.");
  document.querySelectorAll("[data-review-status]").forEach((button) => {
    button.disabled = caseDetail.status !== "completed";
  });
}

function renderResult(payload) {
  latestInspectionPayload = payload;
  const report = payload.report;
  const schedule = report.schedule;
  const plan = report.maintenance_plan;
  metricSeverity.textContent = sentenceCase(report.severity.severity);
  metricRepair.textContent = report.severity.repair_required ? "Required" : "Monitor";
  metricSchedule.textContent = formatWindow(schedule);
  metricRisk.textContent = schedule ? String(schedule.context_risk_score) : "None";
  renderList(decisionSummary, [
    item("Urgency", sentenceCase(report.severity.urgency)),
    item("Confidence", `${Math.round(report.severity.confidence * 100)}%`),
    item("Recommended action", plan.recommended_action),
    item("Rationale", report.severity.rationale),
  ], "Assessment details are unavailable for this run.");
  renderObservations(report.observations || []);
  renderRag(report);
  renderPlan(plan);
  renderSchedule(schedule);
  renderFormalReport(payload);
  setExportEnabled(true);
}

async function loadActivity(runId) {
  eventStream.className = "event-stream muted";
  eventStream.textContent = "Loading workflow activity...";
  try {
    const [eventsResponse, reviewEventsResponse] = await Promise.all([
      fetch(`/cases/${encodeURIComponent(runId)}/events`, { headers: requestHeaders() }),
      fetch(`/cases/${encodeURIComponent(runId)}/review-events`, { headers: requestHeaders() }),
    ]);
    if (!eventsResponse.ok) throw new Error(await eventsResponse.text());
    const events = await eventsResponse.json();
    const reviewEvents = reviewEventsResponse.ok ? await reviewEventsResponse.json() : [];
    const rows = [
      ...events.map((event) => ({ ...event, type: event.event_type || "workflow" })),
      ...reviewEvents.map((event) => ({ stage: "review", status: event.new_status, message: event.reviewer_notes || `Review changed to ${sentenceCase(event.new_status)}`, created_at: event.created_at, type: "review" })),
    ].sort((left, right) => String(right.created_at).localeCompare(String(left.created_at)));
    if (!rows.length) {
      eventStream.className = "event-stream muted";
      eventStream.textContent = "This run has zero durable workflow events.";
      return;
    }
    eventStream.className = "event-stream";
    eventStream.innerHTML = rows.map((event) => `<div class="event-row"><time>${escapeHtml(formatDateTime(event.created_at))}</time><strong>${escapeHtml(sentenceCase(event.stage))}</strong><span>${escapeHtml(event.message)}</span><small>${escapeHtml(sentenceCase(event.status || event.type))}${event.attempt ? ` · attempt ${escapeHtml(event.attempt)}` : ""}</small></div>`).join("");
  } catch (error) {
    eventStream.className = "event-stream muted";
    eventStream.textContent = error.message;
  }
}

async function loadCaseDetail(runId) {
  const response = await fetch(`/cases/${encodeURIComponent(runId)}`, { headers: requestHeaders() });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

async function selectRun(runId) {
  const requestId = ++selectionRequest;
  focusedRunId = runId;
  selectedRunId = runId;
  renderInspectionQueue();
  showTab(activeTab);
  const progress = activeProgress.get(runId);
  if (progress) renderProgress(progress);
  else renderProgressPlaceholder("Loading run state...");
  try {
    const caseDetail = await loadCaseDetail(runId);
    if (requestId !== selectionRequest) return;
    selectedCaseDetail = caseDetail;
    renderCaseHeader(caseDetail);
    renderReviewSummary(caseDetail);
    if (progress) renderProgress(progress);
    else renderPersistedProgress(caseDetail);
    if (caseDetail.report) {
      renderResult({
        run_id: caseDetail.run_id,
        report: caseDetail.report,
        rendered_report: caseDetail.rendered_report || "",
        request: caseDetail.request || {},
        media: caseDetail.media || [],
      });
    } else {
      clearResultData(caseDetail.error || "This inspection is still running. Results will appear as each stage completes.");
    }
    await loadActivity(runId);
  } catch (error) {
    if (requestId !== selectionRequest) return;
    clearResultData(error.message);
    setStatus("Unavailable", "error");
  }
}

function startProgressPolling(runId, onTerminalStatus = null, focusRun = true) {
  if (focusRun) {
    focusedRunId = runId;
    selectedRunId = runId;
    renderProgressPlaceholder("Waiting for workflow to start...");
  }
  if (progressPollTimers.has(runId)) clearInterval(progressPollTimers.get(runId));

  const poll = async () => {
    try {
      const response = await fetch(`/cases/${encodeURIComponent(runId)}/progress`, { headers: requestHeaders() });
      if (response.status === 404) return;
      if (!response.ok) throw new Error(await response.text());
      const progress = await response.json();
      activeProgress.set(runId, progress);
      if (focusedRunId === runId) renderProgress(progress);
      renderInspectionQueue();
      if (isTerminalStatus(progress.status)) {
        clearInterval(progressPollTimers.get(runId));
        progressPollTimers.delete(runId);
        if (onTerminalStatus) await onTerminalStatus(progress);
        else {
          await loadCases(false);
          if (focusedRunId === runId) await selectRun(runId);
        }
      }
    } catch (error) {
      if (focusedRunId === runId) renderProgressPlaceholder(error.message, "failed");
    }
  };

  poll();
  progressPollTimers.set(runId, setInterval(poll, 1000));
  renderInspectionQueue();
}

function stopProgressPolling(runId) {
  const timer = progressPollTimers.get(runId);
  if (timer) clearInterval(timer);
  progressPollTimers.delete(runId);
  activeProgress.delete(runId);
  renderInspectionQueue();
}

async function cancelRun(runId) {
  const response = await fetch(`/cases/${encodeURIComponent(runId)}/cancel`, {
    method: "PATCH",
    headers: requestHeaders(),
  });
  if (!response.ok) {
    setStatus("Cancel error", "error");
    if (focusedRunId === runId) clearResultData(await response.text());
    return;
  }
  const caseDetail = await response.json();
  activeProgress.set(runId, {
    run_id: runId,
    status: "canceled",
    current_stage: "canceled",
    message: caseDetail.error || "Inspection canceled by operator.",
    percent: 100,
    started_at: caseDetail.created_at,
    updated_at: caseDetail.completed_at || caseDetail.created_at,
    events: [],
  });
  stopProgressPolling(runId);
  await loadCases(false);
  if (focusedRunId === runId) await selectRun(runId);
}

async function clearActiveQueue() {
  const runIdsToClear = activeRunIds();
  clearQueueButton.disabled = true;
  clearQueueButton.textContent = "Clearing...";
  try {
    const response = await fetch("/cases/queue/clear", {
      method: "POST",
      headers: requestHeaders(),
    });
    if (!response.ok) throw new Error(await response.text());
    const payload = await response.json();
    const canceledRunIds = new Set(payload.canceled_runs || []);
    for (const runId of runIdsToClear) {
      if (canceledRunIds.has(runId)) {
        stopProgressPolling(runId);
        continue;
      }
      const cancelResponse = await fetch(`/cases/${encodeURIComponent(runId)}/cancel`, {
        method: "PATCH",
        headers: requestHeaders(),
      });
      stopProgressPolling(runId);
      if (cancelResponse.ok) canceledRunIds.add(runId);
    }
    await loadCases(false);
    if (focusedRunId && canceledRunIds.has(focusedRunId)) await selectRun(focusedRunId);
  } catch (error) {
    setStatus("Clear error", "error");
    clearResultData(error.message);
  } finally {
    clearQueueButton.textContent = "Clear";
    renderInspectionQueue();
  }
}

async function loadCases(selectFirst = true) {
  const response = await fetch("/cases?limit=50", { headers: requestHeaders() });
  if (!response.ok) {
    inspectionQueue.className = "inspection-queue muted";
    inspectionQueue.textContent = await response.text();
    return;
  }
  latestCases = await response.json();
  for (const entry of latestCases) {
    if (!isTerminalStatus(entry.status) && !progressPollTimers.has(entry.run_id)) startProgressPolling(entry.run_id, null, false);
  }
  renderInspectionQueue();
  if (selectFirst && !focusedRunId && latestCases.length) await selectRun(latestCases[0].run_id);
}

async function exportReport() {
  if (!latestInspectionPayload) return;
  exportButtons.forEach((button) => {
    button.disabled = true;
    button.dataset.originalLabel = button.textContent;
    button.textContent = "Preparing PDF...";
  });
  try {
    const response = await fetch("/reports/pdf", { method: "POST", headers: requestHeaders(true), body: JSON.stringify(latestInspectionPayload) });
    if (!response.ok) throw new Error(await response.text());
    const blob = await response.blob();
    const caseId = latestInspectionPayload.report.case.case_id || "inspection-report";
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${caseId}.pdf`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch (error) {
    setStatus("Export error", "error");
    formalReport.insertAdjacentHTML("afterbegin", `<div class="empty-report">${escapeHtml(error.message)}</div>`);
  } finally {
    exportButtons.forEach((button) => {
      button.textContent = button.dataset.originalLabel || "Export report";
      button.disabled = false;
    });
  }
}

document.querySelectorAll("[data-tab]").forEach((button) => {
  button.addEventListener("click", () => showTab(button.dataset.tab));
  button.addEventListener("keydown", (event) => {
    if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
    const tabs = [...document.querySelectorAll("[data-tab]")];
    const current = tabs.indexOf(button);
    const next = event.key === "ArrowRight" ? (current + 1) % tabs.length : (current - 1 + tabs.length) % tabs.length;
    showTab(tabs[next].dataset.tab, true);
  });
});

document.querySelectorAll("[data-open-tab]").forEach((button) => {
  button.addEventListener("click", () => showTab(button.dataset.openTab, true));
});

openDrawerButton.addEventListener("click", openDrawer);
closeDrawerButton.addEventListener("click", closeDrawer);
cancelInspectionButton.addEventListener("click", closeDrawer);
drawerOverlay.addEventListener("click", closeDrawer);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && inspectionDrawer.classList.contains("open")) closeDrawer();
});

dropZone.addEventListener("dragover", (event) => {
  event.preventDefault();
  dropZone.classList.add("dragover");
});
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
dropZone.addEventListener("drop", async (event) => {
  event.preventDefault();
  dropZone.classList.remove("dragover");
  await uploadMedia(event.dataTransfer.files[0]);
});
mediaUpload.addEventListener("change", async () => uploadMedia(mediaUpload.files[0]));

runSearch.addEventListener("input", renderInspectionQueue);
runStatusFilter.addEventListener("change", renderInspectionQueue);
refreshCasesButton.addEventListener("click", () => loadCases(false));
clearQueueButton.addEventListener("click", clearActiveQueue);
exportButtons.forEach((button) => button.addEventListener("click", exportReport));
sidebarToggleButton.addEventListener("click", () => setSidebarCollapsed(!sidebarCollapsed));
railSectionToggles.forEach((button) => {
  button.addEventListener("click", () => {
    const sectionName = button.dataset.toggleSection;
    const section = railSections.find((node) => node.dataset.railSection === sectionName);
    setRailSectionCollapsed(sectionName, !section?.classList.contains("collapsed"));
  });
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!validateMediaSelection()) return;
  setStatus("Queueing", "running");
  runButton.disabled = true;
  runButton.textContent = "Queueing...";
  setExportEnabled(false);
  const runId = makeRunId();
  const payload = { ...formPayload(), client_run_id: runId };
  try {
    const response = await fetch("/inspections", { method: "POST", headers: requestHeaders(true), body: JSON.stringify(payload) });
    if (!response.ok) throw new Error(await response.text());
    const responsePayload = await response.json();
    closeDrawer();
    showTab("overview");
    startProgressPolling(responsePayload.run_id, async (progress) => {
      await loadCases(false);
      if (progress.status === "failed") {
        if (focusedRunId === responsePayload.run_id) await selectRun(responsePayload.run_id);
        return;
      }
      if (focusedRunId === responsePayload.run_id) await selectRun(responsePayload.run_id);
    });
    await loadCases(false);
  } catch (error) {
    setStatus("Queue error", "error");
    uploadStatus.textContent = error.message;
    stopProgressPolling(runId);
  } finally {
    runButton.disabled = false;
    runButton.textContent = "Run Inspection";
  }
});

document.querySelectorAll("[data-review-status]").forEach((button) => {
  button.addEventListener("click", async () => {
    if (!selectedRunId) return;
    const originalLabel = button.textContent;
    button.disabled = true;
    button.textContent = "Saving...";
    try {
      const response = await fetch(`/cases/${encodeURIComponent(selectedRunId)}/review`, {
        method: "PATCH",
        headers: requestHeaders(true),
        body: JSON.stringify({ review_status: button.dataset.reviewStatus, reviewer_notes: reviewNotes.value, reviewed_by: "demo_reviewer" }),
      });
      if (!response.ok) throw new Error(await response.text());
      const caseDetail = await response.json();
      selectedCaseDetail = caseDetail;
      renderReviewSummary(caseDetail);
      await Promise.all([loadCases(false), loadActivity(selectedRunId)]);
    } catch (error) {
      reviewSummary.innerHTML = `<div class="empty-report">${escapeHtml(error.message)}</div>`;
    } finally {
      button.textContent = originalLabel;
      button.disabled = selectedCaseDetail?.status !== "completed";
    }
  });
});

showTab("overview");
renderWorkflowRoute();
applyRailSectionState();
setSidebarCollapsed(sidebarCollapsed);
loadCases();
