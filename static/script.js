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
let previewUrl = "";

const analytics = {
  totalScans: 0,
  highRiskCount: 0,
  averageScore: 0
};

const MAX_FILE_SIZE = 16;
const ALLOWED_EXTENSIONS = ["jpg", "jpeg", "png", "tiff", "tif", "heic", "webp"];

function setMode(text, className = "") {
  modePill.textContent = text;
  modePill.className = `status-pill ${className}`.trim();
}

function showStatus(text, isError = false) {
  status.hidden = false;
  status.textContent = text;
  status.className = isError ? "status-message error" : "status-message";
  setMode(isError ? "Check file" : "Scanning", isError ? "error" : "scanning");
}

function hideStatus() {
  status.hidden = true;
  status.textContent = "";
  status.className = "status-message";
}

function formatFileSize(bytes) {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB"];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(k)), sizes.length - 1);
  return `${Math.round((bytes / Math.pow(k, i)) * 100) / 100} ${sizes[i]}`;
}

function validateFile(file) {
  if (file.size > MAX_FILE_SIZE * 1024 * 1024) {
    return `File size (${formatFileSize(file.size)}) exceeds maximum allowed size (${MAX_FILE_SIZE} MB).`;
  }

  const extension = file.name.split(".").pop().toLowerCase();
  if (!ALLOWED_EXTENSIONS.includes(extension)) {
    return "Please choose a JPG, PNG, TIFF, HEIC, or WebP image.";
  }

  return null;
}

function updateFileMeta() {
  const file = fileInput.files[0];
  if (!file) {
    fileMeta.hidden = true;
    fileMeta.textContent = "";
    setMode("Ready");
    updatePreview(null);
    return;
  }

  fileMeta.hidden = false;
  fileMeta.textContent = `${file.name} - ${formatFileSize(file.size)}`;
  setMode("Selected");
  updatePreview(file);
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
  result.hidden = true;
  hideStatus();
  updateFileMeta();
  setMode("Ready");

  const progressFill = document.getElementById("progressFill");
  if (progressFill) progressFill.style.width = "0%";
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
  strong.textContent = "No sensitive metadata detected";
  const small = document.createElement("small");
  small.textContent = "The scanner did not find known high-risk EXIF fields in this file.";
  li.append(strong, small);
  risks.appendChild(li);
}

function renderList(el, items, rich) {
  clearList(el);

  for (const item of items) {
    const li = document.createElement("li");

    if (rich) {
      li.className = `severity-${item.severity}`;
      const name = document.createElement("strong");
      name.textContent = item.name;
      const value = document.createElement("span");
      value.textContent = item.value;
      const advice = document.createElement("small");
      advice.textContent = item.advice;
      li.append(name, value, advice);
    } else {
      li.textContent = `${item.tag}: ${item.value}`;
    }

    el.appendChild(li);
  }
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
  const score = Math.min(data.score || 0, 100);
  const risks = data.risks || [];
  const safe = data.safe_fields || [];

  document.getElementById("score").textContent = score;
  updateGrade(data.grade || "Safe");
  document.getElementById("summary").textContent = data.summary?.headline || "Scan complete.";
  document.getElementById("nextStep").textContent = data.summary?.next_step || "Review the metadata before sharing.";
  document.getElementById("riskCount").textContent = String(risks.length);
  document.getElementById("progressFill").style.width = `${score}%`;

  if (risks.length) {
    renderList(document.getElementById("risks"), risks, true);
  } else {
    renderEmptyRisk();
  }

  const safeWrap = document.getElementById("safe-wrap");
  safeWrap.hidden = safe.length === 0;
  renderList(document.getElementById("safe"), safe, false);

  updateAnalytics(score);
  result.hidden = false;
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
    label.textContent = item.filename || "Uploaded image";
    score.className = "history-score";
    score.textContent = `${item.score}/100`;
    li.append(label, score);
    historyList.appendChild(li);
  }
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
    serverStats.querySelector("p").textContent =
      `Total: ${data.total} | Success: ${data.successful} | Failed: ${data.failed}`;
  } catch (_error) {
    serverStats.querySelector("p").textContent = "Stats unavailable.";
  }
}

function setDroppedFile(file) {
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
  result.hidden = true;
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
    btn.disabled = false;
  }
});

fileInput.addEventListener("change", () => {
  updateFileMeta();
  hideStatus();
});

clearBtn.addEventListener("click", resetScan);
refreshHistory();
refreshServerStats();
