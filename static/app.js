const form = document.querySelector("#uploadForm");
const input = document.querySelector("#harfile");
const dropTarget = document.querySelector("#dropTarget");
const fileLabel = document.querySelector("#fileLabel");
const fileError = document.querySelector("#fileError");
const results = document.querySelector("#results");
const errorBox = document.querySelector("#errorBox");
const errorMessage = document.querySelector("#errorMessage");
const submitBtn = document.querySelector("#submitBtn");
const submitLabel = document.querySelector("#submitLabel");
const progressRail = document.querySelector("#progressRail");

const STEP_IDS = ["step-upload", "step-detect", "step-correlate", "step-generate"];

input.addEventListener("change", () => {
  fileLabel.textContent = input.files[0]?.name || "Drop or choose a HAR file";
  clearFileError();
});

["dragover", "dragenter"].forEach((evt) => {
  dropTarget.addEventListener(evt, (event) => {
    event.preventDefault();
    dropTarget.classList.add("is-dragover");
  });
});

["dragleave", "dragend"].forEach((evt) => {
  dropTarget.addEventListener(evt, () => dropTarget.classList.remove("is-dragover"));
});

dropTarget.addEventListener("drop", (event) => {
  event.preventDefault();
  dropTarget.classList.remove("is-dragover");
  const file = event.dataTransfer?.files?.[0];
  if (file) {
    input.files = event.dataTransfer.files;
    fileLabel.textContent = file.name;
    clearFileError();
  }
});

function clearFileError() {
  dropTarget.classList.remove("is-invalid");
  fileError.classList.add("hidden");
}

function showFileError() {
  dropTarget.classList.add("is-invalid");
  fileError.classList.remove("hidden");
  setTimeout(() => dropTarget.classList.remove("is-invalid"), 360);
}

function setStepper(state) {
  // state: "idle" | "working" | "done"
  STEP_IDS.forEach((id, index) => {
    const el = document.getElementById(id);
    el.classList.remove("is-active", "is-done");
    if (state === "idle") {
      if (index === 0) el.classList.add("is-active");
    } else if (state === "working") {
      el.classList.add("is-done");
      if (index === STEP_IDS.length - 1) el.classList.remove("is-done");
    } else if (state === "done") {
      el.classList.add("is-done");
    }
  });
  if (state === "working") {
    document.getElementById(STEP_IDS[STEP_IDS.length - 1]).classList.add("is-active");
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  errorBox.classList.add("hidden");
  results.classList.add("hidden");

  if (!input.files.length) {
    showFileError();
    return;
  }
  clearFileError();

  const formData = new FormData();
  formData.append("harfile", input.files[0]);
  formData.append("threads", document.querySelector("#threads").value);
  formData.append("loops", document.querySelector("#loops").value);
  formData.append("ramp", document.querySelector("#ramp").value);
  formData.append("clearCookies", document.querySelector("#clearCookies").checked ? "true" : "false");

  submitBtn.disabled = true;
  submitBtn.classList.add("is-loading");
  submitLabel.textContent = "Analyzing HAR...";
  progressRail.classList.remove("hidden");
  setStepper("working");

  try {
    const response = await fetch("/api/convert", {
      method: "POST",
      body: formData,
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Unable to generate the JMeter script.");
    }
    renderResults(payload);
    setStepper("done");
  } catch (error) {
    showError(error.message);
    setStepper("idle");
  } finally {
    submitBtn.disabled = false;
    submitBtn.classList.remove("is-loading");
    submitLabel.textContent = "Generate JMeter script";
    progressRail.classList.add("hidden");
  }
});

function renderResults(payload) {
  const score = Number(payload.readinessScore || 0);
  document.querySelector("#readinessScore").textContent = `${score}%`;
  document.querySelector("#scoreBar").style.width = `${score}%`;
  document.querySelector("#qualityText").textContent = qualityText(score, payload);

  const gate = payload.qualityGate || {};
  const gateBadge = document.querySelector("#qualityGateBadge");
  if (gateBadge) {
    gateBadge.textContent = gate.label || (gate.passed ? "Passed" : "Needs review");
    gateBadge.className = "pill " + (gate.passed ? "pill-high" : "pill-medium");
  }

  document.querySelector("#samplerCount").textContent = payload.samplers;
  document.querySelector("#transactionCount").textContent = payload.transactions;
  document.querySelector("#parameterCount").textContent = payload.parameters.length;
  document.querySelector("#correlationCount").textContent = payload.correlations.length;
  document.querySelector("#filteredCount").textContent = payload.filteredEntries;
  document.querySelector("#avgTime").textContent = payload.avgResponseTimeMs;

  document.querySelector("#categoryBars").innerHTML = categoryRows(payload.categoryScores);

  const correctionsSection = document.querySelector("#autoCorrectionsSection");
  const corrections = payload.autoCorrections || [];
  if (correctionsSection) {
    if (corrections.length) {
      document.querySelector("#autoCorrectionsList").innerHTML = autoCorrectionRows(corrections);
      correctionsSection.classList.remove("hidden");
    } else {
      correctionsSection.classList.add("hidden");
    }
  }

  const checklistEl = document.querySelector("#validationChecklist");
  if (checklistEl) {
    checklistEl.innerHTML = validationChecklistRows(payload.validationChecklist || []);
  }

  const enterpriseSection = document.querySelector("#enterpriseSection");
  const apps = payload.enterpriseApps || [];
  if (apps.length) {
    document.querySelector("#appBadges").innerHTML = apps.map((name) => `<span class="app-badge">${platformIcon()}${escapeHtml(name)}</span>`).join("");
    enterpriseSection.classList.remove("hidden");
  } else {
    enterpriseSection.classList.add("hidden");
  }

  document.querySelector("#parameterList").innerHTML = parameterRows(payload.parameters);
  document.querySelector("#correlationList").innerHTML = correlationRows(payload.correlations);
  document.querySelector("#trafficProfile").innerHTML = trafficRows(payload);
  document.querySelector("#reviewNotes").innerHTML = noteRows(payload.reviewNotes);
  document.querySelector("#endpointList").innerHTML = waterfallRows(payload.endpoints);

  const downloadFile = payload.download || payload.jmx;
  document.querySelector("#downloadLink").href = `/download/${downloadFile}`;
  document.querySelector("#downloadTitle").textContent = "Download your complete package (.zip)";
  document.querySelector("#downloadNote").textContent =
    "Includes the .jmx, CSV test data, and a README plus full correlation/parameterization/replay reports -- unzip everything into one folder before opening the .jmx in JMeter.";

  const reportsList = document.querySelector("#reportsList");
  if (reportsList) {
    const reports = payload.reports || [];
    reportsList.innerHTML = reports.length
      ? reports.map((r) => `<li>${escapeHtml(r.label || r.filename)}</li>`).join("")
      : "";
  }

  document.querySelector("#generatedAt").textContent = `Generated ${payload.generatedAt} -- ${payload.testName}`;
  results.classList.remove("hidden");
  results.scrollIntoView({ behavior: "smooth", block: "start" });
}

function autoCorrectionRows(items) {
  return items
    .map(
      (item) => `
      <div class="checklist-item is-ok">
        ${okIcon()}
        <span><strong>[${escapeHtml(item.rule)}]</strong> ${escapeHtml(item.action)} -- ${escapeHtml(item.detail)}</span>
      </div>`
    )
    .join("");
}

function validationChecklistRows(items) {
  if (!items.length) return "";
  return items
    .map(
      (v) => `
      <div class="checklist-item ${v.passed ? "is-ok" : "is-warn"}">
        ${v.passed ? okIcon() : warnIcon()}
        <span><strong>${escapeHtml(v.check)}</strong>${v.detail ? " -- " + escapeHtml(v.detail) : ""}</span>
      </div>`
    )
    .join("");
}

function qualityText(score, payload) {
  if (score >= 85) {
    return `Clean capture: ${payload.filteredEntries} browser-noise request(s) removed, dynamic values wired into the JMX.`;
  }
  if (score >= 65) {
    return "Good draft: open in JMeter, review the correlation extractors, then confirm workload and assertions.";
  }
  return "Needs review: capture the full login and business flow, then confirm dynamic values before running load.";
}

function categoryRows(scores) {
  if (!scores) return "";
  const labels = {
    correlationCompleteness: "Correlation",
    parameterizationCompleteness: "Parameterization",
    authenticationHandling: "Authentication",
    maintainability: "Maintainability",
    performanceReadiness: "Performance readiness",
  };
  return Object.entries(labels)
    .map(([key, label]) => {
      const value = Number(scores[key] ?? 0);
      const band = value >= 80 ? "band-high" : value >= 50 ? "band-mid" : "band-low";
      return `
        <div class="category-row">
          <span class="cat-label">${escapeHtml(label)}</span>
          <span class="cat-track"><span class="${band}" style="width:${value}%"></span></span>
          <span class="cat-value">${value}%</span>
        </div>`;
    })
    .join("");
}

function confidencePill(level) {
  const key = String(level || "").toLowerCase();
  const cls = key === "high" ? "pill-high" : key === "medium" ? "pill-medium" : key === "low" ? "pill-low" : "pill-neutral";
  return `<span class="pill ${cls}">${escapeHtml(level || "n/a")}</span>`;
}

function parameterRows(items) {
  if (!items.length) {
    return emptyRow("No parameters detected", "The script is still generated; review dynamic values manually before load execution.");
  }
  return items
    .slice(0, 8)
    .map(
      (item) => `
      <div class="row">
        <div class="row-top">
          <code>\${${escapeHtml(item.name)}}</code>
          ${confidencePill(item.confidence)}
          ${classificationPill(item.classification, "Business Input")}
          ${item.csv_bound ? '<span class="pill pill-neutral">CSV</span>' : '<span class="pill pill-neutral">UDV</span>'}
        </div>
        <span class="meta">${escapeHtml(item.reason)} -- ${item.occurrences} occurrence(s)</span>
      </div>`
    )
    .join("");
}

function classificationPill(code, label) {
  if (!code) return "";
  const CLASS_STYLES = {
    A: "pill-classification-a",
    B: "pill-classification-b",
    C: "pill-classification-c",
    D: "pill-classification-d",
    E: "pill-classification-e",
    F: "pill-neutral",
  };
  const cls = CLASS_STYLES[code] || "pill-neutral";
  return `<span class="pill ${cls}" title="${escapeHtml(label || code)}">${escapeHtml(code)} \u00b7 ${escapeHtml(label || code)}</span>`;
}

function correlationRows(items) {
  if (!items.length) {
    return emptyRow("No correlations detected", "Review login/session requests manually -- dynamic tokens may need a manual extractor.");
  }
  return items
    .slice(0, 8)
    .map((item) => {
      const consumers = item.consumers || [];
      const consumerText = consumers.length
        ? `consumed by ${consumers.length} request(s): ${consumers.slice(0, 2).map(escapeHtml).join(", ")}${consumers.length > 2 ? ` (+${consumers.length - 2} more)` : ""}`
        : "";
      return `
      <div class="row">
        <div class="row-top">
          <code>\${${escapeHtml(item.variable)}}</code>
          ${confidencePill(item.confidence)}
          ${classificationPill(item.classification, item.classificationLabel)}
          <span class="pill pill-neutral">${item.extractor === "json" ? "JSON Extractor" : item.extractor === "css" ? "CSS Selector" : "Regex Extractor"}</span>
        </div>
        <span class="meta">${escapeHtml(item.reason || item.field)}</span>
        <span class="meta">origin: ${escapeHtml(item.origin || item.source_sampler)}${consumerText ? " -- " + consumerText : ""}</span>
      </div>`;
    })
    .join("");
}

function trafficRows(payload) {
  const methodText = Object.entries(payload.methods || {}).map(([n, c]) => `${n}: ${c}`).join(", ") || "No methods";
  const domainText = Object.entries(payload.domains || {}).map(([n, c]) => `${n}: ${c}`).join(", ") || "No domains";
  const statusText = Object.entries(payload.statuses || {}).map(([n, c]) => `${n}: ${c}`).join(", ") || "No statuses";
  return [
    ["Request filter", `${payload.filteredEntries} removed from ${payload.totalEntries} HAR entries`],
    ["Method mix", methodText],
    ["Domains", domainText],
    ["Status codes", statusText],
    ["Users", `${payload.threads} concurrent`],
    ["Iterations", `${payload.loops} per user`],
    ["Ramp-up", `${payload.ramp} seconds`],
    ["Cookie policy", payload.clearCookies === true || payload.clearCookies === "true" ? "Clear each iteration" : "Keep across iterations"],
  ]
    .map(([title, value]) => `<div class="row"><span class="row-top"><strong>${escapeHtml(title)}</strong></span><span class="meta">${escapeHtml(value)}</span></div>`)
    .join("");
}

function noteRows(notes) {
  if (!notes || !notes.length) {
    return `<div class="checklist-item is-ok">${okIcon()}<span>No critical review notes -- still confirm the workload model and assertions in JMeter before a full run.</span></div>`;
  }
  return notes.map((note) => `<div class="checklist-item is-warn">${warnIcon()}<span>${escapeHtml(note)}</span></div>`).join("");
}

function waterfallRows(items) {
  if (!items.length) {
    return emptyRow("No endpoints detected", "");
  }
  const maxTime = Math.max(1, ...items.map((item) => Number(item.timeMs) || 0));
  let lastTransaction = null;
  return items
    .map((item) => {
      const showTxn = item.transaction !== lastTransaction;
      lastTransaction = item.transaction;
      const pct = Math.max(4, Math.round(((Number(item.timeMs) || 0) / maxTime) * 100));
      return `
        <div class="waterfall-row">
          <span class="waterfall-step" aria-hidden="true"><span class="waterfall-dot"></span></span>
          <span class="method-pill method-${escapeHtml(item.method)}">${escapeHtml(item.method)}</span>
          <span class="waterfall-path">
            ${showTxn ? `<span class="txn">${escapeHtml(item.transaction)}</span>` : ""}
            ${escapeHtml(item.path)}
          </span>
          ${statusPill(item.status)}
          <span class="waterfall-bar-track"><span class="waterfall-bar" style="width:${pct}%"></span></span>
        </div>`;
    })
    .join("");
}

function statusPill(status) {
  const code = String(status || "");
  let cls = "status-na";
  if (/^2/.test(code)) cls = "status-2xx";
  else if (/^3/.test(code)) cls = "status-3xx";
  else if (/^4/.test(code)) cls = "status-4xx";
  else if (/^5/.test(code)) cls = "status-5xx";
  return `<span class="status-pill ${cls}">${escapeHtml(code || "--")}</span>`;
}

function emptyRow(title, subtitle) {
  return `<div class="empty-row"><strong>${escapeHtml(title)}</strong>${subtitle ? `<br><span class="meta">${escapeHtml(subtitle)}</span>` : ""}</div>`;
}

function warnIcon() {
  return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.3 3.9 1.8 18a1 1 0 0 0 .9 1.5h18.6a1 1 0 0 0 .9-1.5L13.7 3.9a1 1 0 0 0-1.7 0Z"/><path d="M12 9.5v4"/><path d="M12 16.5h.01"/></svg>';
}

function okIcon() {
  return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="m8 12.5 2.5 2.5L16 9.5"/></svg>';
}

function platformIcon() {
  return '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>';
}

function showError(message) {
  errorMessage.textContent = message;
  errorBox.classList.remove("hidden");
  errorBox.scrollIntoView({ behavior: "smooth", block: "center" });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
