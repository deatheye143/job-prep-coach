import os, json, sqlite3, time, urllib.request, urllib.error
from flask import Flask, request, jsonify, render_template, session
from werkzeug.security import generate_password_hash, check_password_hash
from questions import QUESTIONS, SUBJECTS

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")
DB_PATH = os.environ.get("DB_PATH", "coaching.db")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")   # Google AI Studio se free key
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
MOCK_SECONDS_PER_Q = 60  # mock test: 1 sawal = 1 minute

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS accounts (phone TEXT PRIMARY KEY, name TEXT, pw_hash TEXT, created INTEGER)")
        c.execute("""CREATE TABLE IF NOT EXISTS scores (id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT,
                     subject TEXT, score INTEGER, total INTEGER, seconds INTEGER, created INTEGER)""")

init_db()

def me_phone():
    return session.get("phone")

def not_logged_in():
    return jsonify(error="Pehle login karein"), 401

def save_score(phone, subject, score, total, seconds):
    with db() as c:
        c.execute("INSERT INTO scores (phone, subject, score, total, seconds, created) VALUES (?, ?, ?, ?, ?, ?)",
                  (phone, subject, score, total, seconds, int(time.time())))

def chapter_items(subject, ci):
    name, items = list(QUESTIONS[subject].items())[ci]
    return name, items

def valid_chapter(subject, ci):
    return subject in QUESTIONS and 0 <= ci < len(QUESTIONS[subject])

def score_items(entries, answers):
    # entries: (subject naam, question id, question data)
    details, score = [], 0
    for subj_name, qid, it in entries:
        chosen = answers.get(qid)
        score += int(chosen == it["answer"])
        details.append({"subject": subj_name, "q": it["q"], "options": it["options"], "chosen": chosen,
                        "correct": it["answer"], "solution": it["solution"], "trick": it["trick"]})
    return score, details

# ---------- LOGIN (phone + password) ----------
@app.route("/")
def index():
    return render_template("index.html")

@app.post("/api/register")
def register():
    d = request.json or {}
    phone = str(d.get("phone", "")).strip()
    pw = str(d.get("password", ""))
    name = str(d.get("name", "")).strip()[:40]
    if not (phone.isdigit() and len(phone) == 10):
        return jsonify(error="10 digit ka mobile number likhein"), 400
    if len(pw) < 6:
        return jsonify(error="Password kam se kam 6 akshar ka ho"), 400
    with db() as c:
        if c.execute("SELECT 1 FROM accounts WHERE phone = ?", (phone,)).fetchone():
            return jsonify(error="Ye number pehle se registered hai. Login karein."), 409
        c.execute("INSERT INTO accounts VALUES (?, ?, ?, ?)",
                  (phone, name, generate_password_hash(pw), int(time.time())))
    session["phone"] = phone
    return jsonify(ok=True)

@app.post("/api/login")
def login():
    d = request.json or {}
    phone = str(d.get("phone", "")).strip()
    pw = str(d.get("password", ""))
    with db() as c:
        row = c.execute("SELECT pw_hash FROM accounts WHERE phone = ?", (phone,)).fetchone()
    if not row or not check_password_hash(row["pw_hash"], pw):
        return jsonify(error="Number ya password galat hai"), 401
    session["phone"] = phone
    return jsonify(ok=True)

@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)

@app.get("/api/me")
def me():
    return jsonify(phone=me_phone())

# ---------- SUBJECTS, CHAPTERS, QUIZ ----------
@app.get("/api/subjects")
def subjects():
    return jsonify([{"key": k, "name": v, "chapters": len(QUESTIONS.get(k, {}))} for k, v in SUBJECTS.items()])

@app.get("/api/chapters/<subject>")
def chapters(subject):
    if not me_phone():
        return not_logged_in()
    if subject not in SUBJECTS:
        return jsonify(error="Subject nahi mila"), 404
    chs = QUESTIONS.get(subject, {})
    return jsonify(subject=SUBJECTS[subject],
                   chapters=[{"index": i, "name": n, "count": len(v)} for i, (n, v) in enumerate(chs.items())])

@app.get("/api/quiz/<subject>/<int:ci>")
def quiz(subject, ci):
    if not me_phone():
        return not_logged_in()
    if not valid_chapter(subject, ci):
        return jsonify(error="Chapter nahi mila"), 404
    name, items = chapter_items(subject, ci)
    qs = [{"id": f"{subject}|{ci}|{i}", "q": it["q"], "options": it["options"]} for i, it in enumerate(items)]
    return jsonify(subject=SUBJECTS[subject], chapter=name, questions=qs, time_limit=600)

@app.post("/api/submit")
def submit():
    phone = me_phone()
    if not phone:
        return not_logged_in()
    d = request.json or {}
    subject, ci = d.get("subject"), int(d.get("chapter", -1))
    if not valid_chapter(subject, ci):
        return jsonify(error="Chapter nahi mila"), 404
    _, items = chapter_items(subject, ci)
    entries = [(SUBJECTS[subject], f"{subject}|{ci}|{i}", it) for i, it in enumerate(items)]
    score, details = score_items(entries, d.get("answers", {}))
    save_score(phone, subject, score, len(items), int(d.get("seconds", 0)))
    return jsonify(score=score, total=len(items), details=details)

# ---------- MOCK TEST (sab subjects, sab chapters) ----------
@app.get("/api/mock")
def mock_start():
    if not me_phone():
        return not_logged_in()
    qs = [{"id": f"{s}|{ci}|{i}", "subject": SUBJECTS[s], "q": it["q"], "options": it["options"]}
          for s, chs in QUESTIONS.items()
          for ci, (_, items) in enumerate(chs.items())
          for i, it in enumerate(items)]
    return jsonify(questions=qs, time_limit=MOCK_SECONDS_PER_Q * len(qs))

@app.post("/api/mock/submit")
def mock_submit():
    phone = me_phone()
    if not phone:
        return not_logged_in()
    d = request.json or {}
    entries = [(SUBJECTS[s], f"{s}|{ci}|{i}", it)
               for s, chs in QUESTIONS.items()
               for ci, (_, items) in enumerate(chs.items())
               for i, it in enumerate(items)]
    score, details = score_items(entries, d.get("answers", {}))
    by_subject = {}
    for row in details:
        b = by_subject.setdefault(row["subject"], {"score": 0, "total": 0})
        b["total"] += 1
        b["score"] += int(row["chosen"] == row["correct"])
    save_score(phone, "mock", score, len(details), int(d.get("seconds", 0)))
    return jsonify(score=score, total=len(details), by_subject=by_subject, details=details)

@app.get("/api/history")
def history():
    phone = me_phone()
    if not phone:
        return not_logged_in()
    with db() as c:
        rows = c.execute("""SELECT subject, score, total, seconds, created FROM scores
                            WHERE phone = ? ORDER BY id DESC LIMIT 20""", (phone,)).fetchall()
    return jsonify([dict(r) for r in rows])

# ---------- CHATBOX (Google Gemini, free key) ----------
SYSTEM_PROMPT = ("Tum ek job preparation coach ho (Math, Reasoning, GS, English, Computer, Odia). "
                 "Student ke sawal ka sahi, saral jawab Hindi-English mix me do. "
                 "Agar MCQ ho to sahi option aur kyon, dono batao. Step by step samjhao aur ek shortcut trick bhi do.")

@app.post("/api/chat")
def chat():
    if not me_phone():
        return not_logged_in()
    text = str((request.json or {}).get("message", "")).strip()
    if not text:
        return jsonify(error="Sawal likhein"), 400
    if not GEMINI_KEY:
        return jsonify(reply="Chat abhi set nahi hai. Render me GEMINI_API_KEY set karein (Google AI Studio se free key milti hai).")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    body = json.dumps({"systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                       "contents": [{"role": "user", "parts": [{"text": text}]}]}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json",
                                                          "x-goog-api-key": GEMINI_KEY})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            out = json.load(r)
        parts = out["candidates"][0]["content"]["parts"]
        reply = "".join(p.get("text", "") for p in parts).strip()
        return jsonify(reply=reply or "Jawab khaali aaya. Sawal thoda badal kar likhein.")
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            return jsonify(error="Free limit khatam ya key me dikkat hai. Thodi der baad try karein, ya nayi key lein."), 502
        return jsonify(error="AI se jawab nahi aaya, thodi der baad try karein"), 502
    except Exception:
        return jsonify(error="AI se jawab nahi aaya, thodi der baad try karein"), 502

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
