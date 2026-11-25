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
        return err(f"Is chapter me naye sawal sirf {len(rows)
