// frontend/app.js
const API = "/api";
const STEPS = [
  { id: 1, title: "회사·기준일",           render: renderStep1 },
  { id: 2, title: "원장 · Control Sheet 업로드", render: renderUpload(["gl","cs"]) },
  { id: 3, title: "표본추출 실행",          render: renderStep4 },
  { id: 4, title: "전기 Control Sheet 비교", render: renderUpload(["prior_cs"], true) },
  { id: 5, title: "월보 · 담보 · 보증",      render: renderUpload(["union","collateral","guarantee"], true) },
  { id: 6, title: "주소 유효성",            render: renderStep7 },
  { id: 7, title: "회신본 업로드",           render: renderStep8 },
  { id: 8, title: "추출 결과 검토",          render: renderStep9 },
  { id: 9, title: "4150 조서 생성",          render: renderStep10 },
];

// 파일 종류·교차검증 섹션 한글 라벨 (원장·Control Sheet 같은 정착 용어는 유지)
const KIND_LABEL = {
  gl:"원장(G/L)", cs:"Control Sheet", prior_cs:"전기 Control Sheet",
  union:"은행연합회 월보", collateral:"담보제공명세", guarantee:"연대보증명세",
};
const SECTION_LABEL = {
  bidirectional:"양방향 대사", prior:"전기 비교", union:"월보 대사",
  collateral:"담보 대사", guarantee:"보증 대사", address:"주소 유효성",
};

const state = { projectId: null, current: 1, done: new Set() };

function $(s){ return document.querySelector(s); }
function goNext(){ state.done.add(state.current); state.current++; render(); }
function el(tag, props={}, ...children){
  const n = document.createElement(tag);
  Object.assign(n, props);
  for(const c of children) n.append(c?.nodeType ? c : document.createTextNode(c ?? ""));
  return n;
}

function renderNav(){
  const ol = $("#stepList"); ol.innerHTML = "";
  for(const s of STEPS){
    const li = el("li", { textContent: `${s.id}. ${s.title}` });
    if(s.id === state.current) li.classList.add("active");
    if(state.done.has(s.id)) li.classList.add("done");
    li.onclick = () => { state.current = s.id; render(); };
    ol.append(li);
  }
}

function render(){
  renderNav();
  const right = document.querySelector('.hd-right');
  if(right) right.innerHTML = "";   // 단계별 다운로드 배너·헤더 버튼 제거 — 다운로드는 마지막 단계에서만
  const panel = $("#panel"); panel.innerHTML = "";
  const step = STEPS.find(s => s.id === state.current);
  step.render(panel);
}

async function post(path, body, isForm=false){
  const opts = { method:"POST" };
  if(isForm){ opts.body = body; }
  else { opts.headers = {"Content-Type":"application/json"}; opts.body = JSON.stringify(body || {}); }
  const r = await fetch(API + path, opts);
  if(!r.ok) throw new Error(await r.text());
  return r.json();
}

async function del(path){
  const r = await fetch(API + path, { method:"DELETE" });
  if(!r.ok) throw new Error(await r.text());
  return r.json();
}

function renderStep1(panel){
  const card = el("div", { className:"card" });
  card.append(el("h2", {}, "프로젝트 설정"));
  const name = el("input", { placeholder:"회사명 (예: 코스맥스비티아이)" });
  const date = el("input", { type:"date", value:"2025-12-31" });
  const btn = el("button", { className:"btn" }, "프로젝트 생성");
  btn.onclick = async () => {
    btn.disabled = true;
    const r = await post("/projects", { name: name.value, fiscal_date: date.value });
    state.projectId = r.id; state.done.add(1); state.current = 2; render();
  };
  card.append(name, " ", date, " ", btn);
  panel.append(card);
}

function renderUpload(kinds, optional=false){
  return function(panel){
    panel.append(el("h2", {}, `파일 업로드 (${kinds.map(k=>KIND_LABEL[k]||k).join(" · ")})${optional?" - 선택":""}`));
    for(const kind of kinds){
      const card = el("div", { className:"card" });
      card.append(el("h3", {}, KIND_LABEL[kind]||kind));
      const drop = el("div", { className:"drop-zone", textContent:`${KIND_LABEL[kind]||kind} 파일 드롭 또는 클릭` });
      drop.onclick = () => {
        const f = el("input", { type:"file" });
        f.onchange = async (e) => uploadFile(kind, e.target.files[0], drop);
        f.click();
      };
      drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("dragover"); };
      drop.ondragleave = () => drop.classList.remove("dragover");
      drop.ondrop = async (e) => {
        e.preventDefault(); drop.classList.remove("dragover");
        await uploadFile(kind, e.dataTransfer.files[0], drop);
      };
      card.append(drop);
      panel.append(card);
    }
    const next = el("button", { className:"btn" }, "다음 단계 →");
    next.onclick = () => { state.done.add(state.current); state.current++; render(); };
    panel.append(next);
  };
}

async function uploadFile(kind, file, drop){
  if(!file || !state.projectId) return;
  const fd = new FormData(); fd.append("file", file);
  drop.textContent = "업로드 중…";
  try{
    await post(`/projects/${state.projectId}/upload/${kind}`, fd, true);
    drop.textContent = `✓ ${file.name}`;
  }catch(err){ drop.textContent = "실패: " + err.message; }
}

function renderStep4(panel){
  const card = el("div", { className:"card" });
  card.append(el("h2", {}, "표본추출 실행"));
  const btn = el("button", { className:"btn" }, "원장에서 금융기관 표본추출");
  const result = el("div");
  btn.onclick = async () => {
    btn.disabled = true; btn.textContent = "추출 중…";
    const r = await post(`/projects/${state.projectId}/sampling/run`);
    result.innerHTML = "";
    const tbl = el("table");
    tbl.append(el("tr", {},
      el("th", {}, "금융기관"), el("th", {}, "지점"),
      el("th", {}, "B/S 잔액"), el("th", {}, "P/L 거래액"),
      el("th", {}, "B/S 계정"), el("th", {}, "P/L 계정"),
      el("th", {}, "제거"),
    ));
    const countLabel = el("div", { className:"muted" });
    const refreshCount = () => {
      const n = tbl.querySelectorAll("tr").length - 1;
      countLabel.textContent = `조회대상 ${n}건`;
    };
    for(const p of r.parties){
      const rmBtn = el("button", { className:"btn secondary", title:"이 거래처를 조회대상에서 제외" }, "제거");
      const row = el("tr", {},
        el("td", {}, p.canonical),
        el("td", {}, p.branch || ""),
        el("td", { className:"num" }, p.bs_amount.toLocaleString()),
        el("td", { className:"num" }, p.pl_amount.toLocaleString()),
        el("td", {}, p.bs_accounts.join(", ")),
        el("td", {}, p.pl_accounts.join(", ")),
        el("td", {}, rmBtn),
      );
      rmBtn.onclick = async () => {
        if(p.id == null){ alert("거래처 ID 없음 — 표본추출 재실행 필요"); return; }
        rmBtn.disabled = true; rmBtn.textContent = "…";
        try {
          await del(`/projects/${state.projectId}/counterparty/${p.id}`);
          row.remove();
          refreshCount();
        } catch(e){
          rmBtn.disabled = false; rmBtn.textContent = "제거";
          alert("제거 실패: " + e.message);
        }
      };
      tbl.append(row);
    }
    result.append(tbl, countLabel);
    refreshCount();
    btn.textContent = "재실행"; btn.disabled = false;
    state.done.add(state.current);
  };
  card.append(btn, result);
  panel.append(card);
  const next = el("button", { className:"btn" }, "다음 →");
  next.onclick = goNext;
  panel.append(next);
}

function renderStep7(panel){
  panel.append(el("h2", {}, "주소 유효성 + 교차검증 실행"));
  const btn = el("button", { className:"btn" }, "교차검증 실행");
  const result = el("div");
  btn.onclick = async () => {
    btn.disabled = true;
    const r = await post(`/projects/${state.projectId}/crosscheck/run`);
    result.innerHTML = "";
    for(const section of ["bidirectional","prior","union","collateral","guarantee","address"]){
      result.append(el("h3", {}, SECTION_LABEL[section]||section));
      result.append(el("pre", { textContent: JSON.stringify(r[section], null, 2).slice(0, 1500) }));
    }
    btn.disabled = false;
  };
  panel.append(btn, result);
  const next = el("button", { className:"btn secondary" }, "다음 →");
  next.onclick = goNext;
  panel.append(next);
}

function renderStep8(panel){
  panel.append(el("h2", {}, "회신본 PDF 업로드 (여러 파일)"));
  const card = el("div", { className:"card" });
  const drop = el("div", { className:"drop-zone", textContent:"PDF 파일 드롭 또는 클릭 (여러 파일 가능)" });
  const list = el("ul");
  drop.onclick = () => {
    const f = el("input", { type:"file", multiple:true, accept:".pdf" });
    f.onchange = async (e) => { for(const file of e.target.files) await uploadResponse(file, list); };
    f.click();
  };
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("dragover"); };
  drop.ondragleave = () => drop.classList.remove("dragover");
  drop.ondrop = async (e) => {
    e.preventDefault(); drop.classList.remove("dragover");
    for(const f of e.dataTransfer.files) await uploadResponse(f, list);
  };
  card.append(drop, list);
  panel.append(card);
  const next = el("button", { className:"btn" }, "다음 →");
  next.onclick = goNext;
  panel.append(next);
}

async function uploadResponse(file, list){
  const fd = new FormData(); fd.append("file", file);
  await post(`/projects/${state.projectId}/upload/response`, fd, true);
  list.append(el("li", {}, "✓ " + file.name));
}

function renderStep9(panel){
  panel.append(el("h2", {}, "회신 추출·매칭"));
  const btn = el("button", { className:"btn" }, "회신 추출 실행");
  const result = el("div");
  btn.onclick = async () => {
    btn.disabled = true;
    const r = await post(`/projects/${state.projectId}/response/parse`);
    const tbl = el("table");
    tbl.append(el("tr", {},
      el("th", {}, "Section"), el("th", {}, "BC"), el("th", {}, "Bank"),
      el("th", {}, "Confidence"), el("th", {}, "Preview"),
    ));
    for(const rec of r.records.slice(0, 200)){
      const tr = el("tr", {},
        el("td", {}, rec.section),
        el("td", {}, rec.bc_no || ""),
        el("td", {}, rec.bank),
        el("td", {}, rec.confidence),
        el("td", { style:"font-size:0.7rem;color:#4E5968" }, JSON.stringify(rec.payload).slice(0,80)),
      );
      if(rec.confidence === "low") tr.style.background = "var(--conf-low)";
      tbl.append(tr);
    }
    result.innerHTML = ""; result.append(tbl);
    btn.disabled = false;
  };
  panel.append(btn, result);
  const next = el("button", { className:"btn secondary" }, "다음 →");
  next.onclick = goNext;
  panel.append(next);
}

function renderStep10(panel){
  panel.append(el("h2", {}, "4150 조서 생성"));
  const btn = el("button", { className:"btn" }, "Excel 다운로드");
  btn.onclick = async () => {
    btn.disabled = true; btn.textContent = "생성 중…";
    const r = await fetch(`${API}/projects/${state.projectId}/workpaper/export`, { method:"POST" });
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = el("a", { href:url, download:`4150_AC_금융기관조회_${Date.now()}.xlsx` });
    a.click();
    btn.textContent = "재생성"; btn.disabled = false;
    state.done.add(state.current);
  };
  panel.append(btn);
}

render();
