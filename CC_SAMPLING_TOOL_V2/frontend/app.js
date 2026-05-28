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
  renderConfirmationsTable();
  renderAlternativesTable();
  renderProjection();
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
  const arRecv = (s.confirmations?.AR || []).filter(c => c.verdict).length;
  const apRecv = (s.confirmations?.AP || []).filter(c => c.verdict).length;
  setStep("send", s.samples.AR.count + s.samples.AP.count > 0 ? "done" : null);
  setStep("receive", (arRecv + apRecv) > 0 ? "done" : null);
  setStep("projection", (s.projection?.AR || s.projection?.AP) ? "done" : null);
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
    if (result.needs_mapping_confirmation) {
      await showMappingModal(result);
    }
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

// ---- ④ Confirmations ----
function downloadSendlist(ev) {
  ev.preventDefault();
  if (!currentProjectId) { alert("프로젝트 선택"); return; }
  window.location.href = `${API}/projects/${currentProjectId}/sendlist`;
}

async function uploadConfirmations() {
  if (!currentProjectId) { alert("프로젝트 선택"); return; }
  const files = $("#file-confirmation").files;
  if (!files.length) { alert("PDF 1개 이상 선택"); return; }
  const kind = $("#uploadKind").value;
  const results = [];
  $("#confResult").textContent = "업로드 중...";
  for (const f of files) {
    const fd = new FormData();
    fd.append("pdf", f);
    fd.append("kind", kind);
    try {
      const r = await api("POST",
        `/projects/${currentProjectId}/confirmations/upload`, fd, true);
      results.push(`${f.name} → ${r.matched_party || "매칭실패"} (${r.verdict})`);
    } catch (e) {
      results.push(`${f.name} → 오류 ${e.message}`);
    }
  }
  $("#confResult").innerHTML = results.map(l => `<div>${l}</div>`).join("");
  await refreshState();
}

function renderConfirmationsTable() {
  const tbody = $("#confirmationsTable tbody");
  tbody.innerHTML = "";
  const rows = [];
  for (const k of ["AR", "AP"]) {
    for (const c of (currentState.confirmations || {})[k] || []) {
      rows.push({ ...c, kind: k });
    }
  }
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--color-muted);padding:2rem;">회신 없음 — PDF 업로드 필요</td></tr>`;
    return;
  }
  for (const r of rows) {
    const tr = document.createElement("tr");
    const diffStr = r.diff == null ? "—" : fmt(r.diff);
    tr.innerHTML = `
      <td><span class="kind-tag ${r.kind}">${r.kind}</span></td>
      <td>${r.name} (${r.party_id})</td>
      <td class="num">${fmt(r.expected)}</td>
      <td class="num">${fmt(r.confirmed)}</td>
      <td class="num">${diffStr}</td>
      <td><span class="verdict-tag ${r.verdict || "NO_RESPONSE"}">${r.verdict || "—"}</span></td>
      <td>${r.status}</td>
    `;
    tr.style.cursor = "pointer";
    tr.title = "클릭하여 수기 보정";
    tr.onclick = () => openCorrectionModal(r);
    tbody.appendChild(tr);
  }
}

// ---- ⑤ Alternative ----
async function registerAlternative() {
  if (!currentProjectId) { alert("프로젝트 선택"); return; }
  const partyId = $("#altPartyId").value.trim();
  if (!partyId) { alert("거래처코드 필수"); return; }
  const body = {
    kind: $("#altKind").value,
    party_id: partyId,
    procedure_type: $("#altType").value,
    evidence_sum: parseFloat($("#altEvidence").value || "0"),
    note: $("#altNote").value || null,
  };
  $("#altResult").textContent = "등록 중...";
  try {
    const r = await api("POST", `/projects/${currentProjectId}/alternative`, body);
    $("#altResult").innerHTML = `coverage ${pct(r.coverage_pct)} (${r.verdict}) · 누적증빙 ₩${fmt(r.covered_amt)}/${fmt(r.non_response_total)}`;
    await refreshState();
  } catch (e) {
    $("#altResult").textContent = "오류: " + e.message;
  }
}

function renderAlternativesTable() {
  const tbody = $("#alternativesTable tbody");
  tbody.innerHTML = "";
  const rows = [];
  for (const k of ["AR", "AP"]) {
    for (const a of (currentState.alternatives || {})[k] || []) {
      rows.push({ ...a, kind: k });
    }
  }
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--color-muted);padding:1.5rem;">대체적 절차 없음</td></tr>`;
    return;
  }
  for (const r of rows) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><span class="kind-tag ${r.kind}">${r.kind}</span></td>
      <td>${r.name} (${r.party_id})</td>
      <td>${r.procedure_type}</td>
      <td class="num">${fmt(r.evidence_sum)}</td>
      <td>${r.note || "—"}</td>
    `;
    tbody.appendChild(tr);
  }
}

// ---- ⑥ Projection ----
async function runProjection(ev) {
  if (!currentProjectId) { alert("프로젝트 선택"); return; }
  const kind = ev.target.dataset.kind;
  const confidence = parseFloat($("#projConfidence").value);
  try {
    await api("POST", `/projects/${currentProjectId}/projection`,
              { kind, confidence });
    await refreshState();
  } catch (e) {
    alert("오류: " + e.message);
  }
}

function renderProjection() {
  const st = currentState;
  if (!st) return;
  const drawCard = (kind) => {
    const p = (st.projection || {})[kind];
    const card = document.querySelector(`.proj-card[data-kind="${kind}"] .proj-content`);
    if (!p) { card.textContent = "— (계산 전)"; return; }
    card.innerHTML = `
      <div class="row"><span class="label">신뢰수준</span><span class="value">${(p.confidence*100).toFixed(0)}%</span></div>
      <div class="row"><span class="label">표본간격</span><span class="value">₩${fmt(p.sampling_interval)}</span></div>
      <div class="row"><span class="label">추정 misstatement</span><span class="value">₩${fmt(p.projected_misstatement)}</span></div>
      <div class="row"><span class="label">basic precision</span><span class="value">₩${fmt(p.basic_precision)}</span></div>
      <div class="row"><span class="label">incremental</span><span class="value">₩${fmt(p.incremental_allowance)}</span></div>
      <div class="row"><span class="label">upper limit</span><span class="value">₩${fmt(p.upper_limit)}</span></div>
      <div class="row"><span class="label">tolerable</span><span class="value">₩${fmt(p.tolerable)}</span></div>
      <div class="row"><span class="label">판정</span><span class="value proj-verdict ${p.verdict}">${p.verdict}</span></div>
    `;
  };
  drawCard("AR");
  drawCard("AP");

  const ar = (st.projection || {}).AR;
  const ap = (st.projection || {}).AP;
  const combined = $("#projectionCombined");
  if (!ar && !ap) {
    combined.textContent = "— (각 계산 후 합산 표시)";
    return;
  }
  const sumProj = (ar?.projected_misstatement || 0) + (ap?.projected_misstatement || 0);
  const sumUpper = (ar?.upper_limit || 0) + (ap?.upper_limit || 0);
  const sumTol = (ar?.tolerable || 0) + (ap?.tolerable || 0);
  const verdict = sumUpper <= sumTol ? "WITHIN_TOLERABLE" : "EXCEED";
  combined.innerHTML = `
    <div class="row"><span class="label">AR+AP projected</span><span class="value">₩${fmt(sumProj)}</span></div>
    <div class="row"><span class="label">AR+AP upper limit</span><span class="value">₩${fmt(sumUpper)}</span></div>
    <div class="row"><span class="label">AR+AP tolerable</span><span class="value">₩${fmt(sumTol)}</span></div>
    <div class="row"><span class="label">합산 판정</span><span class="value proj-verdict ${verdict}">${verdict}</span></div>
    ${verdict === "EXCEED" ? '<div style="color:var(--color-bad);font-size:.8rem;margin-top:.5rem;">⚠ tolerable 초과 — 추가절차 필요</div>' : ""}
  `;
}

let _correctionContext = null;

function openCorrectionModal(row) {
  _correctionContext = { kind: row.kind, party_id: row.party_id,
                          name: row.name };
  $("#correctionTarget").textContent =
    `${row.kind} · ${row.name} (${row.party_id}) · 장부잔액 ₩${fmt(row.expected)}`;
  $("#correctionAmt").value = row.confirmed != null ? row.confirmed : "";
  $("#correctionReason").value = row.diff_reason || "";
  $("#correctionModal").hidden = false;
}

async function saveCorrection() {
  if (!_correctionContext) return;
  const amt = $("#correctionAmt").value;
  const body = {
    kind: _correctionContext.kind,
    party_id: _correctionContext.party_id,
    confirmed: amt === "" ? null : parseFloat(amt),
    diff_reason: $("#correctionReason").value || null,
  };
  try {
    await api("POST",
      `/projects/${currentProjectId}/confirmations/correct`, body);
    $("#correctionModal").hidden = true;
    _correctionContext = null;
    await refreshState();
  } catch (e) {
    alert("저장 실패: " + e.message);
  }
}

function showMappingModal(result) {
  return new Promise((resolve) => {
    $("#mappingMessage").textContent =
      "자동감지 신뢰도가 95% 미만입니다. 매핑 결과를 확인해주세요.";
    $("#mappingDetails").innerHTML = `
      <div>AR 자동감지: ${pct(result.confidence_ar)}</div>
      <div>AP 자동감지: ${pct(result.confidence_ap)}</div>
    `;
    $("#mappingModal").hidden = false;
    const close = (confirm) => {
      $("#mappingModal").hidden = true;
      if (confirm) {
        api("POST",
          `/projects/${currentProjectId}/ingest/confirm-mapping`, {})
          .finally(() => resolve());
      } else {
        resolve();
      }
    };
    $("#mappingConfirmBtn").onclick = () => close(true);
    $("#mappingCancelBtn").onclick = () => close(false);
  });
}

// ---- ⑦ Downloads ----
function downloadWorkpaper(template) {
  if (!currentProjectId) { alert("프로젝트 선택"); return; }
  window.location.href = `${API}/projects/${currentProjectId}/workpaper/${template}`;
}

function downloadSendlistFromSide(ev) {
  ev.preventDefault();
  if (!currentProjectId) { alert("프로젝트 선택"); return; }
  window.location.href = `${API}/projects/${currentProjectId}/sendlist`;
}

async function deleteCurrentProject() {
  if (!currentProjectId) { alert("프로젝트 선택"); return; }
  if (!confirm("프로젝트 + 모든 데이터를 삭제합니다. 진행?")) return;
  try {
    await api("DELETE", `/projects/${currentProjectId}`);
    currentProjectId = null;
    currentState = null;
    await loadProjectList();
  } catch (e) {
    alert("삭제 실패: " + e.message);
  }
}

async function init() {
  $("#projectSelect").addEventListener("change", e => selectProject(e.target.value));
  $("#newProjectBtn").addEventListener("click", newProject);
  $("#deleteProjectBtn").addEventListener("click", deleteCurrentProject);
  $("#filterKind").addEventListener("change", renderMergedTable);
  $("#filterReason").addEventListener("change", renderMergedTable);
  $("#ingestBtn").addEventListener("click", runIngest);
  $$(".runDesign").forEach(btn => btn.addEventListener("click", runDesign));
  $("#downloadSendlist").addEventListener("click", downloadSendlist);
  $("#uploadConfBtn").addEventListener("click", uploadConfirmations);
  $("#altRegisterBtn").addEventListener("click", registerAlternative);
  $$(".runProjection").forEach(b => b.addEventListener("click", runProjection));
  $("#dlC100Btn").addEventListener("click", () => downloadWorkpaper("c100"));
  $("#dlAA100Btn").addEventListener("click", () => downloadWorkpaper("aa100"));
  $("#dlSendlistBtn").addEventListener("click", downloadSendlistFromSide);
  $("#correctionSaveBtn").addEventListener("click", saveCorrection);
  $("#correctionCancelBtn").addEventListener("click", () => {
    $("#correctionModal").hidden = true;
    _correctionContext = null;
  });
  await loadProjectList();
}

init().catch(e => { console.error(e); alert("초기화 실패: " + e.message); });
