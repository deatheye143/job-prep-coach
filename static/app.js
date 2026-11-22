const QUIZ_SECONDS = 600;   // chapter quiz ka timer (10 minute)
const LETTERS = "ABCD";
const state = { mode: "quiz", subject: null, chapterIndex: null, questions: [], index: 0, answers: {},
                timeLeft: 0, limit: 0, timerId: null, lastResult: null, phone: "" };
const $ = id => document.getElementById(id);
const show = (id, on = true) => $(id).classList.toggle("hidden", !on);
const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

async function api(url, method = "GET", body) {
  const res = await fetch(url, { method, headers: { "Content-Type": "application/json" },
                                 body: body ? JSON.stringify(body) : undefined });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "Kuch galat ho gaya");
  return data;
}

// ---------- LOGIN / REGISTER ----------
let authMode = "login";
$("authSwitch").onclick = () => {
  authMode = authMode === "login" ? "register" : "login";
  const isLogin = authMode === "login";
  $("authTitle").textContent = isLogin ? "Login karein" : "Naya account banayein";
  $("authBtn").textContent = isLogin ? "Login" : "Account banayein";
  $("authSwitch").textContent = isLogin ? "Naya account banana hai? Yahan dabayein" : "Pehle se account hai? Login karein";
  show("nameField", !isLogin);
  $("loginMsg").textContent = "";
};

$("authBtn").onclick = async () => {
  $("loginMsg").textContent = "";
  const phone = $("phone").value.trim();
  const body = { phone, password: $("password").value, name: $("name").value.trim() };
  try {
    await api(authMode === "login" ? "/api/login" : "/api/register", "POST", body);
    enterApp(phone);
  } catch (e) { $("loginMsg").textContent = e.message; }
};

$("logoutBtn").onclick = async () => { await api("/api/logout", "POST"); location.reload(); };

function enterApp(phone) {
  state.phone = phone;
  show("loginView", false); show("appView"); show("logoutBtn"); show("bottomNav");
  loadSubjects(); loadHistory();
}

// ---------- TABS ----------
function activateTab(id) {
  document.querySelectorAll("#bottomNav button").forEach(b => b.classList.toggle("active", b.dataset.tab === id));
  document.querySelectorAll(".tab").forEach(t => show(t.id, t.id === id));
  if (id === "scoreTab") loadHistory();
}
document.querySelectorAll("#bottomNav button").forEach(b => b.onclick = () => activateTab(b.dataset.tab));

// ---------- SUBJECT -> CHAPTER -> QUIZ ----------
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
  $("chapterList").innerHTML = d.chapters.length
    ? d.chapters.map(c => `<button class="chap" data-i="${c.index}">${esc(c.name)}<small>${c.count} sawal · 10 min</small></button>`).join("")
    : "<p class='muted'>Is subject ke chapter abhi add nahi hue hain.</p>";
  document.querySelectorAll(".chap").forEach(b => b.onclick = () => startChapter(Number(b.dataset.i)));
  show("subjectList", false); show("chapterBox");
}

$("chapBackBtn").onclick = () => loadSubjects();

async function startChapter(ci) {
  const d = await api(`/api/quiz/${state.subject}/${ci}`);
  state.chapterIndex = ci;
  $("subjectName").textContent = `${d.subject} · ${d.chapter}`;
  beginExam("quiz", d.questions, d.time_limit || QUIZ_SECONDS);
}

// ---------- MOCK TEST ----------
$("mockStartBtn").onclick = async () => {
  try {
    const d = await api("/api/mock");
    activateTab("quizTab");
    $("subjectName").textContent = "Mock test";
    beginExam("mock", d.questions, d.time_limit);
  } catch (e) { alert(e.message); }
};

// ---------- EXAM (chapter quiz aur mock dono) ----------
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
  if (state.timeLeft <= 0) { alert("Time khatam! Score submit ho raha hai, solution neeche dikhega."); submitExam(true); }
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
    b.querySelector("span").textContent = q.options[i];   // text safe rakhne ke liye
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
  if (state.mode === "mock") activateTab("mockTab");
  else show("chapterBox");
}

async function submitExam(timeUp) {
  clearInterval(state.timerId);
  const seconds = state.limit - Math.max(state.timeLeft, 0);
  const isMock = state.mode === "mock";
  try {
    const d = await api(isMock ? "/api/mock/submit" : "/api/submit", "POST",
      isMock ? { answers: state.answers, seconds }
             : { subject: state.subject, chapter: state.chapterIndex, answers: state.answers, seconds });
    state.lastResult = { ...d, isMock, timeUp, phone: state.phone, stamp: new Date().toLocaleString() };
    showResult(state.lastResult);
    loadHistory();
  } catch (e) { alert(e.message); }
}

function showResult(r) {
  show("quizBox", false);
  const bySubject = r.isMock
    ? `<div class="card subjRow">${Object.entries(r.by_subject).map(([n, v]) =>
        `<div><span>${esc(n)}</span><b>${v.score} / ${v.total}</b></div>`).join("")}</div>` : "";
  const items = r.details.map((x, i) => `
      <div class="item">
        <div class="${x.chosen === x.correct ? "ok" : "bad"}">${x.subject ? esc(x.subject) + " · " : ""}Sawal ${i + 1}: ${x.chosen === x.correct ? "Sahi" : "Galat"} · Sahi jawab: ${LETTERS[x.correct]} (${esc(x.options[x.correct])})</div>
        <div class="qtext">${esc(x.q)}</div>
        <div class="sol"><b>Solution:</b> ${esc(x.solution)}</div>
        <div class="trick"><b>Shortcut trick:</b> ${esc(x.trick)}</div>
      </div>`).join("");
  $("resultBox").innerHTML = `
    <div class="card">
      <p class="muted">${r.timeUp ? "Time khatam ho gaya. " : ""}${r.isMock ? "Mock test ka result" : "Aapka result"}</p>
      <div class="score">${r.score} / ${r.total}</div>
      <p class="muted">Score save ho gaya. Scores tab me dekh sakte hain.</p>
    </div>
    ${bySubject}
    ${r.isMock ? `<button id="pdfBtn" class="ghost">PDF download karein</button>
      <p class="muted">Jo print window khule usme "Save as PDF" choose karke phone me save karein.</p>` : ""}
    <div class="review">${items}</div>
    <button id="resultBtn" class="gold">${r.isMock ? "Naya mock test" : "Aur chapter"}</button>`;
  show("resultBox");
  if (r.isMock) $("pdfBtn").onclick = () => downloadPdf(state.lastResult);
  $("resultBtn").onclick = () => {
    show("resultBox", false);
    if (r.isMock) activateTab("mockTab"); else show("chapterBox");
  };
}

// ---------- PDF (phone par "Save as PDF" se) ----------
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
  const table = Object.entries(r.by_subject).map(([n, v]) =>
    `<tr><td>${esc(n)}</td><td>${v.score} / ${v.total}</td></tr>`).join("");
  const html = `<!DOCTYPE html><html lang="hi"><head><meta charset="utf-8"><title>Mock Test Result</title>
  <style>
    body{font-family:system-ui,sans-serif;color:#222;padding:16px;font-size:14px;line-height:1.45}
    h1{font-size:20px;margin:0 0 6px} table{border-collapse:collapse;margin:10px 0}
    td{border:1px solid #aaa;padding:6px 12px}
    .q{border-bottom:1px solid #ddd;padding:10px 0} .q p{margin:3px 0}
    .sub{color:#666;font-size:12px} .qt{font-weight:bold}
    .right{color:#17704a;font-weight:bold} .wrong{color:#b42318;text-decoration:line-through}
  </style></head><body>
  <h1>Job Prep Coach - Mock Test Result</h1>
  <p>Mobile: ${esc(r.phone)} · ${esc(r.stamp)}</p>
  <h2>Total: ${r.score} / ${r.total}</h2>
  <table>${table}</table>
  ${body}
  <script>window.onload = function () { setTimeout(function () { window.print(); }, 400); };<\/script>
  </body></html>`;
  const w = window.open("", "_blank");
  if (!w) { alert("Popup allow karein, phir dobara PDF dabayein."); return; }
  w.document.open(); w.document.write(html); w.document.close();
}

// ---------- CHATBOX ----------
$("sendChatBtn").onclick = sendChat;
$("chatText").addEventListener("keydown", e => { if (e.key === "Enter") sendChat(); });

async function sendChat() {
  const text = $("chatText").value.trim();
  if (!text) return;
  addBubble(text, "me");
  $("chatText").value = "";
  const wait = addBubble("Soch raha hoon...", "bot");
  try {
    const d = await api("/api/chat", "POST", { message: text });
    wait.textContent = d.reply;
  } catch (e) { wait.textContent = e.message; }
}

function addBubble(text, who) {
  const div = document.createElement("div");
  div.className = `bubble ${who}`;
  div.textContent = text;
  $("chatLog").appendChild(div);
  $("chatLog").scrollTop = $("chatLog").scrollHeight;
  return div;
}

// ---------- SCORES ----------
async function loadHistory() {
  try {
    const rows = await api("/api/history");
    $("historyList").innerHTML = rows.length
      ? `<table><tr><th>Subject</th><th>Score</th><th>Time</th></tr>${rows.map(r =>
          `<tr><td>${r.subject === "mock" ? "Mock test" : esc(r.subject)}</td><td>${r.score}/${r.total}</td><td>${new Date(r.created * 1000).toLocaleString()}</td></tr>`).join("")}</table>`
      : "<p>Abhi koi score nahi hai. Quiz khelein!</p>";
  } catch (e) { /* login se pehle chup rahe */ }
}

// ---------- START ----------
(async () => {
  try {
    const me = await api("/api/me");
    if (me.phone) enterApp(me.phone);
  } catch (e) { /* login screen dikhegi */ }
})();
