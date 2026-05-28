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
  rows.sort((a, b) => Math.abs(b.balance_krw) - Math.abs(a.balance_krw));
  const filtered = rows.filter(r =>
    (!filterKind || r.kind === filterKind)
    && (!filterReason || r.selection_reason === filterReason)
  );
  for (const r of filtered) {
    const tr = document.createElement("tr");
    const badges = [];
    if (r.is_related_party) badges.push(`<span class="badge rp">RP</span>`);
    if (r.is_bad_debt) badges.push(`<span class="badge bad">BAD</span>`);
    tr.innerHTML = `
      <td><span class="kind-tag ${r.kind}">${r.kind}</span></td>
      <td>${r.party_id}</td>
      <td>${r.name} ${badges.join(" ")}</td>
      <td class="num">${fmt(r.balance_krw)}</td>
      <td>${r.ccy}</td>
      <td><span class="reason-tag ${r.selection_reason}">${r.selection_reason}</span></td>
    `;
    tbody.appendChild(tr);
  }
  if (!filtered.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="6" style="text-align:center;color:var(--color-muted);padding:2rem;">표본 없음 — ② 패널에서 설계 실행</td>`;
    tbody.appendChild(tr);
  }
}

async function runIngest() {
  if (!currentProjectId) { alert("프로젝트 먼저 선택"); return; }
  const fd = new FormData();
  const ledger = $("#file-ledger").files[0];
  if (!ledger) { alert("거래처원장 필수"); return; }
  fd.append("ledger", ledger);
  for (const [name, id] of [["fs", "file-fs"], ["rp", "file-rp"], ["allowance", "file-allowance"]]) {
    const f = $("#" + id).files[0];
    if (f) fd.append(name, f);
  }
  $("#ingestResult").textContent = "업로드·자동감지 중...";
  try {
    const result = await api("POST", `/projects/${currentProjectId}/ingest`, fd, true);
    const lines = [
      `AR ${result.ar_count}건 · ₩${fmt(result.ar_total_krw)} (자동감지 ${pct(result.confidence_ar)})`,
      `AP ${result.ap_count}건 · ₩${fmt(result.ap_total_krw)} (자동감지 ${pct(result.confidence_ap)})`,
    ];
    if (result.needs_mapping_confirmation) {
      lines.push("⚠ 자동감지 신뢰도 < 95% — 매핑확인 필요 (Phase 2 향후 추가)");
    }
    if (result.fs_totals && Object.keys(result.fs_totals).length > 0) {
      lines.push(`FS cross-check: AR=₩${fmt(result.fs_totals.AR)}, AP=₩${fmt(result.fs_totals.AP)}`);
    }
    $("#ingestResult").innerHTML = lines.map(l => `<div>${l}</div>`).join("");
    await refreshState();
  } catch (e) {
    $("#ingestResult").textContent = "오류: " + e.message;
  }
}

async function runDesign(ev) {
  if (!currentProjectId) { alert("프로젝트 선택"); return; }
  const col = ev.target.closest(".kind-col");
  const kind = col.dataset.kind;
  const params = {
    kind,
    confidence: parseFloat(col.querySelector(".conf").value),
    expected_ms_pct: parseFloat(col.querySelector(".ems").value),
    key_threshold: parseFloat(col.querySelector(".keyth").value || "0"),
    n_strata: parseInt(col.querySelector(".nstrata").value, 10),
    seed: Math.floor(Math.random() * 1_000_000),
  };
  const resultDiv = col.querySelector(".designResult");
  resultDiv.textContent = "설계 중...";
  try {
    const r = await api("POST", `/projects/${currentProjectId}/sampling/design`, params);
    const lines = [
      `표본 ${r.n_total}건 (강제 ${r.n_forced} · 대표 ${r.n_representative})`,
      `제외 ${r.n_excluded} · BV ₩${fmt(r.population_bv)}`,
      `seed ${r.used_seed}`,
    ];
    resultDiv.innerHTML = lines.map(l => `<div>${l}</div>`).join("");
    await refreshState();
  } catch (e) {
    resultDiv.textContent = "오류: " + e.message;
  }
}

async function init() {
  $("#projectSelect").addEventListener("change", e => selectProject(e.target.value));
  $("#newProjectBtn").addEventListener("click", newProject);
  $("#filterKind").addEventListener("change", renderMergedTable);
  $("#filterReason").addEventListener("change", renderMergedTable);
  $("#ingestBtn").addEventListener("click", runIngest);
  $$(".runDesign").forEach(btn => btn.addEventListener("click", runDesign));
  await loadProjectList();
}

init().catch(e => { console.error(e); alert("초기화 실패: " + e.message); });
