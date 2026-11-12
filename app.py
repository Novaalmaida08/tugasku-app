"""
TugasKu - Website pengumpulan tugas kuliah
Stack: Python (Flask) + SQLite
Jalankan: python app.py  ->  http://localhost:5000
"""
import os, re, json, sqlite3, secrets, shutil, urllib.request
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import urlencode, urlparse
from zoneinfo import ZoneInfo

from flask import (Flask, g, render_template, request, redirect, url_for,
                   session, flash, send_from_directory, abort, jsonify)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "tugasku.db")
UPLOAD_DIR = os.path.join(BASE, "uploads")
TZ = ZoneInfo("Asia/Jakarta")

DAYS = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
MONTHS_FULL = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
               "Agustus", "September", "Oktober", "November", "Desember"]
ALLOWED_EXT = {"pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "txt", "zip", "rar",
               "png", "jpg", "jpeg", "py", "ipynb", "csv", "md", "java", "c", "cpp", "html"}
ABSENSI_URL = "https://sso.umc.ac.id/dashboard"

# ---- Konfigurasi SSO (diisi lewat environment variable, lihat README) ----
SSO = {k: os.environ.get(f"SSO_{k}", "") for k in
       ("AUTHORIZE_URL", "TOKEN_URL", "USERINFO_URL", "CLIENT_ID", "CLIENT_SECRET")}


def sso_enabled():
    return all(SSO.values())


def load_secret():
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    path = os.path.join(BASE, ".secret_key")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
    return open(path).read().strip()


app = Flask(__name__)
app.config.update(
    SECRET_KEY=load_secret(),
    MAX_CONTENT_LENGTH=25 * 1024 * 1024,  # 25 MB per file
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("HTTPS", "0") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(days=14),
)

# ------------------------------------------------------------------ DATABASE
SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, npm TEXT,
  password_hash TEXT, sso_sub TEXT UNIQUE,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS courses(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL, code TEXT, lecturer TEXT, color TEXT DEFAULT '#6366f1');
CREATE TABLE IF NOT EXISTS schedules(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  day INTEGER NOT NULL, start_time TEXT NOT NULL, end_time TEXT NOT NULL, room TEXT);
CREATE TABLE IF NOT EXISTS tasks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  title TEXT NOT NULL, description TEXT, deadline TEXT NOT NULL,
  done INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS files(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
  original_name TEXT NOT NULL, stored_name TEXT NOT NULL, size INTEGER,
  uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_):
    db = g.pop("db", None)
    if db:
        db.close()


def q(sql, args=(), one=False):
    rows = get_db().execute(sql, args).fetchall()
    if one:
        return rows[0] if rows else None
    return rows


def ex(sql, args=()):
    db = get_db()
    cur = db.execute(sql, args)
    db.commit()
    return cur.lastrowid


def init_db():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    con.commit()
    con.close()


init_db()

# ------------------------------------------------------------------ HELPERS
def now():
    return datetime.now(TZ).replace(tzinfo=None)


def parse_dt(s):
    return datetime.strptime(s[:16], "%Y-%m-%dT%H:%M")


def rel_time(s):
    secs = int((parse_dt(s) - now()).total_seconds())
    past, secs = secs < 0, abs(secs)
    if secs < 3600:
        txt = f"{max(secs // 60, 1)} menit"
    elif secs < 86400:
        txt = f"{secs // 3600} jam"
    else:
        txt = f"{secs // 86400} hari"
    return f"Terlambat {txt}" if past else f"{txt} lagi"


def urgency(t):
    if t["done"]:
        return "done"
    d = parse_dt(t["deadline"]) - now()
    if d.total_seconds() < 0:
        return "overdue"
    if d <= timedelta(days=1):
        return "urgent"
    if d <= timedelta(days=3):
        return "soon"
    return "ok"


@app.template_filter("fmt_dt")
def fmt_dt(s):
    d = parse_dt(s)
    return f"{DAYS[d.weekday()][:3]}, {d.day} {MONTHS[d.month - 1]} {d.year} · {d.strftime('%H:%M')}"


@app.template_filter("fmt_size")
def fmt_size(n):
    n = n or 0
    for u in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f} {u}"
        n /= 1024
    return f"{n:.1f} GB"


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


@app.before_request
def csrf_protect():
    if request.method == "POST":
        if not session.get("_csrf") or session["_csrf"] != request.form.get("_csrf"):
            abort(400, "Token keamanan tidak valid. Muat ulang halaman.")


def current_user():
    if "user" not in g:
        uid = session.get("uid")
        g.user = q("SELECT * FROM users WHERE id=?", (uid,), one=True) if uid else None
    return g.user


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not current_user():
            return redirect(url_for("login"))
        return fn(*a, **kw)
    return wrapper


@app.context_processor
def inject():
    u = current_user()
    courses = q("SELECT * FROM courses WHERE user_id=? ORDER BY name", (u["id"],)) if u else []
    return dict(user=u, my_courses=courses, csrf_token=csrf_token, urgency=urgency,
                rel_time=rel_time, DAYS=DAYS, sso_enabled=sso_enabled(), ABSENSI_URL=ABSENSI_URL)


def owned(table, rid):
    row = q(f"SELECT * FROM {table} WHERE id=? AND user_id=?", (rid, current_user()["id"]), one=True)
    if not row:
        abort(404)
    return row


def back(default="dashboard"):
    ref = request.referrer
    if ref and urlparse(ref).netloc == request.host:
        return redirect(ref)
    return redirect(url_for(default))


def valid_time(s):
    return bool(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", s or ""))


# --------------------------------------------------------------------- AUTH
@app.route("/")
def index():
    return redirect(url_for("dashboard" if current_user() else "login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user():
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:80]
        npm = request.form.get("npm", "").strip()[:30]
        email = request.form.get("email", "").strip().lower()[:120]
        pw = request.form.get("password", "")
        if not name or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            flash("Nama dan email yang valid wajib diisi.", "error")
        elif len(pw) < 6:
            flash("Password minimal 6 karakter.", "error")
        elif q("SELECT 1 FROM users WHERE email=?", (email,), one=True):
            flash("Email sudah terdaftar. Silakan masuk.", "error")
        else:
            uid = ex("INSERT INTO users(name,email,npm,password_hash) VALUES(?,?,?,?)",
                     (name, email, npm, generate_password_hash(pw)))
            session.clear()
            session.permanent = True
            session["uid"] = uid
            flash(f"Akun berhasil dibuat. Selamat datang, {name}!", "success")
            return redirect(url_for("dashboard"))
    return render_template("auth.html", mode="register")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        ident = request.form.get("ident", "").strip().lower()
        pw = request.form.get("password", "")
        u = q("SELECT * FROM users WHERE lower(email)=? OR lower(npm)=?", (ident, ident), one=True)
        if u and u["password_hash"] and check_password_hash(u["password_hash"], pw):
            session.clear()
            session.permanent = True
            session["uid"] = u["id"]
            return redirect(url_for("dashboard"))
        flash("Email/NPM atau password salah.", "error")
    return render_template("auth.html", mode="login")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------- SSO (OAuth2)
@app.route("/sso/login")
def sso_login():
    if not sso_enabled():
        flash("SSO belum dikonfigurasi oleh admin. Lihat README (bagian SSO).", "error")
        return redirect(url_for("login"))
    state = secrets.token_urlsafe(16)
    session["sso_state"] = state
    params = dict(response_type="code", client_id=SSO["CLIENT_ID"],
                  redirect_uri=url_for("sso_callback", _external=True),
                  scope=os.environ.get("SSO_SCOPE", "openid profile email"), state=state)
    return redirect(SSO["AUTHORIZE_URL"] + "?" + urlencode(params))


@app.route("/sso/callback")
def sso_callback():
    if not sso_enabled() or request.args.get("state") != session.pop("sso_state", None):
        abort(400)
    try:
        body = urlencode(dict(grant_type="authorization_code", code=request.args.get("code", ""),
                              redirect_uri=url_for("sso_callback", _external=True),
                              client_id=SSO["CLIENT_ID"], client_secret=SSO["CLIENT_SECRET"])).encode()
        tok = json.load(urllib.request.urlopen(
            urllib.request.Request(SSO["TOKEN_URL"], data=body, headers={"Accept": "application/json"}), timeout=10))
        info = json.load(urllib.request.urlopen(
            urllib.request.Request(SSO["USERINFO_URL"], headers={"Authorization": "Bearer " + tok["access_token"]}),
            timeout=10))
    except Exception:
        flash("Gagal login via SSO. Coba lagi atau gunakan email/password.", "error")
        return redirect(url_for("login"))
    # Nama field bisa berbeda per kampus -> sesuaikan di sini
    sub = str(info.get("sub") or info.get("id") or info.get("nim") or info.get("email"))
    npm = str(info.get("nim") or info.get("npm") or info.get("preferred_username") or "")
    email = (info.get("email") or f"{sub}@sso.local").lower()
    name = info.get("name") or info.get("preferred_username") or sub
    u = q("SELECT * FROM users WHERE sso_sub=?", (sub,), one=True) or \
        q("SELECT * FROM users WHERE email=?", (email,), one=True)
    if u:
        ex("UPDATE users SET sso_sub=? WHERE id=?", (sub, u["id"]))
        uid = u["id"]
    else:
        uid = ex("INSERT INTO users(name,email,npm,sso_sub) VALUES(?,?,?,?)", (name, email, npm, sub))
    session.clear()
    session.permanent = True
    session["uid"] = uid
    return redirect(url_for("dashboard"))


# ---------------------------------------------------------------- DASHBOARD
@app.route("/dashboard")
@login_required
def dashboard():
    uid, n = current_user()["id"], now()
    today = q("""SELECT s.*, c.name course_name, c.color, c.lecturer FROM schedules s
                 JOIN courses c ON c.id=s.course_id
                 WHERE s.user_id=? AND s.day=? ORDER BY s.start_time""", (uid, n.weekday()))
    upcoming = q("""SELECT t.*, c.name course_name, c.color FROM tasks t JOIN courses c ON c.id=t.course_id
                    WHERE t.user_id=? AND t.done=0 ORDER BY t.deadline LIMIT 6""", (uid,))
    stats = dict(
        courses=q("SELECT COUNT(*) n FROM courses WHERE user_id=?", (uid,), one=True)["n"],
        pending=q("SELECT COUNT(*) n FROM tasks WHERE user_id=? AND done=0", (uid,), one=True)["n"],
        done=q("SELECT COUNT(*) n FROM tasks WHERE user_id=? AND done=1", (uid,), one=True)["n"],
        overdue=q("SELECT COUNT(*) n FROM tasks WHERE user_id=? AND done=0 AND deadline<?",
                  (uid, n.strftime("%Y-%m-%dT%H:%M")), one=True)["n"])
    label = f"{DAYS[n.weekday()]}, {n.day} {MONTHS_FULL[n.month - 1]} {n.year}"
    return render_template("dashboard.html", today=today, upcoming=upcoming, stats=stats,
                           today_label=label, now_time=n.strftime("%H:%M"))


# ------------------------------------------------------------------ COURSES
@app.route("/courses")
@login_required
def courses():
    rows = q("""SELECT c.*,
        (SELECT COUNT(*) FROM tasks t WHERE t.course_id=c.id AND t.done=0) pending,
        (SELECT COUNT(*) FROM files f WHERE f.course_id=c.id) nfiles
        FROM courses c WHERE c.user_id=? ORDER BY c.name""", (current_user()["id"],))
    return render_template("courses.html", rows=rows)


@app.post("/courses/add")
@login_required
def course_add():
    name = request.form.get("name", "").strip()[:80]
    color = request.form.get("color", "#6366f1")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        color = "#6366f1"
    if not name:
        flash("Nama mata kuliah wajib diisi.", "error")
        return back("courses")
    cid = ex("INSERT INTO courses(user_id,name,code,lecturer,color) VALUES(?,?,?,?,?)",
             (current_user()["id"], name, request.form.get("code", "").strip()[:20],
              request.form.get("lecturer", "").strip()[:80], color))
    flash(f"Folder “{name}” dibuat.", "success")
    return redirect(url_for("course_view", cid=cid))


@app.route("/courses/<int:cid>")
@login_required
def course_view(cid):
    c = owned("courses", cid)
    uid = current_user()["id"]
    tasks = q("""SELECT t.*, c.name course_name, c.color FROM tasks t JOIN courses c ON c.id=t.course_id
                 WHERE t.course_id=? AND t.user_id=? ORDER BY t.done, t.deadline""", (cid, uid))
    files = q("""SELECT f.*, t.title task_title FROM files f LEFT JOIN tasks t ON t.id=f.task_id
                 WHERE f.course_id=? AND f.user_id=? ORDER BY f.uploaded_at DESC""", (cid, uid))
    sched = q("SELECT * FROM schedules WHERE course_id=? ORDER BY day,start_time", (cid,))
    return render_template("course.html", c=c, tasks=tasks, files=files, sched=sched)


@app.post("/courses/<int:cid>/delete")
@login_required
def course_delete(cid):
    owned("courses", cid)
    ex("DELETE FROM courses WHERE id=?", (cid,))
    shutil.rmtree(os.path.join(UPLOAD_DIR, str(current_user()["id"]), str(cid)), ignore_errors=True)
    flash("Folder mata kuliah dihapus.", "success")
    return redirect(url_for("courses"))


@app.post("/courses/<int:cid>/upload")
@login_required
def upload(cid):
    owned("courses", cid)
    uid = current_user()["id"]
    f = request.files.get("file")
    if not f or not f.filename:
        flash("Pilih file terlebih dahulu.", "error")
        return back("courses")
    safe = secure_filename(f.filename)
    ext = safe.rsplit(".", 1)[-1].lower() if "." in safe else ""
    if ext not in ALLOWED_EXT:
        flash("Tipe file tidak diizinkan.", "error")
        return back("courses")
    folder = os.path.join(UPLOAD_DIR, str(uid), str(cid))
    os.makedirs(folder, exist_ok=True)
    stored = f"{secrets.token_hex(8)}.{ext}"
    path = os.path.join(folder, stored)
    f.save(path)
    tid = request.form.get("task_id", type=int)
    if tid and not q("SELECT 1 FROM tasks WHERE id=? AND user_id=? AND course_id=?", (tid, uid, cid), one=True):
        tid = None
    ex("INSERT INTO files(user_id,course_id,task_id,original_name,stored_name,size) VALUES(?,?,?,?,?,?)",
       (uid, cid, tid, os.path.basename(f.filename)[:150], stored, os.path.getsize(path)))
    if tid and request.form.get("mark_done"):
        ex("UPDATE tasks SET done=1 WHERE id=?", (tid,))
    flash("File berhasil diunggah ke folder.", "success")
    return redirect(url_for("course_view", cid=cid))


@app.route("/files/<int:fid>")
@login_required
def file_download(fid):
    f = owned("files", fid)
    folder = os.path.join(UPLOAD_DIR, str(f["user_id"]), str(f["course_id"]))
    return send_from_directory(folder, f["stored_name"], as_attachment=True, download_name=f["original_name"])


@app.post("/files/<int:fid>/delete")
@login_required
def file_delete(fid):
    f = owned("files", fid)
    try:
        os.remove(os.path.join(UPLOAD_DIR, str(f["user_id"]), str(f["course_id"]), f["stored_name"]))
    except OSError:
        pass
    ex("DELETE FROM files WHERE id=?", (fid,))
    flash("File dihapus.", "success")
    return back("courses")


# -------------------------------------------------------------------- TASKS
@app.route("/tasks")
@login_required
def tasks():
    flt = request.args.get("f", "active")
    uid, n = current_user()["id"], now().strftime("%Y-%m-%dT%H:%M")
    where = {"active": "AND t.done=0", "done": "AND t.done=1",
             "overdue": f"AND t.done=0 AND t.deadline<'{n}'", "all": ""}.get(flt, "AND t.done=0")
    rows = q(f"""SELECT t.*, c.name course_name, c.color FROM tasks t JOIN courses c ON c.id=t.course_id
                 WHERE t.user_id=? {where} ORDER BY t.done, t.deadline""", (uid,))
    return render_template("tasks.html", rows=rows, flt=flt)


@app.post("/tasks/add")
@login_required
def task_add():
    uid = current_user()["id"]
    cid = request.form.get("course_id", type=int)
    title = request.form.get("title", "").strip()[:120]
    deadline = request.form.get("deadline", "")
    try:
        parse_dt(deadline)
    except ValueError:
        deadline = ""
    if not (cid and q("SELECT 1 FROM courses WHERE id=? AND user_id=?", (cid, uid), one=True)) or not title or not deadline:
        flash("Lengkapi mata kuliah, judul, dan deadline tugas.", "error")
        return back("tasks")
    ex("INSERT INTO tasks(user_id,course_id,title,description,deadline) VALUES(?,?,?,?,?)",
       (uid, cid, title, request.form.get("description", "").strip()[:1000], deadline[:16]))
    flash("Tugas ditambahkan. Pengingat akan muncul otomatis.", "success")
    return back("tasks")


@app.post("/tasks/<int:tid>/toggle")
@login_required
def task_toggle(tid):
    t = owned("tasks", tid)
    ex("UPDATE tasks SET done=? WHERE id=?", (0 if t["done"] else 1, tid))
    return back("tasks")


@app.post("/tasks/<int:tid>/delete")
@login_required
def task_delete(tid):
    owned("tasks", tid)
    ex("DELETE FROM tasks WHERE id=?", (tid,))
    flash("Tugas dihapus.", "success")
    return back("tasks")


# ----------------------------------------------------------------- SCHEDULE
@app.route("/schedule")
@login_required
def schedule():
    rows = q("""SELECT s.*, c.name course_name, c.color, c.lecturer FROM schedules s
                JOIN courses c ON c.id=s.course_id WHERE s.user_id=? ORDER BY s.day, s.start_time""",
             (current_user()["id"],))
    by_day = {i: [] for i in range(7)}
    for r in rows:
        by_day[r["day"]].append(r)
    return render_template("schedule.html", by_day=by_day, today_idx=now().weekday())


@app.post("/schedule/add")
@login_required
def schedule_add():
    uid = current_user()["id"]
    cid = request.form.get("course_id", type=int)
    day = request.form.get("day", type=int)
    st, en = request.form.get("start_time", ""), request.form.get("end_time", "")
    ok = (cid and q("SELECT 1 FROM courses WHERE id=? AND user_id=?", (cid, uid), one=True)
          and day is not None and 0 <= day <= 6 and valid_time(st) and valid_time(en) and st < en)
    if not ok:
        flash("Data jadwal tidak valid (cek hari & jam).", "error")
        return back("schedule")
    ex("INSERT INTO schedules(user_id,course_id,day,start_time,end_time,room) VALUES(?,?,?,?,?,?)",
       (uid, cid, day, st, en, request.form.get("room", "").strip()[:40]))
    flash("Jadwal kuliah ditambahkan.", "success")
    return back("schedule")


@app.post("/schedule/<int:sid>/delete")
@login_required
def schedule_delete(sid):
    owned("schedules", sid)
    ex("DELETE FROM schedules WHERE id=?", (sid,))
    flash("Jadwal dihapus.", "success")
    return back("schedule")


# ------------------------------------------------------------ NOTIFIKASI API
@app.get("/api/notifications")
@login_required
def api_notifications():
    uid, n = current_user()["id"], now()
    day = n.strftime("%Y%m%d")
    items = []
    rows = q("""SELECT t.*, c.name course_name FROM tasks t JOIN courses c ON c.id=t.course_id
                WHERE t.user_id=? AND t.done=0 AND t.deadline<=? ORDER BY t.deadline""",
             (uid, (n + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M")))
    icons = {"overdue": "⛔", "urgent": "🔥", "soon": "⏰"}
    for t in rows:
        u = urgency(t)
        items.append(dict(key=f"t{t['id']}-{u}-{day}", level=u, icon=icons.get(u, "⏰"),
                          title=t["title"], text=f"{t['course_name']} · {rel_time(t['deadline'])}",
                          url=url_for("course_view", cid=t["course_id"])))
    for s in q("""SELECT s.*, c.name course_name FROM schedules s JOIN courses c ON c.id=s.course_id
                  WHERE s.user_id=? AND s.day=?""", (uid, n.weekday())):
        start = datetime.combine(n.date(), datetime.strptime(s["start_time"], "%H:%M").time())
        mins = int((start - n).total_seconds() // 60)
        if 0 <= mins <= 60:
            items.append(dict(key=f"c{s['id']}-{day}", level="class", icon="🎓",
                              title=f"Kuliah {s['course_name']}",
                              text=f"Mulai {s['start_time']} ({mins} menit lagi) · {s['room'] or '-'}",
                              url=url_for("schedule")))
    return jsonify(items=items)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)),
            debug=os.environ.get("FLASK_DEBUG", "0") == "1")
