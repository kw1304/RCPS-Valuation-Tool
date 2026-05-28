"use strict";

const API = "/api";
let currentProjectId = null;
let currentState = null;

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const fmt = (n) => (n == null ? "—" : new Intl.NumberFormat("ko-KR").format(Math.round(n)));
const pct = (v) => (v == null ? "—" : (v * 100).toFixed(1) + "%");

async function api(method, path, body, isFile = false) {
  const opts = { method };
  if (body && !isFile) {
    opts.headers = { "Content-Type": "application/json" };
    opts.body = JSON.stringify(body);
  } else if (body && isFile) {
    opts.body = body;
  }
  const resp = await fetch(API + path, opts);
  if (!resp.ok) {
    const err = await resp.text();
    throw new Error(`${resp.status}: ${err}`);
  }
  return resp.json();
}

async function loadProjectList() {
  const projects = await api("GET", "/projects");
  const sel = $("#projectSelect");
  sel.innerHTML = '<option value="">— 프로젝트 선택 —</option>';
  for (const p of projects) {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = `${p.client} · ${p.period_end}`;
    sel.appendChild(opt);
  }
  if (projects.length && currentProjectId == null) {
    sel.value = projects[0].id;
    await selectProject(projects[0].id);
  }
}

async function selectProject(pid) {
  currentProjectId = parseInt(pid, 10);
  if (!currentProjectId) return;
  await refreshState();
}

async function newProject() {
  const client = prompt("회사명?");
  if (!client) return;
  const period_end = prompt("평가기준일 (YYYY-MM-DD)?", "2025-12-31");
  if (!period_end) return;
  const materiality = parseFloat(prompt("Materiality (KRW)?", "500000000"));
  const tolerable = parseFloat(prompt("Tolerable misstatement (KRW)?", "250000000"));
  const created = await api("POST", "/projects", {
    client, period_end, base_ccy: "KRW", materiality, tolerable,
  });
  await loadProjectList();
  $("#projectSelect").value = created.id;
  await selectProject(created.id);
}

async function refreshState() {
  if (!currentProjectId) return;
  currentState = await api("GET", `/projects/${currentProjectId}/state`);
  renderSidePanel();
  renderMergedTable();
}

function renderSidePanel() {
  const s = currentState;
  if (!s) return;
  const pop = (s.populations.AR.total_krw || 0) + (s.populations.AP.total_krw || 0);
  const samp = (s.samples.AR.total_krw || 0) + (s.samples.AP.total_krw || 0);
  $("#populationTotal").textContent = "₩" + fmt(pop);
  $("#sampleTotal").textContent = "₩" + fmt(samp);
  $("#coveragePct").textContent = pop > 0 ? pct(samp / pop) : "—";

  const setStep = (step, status) => {
    const li = $(`#progressList li[data-step="${step}"]`);
    if (!li) return;
    li.classList.remove("done", "disabled");
    if (status) li.classList.add(status);
  };
  setStep("ingest", s.populations.AR.count + s.populations.AP.count > 0 ? "done" : null);
  setStep("design-ar", s.samples.AR.count > 0 ? "done" : null);
  setStep("design-ap", s.samples.AP.count > 0 ? "done" : null);
  setStep("send", "disabled");
  setStep("receive", "disabled");
  setStep("projection", "disabled");
}

function renderMergedTable() {
  const tbody = $("#mergedTable tbody");
  tbody.innerHTML = "";
  const filterKind = $("#filterKind").value;
  const filterReason = $("#filterReason").value;
  const rows = [];
  for (const k of ["AR", "AP"]) {
    for (const it of currentState.samples[k].items || []) {
      rows.push({ ...it, kind: k });
    }
  }
  const filtered = rows.filter(r =>
    (!filterKind || r.kind === filterKind)
    && (!filterReason || r.selection_reason === filterReason)
  );
  for (const r of filtered) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><span class="kind-tag ${r.kind}">${r.kind}</span></td>
      <td>${r.party_id}</td>
      <td>${r.name}</td>
      <td class="num">${fmt(r.balance_krw)}</td>
      <td>${r.ccy}</td>
      <td><span class="reason-tag ${r.selection_reason}">${r.selection_reason}</span></td>
    `;
    tbody.appendChild(tr);
  }
}

async function init() {
  $("#projectSelect").addEventListener("change", e => selectProject(e.target.value));
  $("#newProjectBtn").addEventListener("click", newProject);
  $("#filterKind").addEventListener("change", renderMergedTable);
  $("#filterReason").addEventListener("change", renderMergedTable);
  await loadProjectList();
}

init().catch(e => { console.error(e); alert("초기화 실패: " + e.message); });
