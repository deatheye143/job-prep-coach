const QUIZ_SECONDS = 600;
const LETTERS = "ABCD";
const state = { mode: "quiz", subject: null, chapterIndex: null, chapterName: "", questions: [],
                index: 0, answers: {}, timeLeft: 0, limit: 0, timerId: null, lastResult: null };
const $ = id => document.getElementById(id);
const show = (id, on = true) => $(id).classList.toggle("hidden", !on);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const fmtDate = ms => new Date(ms).toLocaleDateString("hi-IN", { day: "2-digit", month: "short", year: "numeric" });

async function api(url, method = "GET", body) {
  const res = await fetch(url, { method, headers: { "Content-Type": "application/json" },
                                 body: body ? JSON.stringify(body) : undefined });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) { const e = new Error(data.error || "Kuch galat ho gaya"); e.status = res.status; throw e; }
  return data;
}

// ---------- LOGIN / SIGN UP / FORGOT ----------
const AUTH_PANELS = ["authLogin", "authSignup", "authSignupOtp", "authForgot", "authForgotOtp", "authNewPass"];
let resetId = "", resetOtp = "", signupPhone = "";

function showAuth(panel) {
  AUTH_PANELS.forEach(p => show(p, p === panel));
  setMsg(""); setNote("");
}
function setMsg(t) { $("authMsg").textContent = t; }
function setNote(t) { $("authNote").textContent = t; show("authNote", !!t); }
function otpNote(d) {
  if (d.demo_otp) setNote(`Demo OTP: ${d.demo_otp} (SMS/email setting abhi nahi hai)`);
  else setNote(`OTP ${d.channel === "email" ? "email" : "number"} par bhej diya gaya hai.`);
}

$("loginBtn").onclick = async () => {
  try {
    await api("/api/login", "POST", { phone: $("loginPhone").value.trim(), password: $("loginPass").value });
    enterApp();
  } catch (e) { setMsg(e.message); }
};
$("gotoSignup").onclick = () => showAuth("authSignup");
$("gotoForgot").onclick = () => showAuth("authForgot");

$("suBtn").onclick = async () => {
  const body = { name: $("suName").value.trim(), email: $("suEmail").value.trim(),
                 phone: $("suPhone").value.trim(), password: $("suPass").value, confirm: $("suPass2").value };
  try {
    const d = await api("/api/signup/start", "POST", body);
    signupPhone = body.phone;
    showAuth("authSignupOtp"); otpNote(d);
  } catch (e) { setMsg(e.message); }
};
$("suBack").onclick = () => showAuth("authLogin");
$("suOtpBtn").onclick = async () => {
  try { await api("/api/signup/verify", "POST", { phone: signupPhone, otp: $("suOtp").value.trim() }); enterApp(); }
  catch (e) { setMsg(e.message); }
};
$("suOtpBack").onclick = () => showAuth("authSignup");

$("fgBtn").onclick = async () => {
  resetId = $("fgId").value.trim().toLowerCase();
  try { const d = await api("/api/reset/start", "POST", { identifier: resetId }); showAuth("authForgotOtp"); otpNote(d); }
  catch (e) { setMsg(e.message); }
};
$("fgBack").onclick = () => showAuth("authLogin");
$("fgOtpBtn").onclick = async () => {
  resetOtp = $("fgOtp").value.trim();
  try { await api("/api/reset/verify", "POST", { identifier: resetId, otp: resetOtp }); showAuth("authNewPass"); }
  catch (e) { setMsg(e.message); }
};
$("fgOtpBack").onclick = () => showAuth("authForgot");
$("npBtn").onclick = async () => {
  try {
    await api("/api/reset/password", "POST", { identifier: resetId, otp: resetOtp,
      password: $("npPass").value, confirm: $("npPass2").value });
    if (!resetId.includes("@")) $("loginPhone").value = resetId;
    showAuth("authLogin"); setNote("Password badal gaya. Naye password se login karein.");
  } catch (e) { setMsg(e.message); }
};

// Google login (account chooser: phone par jo Gmail hai wo dikhega)
window.addEventListener("load", async () => {
  try {
    const c = await api("/api/config");
    if (!c.google_client_id || !window.google) { show("gWrap", false); return; }
    google.accounts.id.initialize({ client_id: c.google_client_id, callback: onGoogle });
    google.accounts.id.renderButton($("gBtn"), { theme: "outline", size: "large", width: 320, text: "continue_with" });
  } catch (e) { show("gWrap", false); }
});
async function onGoogle(resp) {
  try { await api("/api/google", "POST", { credential: resp.credential }); enterApp(); }
  catch (e) { setMsg(e.message); }
}

$("logoutBtn").onclick = async () => { await api("/api/logout", "POST"); location.reload(); };

async function enterApp() {
  const me = await api("/api/me");
  $("who").textContent = me.name || me.email || "";
  state.mark = me.email || me.uid || "";
  show("authView", false); show("appView");
  loadSubjects(); loadHistory();
}

// ---------- TABS ----------
function activateTab(id) {
  document.querySelectorAll(".bottomnav button").forEach(b => b.classList.toggle("active", b.dataset.tab === id));
  document.querySelectorAll(".tab").forEach(t => show(t.id, t.id === id));
  if (id === "scoreTab") loadHistory();
  if (id === "planTab") loadPlan();
}
document.querySelectorAll(".bottomnav button").forEach(b => b.onclick = () => activateTab(b.dataset.tab));

function paywall(e) {
  if (e.status === 402) { alert(e.message); activateTab("planTab"); return true; }
  alert(e.message); return false;
}

// ---------- SUBJECT -> CHAPTER ----------
async function loadSubjects() {
  show("chapterBox", false); show("subjectList");
  const list = await api("/api/subjects");
  $("subjectList").innerHTML = list.map(s =>
    `<button class="subj" data-key="${esc(s.key)}">${esc(s.name)}<small>${s.chapters} chapter</small></button>`).join("");
  document.querySelectorAll(".subj").forEach(b => b.onclick = () => openChapters(b.dataset.key));
}

async function openChapters(key) {
  const d = await api(`/api/chapters/${key}`);
  state.subject = key;
  $("chapTitle").textContent = d.subject;
  $("chapterList").innerHTML = d.chapters.length ? d.chapters.map(c => `
    <div class="chap">
      <div class="chap-name">${esc(c.name)}${c.locked ? '<span class="lock">Subscription chahiye</span>' : ""}
        <small>${c.fresh} naye sawal · 50 quiz · 40 min</small></div>
      <div class="chap-actions">
        <button data-quiz="${esc(c.name)}">Quiz</button>
        <button class="ghost" data-notes="${esc(c.name)}">Notes</button>
      </div>
    </div>`).join("") : "<p class='muted'>Is subject ke chapter abhi add nahi hue hain.</p>";
  document.querySelectorAll("[data-quiz]").forEach(b => b.onclick = () => startChapter(b.dataset.quiz));
  document.querySelectorAll("[data-notes]").forEach(b => b.onclick = () => loadNotes(b.dataset.notes));
  show("notesBox", false);
  show("subjectList", false); show("chapterBox");
}

$("chapBackBtn").onclick = () => loadSubjects();

async function loadNotes(chapter) {
  try {
    const rows = await api(`/api/materials?subject=${encodeURIComponent(state.subject)}&chapter=${encodeURIComponent(chapter)}`);
    $("notesBox").innerHTML = `<h3>Notes: ${esc(chapter)}</h3>` + (rows.length
      ? rows.map(r => `<button class="note-link" data-pdf="${r.id}" data-title="${esc(r.title)}">${esc(r.title)}</button>`).join("")
      : "<p class='muted'>Is chapter ke notes abhi nahi hain.</p>");
    show("notesBox");
    document.querySelectorAll("[data-pdf]").forEach(b => b.onclick = () => openPdf(Number(b.dataset.pdf), b.dataset.title));
  } catch (e) { paywall(e); }
}

async function startChapter(name) {
  try {
    const d = await api(`/api/quiz/${state.subject}?chapter=${encodeURIComponent(name)}`);
    state.chapterIndex = name;
    $("subjectName").textContent = `${d.subject} · ${d.chapter}`;
    beginExam("quiz", d.questions, d.time_limit || QUIZ_SECONDS);
  } catch (e) { paywall(e); }
}

// ---------- MOCK ----------
$("mockStartBtn").onclick = async () => {
  try {
    const d = await api("/api/mock");
    activateTab("quizTab");
    $("subjectName").textContent = "Mock test";
    beginExam("mock", d.questions, d.time_limit);
  } catch (e) { paywall(e); }
};

// ---------- EXAM ----------
function beginExam(mode, questions, seconds) {
  Object.assign(state, { mode, questions, index: 0, answers: {}, timeLeft: seconds, limit: seconds });
  show("subjectList", false); show("chapterBox", false); show("resultBox", false); show("quizBox");
  updateTimer();
  clearInterval(state.timerId);
  state.timerId = setInterval(tick, 1000);
  renderQuestion();
}

function updateTimer() {
  const t = Math.max(state.timeLeft, 0);
  $("timer").textContent = `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`;
  $("timer").classList.toggle("low", state.timeLeft <= 60);
}

function tick() {
  state.timeLeft--;
  updateTimer();
  if (state.timeLeft <= 0) { alert("Time khatam! Score submit ho raha hai."); submitExam(true); }
}

function renderQuestion() {
  const q = state.questions[state.index];
  const label = state.mode === "mock" ? `${q.subject} · ` : "";
  $("qNo").textContent = `${label}Sawal ${state.index + 1} / ${state.questions.length}`;
  $("qText").textContent = q.q;
  $("progressBar").style.width = `${(state.index + 1) / state.questions.length * 100}%`;
  $("options").innerHTML = q.options.map((o, i) =>
    `<button class="opt ${state.answers[q.id] === i ? "picked" : ""}"><b>${LETTERS[i]}</b><span></span></button>`).join("");
  document.querySelectorAll(".opt").forEach((b, i) => {
    b.querySelector("span").textContent = q.options[i];
    b.onclick = () => { state.answers[q.id] = i; renderQuestion(); };
  });
  $("prevBtn").disabled = state.index === 0;
  $("nextBtn").disabled = state.index === state.questions.length - 1;
}

$("prevBtn").onclick = () => { state.index--; renderQuestion(); };
$("nextBtn").onclick = () => { state.index++; renderQuestion(); };
$("submitBtn").onclick = () => { if (confirm("Submit karein?")) submitExam(false); };
$("backBtn").onclick = () => {
  if (confirm("Exam chhodein? Score save nahi hoga.")) { clearInterval(state.timerId); leaveExam(); }
};

function leaveExam() {
  show("quizBox", false); show("resultBox", false);
  if (state.mode === "mock") activateTab("mockTab"); else show("chapterBox");
}

async function submitExam(timeUp) {
  clearInterval(state.timerId);
  const seconds = state.limit - Math.max(state.timeLeft, 0);
  const isMock = state.mode === "mock";
  try {
    const d = await api(isMock ? "/api/mock/submit" : "/api/submit", "POST",
      isMock ? { answers: state.answers, qids: state.questions.map(q => q.id), seconds }
             : { answers: state.answers, qids: state.questions.map(q => q.id), seconds });
    state.lastResult = { ...d, isMock, timeUp, stamp: new Date().toLocaleString() };
    showResult(state.lastResult);
    loadHistory();
  } catch (e) { paywall(e); }
}

function showResult(r) {
  state.lastResult = r;
  show("quizBox", false);
  const bySubject = r.isMock
    ? `<div class="card subjRow">${Object.entries(r.by_subject).map(([n, v]) =>
        `<div><span>${esc(n)}</span><b>${v.score} / ${v.total}</b></div>`).join("")}</div>` : "";
  const items = r.details.map((x, i) => `
      <div class="item">
        <div class="${x.chosen === x.correct ? "ok-t" : "bad-t"}">${x.subject ? esc(x.subject) + " · " : ""}Sawal ${i + 1}: ${x.chosen === x.correct ? "Sahi" : "Galat"} · Sahi jawab: ${LETTERS[x.correct]} (${esc(x.options[x.correct])})</div>
        <div class="qtext">${esc(x.q)}</div>
        <div class="sol"><b>Solution:</b> ${esc(x.solution)}</div>
        <div class="trick"><b>Shortcut trick:</b> ${esc(x.trick)}</div>
      </div>`).join("");
  $("resultBox").innerHTML = `
    <div class="card">
      <p class="muted">${r.timeUp ? "Time khatam ho gaya. " : ""}${r.isMock ? "Mock test ka result" : "Aapka result"}</p>
      <div class="score">${r.score} / ${r.total}</div>
      <p class="muted">Score save ho gaya.</p>
    </div>
    ${bySubject}
    ${true ? `<button id="pdfBtn" class="ghost">PDF download karein</button>
      <p class="muted">Print window me "Save as PDF" choose karein.</p>` : ""}
    <div class="review">${items}</div>
    <button id="resultBtn" class="gold">${r.isMock ? "Naya mock test" : "Aur chapter"}</button>`;
  show("resultBox");
  $("pdfBtn").onclick = () => downloadPdf(state.lastResult);
  $("resultBtn").onclick = () => {
    show("resultBox", false);
    if (state.fromDash) { state.fromDash = false; activateTab("scoreTab"); } else if (r.isMock) activateTab("mockTab"); else show("chapterBox");
  };
}

function downloadPdf(r) {
  const body = r.details.map((x, i) => `
    <div class="q">
      <p class="sub">${esc(x.subject || "")} · Sawal ${i + 1}</p>
      <p class="qt">${esc(x.q)}</p>
      ${x.options.map((o, j) => `<p class="${j === x.correct ? "right" : j === x.chosen ? "wrong" : ""}">${LETTERS[j]}. ${esc(o)}</p>`).join("")}
      <p>Aapka jawab: ${x.chosen == null ? "Nahi diya" : LETTERS[x.chosen]} · Sahi jawab: ${LETTERS[x.correct]}</p>
      <p><b>Solution:</b> ${esc(x.solution)}</p>
      <p><b>Shortcut trick:</b> ${esc(x.trick)}</p>
    </div>`).join("");
  const table = Object.entries(r.by_subject || {}).map(([n, v]) => `<tr><td>${esc(n)}</td><td>${v.score} / ${v.total}</td></tr>`).join("");
  const html = `<!DOCTYPE html><html lang="hi"><head><meta charset="utf-8"><title>${esc(r.title || "Result")}</title><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+Oriya:wght@400;600&family=Noto+Sans+Devanagari:wght@400;600&display=swap">
  <style>body{font-family:'Noto Sans Oriya','Noto Sans Devanagari',system-ui,sans-serif;color:#222;padding:16px;font-size:14px;line-height:1.45}
  h1{font-size:20px} table{border-collapse:collapse;margin:10px 0} td{border:1px solid #aaa;padding:6px 12px}
  .q{border-bottom:1px solid #ddd;padding:10px 0} .q p{margin:3px 0} .sub{color:#666;font-size:12px} .qt{font-weight:bold}
  .right{color:#166534;font-weight:bold} .wrong{color:#991b1b;text-decoration:line-through}</style></head><body>
  <h1>Job Prep Coach - ${esc(r.title || "Result")}</h1>
  <p>${esc(r.stamp)}</p><h2>Total: ${r.score} / ${r.total}</h2>
  <table>${table}</table>${body}
  <script>window.onload=function(){setTimeout(function(){window.print();},400);};<\/script></body></html>`;
  const w = window.open("", "_blank");
  if (!w) { alert("Popup allow karein, phir dobara dabayein."); return; }
  w.document.open(); w.document.write(html); w.document.close();
}

// ---------- PLAN / SUBSCRIPTION ----------
async function loadPlan() {
  const s = await api("/api/subscription");
  $("subStatus").className = `card ${s.active ? "sub-active" : "sub-none"}`;
  $("subStatus").innerHTML = s.active
    ? `<b>Subscription active hai</b><div class="muted">${fmtDate(s.until * 1000)} tak valid</div>`
    : `<b>Abhi koi active subscription nahi hai</b><div class="muted">Plan chuniye aur payment karein. Pehla chapter free hai.</div>`;
  $("planList").innerHTML = Object.entries(s.plans).map(([k, p], i) =>
    `<label class="plan"><input type="radio" name="plan" value="${k}" ${i === 0 ? "checked" : ""}>
     <div>${esc(p.label)} <span>₹${p.amount}</span></div></label>`).join("");
  $("qrImg").src = "/api/qr?t=" + Date.now();
  show("qrImg", true); show("qrFallback", false);
  $("payList").innerHTML = s.payments.length
    ? `<table><tr><th>Plan</th><th>UTR</th><th>Status</th></tr>${s.payments.map(p =>
        `<tr><td>${esc(p.plan)}</td><td><code>${esc(p.utr)}</code></td><td><span class="tag ${esc(p.status)}">${esc(p.status)}</span></td></tr>`).join("")}</table>`
    : "<p class='muted'>Abhi koi payment submit nahi hua.</p>";
}
$("qrImg").onerror = () => { show("qrImg", false); show("qrFallback", true); };

$("utrBtn").onclick = async () => {
  const plan = document.querySelector('input[name="plan"]:checked')?.value;
  try {
    await api("/api/subscribe", "POST", { plan, utr: $("utr").value });
    $("utr").value = "";
    $("planMsg").className = "muted"; $("planMsg").textContent = "Payment submit ho gaya. Admin check karke approve karega.";
    loadPlan();
  } catch (e) { $("planMsg").className = "error"; $("planMsg").textContent = e.message; }
};

// ---------- DASHBOARD (saare exam, har exam ka PDF save) ----------
async function loadHistory() {
  try {
    const rows = await api("/api/attempts");
    $("historyList").innerHTML = rows.length ? rows.map(r => `
      <div class="chap">
        <div class="chap-name">${esc(r.title)}<small>${r.kind === "mock" ? "Mock test" : "Chapter quiz"} · ${new Date(r.created * 1000).toLocaleString("hi-IN")}</small></div>
        <div class="chap-actions"><b>${r.score} / ${r.total}</b><button class="small" data-att="${r.id}">Dekhein / PDF</button></div>
      </div>`).join("") : "<p class='muted'>Abhi koi exam nahi diya. Quiz ya mock test shuru karein.</p>";
    document.querySelectorAll("[data-att]").forEach(b => b.onclick = () => openAttempt(b.dataset.att));
  } catch (e) { /* login se pehle */ }
}

async function openAttempt(id) {
  const a = await api("/api/attempt/" + id);
  state.fromDash = true;
  activateTab("quizTab");
  show("subjectList", false); show("chapterBox", false); show("quizBox", false);
  showResult({ ...a, isMock: a.kind === "mock", stamp: new Date(a.created * 1000).toLocaleString("hi-IN") });
}

// ---------- PDF VIEWER (app ke andar, download link nahi) ----------
if (window.pdfjsLib) pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
let pdfDoc = null, pdfPage = 1;

async function openPdf(id, title) {
  show("pdfViewer");
  $("pdfTitle").textContent = title;
  $("pdfPages").innerHTML = "<p class='muted'>PDF load ho rahi hai...</p>";
  try {
    const res = await fetch(`/api/material/${id}`);
    if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.error || "PDF nahi khuli"); }
    pdfDoc = await pdfjsLib.getDocument({ data: await res.arrayBuffer() }).promise;
    pdfPage = 1;
    await renderPdfPage();
  } catch (e) { $("pdfPages").innerHTML = `<p class="error">${esc(e.message)}</p>`; }
}

async function renderPdfPage() {
  const page = await pdfDoc.getPage(pdfPage);
  const cssW = Math.min(window.innerWidth - 24, 820);
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const base = page.getViewport({ scale: 1 });
  const vp = page.getViewport({ scale: (cssW * dpr) / base.width });
  const canvas = document.createElement("canvas");
  canvas.width = vp.width; canvas.height = vp.height;
  canvas.style.width = cssW + "px";
  await page.render({ canvasContext: canvas.getContext("2d"), viewport: vp }).promise;
  watermark(canvas);
  $("pdfPages").innerHTML = "";
  $("pdfPages").appendChild(canvas);
  $("pdfInfo").textContent = `${pdfPage} / ${pdfDoc.numPages}`;
  $("pdfPrev").disabled = pdfPage <= 1;
  $("pdfNext").disabled = pdfPage >= pdfDoc.numPages;
}

// Har page par user ka email/number halka sa likha hota hai, taaki leak hone par pata chale
function watermark(canvas) {
  const ctx = canvas.getContext("2d");
  ctx.save();
  ctx.globalAlpha = 0.13;
  ctx.fillStyle = "#1d4ed8";
  ctx.font = `${Math.round(canvas.width / 24)}px sans-serif`;
  ctx.translate(canvas.width / 2, canvas.height / 2);
  ctx.rotate(-Math.PI / 6);
  for (let y = -canvas.height; y < canvas.height; y += canvas.height / 6) ctx.fillText(state.mark || "Job Prep Coach", -canvas.width, y);
  ctx.restore();
}

$("pdfPrev").onclick = () => { if (pdfPage > 1) { pdfPage--; renderPdfPage(); } };
$("pdfNext").onclick = () => { if (pdfDoc && pdfPage < pdfDoc.numPages) { pdfPage++; renderPdfPage(); } };
$("pdfClose").onclick = () => { show("pdfViewer", false); $("pdfPages").innerHTML = ""; pdfDoc = null; };

// ---------- START ----------
(async () => {
  try {
    const me = await api("/api/me");
    if (me.uid) enterApp();
  } catch (e) { /* login screen */ }
})();
                                                
