const form = document.querySelector("#inspection-form");
const runButton = document.querySelector("#run-button");
const statusPill = document.querySelector("#status-pill");
const sampleStrip = document.querySelector("#sample-strip");
const dropZone = document.querySelector("#drop-zone");
const mediaUpload = document.querySelector("#media-upload");
const uploadStatus = document.querySelector("#upload-status");
const uploadPreview = document.querySelector("#upload-preview");
const videoUploadPreview = document.querySelector("#video-upload-preview");
const exportReportButton = document.querySelector("#export-report-button");
const refreshCasesButton = document.querySelector("#refresh-cases-button");
const caseHistory = document.querySelector("#case-history");
const reviewSummary = document.querySelector("#review-summary");
const reviewNotes = document.querySelector("#review-notes");
const progressPanel = document.querySelector("#progress-panel");

const caseTitle = document.querySelector("#case-title");
const metricSeverity = document.querySelector("#metric-severity");
const metricRepair = document.querySelector("#metric-repair");
const metricSchedule = document.querySelector("#metric-schedule");
const metricRisk = document.querySelector("#metric-risk");
const observationsBlock = document.querySelector("#observations");
const contextBlock = document.querySelector("#context");
const planBlock = document.querySelector("#plan");
const formalReport = document.querySelector("#formal-report");
let latestInspectionPayload = null;
let selectedRunId = null;
let progressPollTimer = null;

function makeRunId() {
  if (crypto.randomUUID) {
    return crypto.randomUUID().replaceAll("-", "");
  }
  return `run_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function setStatus(label, state) {
  statusPill.textContent = label;
  statusPill.className = `status-pill ${state}`;
}

function formPayload() {
  const data = new FormData(form);
  const imagePath = data.get("image_path").trim();
  const videoPath = data.get("video_path").trim();
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
    image_analyzer: data.get("image_analyzer"),
    embedding_backend: data.get("embedding_backend"),
    video_sampler: data.get("video_sampler"),
    video_frame_interval: Number(data.get("video_frame_interval") || 5),
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

function item(title, body, variant = "") {
  const className = variant ? `item ${variant}` : "item";
  return `<div class="${className}"><strong>${escapeHtml(title)}</strong><p>${escapeHtml(body)}</p></div>`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => {
      const result = String(reader.result || "");
      resolve(result.split(",", 2)[1] || "");
    });
    reader.addEventListener("error", () => reject(reader.error));
    reader.readAsDataURL(file);
  });
}

async function uploadImage(file) {
  if (!file || !file.type.startsWith("image/")) {
    uploadStatus.textContent = "Choose a JPG, PNG, or WEBP image.";
    return;
  }

  uploadStatus.textContent = `Uploading ${file.name}...`;
  const contentBase64 = await readFileAsBase64(file);
  const response = await fetch("/uploads/images", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      filename: file.name,
      content_base64: contentBase64,
    }),
  });
  if (!response.ok) {
    uploadStatus.textContent = await response.text();
    return;
  }

  const payload = await response.json();
  form.elements.image_path.value = payload.file_path;
  form.elements.video_path.value = "";
  if (form.elements.image_analyzer.value === "metadata") {
    form.elements.image_analyzer.value = "roboflow";
  }
  uploadPreview.src = payload.preview_url;
  uploadPreview.hidden = false;
  videoUploadPreview.hidden = true;
  videoUploadPreview.removeAttribute("src");
  uploadStatus.textContent = `${file.name} uploaded. Analyzer set to ${form.elements.image_analyzer.value}.`;
}

async function uploadVideo(file) {
  if (!file || !file.type.startsWith("video/")) {
    uploadStatus.textContent = "Choose an MP4, MOV, AVI, or MKV video.";
    return;
  }

  uploadStatus.textContent = `Uploading ${file.name}...`;
  const contentBase64 = await readFileAsBase64(file);
  const response = await fetch("/uploads/videos", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      filename: file.name,
      content_base64: contentBase64,
    }),
  });
  if (!response.ok) {
    uploadStatus.textContent = await response.text();
    return;
  }

  const payload = await response.json();
  form.elements.image_path.value = "";
  form.elements.video_path.value = payload.file_path;
  form.elements.video_sampler.value = "opencv";
  uploadPreview.hidden = true;
  uploadPreview.removeAttribute("src");
  videoUploadPreview.src = payload.preview_url;
  videoUploadPreview.hidden = false;
  uploadStatus.textContent = `${file.name} uploaded. OpenCV sampling enabled.`;
}

async function uploadMedia(file) {
  if (!file) return;
  if (file.type.startsWith("image/")) {
    await uploadImage(file);
    return;
  }
  if (file.type.startsWith("video/")) {
    await uploadVideo(file);
    return;
  }
  uploadStatus.textContent = "Choose an image or video file.";
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

function formatWindow(schedule) {
  if (!schedule) return "-";
  const start = schedule.recommended_window.start;
  const end = schedule.recommended_window.end;
  return `${start.slice(5, 16).replace("T", " ")} to ${end.slice(5, 16).replace("T", " ")}`;
}

function sentenceCase(value) {
  const text = String(value ?? "-").replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function formatDateTime(value) {
  if (!value) return "-";
  return String(value).slice(0, 19).replace("T", " ");
}

function renderRows(rows) {
  return rows
    .map(
      (row) => `
        <tr>
          ${row.map((cell) => `<td>${escapeHtml(cell)}</td>`).join("")}
        </tr>
      `,
    )
    .join("");
}

function stripMarkdownSyntax(text) {
  return String(text ?? "")
    .replace(/```[\s\S]*?```/g, "")
    .split("\n")
    .map((line) =>
      line
        .replace(/^\s{0,3}#{1,6}\s+/g, "")
        .replace(/^\s*[-*]\s+/g, "")
        .replace(/^\s*\d+\.\s+/g, "")
        .replace(/\*\*(.*?)\*\*/g, "$1")
        .replace(/__(.*?)__/g, "$1")
        .replace(/`([^`]+)`/g, "$1")
        .trim(),
    )
    .filter((line) => line && !/^[-=_]{3,}$/.test(line))
    .join("\n");
}

function renderProgress(progress) {
  const events = progress.events || [];
  const recentEvents = events.slice(-4).reverse();
  progressPanel.innerHTML = `
    <div class="progress-head">
      <div>
        <span>Live Progress</span>
        <strong>${escapeHtml(sentenceCase(progress.current_stage))}: ${escapeHtml(progress.message)}</strong>
      </div>
      <span>${escapeHtml(progress.percent)}%</span>
    </div>
    <div class="progress-track">
      <div class="progress-fill" style="width: ${Math.max(0, Math.min(100, Number(progress.percent || 0)))}%"></div>
    </div>
    <div class="progress-events">
      ${recentEvents
        .map(
          (event) =>
            `<div><strong>${escapeHtml(sentenceCase(event.stage))}</strong>${escapeHtml(event.message)}</div>`,
        )
        .join("")}
    </div>
  `;
}

function renderProgressPlaceholder(message) {
  progressPanel.innerHTML = `
    <div class="progress-head">
      <div>
        <span>Live Progress</span>
        <strong>${escapeHtml(message)}</strong>
      </div>
      <span>0%</span>
    </div>
    <div class="progress-track"><div class="progress-fill" style="width: 0%"></div></div>
  `;
}

function stopProgressPolling() {
  if (progressPollTimer) {
    clearInterval(progressPollTimer);
    progressPollTimer = null;
  }
}

function startProgressPolling(runId, onTerminalStatus = null) {
  stopProgressPolling();
  renderProgressPlaceholder("Waiting for workflow to start...");

  const poll = async () => {
    try {
      const response = await fetch(`/cases/${encodeURIComponent(runId)}/progress`);
      if (response.status === 404) return;
      if (!response.ok) throw new Error(await response.text());
      const progress = await response.json();
      renderProgress(progress);
      if (progress.status === "completed" || progress.status === "failed") {
        stopProgressPolling();
        if (onTerminalStatus) await onTerminalStatus(progress);
      }
    } catch (error) {
      renderProgressPlaceholder(error.message);
    }
  };

  poll();
  progressPollTimer = setInterval(poll, 1000);
}

function renderNarrative(text) {
  const cleaned = stripMarkdownSyntax(text);
  if (!cleaned) return "";
  const paragraphs = cleaned
    .split(/\n{2,}/)
    .map((paragraph) => paragraph.replace(/\n/g, " ").trim())
    .filter(Boolean);
  return paragraphs.map((paragraph) => `<p>${escapeHtml(paragraph)}</p>`).join("");
}

function renderFormalReport(payload) {
  latestInspectionPayload = payload;
  const report = payload.report;
  const schedule = report.schedule;
  const plan = report.maintenance_plan;
  const citations = report.severity.citations || [];
  const observations = report.observations || [];
  const tasks = plan.tasks || [];
  const precedents = plan.historical_precedents || [];

  formalReport.innerHTML = `
    <div class="report-title-block">
      <p class="eyebrow">Infrastructure Inspection Report</p>
      <h2>${escapeHtml(report.case.asset.name)}</h2>
      <p>${escapeHtml(report.case.asset.location)} · ${escapeHtml(report.case.asset.asset_type)} · ${escapeHtml(report.case.case_id)}</p>
      <div class="report-meta">
        <div><span>Severity</span><strong>${escapeHtml(sentenceCase(report.severity.severity))}</strong></div>
        <div><span>Urgency</span><strong>${escapeHtml(sentenceCase(report.severity.urgency))}</strong></div>
        <div><span>Repair</span><strong>${report.severity.repair_required ? "Required" : "Monitor"}</strong></div>
        <div><span>Schedule</span><strong>${escapeHtml(formatWindow(schedule))}</strong></div>
      </div>
    </div>

    <section class="report-section">
      <h4>Executive Summary</h4>
      <div class="report-two-column">
        <div class="report-callout">
          <span class="report-section-label">Recommended Action</span>
          ${escapeHtml(plan.recommended_action)}
        </div>
        <div class="report-callout">
          <span class="report-section-label">Estimated Duration</span>
          ${escapeHtml(plan.estimated_duration_hours)} hours
        </div>
      </div>
      <p>${escapeHtml(report.severity.rationale)}</p>
    </section>

    ${
      payload.rendered_report
        ? `
          <section class="report-section">
            <h4>Supervisor Narrative</h4>
            <div class="report-narrative">${renderNarrative(payload.rendered_report)}</div>
          </section>
        `
        : ""
    }

    <section class="report-section">
      <h4>Observed Conditions</h4>
      <table class="report-table">
        <thead><tr><th>ID</th><th>Defect</th><th>Source</th><th>Confidence</th><th>Description</th></tr></thead>
        <tbody>
          ${renderRows(
            observations.map((observation) => [
              observation.observation_id,
              sentenceCase(observation.defect_type),
              observation.source_modality,
              `${Math.round(observation.confidence * 100)}%`,
              observation.description,
            ]),
          )}
        </tbody>
      </table>
    </section>

    <section class="report-section">
      <h4>Guidance And Precedents</h4>
      <div class="report-two-column">
        <div>
          <span class="report-section-label">Retrieved Guidance</span>
          <ul class="report-list">
            ${
              citations.length
                ? citations.map((citation) => `<li>${escapeHtml(citation.title)} [${escapeHtml(citation.document_id)}]</li>`).join("")
                : "<li>No standards matched strongly enough.</li>"
            }
          </ul>
        </div>
        <div>
          <span class="report-section-label">Historical Repairs</span>
          <ul class="report-list">
            ${
              precedents.length
                ? precedents.map((precedent) => `<li>${escapeHtml(precedent.title)} [${escapeHtml(precedent.document_id)}]</li>`).join("")
                : "<li>No similar historical repairs found.</li>"
            }
          </ul>
        </div>
      </div>
    </section>

    <section class="report-section">
      <h4>Maintenance Plan</h4>
      <table class="report-table">
        <thead><tr><th>Task</th><th>Description</th><th>Hours</th></tr></thead>
        <tbody>
          ${renderRows(tasks.map((task) => [task.name, task.description, task.estimated_hours]))}
        </tbody>
      </table>
      <div class="report-two-column report-section">
        <div><span class="report-section-label">Materials</span><p>${escapeHtml(plan.materials.join(", ") || "None listed")}</p></div>
        <div><span class="report-section-label">Equipment</span><p>${escapeHtml(plan.equipment.join(", ") || "None listed")}</p></div>
      </div>
      <span class="report-section-label">Risks</span>
      <ul class="report-list">
        ${(plan.risks || []).map((risk) => `<li>${escapeHtml(risk)}</li>`).join("") || "<li>None listed.</li>"}
      </ul>
    </section>

    <section class="report-section">
      <h4>Repair Schedule</h4>
      ${
        schedule
          ? `
            <div class="report-meta">
              <div><span>Window</span><strong>${escapeHtml(formatWindow(schedule))}</strong></div>
              <div><span>Disruption</span><strong>${escapeHtml(schedule.disruption_score)}</strong></div>
              <div><span>Context Risk</span><strong>${escapeHtml(schedule.context_risk_score)}</strong></div>
              <div><span>Total Score</span><strong>${escapeHtml(schedule.total_score)}</strong></div>
            </div>
            <div class="report-two-column report-section">
              <div>
                <span class="report-section-label">Context</span>
                <ul class="report-list">${schedule.context_summary.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul>
              </div>
              <div>
                <span class="report-section-label">Tradeoffs</span>
                <ul class="report-list">${schedule.tradeoffs.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul>
              </div>
            </div>
          `
          : "<p>No repair window required. Continue monitoring.</p>"
      }
    </section>

  `;
  exportReportButton.disabled = false;
}

function renderReviewSummary(caseDetail) {
  selectedRunId = caseDetail.run_id;
  reviewNotes.value = caseDetail.reviewer_notes || "";
  renderList(
    reviewSummary,
    [
      item("Case", `${caseDetail.case_id || "Pending"} · ${caseDetail.status}`),
      item("Asset", `${caseDetail.asset_name} · ${caseDetail.location}`),
      item("Severity", `${sentenceCase(caseDetail.severity)} · repair ${caseDetail.repair_required ? "required" : "not required"}`),
      item("Review", `${sentenceCase(caseDetail.review_status)}${caseDetail.reviewed_by ? ` by ${caseDetail.reviewed_by}` : ""}`),
      item("Trace", caseDetail.workflow_trace_id || "No workflow trace recorded"),
    ],
    "Select a saved case.",
  );
}

async function loadCaseDetail(runId) {
  const response = await fetch(`/cases/${encodeURIComponent(runId)}`);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  const caseDetail = await response.json();
  renderReviewSummary(caseDetail);
  return caseDetail;
}

async function loadCases() {
  caseHistory.textContent = "Loading saved cases...";
  caseHistory.className = "case-history muted";
  const response = await fetch("/cases?limit=12");
  if (!response.ok) {
    caseHistory.textContent = await response.text();
    return;
  }
  const cases = await response.json();
  if (!cases.length) {
    caseHistory.textContent = "No saved cases yet.";
    return;
  }
  caseHistory.className = "case-history";
  caseHistory.innerHTML = cases
    .map(
      (item) => `
        <button type="button" class="case-row" data-run-id="${escapeHtml(item.run_id)}">
          <span>
            <strong>${escapeHtml(item.case_id || item.asset_id)}</strong>
            ${escapeHtml(item.asset_name)}
          </span>
          <span class="case-row-meta">
            ${escapeHtml(sentenceCase(item.review_status))} · ${escapeHtml(formatDateTime(item.completed_at || item.created_at))}
          </span>
        </button>
      `,
    )
    .join("");
  caseHistory.querySelectorAll(".case-row").forEach((button) => {
    button.addEventListener("click", async () => {
      caseHistory.querySelectorAll(".case-row").forEach((row) => row.classList.remove("selected"));
      button.classList.add("selected");
      try {
        await loadCaseDetail(button.dataset.runId);
      } catch (error) {
        reviewSummary.innerHTML = `<div class="empty-report">${escapeHtml(error.message)}</div>`;
      }
    });
  });
}

function renderResult(payload) {
  const report = payload.report;
  const schedule = report.schedule;
  caseTitle.textContent = report.case.case_id;
  metricSeverity.textContent = report.severity.severity;
  metricRepair.textContent = report.severity.repair_required ? "Required" : "Monitor";
  metricSchedule.textContent = formatWindow(schedule);
  metricRisk.textContent = schedule ? String(schedule.context_risk_score) : "-";

  renderList(
    observationsBlock,
    report.observations.map((observation) =>
      item(
        `${observation.defect_type} · ${Math.round(observation.confidence * 100)}%`,
        observation.description,
      ),
    ),
    "No observations.",
  );

  const contextRows = [];
  for (const citation of report.severity.citations || []) {
    contextRows.push(item(`Retrieved: ${citation.document_id}`, citation.title));
  }
  for (const summary of schedule?.context_summary || []) {
    contextRows.push(item("Schedule Context", summary, summary.includes("event") ? "warn" : ""));
  }
  renderList(contextBlock, contextRows, "No RAG or scheduling context.");

  const plan = report.maintenance_plan;
  const planRows = [
    item("Recommended Action", plan.recommended_action),
    item("Estimated Duration", `${plan.estimated_duration_hours} hours`),
    item("Materials", plan.materials.join(", ") || "None listed"),
    item("Equipment", plan.equipment.join(", ") || "None listed"),
    item("Risks", plan.risks.join(" ") || "None listed", "warn"),
  ];
  renderList(planBlock, planRows, "No maintenance plan.");

  renderFormalReport(payload);
}

async function loadSampleImages() {
  const response = await fetch("/sample-images?limit=10");
  if (!response.ok) return;
  const samples = await response.json();
  sampleStrip.innerHTML = samples
    .map(
      (sample) => `
        <button class="sample-card" type="button" data-path="${escapeHtml(sample.file_path)}">
          <img src="${escapeHtml(sample.preview_url)}" alt="${escapeHtml(sample.defect_type)} bridge defect" />
          <div><strong>${escapeHtml(sample.defect_type)}</strong>${escapeHtml(sample.severity_label)}</div>
        </button>
      `,
    )
    .join("");
  sampleStrip.querySelectorAll(".sample-card").forEach((card) => {
    card.addEventListener("click", () => {
      form.elements.image_path.value = card.dataset.path;
      form.elements.video_path.value = "";
      form.elements.image_analyzer.value = "metadata";
      uploadPreview.hidden = true;
      videoUploadPreview.hidden = true;
      uploadStatus.textContent = "Sample image selected from annotated dataset.";
    });
  });
}

dropZone.addEventListener("dragover", (event) => {
  event.preventDefault();
  dropZone.classList.add("dragover");
});

dropZone.addEventListener("dragleave", () => {
  dropZone.classList.remove("dragover");
});

dropZone.addEventListener("drop", async (event) => {
  event.preventDefault();
  dropZone.classList.remove("dragover");
  await uploadMedia(event.dataTransfer.files[0]);
});

mediaUpload.addEventListener("change", async () => {
  await uploadMedia(mediaUpload.files[0]);
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  setStatus("Running", "running");
  runButton.disabled = true;
  exportReportButton.disabled = true;
  latestInspectionPayload = null;
  formalReport.innerHTML = '<div class="empty-report">Running the inspection workflow...</div>';
  const runId = makeRunId();
  const payload = formPayload();
  payload.client_run_id = runId;
  startProgressPolling(runId, async (progress) => {
    await loadCases();
    const caseDetail = await loadCaseDetail(runId);
    if (progress.status === "failed") {
      setStatus("Error", "error");
      formalReport.innerHTML = `<div class="empty-report">${escapeHtml(caseDetail.error || progress.message)}</div>`;
      runButton.disabled = false;
      return;
    }
    if (caseDetail.report) {
      renderResult({
        run_id: caseDetail.run_id,
        report: caseDetail.report,
        rendered_report: caseDetail.rendered_report || "",
      });
      setStatus("Complete", "done");
      runButton.disabled = false;
    }
  });

  try {
    const response = await fetch("/inspections", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText);
    }
    const responsePayload = await response.json();
    selectedRunId = responsePayload.run_id;
    setStatus("Queued", "running");
  } catch (error) {
    setStatus("Error", "error");
    formalReport.innerHTML = `<div class="empty-report">${escapeHtml(error.message)}</div>`;
    stopProgressPolling();
    runButton.disabled = false;
  }
});

exportReportButton.addEventListener("click", async () => {
  if (!latestInspectionPayload) return;
  exportReportButton.disabled = true;
  const originalLabel = exportReportButton.textContent;
  exportReportButton.textContent = "Preparing PDF...";
  try {
    const response = await fetch("/reports/pdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(latestInspectionPayload),
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
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
    formalReport.insertAdjacentHTML(
      "afterbegin",
      `<div class="empty-report">${escapeHtml(error.message)}</div>`,
    );
  } finally {
    exportReportButton.textContent = originalLabel;
    exportReportButton.disabled = false;
  }
});

refreshCasesButton.addEventListener("click", async () => {
  await loadCases();
});

document.querySelectorAll("[data-review-status]").forEach((button) => {
  button.addEventListener("click", async () => {
    if (!selectedRunId) {
      reviewSummary.innerHTML = '<div class="empty-report">Select a saved case before reviewing.</div>';
      return;
    }
    const originalLabel = button.textContent;
    button.disabled = true;
    button.textContent = "Saving...";
    try {
      const response = await fetch(`/cases/${encodeURIComponent(selectedRunId)}/review`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          review_status: button.dataset.reviewStatus,
          reviewer_notes: reviewNotes.value,
          reviewed_by: "demo_reviewer",
        }),
      });
      if (!response.ok) {
        throw new Error(await response.text());
      }
      const caseDetail = await response.json();
      renderReviewSummary(caseDetail);
      await loadCases();
    } catch (error) {
      reviewSummary.innerHTML = `<div class="empty-report">${escapeHtml(error.message)}</div>`;
    } finally {
      button.textContent = originalLabel;
      button.disabled = false;
    }
  });
});

loadSampleImages();
loadCases();
