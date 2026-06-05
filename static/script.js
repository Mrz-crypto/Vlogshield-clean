const form = document.getElementById("form");
const fileInput = document.getElementById("file");
const btn = document.getElementById("btn");
const status = document.getElementById("status");
const result = document.getElementById("result");

// Analytics tracking
const analytics = {
  totalScans: 0,
  highRiskCount: 0,
  averageScore: 0
};

// Maximum file size in MB
const MAX_FILE_SIZE = 16;

function showStatus(text, isError) {
  status.hidden = false;
  status.textContent = text;
  status.className = isError ? "error" : "";
}

function formatFileSize(bytes) {
  if (bytes === 0) return '0 Bytes';
  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i];
}

function validateFile(file) {
  if (file.size > MAX_FILE_SIZE * 1024 * 1024) {
    return `File size (${formatFileSize(file.size)}) exceeds maximum allowed size (${MAX_FILE_SIZE}MB)`;
  }
  return null;
}

function renderList(el, items, rich) {
  el.innerHTML = "";
  for (const item of items) {
    const li = document.createElement("li");
    if (rich) {
      li.className = `severity-${item.severity}`;
      li.innerHTML = `<strong>${item.name}</strong>${item.value}<br><small>${item.advice}</small>`;
    } else {
      li.textContent = `${item.tag}: ${item.value}`;
    }
    el.appendChild(li);
  }
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const file = fileInput.files[0];
  if (!file) return;

  // Validate file before submission
  const validationError = validateFile(file);
  if (validationError) {
    showStatus(validationError, true);
    return;
  }

  btn.disabled = true;
  result.hidden = true;
  showStatus(`Scanning ${file.name} (${formatFileSize(file.size)})…`);

  const body = new FormData();
  body.append("file", file);

  try {
    const res = await fetch("/scan", { method: "POST", body });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Scan failed");

    // Update analytics
    analytics.totalScans++;
    if (data.score >= 50) analytics.highRiskCount++;
    analytics.averageScore = (analytics.averageScore * (analytics.totalScans - 1) + data.score) / analytics.totalScans;

    document.getElementById("score").textContent = data.score;
    document.getElementById("grade").textContent = data.grade;
    renderList(document.getElementById("risks"), data.risks, true);

    const safeWrap = document.getElementById("safe-wrap");
    const safe = data.safe_fields || [];
    safeWrap.hidden = safe.length === 0;
    renderList(document.getElementById("safe"), safe, false);

    // Display analytics
    const analyticsEl = document.getElementById("analytics");
    if (analyticsEl) {
      analyticsEl.textContent = `Scans: ${analytics.totalScans} | Avg Score: ${analytics.averageScore.toFixed(1)} | High Risk: ${analytics.highRiskCount}`;
    }

    result.hidden = false;
    status.hidden = true;
  } catch (err) {
    showStatus(err.message, true);
  } finally {
    btn.disabled = false;
  }
});
