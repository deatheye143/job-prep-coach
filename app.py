import os, json, hmac, random, threading, secrets, sqlite3, time, smtplib, urllib.request, urllib.parse
from functools import wraps
from email.message import EmailMessage
from flask import Flask, request, jsonify, render_template, session, Response
from werkzeug.security import generate_password_hash, check_password_hash
from questions import QUESTIONS, SUBJECTS
from syllabus import CHAPTERS, MOCK_PLAN
try:
    import psycopg2, psycopg2.extras
except ImportError:
    psycopg2 = None

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024
DATABASE_URL = os.environ.get("DATABASE_URL", "")   # Supabase ka URL (data permanent rehta hai)
DB_PATH = os.environ.get("DB_PATH", "coaching.db")  # DATABASE_URL na ho to local file
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
FAST2SMS_KEY = os.environ.get("FAST2SMS_KEY", "")
MOCK_SECONDS_PER_Q = 60
OTP_SECONDS = 300
PLANS = {"month": {"label": "1 mahina", "days": 30, "amount": 99},   # price yahan badal sakte hain
         "year": {"label": "1 saal", "days": 365, "amount": 799}}
INTEGRITY = (sqlite3.IntegrityError,) + ((psycopg2.IntegrityError,) if psycopg2 else ())

class DB:
    """Supabase (PostgreSQL) ya local SQLite, dono ke liye same code."""
    def __init__(self):
        self.pg = bool(DATABASE_URL)
        if self.pg:
            self.conn = psycopg2.connect(DATABASE_URL)
        else:
            self.conn = sqlite3.connect(DB_PATH)
            self.conn.row_factory = sqlite3.Row
    def q(self, sql, params=()):
        if self.pg:
            cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(sql.replace("?", "%s"), params)
            return cur
        return self.conn.execute(sql, params)
    def __enter__(self):
        return self
    def __exit__(self, et, ev, tb):
        try:
            if et:
                self.conn.rollback()
            else:
                self.conn.commit()
        finally:
            self.conn.close()
        return False

def db():
    return DB()

TABLES = [
    "CREATE TABLE IF NOT EXISTS members (phone TEXT PRIMARY KEY, name TEXT, email TEXT UNIQUE, pw_hash TEXT, created INTEGER)",
    "CREATE TABLE IF NOT EXISTS otps (id INTEGER PRIMARY KEY AUTOINCREMENT, target TEXT, purpose TEXT, code TEXT, expires INTEGER, payload TEXT)",
    "CREATE TABLE IF NOT EXISTS scores (id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT, subject TEXT, score INTEGER, total INTEGER, seconds INTEGER, created INTEGER)",
    "CREATE TABLE IF NOT EXISTS subs (uid TEXT PRIMARY KEY, until INTEGER)",
    "CREATE TABLE IF NOT EXISTS payments (id INTEGER PRIMARY KEY AUTOINCREMENT, uid TEXT, plan TEXT, amount INTEGER, utr TEXT, status TEXT, created INTEGER)",
    "CREATE TABLE IF NOT EXISTS materials (id INTEGER PRIMARY KEY AUTOINCREMENT, subject TEXT, chapter TEXT, title TEXT, filename TEXT, data BLOB, created INTEGER)",
    "CREATE TABLE IF NOT EXISTS questions (id INTEGER PRIMARY KEY AUTOINCREMENT, subject TEXT, chapter TEXT, q TEXT, options TEXT, answer INTEGER, solution TEXT, trick TEXT)",
    "CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v BLOB, mime TEXT)",
    "CREATE TABLE IF NOT EXISTS seen (uid TEXT, qid INTEGER, PRIMARY KEY (uid, qid))",
    "CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY AUTOINCREMENT, uid TEXT, kind TEXT, title TEXT, score REAL, total INTEGER, seconds INTEGER, created INTEGER, payload TEXT)",
]

def init_db():
    with db() as c:
        for sql in TABLES:
            if c.pg:
                sql = (sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
                          .replace(" INTEGER", " BIGINT").replace(" BLOB", " BYTEA"))
            c.q(sql)
        # Pehli baar: questions.py ke sawal database me daal do, taaki admin se edit ho sakein
        if c.q("SELECT COUNT(*) AS n FROM questions").fetchone()["n"] == 0:
            for s, chs in QUESTIONS.items():
                for ch, items in chs.items():
                    for it in items:
                        c.q("INSERT INTO questions (subject, chapter, q, options, answer, solution, trick) VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (s, ch, it["q"], json.dumps(it["options"], ensure_ascii=False), it["answer"],
                             it["solution"], it["trick"]))

init_db()

def err(msg, code=400):
    return jsonify(error=msg), code

def uid():
    return session.get("uid")

def valid_phone(p):
    return p.isdigit() and len(p) == 10

def find_member(ident):
    with db() as c:
        if "@" in ident:
            return c.q("SELECT * FROM members WHERE email = ?", (ident,)).fetchone()
        return c.q("SELECT * FROM members WHERE phone = ?", (ident,)).fetchone()

def set_setting(k, v, mime):
    with db() as c:
        c.q("DELETE FROM settings WHERE k = ?", (k,))
        c.q("INSERT INTO settings (k, v, mime) VALUES (?, ?, ?)", (k, v, mime))

def admin_only(fn):
    @wraps(fn)
    def wrapper(*a, **k):
        if not session.get("admin"):
            return err("Admin login karein", 401)
        return fn(*a, **k)
    return wrapper

# ---------- ADMIN PASSWORD ----------
def admin_pw_hash():
    with db() as c:
        row = c.q("SELECT v FROM settings WHERE k = 'admin_pw'").fetchone()
    return bytes(row["v"]).decode() if row else None

def admin_password_ok(pw):
    stored = admin_pw_hash()
    if stored:
        return check_password_hash(stored, pw)
    return bool(ADMIN_PASSWORD) and hmac.compare_digest(pw.encode(), ADMIN_PASSWORD.encode())

# ---------- SUBSCRIPTION ----------
def sub_until(u):
    if not u:
        return 0
    with db() as c:
        row = c.q("SELECT until FROM subs WHERE uid = ?", (u,)).fetchone()
    return row["until"] if row else 0

def is_active(u):
    return bool(u) and sub_until(u) > time.time()

def set_sub(u, until):
    with db() as c:
        c.q("DELETE FROM subs WHERE uid = ?", (u,))
        c.q("INSERT INTO subs (uid, until) VALUES (?, ?)", (u, until))

def can_open(ci):
    return ci == 0 or is_active(uid())   # har subject ka pehla chapter free

# ---------- QUESTIONS (database se) ----------
def bank():
    with db() as c:
        rows = c.q("SELECT * FROM questions ORDER BY id").fetchall()
    data = {}
    for r in rows:
        data.setdefault(r["subject"], {}).setdefault(r["chapter"], []).append(
            {"q": r["q"], "options": json.loads(r["options"]), "answer": r["answer"],
             "solution": r["solution"], "trick": r["trick"]})
    return data

def chapter_at(B, subject, ci):
    name = list(B[subject].keys())[ci]
    return name, B[subject][name]

def score_items(entries, answers):
    details, score = [], 0
    for subj_name, qid, it in entries:
        chosen = answers.get(qid)
        score += int(chosen == it["answer"])
        details.append({"subject": subj_name, "q": it["q"], "options": it["options"], "chosen": chosen,
                        "correct": it["answer"], "solution": it["solution"], "trick": it["trick"]})
    return score, details

def save_score(phone, subject, score, total, seconds):
    with db() as c:
        c.q("INSERT INTO scores (phone, subject, score, total, seconds, created) VALUES (?, ?, ?, ?, ?, ?)",
            (phone, subject, score, total, seconds, int(time.time())))

# ---------- OTP ----------
def new_otp(target, purpose, payload=None):
    code = f"{secrets.randbelow(10**6):06d}"
    with db() as c:
        c.q("DELETE FROM otps WHERE target = ? AND purpose = ?", (target, purpose))
        c.q("INSERT INTO otps (target, purpose, code, expires, payload) VALUES (?, ?, ?, ?, ?)",
            (target, purpose, code, int(time.time()) + OTP_SECONDS, json.dumps(payload or {})))
    return code

def check_otp(target, purpose, code):
    with db() as c:
        row = c.q("SELECT * FROM otps WHERE target = ? AND purpose = ?", (target, purpose)).fetchone()
    if row and row["code"] == code and time.time() <= row["expires"]:
        return row
    return None

def send_sms(phone, code):
    body = urllib.parse.urlencode({"route": "otp", "variables_values": code, "numbers": phone}).encode()
    req = urllib.request.Request("https://www.fast2sms.com/dev/bulkV2", data=body, headers={
        "authorization": FAST2SMS_KEY, "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=20) as r:
        out = json.load(r)
    if not out.get("return"):
        raise RuntimeError(str(out.get("message", "SMS nahi gaya")))

def send_email(to, code):
    msg = EmailMessage()
    msg["Subject"] = "Job Prep Coach - OTP"
    msg["From"] = SMTP_USER
    msg["To"] = to
    msg.set_content(f"Aapka OTP: {code}\n5 minute me expire ho jayega. Ye OTP kisi ko na batayein.")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as s:
        s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)

def send_otp(phone, email, code, email_only=False):
    if not email_only and FAST2SMS_KEY and phone:
        send_sms(phone, code)
        return "sms"
    if SMTP_USER and SMTP_PASS and email:
        send_email(email, code)
        return "email"
    return None

# ---------- PAGES ----------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/admin")
def admin_page():
    return render_template("admin.html")

@app.get("/api/config")
def config():
    return jsonify(google_client_id=GOOGLE_CLIENT_ID)

# ---------- USER LOGIN / SIGN UP / FORGOT ----------
@app.post("/api/login")
def login():
    d = request.json or {}
    phone = str(d.get("phone", "")).strip()
    with db() as c:
        row = c.q("SELECT pw_hash FROM members WHERE phone = ?", (phone,)).fetchone()
    if not row or not row["pw_hash"] or not check_password_hash(row["pw_hash"], str(d.get("password", ""))):
        return err("Number ya password galat hai", 401)
    session["uid"] = phone
    return jsonify(ok=True)

@app.post("/api/google")
def google_login():
    if not GOOGLE_CLIENT_ID:
        return err("Google login abhi set nahi hai", 503)
    token = str((request.json or {}).get("credential", ""))
    try:
        with urllib.request.urlopen("https://oauth2.googleapis.com/tokeninfo?id_token="
                                    + urllib.parse.quote(token), timeout=15) as r:
            info = json.load(r)
    except Exception:
        return err("Google login verify nahi hua", 401)
    if info.get("aud") != GOOGLE_CLIENT_ID or str(info.get("email_verified")).lower() != "true":
        return err("Google login verify nahi hua", 401)
    email = info["email"].lower()
    name = str(info.get("name", ""))[:40]
    with db() as c:
        row = c.q("SELECT phone FROM members WHERE email = ?", (email,)).fetchone()
        if row:
            key = row["phone"]
        else:
            key = "g:" + info["sub"]
            c.q("INSERT INTO members (phone, name, email, pw_hash, created) VALUES (?, ?, ?, ?, ?)",
                (key, name, email, "", int(time.time())))
    session["uid"] = key
    return jsonify(ok=True)

@app.post("/api/signup/start")
def signup_start():
    d = request.json or {}
    name = str(d.get("name", "")).strip()[:40]
    email = str(d.get("email", "")).strip().lower()
    phone = str(d.get("phone", "")).strip()
    pw, pw2 = str(d.get("password", "")), str(d.get("confirm", ""))
    if not name:
        return err("Naam likhein")
    if "@" not in email or "." not in email.split("@")[-1]:
        return err("Sahi email likhein")
    if not valid_phone(phone):
        return err("10 digit ka mobile number likhein")
    if len(pw) < 6:
        return err("Password kam se kam 6 akshar ka ho")
    if pw != pw2:
        return err("Password aur confirm password same nahi hain")
    with db() as c:
        if c.q("SELECT 1 FROM members WHERE phone = ? OR email = ?", (phone, email)).fetchone():
            return err("Ye number ya email pehle se registered hai. Login karein.", 409)
    code = new_otp(phone, "signup", {"name": name, "email": email, "pw_hash": generate_password_hash(pw)})
    try:
        channel = send_otp(phone, email, code)
    except Exception:
        return err("OTP bhejne me dikkat aayi, thodi der baad try karein", 502)
    return jsonify(ok=True, channel=channel, demo_otp=None if channel else code)

@app.post("/api/signup/verify")
def signup_verify():
    d = request.json or {}
    phone = str(d.get("phone", "")).strip()
    row = check_otp(phone, "signup", str(d.get("otp", "")).strip())
    if not row:
        return err("OTP galat hai ya expire ho gaya")
    p = json.loads(row["payload"])
    try:
        with db() as c:
            c.q("INSERT INTO members (phone, name, email, pw_hash, created) VALUES (?, ?, ?, ?, ?)",
                (phone, p["name"], p["email"], p["pw_hash"], int(time.time())))
            c.q("DELETE FROM otps WHERE target = ? AND purpose = 'signup'", (phone,))
    except INTEGRITY:
        return err("Ye number ya email pehle se registered hai. Login karein.", 409)
    session["uid"] = phone
    return jsonify(ok=True)

@app.post("/api/reset/start")
def reset_start():
    ident = str((request.json or {}).get("identifier", "")).strip().lower()
    acc = find_member(ident)
    if not acc or not acc["pw_hash"]:
        return err("Ye number ya email registered nahi hai", 404)
    code = new_otp(acc["phone"], "reset")
    try:
        channel = send_otp(acc["phone"], acc["email"], code, email_only="@" in ident)
    except Exception:
        return err("OTP bhejne me dikkat aayi, thodi der baad try karein", 502)
    return jsonify(ok=True, channel=channel, demo_otp=None if channel else code)

@app.post("/api/reset/verify")
def reset_verify():
    d = request.json or {}
    acc = find_member(str(d.get("identifier", "")).strip().lower())
    if not acc or not check_otp(acc["phone"], "reset", str(d.get("otp", "")).strip()):
        return err("OTP galat hai ya expire ho gaya")
    return jsonify(ok=True)

@app.post("/api/reset/password")
def reset_password():
    d = request.json or {}
    acc = find_member(str(d.get("identifier", "")).strip().lower())
    otp = str(d.get("otp", "")).strip()
    pw, pw2 = str(d.get("password", "")), str(d.get("confirm", ""))
    if not acc or not check_otp(acc["phone"], "reset", otp):
        return err("OTP galat hai ya expire ho gaya")
    if len(pw) < 6:
        return err("Password kam se kam 6 akshar ka ho")
    if pw != pw2:
        return err("New password aur confirm password same nahi hain")
    with db() as c:
        c.q("UPDATE members SET pw_hash = ? WHERE phone = ?", (generate_password_hash(pw), acc["phone"]))
        c.q("DELETE FROM otps WHERE target = ? AND purpose = 'reset'", (acc["phone"],))
    return jsonify(ok=True)

@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)

@app.get("/api/me")
def me():
    u = uid()
    name, email = "", ""
    if u:
        with db() as c:
            row = c.q("SELECT name, email FROM members WHERE phone = ?", (u,)).fetchone()
        if row:
            name, email = row["name"], row["email"]
    return jsonify(uid=u, name=name, email=email)

# ---------- SUBJECTS, CHAPTERS, QUIZ (har user ko fresh sawal, kabhi repeat nahi) ----------
QUIZ_SIZE = 50
QUIZ_SECONDS = 2400      # 40 minute
MOCK_SECONDS = 7200      # 120 minute (Odisha Police pattern)
MOCK_NEGATIVE = 0.25     # mock me galat jawab par marks katenge
FREE_CHAPTER_INDEX = 0   # har subject ka pehla chapter free

def chapter_names(subject):
    names = list(CHAPTERS.get(subject, []))
    with db() as c:
        rows = c.q("SELECT DISTINCT chapter FROM questions WHERE subject = ? ORDER BY chapter", (subject,)).fetchall()
    for r in rows:
        if r["chapter"] not in names:
            names.append(r["chapter"])
    return names

def qrow_dict(r):
    return {"id": r["id"], "subject": r["subject"], "chapter": r["chapter"], "q": r["q"],
            "options": json.loads(r["options"]), "answer": r["answer"],
            "solution": r["solution"], "trick": r["trick"]}

def fresh_rows(u, subject, chapter=None, n=None):
    sql = "SELECT * FROM questions WHERE subject = ? AND id NOT IN (SELECT qid FROM seen WHERE uid = ?)"
    params = [subject, u]
    if chapter is not None:
        sql += " AND chapter = ?"
        params.append(chapter)
    sql += " ORDER BY random()"
    if n is not None:
        sql += " LIMIT ?"
        params.append(n)
    with db() as c:
        return [qrow_dict(r) for r in c.q(sql, tuple(params)).fetchall()]

def fresh_count(u, subject, chapter):
    with db() as c:
        return c.q("""SELECT COUNT(*) AS n FROM questions WHERE subject = ? AND chapter = ?
                      AND id NOT IN (SELECT qid FROM seen WHERE uid = ?)""", (subject, chapter, u)).fetchone()["n"]

def mark_seen(u, ids):
    with db() as c:
        for qid in ids:
            c.q("INSERT INTO seen (uid, qid) VALUES (?, ?)", (u, qid))

def seen_ids(u, ids):
    if not ids:
        return set()
    with db() as c:
        rows = c.q("SELECT qid FROM seen WHERE uid = ? AND qid IN (" + ",".join("?" * len(ids)) + ")",
                   (u, *ids)).fetchall()
    return {r["qid"] for r in rows}

def rows_for_ids(ids):
    with db() as c:
        rows = [qrow_dict(r) for r in c.q("SELECT * FROM questions WHERE id IN (" + ",".join("?" * len(ids)) + ")",
                                          tuple(ids)).fetchall()]
    order = {qid: i for i, qid in enumerate(ids)}
    rows.sort(key=lambda r: order.get(r["id"], 0))
    return rows

def grade(rows, answers, negative=0.0):
    details, score, by_subject = [], 0.0, {}
    for r in rows:
        chosen = answers.get(str(r["id"]))
        ok = chosen == r["answer"]
        wrong = chosen is not None and not ok
        score += 1 if ok else (-negative if wrong else 0)
        name = SUBJECTS.get(r["subject"], r["subject"])
        b = by_subject.setdefault(name, {"score": 0, "total": 0})
        b["total"] += 1
        b["score"] += int(ok)
        details.append({"subject": name, "q": r["q"], "options": r["options"], "chosen": chosen,
                        "correct": r["answer"], "solution": r["solution"], "trick": r["trick"]})
    return round(score, 2), details, by_subject

def save_attempt(u, kind, title, score, total, seconds, payload):
    with db() as c:
        c.q("INSERT INTO attempts (uid, kind, title, score, total, seconds, created, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (u, kind, title, score, total, seconds, int(time.time()), json.dumps(payload, ensure_ascii=False)))

@app.get("/api/subjects")
def subjects():
    return jsonify([{"key": k, "name": v, "chapters": len(chapter_names(k))} for k, v in SUBJECTS.items()])

@app.get("/api/chapters/<subject>")
def chapters(subject):
    if not uid():
        return err("Pehle login karein", 401)
    if subject not in SUBJECTS:
        return err("Subject nahi mila", 404)
    names = chapter_names(subject)
    paid = is_active(uid())
    return jsonify(subject=SUBJECTS[subject], chapters=[
        {"index": i, "name": n, "fresh": fresh_count(uid(), subject, n),
         "locked": i != FREE_CHAPTER_INDEX and not paid} for i, n in enumerate(names)])

@app.get("/api/quiz/<subject>")
def quiz_start(subject):
    if not uid():
        return err("Pehle login karein", 401)
    chapter = request.args.get("chapter", "")
    names = chapter_names(subject)
    if subject not in SUBJECTS or chapter not in names:
        return err("Chapter nahi mila", 404)
    if names.index(chapter) != FREE_CHAPTER_INDEX and not is_active(uid()):
        return err("Ye chapter subscription me hai", 402)
    rows = fresh_rows(uid(), subject, chapter, QUIZ_SIZE)
    if len(rows) < QUIZ_SIZE:
        return err(f"Is chapter me naye sawal sirf {len(rows)} bache hain. Quiz ke liye {QUIZ_SIZE} chahiye. Admin naye sawal add karega.", 409)
    mark_seen(uid(), [r["id"] for r in rows])
    return jsonify(subject=SUBJECTS[subject], chapter=chapter, kind="quiz", time_limit=QUIZ_SECONDS,
                   questions=[{"id": r["id"], "q": r["q"], "options": r["options"]} for r in rows])

@app.post("/api/submit")
def submit():
    u = uid()
    if not u:
        return err("Pehle login karein", 401)
    d = request.json or {}
    ids = [int(x) for x in d.get("qids", [])]
    if not ids or len(seen_ids(u, ids)) != len(ids):
        return err("Ye exam aapke account se nahi hai", 403)
    rows = rows_for_ids(ids)
    score, details, _ = grade(rows, d.get("answers", {}))
    title = f"{SUBJECTS.get(rows[0]['subject'], '')} · {rows[0]['chapter']}"
    save_attempt(u, "quiz", title, score, len(rows), int(d.get("seconds", 0)),
                 {"title": title, "details": details, "by_subject": {}})
    return jsonify(score=score, total=len(rows), details=details, title=title, kind="quiz")

@app.get("/api/mock")
def mock_start():
    u = uid()
    if not u:
        return err("Pehle login karein", 401)
    if not is_active(u):
        return err("Mock test ke liye subscription chahiye", 402)
    picked, short = [], []
    for s, n in MOCK_PLAN.items():
        rows = fresh_rows(u, s, None, n)
        if len(rows) < n:
            short.append(f"{SUBJECTS.get(s, s)} {len(rows)}/{n}")
        picked += rows
    if short:
        return err("Mock test ke liye naye sawal kam hain: " + ", ".join(short) + ". Admin naye sawal add karega.", 409)
    random.shuffle(picked)
    mark_seen(u, [r["id"] for r in picked])
    return jsonify(kind="mock", title="Mock test", time_limit=MOCK_SECONDS,
                   questions=[{"id": r["id"], "subject": SUBJECTS.get(r["subject"], r["subject"]),
                               "q": r["q"], "options": r["options"]} for r in picked])

@app.post("/api/mock/submit")
def mock_submit():
    u = uid()
    if not u:
        return err("Pehle login karein", 401)
    if not is_active(u):
        return err("Mock test ke liye subscription chahiye", 402)
    d = request.json or {}
    ids = [int(x) for x in d.get("qids", [])]
    if not ids or len(seen_ids(u, ids)) != len(ids):
        return err("Ye exam aapke account se nahi hai", 403)
    rows = rows_for_ids(ids)
    score, details, by_subject = grade(rows, d.get("answers", {}), MOCK_NEGATIVE)
    save_attempt(u, "mock", "Mock test", score, len(rows), int(d.get("seconds", 0)),
                 {"title": "Mock test", "details": details, "by_subject": by_subject})
    return jsonify(score=score, total=len(rows), details=details, by_subject=by_subject,
                   title="Mock test", kind="mock")

@app.get("/api/attempts")
def attempts():
    u = uid()
    if not u:
        return err("Pehle login karein", 401)
    with db() as c:
        rows = c.q("SELECT id, kind, title, score, total, created FROM attempts WHERE uid = ? ORDER BY id DESC LIMIT 200",
                   (u,)).fetchall()
    return jsonify([dict(r) for r in rows])

@app.get("/api/attempt/<int:aid>")
def attempt(aid):
    u = uid()
    if not u:
        return err("Pehle login karein", 401)
    with db() as c:
        row = c.q("SELECT * FROM attempts WHERE id = ? AND uid = ?", (aid, u)).fetchone()
    if not row:
        return err("Exam nahi mila", 404)
    p = json.loads(row["payload"])
    return jsonify(id=row["id"], kind=row["kind"], title=row["title"], score=row["score"], total=row["total"],
                   created=row["created"], details=p.get("details", []), by_subject=p.get("by_subject", {}))

# ---------- NOTES (PDF) ----------
@app.get("/api/materials")
def materials():
    if not uid():
        return err("Pehle login karein", 401)
    if not is_active(uid()):
        return err("Notes ke liye subscription chahiye", 402)
    with db() as c:
        rows = c.q("SELECT id, title FROM materials WHERE subject = ? AND chapter = ? ORDER BY id",
                   (request.args.get("subject", ""), request.args.get("chapter", ""))).fetchall()
    return jsonify([dict(r) for r in rows])

@app.get("/api/material/<int:mid>")
def material(mid):
    if not is_active(uid()):
        return err("Notes ke liye subscription chahiye", 402)
    with db() as c:
        row = c.q("SELECT data FROM materials WHERE id = ?", (mid,)).fetchone()
    if not row:
        return err("File nahi mili", 404)
    return Response(bytes(row["data"]), mimetype="application/pdf", headers={"Content-Disposition": "inline"})

# ---------- SUBSCRIPTION (QR + UTR) ----------
@app.get("/api/subscription")
def subscription():
    if not uid():
        return err("Pehle login karein", 401)
    until = sub_until(uid())
    with db() as c:
        pays = [dict(r) for r in c.q("""SELECT plan, utr, status, created FROM payments
                    WHERE uid = ? ORDER BY id DESC LIMIT 5""", (uid(),)).fetchall()]
    return jsonify(active=until > time.time(), until=until, payments=pays, plans=PLANS)

@app.get("/api/qr")
def qr():
    if not uid():
        return err("Pehle login karein", 401)
    with db() as c:
        row = c.q("SELECT v, mime FROM settings WHERE k = 'qr'").fetchone()
    if not row:
        return err("QR abhi upload nahi hua", 404)
    return Response(bytes(row["v"]), mimetype=row["mime"])

@app.post("/api/subscribe")
def subscribe():
    if not uid():
        return err("Pehle login karein", 401)
    d = request.json or {}
    plan = str(d.get("plan", ""))
    utr = "".join(str(d.get("utr", "")).split()).upper()
    if plan not in PLANS:
        return err("Plan chuniye")
    if not (6 <= len(utr) <= 30) or not utr.isalnum():
        return err("UTR / transaction ID sahi likhein (6 se 30 akshar)")
    with db() as c:
        if c.q("SELECT 1 FROM payments WHERE utr = ?", (utr,)).fetchone():
            return err("Ye UTR pehle se submit ho chuka hai", 409)
        c.q("INSERT INTO payments (uid, plan, amount, utr, status, created) VALUES (?, ?, ?, ?, ?, ?)",
            (uid(), plan, PLANS[plan]["amount"], utr, "pending", int(time.time())))
    return jsonify(ok=True)

# ---------- ADMIN ----------
@app.post("/api/admin/login")
def admin_login():
    if not ADMIN_EMAIL:
        return err("Admin login set nahi hai. Render me ADMIN_EMAIL aur ADMIN_PASSWORD daalein.", 503)
    d = request.json or {}
    ok_email = hmac.compare_digest(str(d.get("email", "")).strip().lower().encode(), ADMIN_EMAIL.lower().encode())
    if not (ok_email and admin_password_ok(str(d.get("password", "")))):
        return err("Email ya password galat hai", 401)
    session["admin"] = True
    return jsonify(ok=True)

@app.post("/api/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return jsonify(ok=True)

@app.post("/api/admin/password")
@admin_only
def admin_password():
    d = request.json or {}
    if not admin_password_ok(str(d.get("current", ""))):
        return err("Purana password galat hai", 401)
    new, conf = str(d.get("new", "")), str(d.get("confirm", ""))
    if len(new) < 6:
        return err("Naya password kam se kam 6 akshar ka ho")
    if new != conf:
        return err("Naya password aur confirm same nahi hain")
    set_setting("admin_pw", generate_password_hash(new).encode(), "text/plain")
    return jsonify(ok=True)

@app.get("/api/admin/overview")
@admin_only
def admin_overview():
    now = time.time()
    with db() as c:
        users = [dict(r) for r in c.q("""SELECT m.phone AS uid, m.name, m.email, COALESCE(s.until, 0) AS until
                    FROM members m LEFT JOIN subs s ON s.uid = m.phone ORDER BY m.created DESC""").fetchall()]
        pays = [dict(r) for r in c.q("""SELECT p.id, p.uid, p.plan, p.amount, p.utr, p.status, p.created,
                    m.name, m.email FROM payments p LEFT JOIN members m ON m.phone = p.uid
                    ORDER BY p.id DESC LIMIT 200""").fetchall()]
        mats = [dict(r) for r in c.q("""SELECT id, subject, chapter, title, filename, created
                    FROM materials ORDER BY id DESC""").fetchall()]
        qr_up = c.q("SELECT 1 FROM settings WHERE k = 'qr'").fetchone() is not None
    with db() as c:
        cnt = {(r["subject"], r["chapter"]): r["n"] for r in c.q(
            "SELECT subject, chapter, COUNT(*) AS n FROM questions GROUP BY subject, chapter").fetchall()}
    coverage = [{"subject": sj, "chapter": n, "count": cnt.get((sj, n), 0)}
                for sj in SUBJECTS for n in chapter_names(sj)]
    for u in users:
        u["active"] = u["until"] > now
    return jsonify(users=users, payments=pays, materials=mats, qr_uploaded=qr_up, subjects=SUBJECTS, coverage=coverage,
                   total=len(users), active=sum(1 for u in users if u["active"]),
                   pending=sum(1 for p in pays if p["status"] == "pending"))

@app.get("/api/admin/chapters")
@admin_only
def admin_chapters():
    return jsonify(chapter_names(request.args.get("subject", "")))

@app.get("/api/admin/questions")
@admin_only
def admin_questions():
    with db() as c:
        rows = c.q("SELECT * FROM questions WHERE subject = ? ORDER BY id",
                   (request.args.get("subject", ""),)).fetchall()
    return jsonify([{"id": r["id"], "chapter": r["chapter"], "q": r["q"],
                     "options": json.loads(r["options"]), "answer": r["answer"],
                     "solution": r["solution"], "trick": r["trick"]} for r in rows])

def parse_question(d):
    subject = str(d.get("subject", ""))
    chapter = str(d.get("chapter", "")).strip()[:80]
    q = str(d.get("q", "")).strip()
    opts = [str(o).strip() for o in d.get("options", [])]
    try:
        ans = int(d.get("answer", -1))
    except (TypeError, ValueError):
        ans = -1
    if subject not in SUBJECTS:
        return None, "Subject chuniye"
    if not chapter:
        return None, "Chapter ka naam likhein"
    if not q:
        return None, "Sawal likhein"
    if len(opts) != 4 or not all(opts):
        return None, "Chaaron options bharein"
    if not 0 <= ans <= 3:
        return None, "Sahi option chuniye"
    return (subject, chapter, q, json.dumps(opts, ensure_ascii=False), ans,
            str(d.get("solution", "")).strip(), str(d.get("trick", "")).strip()), None

@app.post("/api/admin/question")
@admin_only
def admin_add_question():
    row, e = parse_question(request.json or {})
    if e:
        return err(e)
    with db() as c:
        c.q("INSERT INTO questions (subject, chapter, q, options, answer, solution, trick) VALUES (?, ?, ?, ?, ?, ?, ?)", row)
    return jsonify(ok=True)

@app.route("/api/admin/question/<int:qid>", methods=["PUT"])
@admin_only
def admin_edit_question(qid):
    row, e = parse_question(request.json or {})
    if e:
        return err(e)
    with db() as c:
        c.q("""UPDATE questions SET subject = ?, chapter = ?, q = ?, options = ?, answer = ?,
               solution = ?, trick = ? WHERE id = ?""", row + (qid,))
    return jsonify(ok=True)

@app.delete("/api/admin/question/<int:qid>")
@admin_only
def admin_delete_question(qid):
    with db() as c:
        c.q("DELETE FROM questions WHERE id = ?", (qid,))
    return jsonify(ok=True)

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

def insert_questions(subject, chapter, items):
    added = skipped = 0
    for it in items:
        if not isinstance(it, dict):
            skipped += 1
            continue
        row, e = parse_question({**it, "subject": subject, "chapter": chapter})
        if e:
            skipped += 1
            continue
        with db() as c:
            if c.q("SELECT 1 FROM questions WHERE subject = ? AND q = ?", (row[0], row[2])).fetchone():
                skipped += 1
                continue
            c.q("INSERT INTO questions (subject, chapter, q, options, answer, solution, trick) VALUES (?, ?, ?, ?, ?, ?, ?)", row)
        added += 1
    return added, skipped

@app.post("/api/admin/questions/bulk")
@admin_only
def admin_bulk():
    d = request.json or {}
    subject = str(d.get("subject", ""))
    chapter = str(d.get("chapter", "")).strip()[:80]
    items = d.get("items", [])
    if subject not in SUBJECTS or not chapter:
        return err("Subject aur chapter chuniye")
    if not isinstance(items, list) or not items:
        return err("Sawal ki list (JSON array) daalein")
    added, skipped = insert_questions(subject, chapter, items)
    return jsonify(added=added, skipped=skipped)

def generate_batch(subject, chapter, count):
    """AI se 'count' sawal banata hai aur DB me daalta hai. (added, skipped) return karta hai."""
    if not GEMINI_KEY:
        raise RuntimeError("GEMINI_API_KEY Render me set nahi hai")
    with db() as c:
        existing = [r["q"] for r in c.q("SELECT q FROM questions WHERE subject = ? AND chapter = ? ORDER BY id DESC LIMIT 25",
                                        (subject, chapter)).fetchall()]
    lang = ("Odia script (ଓଡ଼ିଆ ଲିପି) me. Sawal, options, solution aur trick sab Odia me"
            if subject == "odia" else "English me")
    prompt = (f"Tum Odisha ke competitive exams (OSSSC, Odisha Police Constable) ke liye MCQ bana rahe ho.\n"
              f"Subject: {SUBJECTS[subject]}. Chapter: {chapter}.\n"
              f"{count} sawal {lang} likho. Exam level ka ho. Koi passage ya comprehension na ho.\n"
              f"Har sawal ke 4 options hon, sirf ek sahi. answer = sahi option ka index (0,1,2,3). Jawab pehle khud check karo.\n"
              f"Ye sawal pehle se hain, inse alag naye sawal likho: {json.dumps(existing, ensure_ascii=False)}\n"
              "Sirf JSON array return karo, koi aur text nahi. Format:\n"
              '[{"q": "...", "options": ["...", "...", "...", "..."], "answer": 0, "solution": "...", "trick": "..."}]')
    body = json.dumps({"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                       "generationConfig": {"responseMimeType": "application/json"}}).encode("utf-8")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json",
                                                          "x-goog-api-key": GEMINI_KEY})
    with urllib.request.urlopen(req, timeout=120) as r:
        out = json.load(r)
    text = "".join(p.get("text", "") for p in out["candidates"][0]["content"]["parts"])
    items = json.loads(text)
    if not isinstance(items, list):
        items = []
    return insert_questions(subject, chapter, items)

@app.post("/api/admin/generate")
@admin_only
def admin_generate():
    d = request.json or {}
    subject = str(d.get("subject", ""))
    chapter = str(d.get("chapter", "")).strip()[:80]
    try:
        count = max(1, min(int(d.get("count", 15)), 15))
    except (TypeError, ValueError):
        count = 15
    if subject not in SUBJECTS or not chapter:
        return err("Subject aur chapter chuniye")
    try:
        added, skipped = generate_batch(subject, chapter, count)
    except RuntimeError as e:
        return err(str(e), 503)
    except Exception:
        return err("AI se sawal nahi bane. Thodi der baad try karein (free limit ho sakti hai).", 502)
    return jsonify(added=added, skipped=skipped)

# ---------- AUTO FILL: sab chapters ko 50 tak bharta hai (background me) ----------
FILL_PAUSE = float(os.environ.get("FILL_PAUSE", "4"))
FILL_TARGET = 50
FILL_ORDER = ["math", "reasoning", "gs", "english", "computer", "odia"]
FILL = {"running": False, "stop": False, "log": [], "current": ""}

def _fill_log(msg):
    FILL["log"] = (FILL["log"] + [msg])[-40:]

def _fill_worker():
    FILL["running"] = True
    FILL["stop"] = False
    try:
        for s in FILL_ORDER:
            for ch in chapter_names(s):
                fails = 0
                while not FILL["stop"]:
                    with db() as c:
                        n = c.q("SELECT COUNT(*) AS n FROM questions WHERE subject = ? AND chapter = ?",
                                (s, ch)).fetchone()["n"]
                    if n >= FILL_TARGET:
                        break
                    FILL["current"] = f"{SUBJECTS.get(s, s)} · {ch} ({n}/{FILL_TARGET})"
                    try:
                        added, _ = generate_batch(s, ch, 15)
                        _fill_log(f"{SUBJECTS.get(s, s)} · {ch}: +{added}")
                        fails = fails + 1 if added == 0 else 0
                    except Exception as e:
                        fails += 1
                        _fill_log(f"{ch}: error {str(e)[:70]}")
                        if fails < 3:
                            time.sleep(60)
                    if fails >= 3:
                        _fill_log(f"{ch}: baar-baar fail, is chapter ko chhod diya")
                        break
                    time.sleep(FILL_PAUSE)
            if FILL["stop"]:
                break
    finally:
        FILL["running"] = False
        FILL["current"] = "Ruka hua / khatam"

@app.post("/api/admin/fill/start")
@admin_only
def fill_start():
    if not GEMINI_KEY:
        return err("GEMINI_API_KEY Render me set nahi hai", 503)
    if FILL["running"]:
        return jsonify(ok=True, already=True)
    FILL["running"] = True
    threading.Thread(target=_fill_worker, daemon=True).start()
    return jsonify(ok=True)

@app.post("/api/admin/fill/stop")
@admin_only
def fill_stop():
    FILL["stop"] = True
    return jsonify(ok=True)

@app.get("/api/admin/fill/status")
@admin_only
def fill_status():
    return jsonify(running=FILL["running"], current=FILL["current"], log=FILL["log"][-15:])

@app.post("/api/admin/material")
@admin_only
def admin_material():
    f = request.files.get("file")
    subject = request.form.get("subject", "")
    chapter = request.form.get("chapter", "").strip()[:80]
    title = request.form.get("title", "").strip()[:80]
    if not f or not f.filename.lower().endswith(".pdf"):
        return err("Sirf PDF file upload karein")
    if subject not in SUBJECTS or not chapter:
        return err("Subject aur chapter chuniye")
    data = f.read()
    if not data.startswith(b"%PDF"):
        return err("Ye valid PDF nahi lagti")
    with db() as c:
        c.q("INSERT INTO materials (subject, chapter, title, filename, data, created) VALUES (?, ?, ?, ?, ?, ?)",
            (subject, chapter, title or f.filename, f.filename, data, int(time.time())))
    return jsonify(ok=True)

@app.delete("/api/admin/material/<int:mid>")
@admin_only
def admin_material_delete(mid):
    with db() as c:
        c.q("DELETE FROM materials WHERE id = ?", (mid,))
    return jsonify(ok=True)

@app.post("/api/admin/qr")
@admin_only
def admin_qr():
    f = request.files.get("file")
    if not f:
        return err("QR image chuniye")
    mime = f.mimetype or ""
    if mime not in ("image/png", "image/jpeg", "image/webp"):
        return err("PNG ya JPG image upload karein")
    set_setting("qr", f.read(), mime)
    return jsonify(ok=True)

@app.post("/api/admin/payment/<int:pid>")
@admin_only
def admin_payment(pid):
    action = (request.json or {}).get("action")
    with db() as c:
        p = c.q("SELECT * FROM payments WHERE id = ?", (pid,)).fetchone()
    if not p:
        return err("Payment nahi mila", 404)
    if p["status"] != "pending":
        return err("Ye payment pehle hi check ho chuka hai")
    if action == "approve":
        days = PLANS.get(p["plan"], PLANS["month"])["days"]
        until = int(max(time.time(), sub_until(p["uid"])) + days * 86400)
        set_sub(p["uid"], until)
        status = "approved"
    elif action == "reject":
        status = "rejected"
    else:
        return err("Action galat hai")
    with db() as c:
        c.q("UPDATE payments SET status = ? WHERE id = ?", (status, pid))
    return jsonify(ok=True)

@app.after_request
def harden(resp):
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    if request.path.startswith(("/api/material", "/api/qr")):
        resp.headers["Cache-Control"] = "private, no-store"
    return resp

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
