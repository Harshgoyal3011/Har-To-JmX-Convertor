"use strict";

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, html) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (html != null) n.innerHTML = html;
  return n;
};
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const form = $("#uploadForm");
const fileInput = $("#harfile");
const dropzone = $("#dropzone");
const submitBtn = $("#submitBtn");

// ---- File selection / drag & drop ----
function setFile(file) {
  if (!file) return;
  dropzone.classList.add("has-file");
  $("#dropTitle").textContent = file.name;
  $("#dropHint").textContent = (file.size / 1024).toFixed(0) + " KB · ready to convert";
  $("#fileMeta").textContent = "";
}
fileInput.addEventListener("change", () => setFile(fileInput.files[0]));
["dragenter", "dragover"].forEach((e) => dropzone.addEventListener(e, (ev) => { ev.preventDefault(); dropzone.classList.add("drag"); }));
["dragleave", "drop"].forEach((e) => dropzone.addEventListener(e, (ev) => { ev.preventDefault(); dropzone.classList.remove("drag"); }));
dropzone.addEventListener("drop", (ev) => {
  const f = ev.dataTransfer.files[0];
  if (f) { fileInput.files = ev.dataTransfer.files; setFile(f); }
});

// ---- Pipeline animation ----
const STEPS = ["parse", "filter", "flow", "correlate", "parameterize", "validate", "emit"];
let pipeTimer = null;
function runPipelineAnim() {
  const steps = [...document.querySelectorAll("#pipelineSteps li")];
  steps.forEach((s) => s.classList.remove("active", "done"));
  let i = 0;
  const tick = () => {
    if (i > 0) steps[i - 1].classList.replace("active", "done");
    if (i < steps.length) { steps[i].classList.add("active"); i++; pipeTimer = setTimeout(tick, 280); }
  };
  tick();
}
function finishPipelineAnim() {
  clearTimeout(pipeTimer);
  document.querySelectorAll("#pipelineSteps li").forEach((s) => { s.classList.remove("active"); s.classList.add("done"); });
}

// ---- Submit ----
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const file = fileInput.files[0];
  if (!file) { $("#fileMeta").textContent = "Choose a .har file first."; return; }

  submitBtn.classList.add("loading"); submitBtn.disabled = true; $("#submitLabel").textContent = "Analyzing…";
  $("#errorBox").classList.add("hidden");
  $("#results").classList.add("hidden");
  $("#pipeline").classList.remove("hidden");
  runPipelineAnim();

  const fd = new FormData();
  fd.append("harfile", file);
  fd.append("threads", $("#threads").value || "50");
  fd.append("loops", $("#loops").value || "5");
  fd.append("ramp", $("#ramp").value || "20");
  fd.append("hold", $("#hold").value || "0");
  if ($("#thinktime").value) fd.append("thinktime", $("#thinktime").value);   // blank → observed pacing

  try {
    const res = await fetch("/api/convert", { method: "POST", body: fd });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    finishPipelineAnim();
    setTimeout(() => { $("#pipeline").classList.add("hidden"); render(data); }, 350);
  } catch (err) {
    clearTimeout(pipeTimer);
    $("#pipeline").classList.add("hidden");
    $("#errorMsg").textContent = err.message || "Unexpected error.";
    $("#errorBox").classList.remove("hidden");
  } finally {
    submitBtn.classList.remove("loading"); submitBtn.disabled = false; $("#submitLabel").textContent = "Generate JMeter plan";
  }
});

$("#restartBtn").addEventListener("click", () => {
  $("#results").classList.add("hidden");
  $("#introSection").scrollIntoView({ behavior: "smooth" });
});

// ---- Render results ----
function render(d) {
  const m = d.metrics, rq = d.requests;

  // capture-quality preflight — correlation is only as good as the capture
  const cq = d.captureQuality;
  const cqBox = $("#captureQuality");
  if (cq && cq.degraded) {
    cqBox.innerHTML = `<strong>Capture quality note:</strong> ${cq.emptyBodies} of ${cq.businessResponses} responses were recorded without a body (${cq.bodyCoveragePct}% have bodies). Values issued by those responses can't be correlated automatically — re-record with response bodies enabled for full correlation.`;
    cqBox.classList.remove("hidden");
  } else {
    cqBox.classList.add("hidden");
    cqBox.innerHTML = "";
  }

  // downloads
  $("#dlZip").href = "/download/" + encodeURIComponent(d.downloads.zip);
  $("#dlJmx").href = "/download/" + encodeURIComponent(d.downloads.jmx);
  $("#resultTitle").textContent = `Plan ready — ${d.config ? d.config.threads : ""} users, ${m.transactions} transactions`;

  // metric tiles
  const readyClass = m.replayReadiness >= 70 ? "" : "warn";
  const tiles = $("#metrics");
  tiles.innerHTML = "";
  const ready = el("div", "tile readiness");
  ready.innerHTML = `<div class="ring"><div class="gauge" style="--v:${m.replayReadiness}"></div>
    <div><div class="score">${m.replayReadiness}</div><div class="l">Replay readiness</div></div></div>`;
  tiles.appendChild(ready);
  [
    [rq.business, "Requests scripted"],
    [rq.excluded, "Noise filtered"],
    [m.correlations, "Correlations"],
    [m.parameters, "Parameters"],
    [m.transactions, "Transactions"],
  ].forEach(([n, l]) => {
    const t = el("div", "tile");
    t.innerHTML = `<div class="n">${n}</div><div class="l">${l}</div>`;
    tiles.appendChild(t);
  });

  // flow
  const flow = $("#flow"); flow.innerHTML = "";
  d.transactions.forEach((t) => {
    const li = el("li");
    li.innerHTML = `<span class="dot"></span>
      <span><span class="fname">${esc(t.name)}</span><br><span class="fcat">${esc(t.category)}</span></span>
      <span class="fcount">${t.requests} req</span>`;
    flow.appendChild(li);
  });
  $("#flowCount").textContent = d.transactions.length + " user actions";

  // stack
  const stack = $("#stack"); stack.innerHTML = "";
  const rowOf = (label, items, cls) => {
    const row = el("div", "row");
    row.appendChild(el("span", "k", label));
    if (!items || !items.length) { row.appendChild(el("span", "chip none", "none detected")); }
    else items.forEach((x) => row.appendChild(el("span", "chip " + (cls || ""), esc(x))));
    return row;
  };
  stack.appendChild(rowOf("API style", d.application.apiStyles, "accent"));
  stack.appendChild(rowOf("Authentication", d.auth.mechanisms, "violet"));
  stack.appendChild(rowOf("Server / framework", d.application.servers));
  if (d.application.enterprise && d.application.enterprise.length) stack.appendChild(rowOf("Platform", d.application.enterprise, "violet"));

  // correlations
  const cbody = $("#corrTable tbody"); cbody.innerHTML = "";
  d.correlations.forEach((c) => {
    const tr = el("tr");
    tr.innerHTML = `<td class="var">\${${esc(c.variable)}}</td>
      <td><span class="ext ${c.extractor === "json" ? "json" : ""}">${esc(c.extractor)}</span></td>
      <td class="val" title="${esc(c.reason)}">${esc(c.value)}</td>
      <td><span class="conf ${esc(c.confidence)}">${esc(c.confidence)}</span></td>
      <td class="val">${esc(c.producedIn || "")}</td>
      <td class="val">${c.consumers}</td>`;
    cbody.appendChild(tr);
  });
  $("#corrCount").textContent = d.correlations.length + " runtime values";
  if (!d.correlations.length) cbody.innerHTML = `<tr><td colspan="6" class="val">No runtime correlations needed for this flow.</td></tr>`;

  // datasets
  const ds = $("#datasets"); ds.innerHTML = "";
  d.parameters.forEach((p) => {
    const card = el("div", "dataset");
    card.innerHTML = `<div class="dh"><span class="dname">${esc(p.dataset)}</span><span class="drows">${p.rows} row${p.rows === 1 ? "" : "s"}</span></div>
      <div class="cols">${p.columns.map((c) => `<span class="col">${esc(c)}</span>`).join("")}</div>`;
    ds.appendChild(card);
  });
  $("#paramCount").textContent = d.parameters.length + " datasets";
  if (!d.parameters.length) ds.innerHTML = `<div class="muted">No parameterizable business inputs detected.</div>`;

  // replay
  const badge = $("#replayBadge");
  badge.textContent = d.replay.passed ? "PASSED" : "REVIEW";
  badge.className = "pill " + (d.replay.passed ? "pill-pass" : "pill-warn");
  const rc = $("#replay"); rc.innerHTML = "";
  d.replay.findings.forEach((f) => {
    const crit = f.severity === "CRITICAL";
    const row = el("div", "check " + (f.passed ? "pass" : "fail") + (crit ? " crit" : ""));
    row.innerHTML = `<span class="mark">${f.passed ? "✓" : "!"}</span>
      <span><span class="ct">${esc(f.check)}</span><span class="cd">${esc(f.detail)}</span></span>`;
    rc.appendChild(row);
  });

  // excluded
  const ex = $("#excluded"); ex.innerHTML = "";
  (d.excluded || []).forEach((e) => {
    const q = el("div", "exq");
    q.innerHTML = `<span class="el">${esc(e.label)}</span><span class="er"><span class="role">${esc(e.role)}</span></span>`;
    ex.appendChild(q);
  });
  $("#excludedCount").textContent = rq.excluded + " requests · " + rq.excludedPct + "%";
  if (!(d.excluded || []).length) ex.innerHTML = `<div class="muted">No noise in this capture — every request was business-relevant.</div>`;

  // needs manual correlation
  const mc = d.manualCorrelations || [];
  const mcWrap = $("#manualCorr"); mcWrap.innerHTML = "";
  const mcCard = $("#manualCard");
  $("#manualCount").textContent = mc.length ? mc.length + " to wire up" : "none";
  if (!mc.length) {
    mcCard.classList.remove("warn");
    mcWrap.innerHTML = `<div class="muted">✓ All dynamic values were correlated automatically — nothing to wire by hand.</div>`;
  } else {
    mcCard.classList.add("warn");
    mc.forEach((m) => {
      const q = el("div", "exq");
      q.innerHTML = `<div><span class="var">${esc(m.field)}</span> <span class="val">${esc(m.value)}</span></div>
        <div class="muted" style="margin-top:4px">${esc(m.reason)}</div>
        <div class="muted" style="margin-top:2px"><b>Used in:</b> ${esc((m.usedIn || []).join("; ") || "a later request")}</div>
        <div class="muted" style="margin-top:2px"><b>Fix:</b> ${esc(m.suggestion)}</div>`;
      mcWrap.appendChild(q);
    });
  }

  $("#results").classList.remove("hidden");
  $("#results").scrollIntoView({ behavior: "smooth", block: "start" });
}
