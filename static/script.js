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

