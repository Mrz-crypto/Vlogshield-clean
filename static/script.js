const form = document.getElementById("form");
const fileInput = document.getElementById("file");
const btn = document.getElementById("btn");
const status = document.getElementById("status");
const result = document.getElementById("result");

function showStatus(text, isError) {
  status.hidden = false;
  status.textContent = text;
  status.className = isError ? "error" : "";
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

  btn.disabled = true;
  result.hidden = true;
  showStatus("Scanning…");

  const body = new FormData();
  body.append("file", file);

  try {
    const res = await fetch("/scan", { method: "POST", body });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Scan failed");

    document.getElementById("score").textContent = data.score;
    document.getElementById("grade").textContent = data.grade;
    renderList(document.getElementById("risks"), data.risks, true);

    const safeWrap = document.getElementById("safe-wrap");
    const safe = data.safe_fields || [];
    safeWrap.hidden = safe.length === 0;
    renderList(document.getElementById("safe"), safe, false);

    result.hidden = false;
    status.hidden = true;
  } catch (err) {
    showStatus(err.message, true);
  } finally {
    btn.disabled = false;
  }
});
