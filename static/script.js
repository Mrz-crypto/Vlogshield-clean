const form = document.getElementById("form");
const fileInput = document.getElementById("file");
const btn = document.getElementById("btn");
const clearBtn = document.getElementById("clearBtn");
const status = document.getElementById("status");
const result = document.getElementById("result");
const fileMeta = document.getElementById("fileMeta");
const dropZone = document.getElementById("dropZone");
const modePill = document.getElementById("modePill");
const historyList = document.getElementById("historyList");
const serverStats = document.getElementById("serverStats");
const imagePreview = document.getElementById("imagePreview");
const maxUploadMb = document.getElementById("maxUploadMb");
const redactionPanel = document.getElementById("redactionPanel");
const redactionCanvas = document.getElementById("redactionCanvas");
const redactionCount = document.getElementById("redactionCount");
const hideModeBtn = document.getElementById("hideModeBtn");
const removeModeBtn = document.getElementById("removeModeBtn");
const blurStrength = document.getElementById("blurStrength");
const coverageMargin = document.getElementById("coverageMargin");
const undoRedactionBtn = document.getElementById("undoRedactionBtn");
const clearRedactionsBtn = document.getElementById("clearRedactionsBtn");
const downloadCleanBtn = document.getElementById("downloadCleanBtn");
const downloadRedactedBtn = document.getElementById("downloadRedactedBtn");
const actionList = document.getElementById("actionList");
const breakdown = document.getElementById("breakdown");
const copyReportBtn = document.getElementById("copyReportBtn");
const copyReportStatus = document.getElementById("copyReportStatus");
let previewUrl = "";
let redactionImage = null;
let redactionBoxes = [];
let pendingRedactionBoxes = [];
let draftBox = null;
let drawingBox = false;
let canvasScale = 1;
let redactionMode = "hide";
let lastScanResult = null;

const analytics = {
  totalScans: 0,
  highRiskCount: 0,
  averageScore: 0
};

let maxFileSizeMb = 16;
const ALLOWED_EXTENSIONS = ["jpg", "jpeg", "png", "tiff", "tif", "heic", "webp"];

function setMode(text, className = "") {
  modePill.textContent = text;
  modePill.className = `status-pill ${className}`.trim();
}

function showStatus(text, isError = false) {
  status.hidden = false;
  status.textContent = text;
  status.className = isError ? "status-message error" : "status-message";
  fileInput.setAttribute("aria-invalid", String(isError));
  setMode(isError ? "Check file" : "Scanning", isError ? "error" : "scanning");
}

function hideStatus() {
  status.hidden = true;
  status.textContent = "";
  status.className = "status-message";
  fileInput.setAttribute("aria-invalid", "false");
}

function clearCopyStatus() {
  copyReportStatus.textContent = "";
  copyReportStatus.className = "copy-status";
}

function formatFileSize(bytes) {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB"];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(k)), sizes.length - 1);
  return `${Math.round((bytes / Math.pow(k, i)) * 100) / 100} ${sizes[i]}`;
}

function validateFile(file) {
  if (file.size > maxFileSizeMb * 1024 * 1024) {
    return `File size (${formatFileSize(file.size)}) exceeds maximum allowed size (${maxFileSizeMb} MB).`;
  }

  const extension = file.name.split(".").pop().toLowerCase();
  if (extension === file.name.toLowerCase() || !ALLOWED_EXTENSIONS.includes(extension)) {
    return "Please choose a JPG, PNG, TIFF, HEIC, or WebP image.";
  }

  return null;
}

function updateSubmitState() {
  const file = fileInput.files[0];
  btn.disabled = !file || Boolean(validateFile(file));
}

function updateFileMeta() {
  const file = fileInput.files[0];
  if (!file) {
    fileMeta.hidden = true;
    fileMeta.textContent = "";
    setMode("Ready");
    updatePreview(null);
    resetRedactionTool();
    updateSubmitState();
    return;
  }

  fileMeta.hidden = false;
  fileMeta.textContent = `${file.name} - ${formatFileSize(file.size)}`;
  setMode("Selected");
  updatePreview(file);
  loadRedactionImage(file);
  updateSubmitState();
}

function updatePreview(file) {
  if (previewUrl) {
    URL.revokeObjectURL(previewUrl);
    previewUrl = "";
  }

  if (!file || !file.type.startsWith("image/")) {
    imagePreview.hidden = true;
    imagePreview.removeAttribute("src");
    dropZone.classList.remove("has-preview");
    return;
  }

  previewUrl = URL.createObjectURL(file);
  imagePreview.src = previewUrl;
  imagePreview.hidden = false;
  dropZone.classList.add("has-preview");
}

function resetScan() {
  form.reset();
  hideCurrentResult();
  hideStatus();
  resetRedactionTool();
  updateFileMeta();
  setMode("Ready");
}

function hideCurrentResult() {
  result.hidden = true;
  lastScanResult = null;
  clearCopyStatus();
  copyReportBtn.disabled = true;

  const progressFill = document.getElementById("progressFill");
  if (progressFill) progressFill.style.width = "0%";
}

function resetRedactionTool() {
  redactionImage = null;
  redactionBoxes = [];
  pendingRedactionBoxes = [];
  draftBox = null;
  drawingBox = false;
  setRedactionMode("hide");
  redactionPanel.hidden = true;
  redactionCanvas.removeAttribute("width");
  redactionCanvas.removeAttribute("height");
  updateRedactionControls();
}

function updateRedactionControls() {
  const count = redactionBoxes.length;
  redactionCount.textContent = `${count} hidden`;
  undoRedactionBtn.disabled = count === 0;
  clearRedactionsBtn.disabled = count === 0;
  downloadCleanBtn.disabled = !redactionImage;
  downloadRedactedBtn.disabled = !redactionImage || count === 0;
}

function setRedactionMode(mode) {
  redactionMode = mode;
  hideModeBtn.classList.toggle("active", mode === "hide");
  removeModeBtn.classList.toggle("active", mode === "remove");
  redactionCanvas.classList.toggle("remove-mode", mode === "remove");
}

function loadRedactionImage(file) {
  if (!file || !file.type.startsWith("image/")) {
    resetRedactionTool();
    return;
  }

  const reader = new FileReader();
  reader.onload = () => {
    const image = new Image();
    image.onload = () => {
      redactionImage = image;
      redactionBoxes = [];
      draftBox = null;
      redactionPanel.hidden = false;
      resizeRedactionCanvas();
      updateRedactionControls();
    };
    image.src = reader.result;
  };
  reader.readAsDataURL(file);
}

function loadRedactionImageFromSrc(src) {
  if (!src) return;

  const image = new Image();
  image.onload = () => {
    redactionImage = image;
    if (pendingRedactionBoxes.length) {
      redactionBoxes = pendingRedactionBoxes;
      pendingRedactionBoxes = [];
      redactionPanel.hidden = false;
      redactionPanel.open = true;
    }
    if (!redactionBoxes.length) {
      redactionPanel.hidden = false;
    }
    resizeRedactionCanvas();
    updateRedactionControls();
    updateEditablePreview();
  };
  image.src = src;
}

function resizeRedactionCanvas() {
  if (!redactionImage) return;

  const maxWidth = redactionPanel.clientWidth || 520;
  canvasScale = Math.min(1, maxWidth / redactionImage.naturalWidth);
  redactionCanvas.width = Math.max(1, Math.round(redactionImage.naturalWidth * canvasScale));
  redactionCanvas.height = Math.max(1, Math.round(redactionImage.naturalHeight * canvasScale));
  drawRedactionCanvas();
}

function drawRedactionCanvas() {
  if (!redactionImage) return;

  const ctx = redactionCanvas.getContext("2d");
  ctx.clearRect(0, 0, redactionCanvas.width, redactionCanvas.height);
  ctx.drawImage(redactionImage, 0, 0, redactionCanvas.width, redactionCanvas.height);

  for (const box of redactionBoxes) {
    paintRedactionBox(ctx, box, false);
  }

  if (draftBox) {
    paintRedactionBox(ctx, draftBox, true);
  }
}

function paintRedactionBox(ctx, box, isDraft) {
  const expanded = expandedRedactionBox(box);
  const x = expanded.x * canvasScale;
  const y = expanded.y * canvasScale;
  const width = expanded.width * canvasScale;
  const height = expanded.height * canvasScale;

  if (width < 2 || height < 2) return;

  ctx.fillStyle = isDraft ? "rgba(244, 183, 64, 0.45)" : "rgba(37, 199, 183, 0.24)";
  ctx.fillRect(x, y, width, height);
  ctx.strokeStyle = isDraft ? "#f4b740" : "#25c7b7";
  ctx.lineWidth = 2;
  ctx.strokeRect(x, y, width, height);
}

function normalizedBox(box) {
  const x = Math.min(box.x1, box.x2);
  const y = Math.min(box.y1, box.y2);
  return {
    x,
    y,
    width: Math.abs(box.x2 - box.x1),
    height: Math.abs(box.y2 - box.y1)
  };
}

function expandedRedactionBox(box) {
  const bounds = normalizedBox(box);
  const marginRatio = Number(coverageMargin.value || 0);
  const padding = Math.round(Math.max(bounds.width, bounds.height) * marginRatio);
  const x = Math.max(0, bounds.x - padding);
  const y = Math.max(0, bounds.y - padding);
  const right = Math.min(redactionImage.naturalWidth, bounds.x + bounds.width + padding);
  const bottom = Math.min(redactionImage.naturalHeight, bounds.y + bounds.height + padding);

  return {
    x,
    y,
    width: Math.max(0, right - x),
    height: Math.max(0, bottom - y)
  };
}

function findRedactionBoxIndex(point) {
  for (let index = redactionBoxes.length - 1; index >= 0; index -= 1) {
    const box = redactionBoxes[index];
    const x1 = Math.min(box.x1, box.x2);
    const y1 = Math.min(box.y1, box.y2);
    const x2 = Math.max(box.x1, box.x2);
    const y2 = Math.max(box.y1, box.y2);
    if (point.x >= x1 && point.x <= x2 && point.y >= y1 && point.y <= y2) {
      return index;
    }
  }
  return -1;
}

function canvasPoint(event) {
  const rect = redactionCanvas.getBoundingClientRect();
  const x = (event.clientX - rect.left) / canvasScale;
  const y = (event.clientY - rect.top) / canvasScale;
  return {
    x: Math.max(0, Math.min(redactionImage.naturalWidth, x)),
    y: Math.max(0, Math.min(redactionImage.naturalHeight, y))
  };
}

function finishDraftBox() {
  if (!draftBox) return;

  const width = Math.abs(draftBox.x2 - draftBox.x1);
  const height = Math.abs(draftBox.y2 - draftBox.y1);
  if (width >= 8 && height >= 8) {
    redactionBoxes.push(draftBox);
  }

  draftBox = null;
  drawingBox = false;
  updateRedactionControls();
  drawRedactionCanvas();
  updateEditablePreview();
}

function buildEditedImageDataUrl() {
  if (!redactionImage) return;

  const output = document.createElement("canvas");
  output.width = redactionImage.naturalWidth;
  output.height = redactionImage.naturalHeight;
  const ctx = output.getContext("2d");
  ctx.drawImage(redactionImage, 0, 0);

  for (const box of redactionBoxes) {
    const expanded = expandedRedactionBox(box);
    const x = Math.round(expanded.x);
    const y = Math.round(expanded.y);
    const width = Math.min(output.width - x, Math.round(expanded.width));
    const height = Math.min(output.height - y, Math.round(expanded.height));
    if (width < 2 || height < 2) continue;
    const imageData = ctx.getImageData(x, y, width, height);
    const scratch = document.createElement("canvas");
    scratch.width = width;
    scratch.height = height;
    const scratchCtx = scratch.getContext("2d");
    scratchCtx.putImageData(imageData, 0, 0);
    ctx.save();
    ctx.filter = `blur(${blurStrength.value}px)`;
    ctx.drawImage(scratch, x, y, width, height);
    ctx.restore();
    ctx.strokeStyle = "#25c7b7";
    ctx.lineWidth = Math.max(2, Math.round(output.width / 500));
    ctx.strokeRect(x, y, width, height);
  }
  return output.toDataURL("image/png");
}

function buildCleanImageDataUrl() {
  if (!redactionImage) return;

  const output = document.createElement("canvas");
  output.width = redactionImage.naturalWidth;
  output.height = redactionImage.naturalHeight;
  const ctx = output.getContext("2d");
  ctx.drawImage(redactionImage, 0, 0);
  return output.toDataURL("image/png");
}

function updateEditablePreview() {
  const edited = buildEditedImageDataUrl();
  if (!edited) return;

  const wrap = document.getElementById("autoRedactionWrap");
  const image = document.getElementById("autoRedactedImage");
  const download = document.getElementById("autoRedactionDownload");
  image.src = edited;
  download.href = edited;
  wrap.hidden = false;
}

function downloadRedactedImage() {
  const edited = buildEditedImageDataUrl();
  if (!edited) return;

  const link = document.createElement("a");
  link.href = edited;
  link.download = "vlogshield-redacted.png";
  link.click();
}

function downloadCleanImage() {
  const clean = buildCleanImageDataUrl();
  if (!clean) return;

  const link = document.createElement("a");
  link.href = clean;
  link.download = "vlogshield-clean.png";
  link.click();
}

function clearList(el) {
  el.replaceChildren();
}

function renderEmptyRisk() {
  const risks = document.getElementById("risks");
  clearList(risks);

  const li = document.createElement("li");
  li.className = "severity-LOW";
  const strong = document.createElement("strong");
  strong.textContent = "No high-risk privacy signals detected";
  const small = document.createElement("small");
  small.textContent = "Camera details, timestamps, and other embedded fields may still appear under More image details.";
  li.append(strong, small);
  risks.appendChild(li);
}

function renderList(el, items, rich) {
  clearList(el);
  const renderedItems = rich ? groupRiskItems(items) : items;

  for (const item of renderedItems) {
    const li = document.createElement("li");

    if (rich) {
      li.className = `severity-${item.severity}`;
      const name = document.createElement("strong");
      name.textContent = item.source === "visual" ? `${item.name} (visual)` : item.name;
      const value = document.createElement("span");
      value.textContent = item.value;
      const advice = document.createElement("small");
      advice.textContent = item.advice;
      li.append(name, value, advice);
    } else {
      li.textContent = `${item.tag}: ${formatMetadataValue(item.value)}`;
    }

    el.appendChild(li);
  }
}

function renderActionList(items) {
  clearList(actionList);
  actionList.hidden = !items.length;

  for (const item of items) {
    const li = document.createElement("li");
    li.textContent = item;
    actionList.appendChild(li);
  }
}

function renderBreakdown(item = {}) {
  breakdown.replaceChildren();
  const entries = [
    ["Metadata", item.metadata || 0],
    ["Visual", item.visual || 0],
    ["Critical", item.critical || 0],
    ["High", item.high || 0],
    ["Medium", item.medium || 0],
    ["Low", item.low || 0]
  ];

  for (const [label, value] of entries) {
    const chip = document.createElement("span");
    chip.className = "breakdown-pill";
    chip.textContent = `${label}: ${value}`;
    breakdown.appendChild(chip);
  }

  breakdown.hidden = false;
}

function groupRiskItems(items) {
  const grouped = new Map();

  for (const item of items) {
    const key = `${item.source || "metadata"}:${item.name}:${item.severity}:${item.advice}`;
    if (!grouped.has(key)) {
      grouped.set(key, { ...item, count: 1 });
      continue;
    }
    grouped.get(key).count += 1;
  }

  return Array.from(grouped.values()).map((item) => {
    if (item.count <= 1) return item;
    return {
      ...item,
      name: `${item.name} (${item.count} found)`,
    };
  });
}

function formatMetadataValue(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function gradeClass(grade) {
  return grade.toLowerCase().replace(/\s+/g, "-");
}

function updateGrade(grade) {
  const gradeEl = document.getElementById("grade");
  gradeEl.textContent = grade;
  gradeEl.className = `grade-pill ${gradeClass(grade)}`;
}

function updateAnalytics(score) {
  analytics.totalScans += 1;
  if (score >= 50) analytics.highRiskCount += 1;
  analytics.averageScore = (
    (analytics.averageScore * (analytics.totalScans - 1) + score) /
    analytics.totalScans
  );

  const analyticsEl = document.getElementById("analytics");
  analyticsEl.querySelector("p").textContent =
    `Scans: ${analytics.totalScans} | Avg score: ${analytics.averageScore.toFixed(1)} | High risk: ${analytics.highRiskCount}`;
}

function renderResult(data) {
  lastScanResult = data;
  copyReportBtn.disabled = false;
  clearCopyStatus();

  const score = Math.min(data.score || 0, 100);
  const risks = data.risks || [];
  const safe = data.safe_fields || [];
  const visualScan = data.visual_scan || {};

  document.getElementById("score").textContent = score;
  updateGrade(data.grade || "Safe");
  document.getElementById("summary").textContent = data.summary?.headline || "Scan complete.";
  document.getElementById("nextStep").textContent = data.summary?.next_step || "Review the metadata before sharing.";
  document.getElementById("riskCount").textContent = String(risks.length);
  document.getElementById("progressFill").style.width = `${score}%`;
  renderBreakdown(data.risk_breakdown || {});
  renderActionList(data.actions || []);
  renderServerPreview(visualScan);
  renderAutoRedaction(visualScan);
  syncDetectedRedactions(risks);

  if (risks.length) {
    renderList(document.getElementById("risks"), risks, true);
  } else {
    renderEmptyRisk();
  }

  const safeWrap = document.getElementById("safe-wrap");
  safeWrap.hidden = safe.length === 0;
  safeWrap.open = safe.length > 0;
  renderList(document.getElementById("safe"), safe, false);

  updateAnalytics(score);
  result.hidden = false;
}

function buildScanReport(data) {
  const lines = [
    "VlogShield scan report",
    `Score: ${data.score || 0}/100 (${data.grade || "Unknown"})`,
    "",
    "Summary:",
    data.summary?.headline || "Scan complete.",
    data.summary?.next_step || "Review the metadata before sharing.",
    "",
    "Breakdown:",
  ];
  const breakdownData = data.risk_breakdown || {};
  lines.push(`Metadata: ${breakdownData.metadata || 0}`);
  lines.push(`Visual: ${breakdownData.visual || 0}`);
  lines.push(`Critical: ${breakdownData.critical || 0}`);
  lines.push(`High: ${breakdownData.high || 0}`);
  lines.push(`Medium: ${breakdownData.medium || 0}`);
  lines.push(`Low: ${breakdownData.low || 0}`);

  lines.push("", "Detected risks:");
  const risks = groupRiskItems(data.risks || []);
  if (risks.length) {
    for (const risk of risks) {
      const source = risk.source === "visual" ? "visual" : "metadata";
      lines.push(`- ${risk.name} [${source}, ${risk.severity}]: ${risk.value}`);
    }
  } else {
    lines.push("- None detected");
  }

  lines.push("", "Recommended actions:");
  for (const action of data.actions || []) {
    lines.push(`- ${action}`);
  }

  lines.push("", "Redaction settings:");
  lines.push(`- Blur: ${blurStrength.options[blurStrength.selectedIndex].text}`);
  lines.push(`- Coverage: ${coverageMargin.options[coverageMargin.selectedIndex].text}`);

  lines.push("", "Privacy guards:");
  for (const guard of data.privacy_guards || []) {
    lines.push(`- ${guard}`);
  }

  return lines.join("\n");
}

function fallbackCopy(text) {
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand("copy");
  textarea.remove();
  if (!copied) throw new Error("Copy failed");
}

async function copyScanReport() {
  if (!lastScanResult) return;

  const text = buildScanReport(lastScanResult);
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
    } else {
      fallbackCopy(text);
    }
    copyReportStatus.textContent = "Copied";
    copyReportStatus.className = "copy-status success";
  } catch (_error) {
    copyReportStatus.textContent = "Copy failed";
    copyReportStatus.className = "copy-status error";
  }
}

function renderServerPreview(visualScan) {
  if (!visualScan.preview_image) return;

  imagePreview.src = visualScan.preview_image;
  imagePreview.hidden = false;
  dropZone.classList.add("has-preview");
  loadRedactionImageFromSrc(visualScan.preview_image);
}

function syncDetectedRedactions(risks) {
  const detectedBoxes = risks
    // Body-content heuristics are review-only: do not turn an uncertain,
    // broad region into an automatic blur box. Faces and plates remain
    // editable redactions.
    .filter((risk) => risk.source === "visual" && risk.box && risk.auto_redact !== false)
    .map((risk) => ({
      x1: risk.box.x,
      y1: risk.box.y,
      x2: risk.box.x + risk.box.width,
      y2: risk.box.y + risk.box.height
    }));

  if (!detectedBoxes.length) return;

  if (!redactionImage) {
    pendingRedactionBoxes = detectedBoxes;
    return;
  }

  redactionBoxes = detectedBoxes;
  redactionPanel.hidden = false;
  redactionPanel.open = true;
  updateRedactionControls();
  drawRedactionCanvas();
}

function renderAutoRedaction(visualScan) {
  const wrap = document.getElementById("autoRedactionWrap");
  const image = document.getElementById("autoRedactedImage");
  const download = document.getElementById("autoRedactionDownload");

  if (!visualScan.redacted_image) {
    wrap.hidden = true;
    image.removeAttribute("src");
    download.removeAttribute("href");
    return;
  }

  image.src = visualScan.redacted_image;
  download.href = visualScan.redacted_image;
  wrap.hidden = false;
}

function renderHistory(items) {
  clearList(historyList);

  if (!items.length) {
    const empty = document.createElement("li");
    empty.textContent = "No scans yet.";
    historyList.appendChild(empty);
    return;
  }

  for (const item of items.slice(-5).reverse()) {
    const li = document.createElement("li");
    const label = document.createElement("span");
    const score = document.createElement("span");
    const fileType = item.file_type ? item.file_type.toUpperCase() : "IMAGE";
    const riskText = item.risk_count === 1 ? "1 risk" : `${item.risk_count || 0} risks`;
    label.textContent = `${fileType} scan - ${item.grade || "Complete"} - ${riskText}`;
    score.className = "history-score";
    score.textContent = `${item.score}/100`;
    li.append(label, score);
    historyList.appendChild(li);
  }
}

function formatPercent(value) {
  return `${Math.round((value || 0) * 100)}%`;
}

function renderServerStats(data) {
  const backend = data.storage_backend || "memory";
  const average = Number.isFinite(data.average_score) ? Number(data.average_score).toFixed(1) : "0.0";
  const stored = data.stored_scans || 0;
  const highRisk = data.high_risk_scans || 0;

  serverStats.querySelector("p").textContent =
    `Backend: ${backend} | Stored: ${stored} | Avg: ${average} | High risk: ${highRisk} | Success: ${formatPercent(data.success_rate)}`;
}

async function refreshHistory() {
  try {
    const res = await fetch("/history");
    if (!res.ok) return;
    const data = await res.json();
    renderHistory(data.scans || []);
  } catch (_error) {
    renderHistory([]);
  }
}

async function refreshServerStats() {
  try {
    const res = await fetch("/stats");
    if (!res.ok) return;
    const data = await res.json();
    if (Number.isFinite(data.max_upload_mb) && maxUploadMb) {
      maxFileSizeMb = data.max_upload_mb;
      maxUploadMb.textContent = String(data.max_upload_mb);
      updateSubmitState();
    }
    renderServerStats(data);
  } catch (_error) {
    serverStats.querySelector("p").textContent = "Stats unavailable.";
  }
}

function setDroppedFile(file) {
  hideCurrentResult();
  const dataTransfer = new DataTransfer();
  dataTransfer.items.add(file);
  fileInput.files = dataTransfer.files;
  updateFileMeta();
  hideStatus();
}

dropZone.addEventListener("dragover", (event) => {
  event.preventDefault();
  dropZone.classList.add("is-dragging");
});

dropZone.addEventListener("dragleave", () => {
  dropZone.classList.remove("is-dragging");
});

dropZone.addEventListener("drop", (event) => {
  event.preventDefault();
  dropZone.classList.remove("is-dragging");

  const file = event.dataTransfer.files[0];
  if (!file) return;

  const validationError = validateFile(file);
  if (validationError) {
    showStatus(validationError, true);
    return;
  }

  setDroppedFile(file);
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = fileInput.files[0];
  if (!file) return;

  const validationError = validateFile(file);
  if (validationError) {
    showStatus(validationError, true);
    return;
  }

  btn.disabled = true;
  hideCurrentResult();
  showStatus(`Scanning ${file.name} (${formatFileSize(file.size)})...`);

  const body = new FormData();
  body.append("file", file);

  try {
    const res = await fetch("/scan", { method: "POST", body });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Scan failed");

    renderResult(data);
    hideStatus();
    setMode("Complete");
    await refreshHistory();
    await refreshServerStats();
  } catch (err) {
    showStatus(err.message, true);
  } finally {
    updateSubmitState();
  }
});

fileInput.addEventListener("change", () => {
  hideCurrentResult();
  updateFileMeta();
  hideStatus();
});

clearBtn.addEventListener("click", resetScan);

redactionCanvas.addEventListener("pointerdown", (event) => {
  if (!redactionImage) return;
  const point = canvasPoint(event);

  if (redactionMode === "remove") {
    const index = findRedactionBoxIndex(point);
    if (index >= 0) {
      redactionBoxes.splice(index, 1);
      updateRedactionControls();
      drawRedactionCanvas();
      updateEditablePreview();
    }
    return;
  }

  redactionCanvas.setPointerCapture(event.pointerId);
  drawingBox = true;
  draftBox = { x1: point.x, y1: point.y, x2: point.x, y2: point.y };
  drawRedactionCanvas();
});

redactionCanvas.addEventListener("pointermove", (event) => {
  if (!drawingBox || !draftBox) return;
  const point = canvasPoint(event);
  draftBox.x2 = point.x;
  draftBox.y2 = point.y;
  drawRedactionCanvas();
});

redactionCanvas.addEventListener("pointerup", finishDraftBox);
redactionCanvas.addEventListener("pointercancel", finishDraftBox);

undoRedactionBtn.addEventListener("click", () => {
  redactionBoxes.pop();
  updateRedactionControls();
  drawRedactionCanvas();
  updateEditablePreview();
});

clearRedactionsBtn.addEventListener("click", () => {
  redactionBoxes = [];
  updateRedactionControls();
  drawRedactionCanvas();
  updateEditablePreview();
});

hideModeBtn.addEventListener("click", () => setRedactionMode("hide"));
removeModeBtn.addEventListener("click", () => setRedactionMode("remove"));
blurStrength.addEventListener("change", updateEditablePreview);
coverageMargin.addEventListener("change", () => {
  drawRedactionCanvas();
  updateEditablePreview();
});
copyReportBtn.addEventListener("click", copyScanReport);
downloadCleanBtn.addEventListener("click", downloadCleanImage);
downloadRedactedBtn.addEventListener("click", downloadRedactedImage);

window.addEventListener("resize", resizeRedactionCanvas);
updateSubmitState();
refreshHistory();
refreshServerStats();
