"""طبقة المصادقة — لا وصول للنظام بدون اسم مستخدم وكلمة مرور.

- كلمات المرور تُخزن بتجزئة PBKDF2-SHA256 (200 ألف دورة + ملح عشوائي)
- الجلسات: رمز موقع HMAC في كوكي HttpOnly صلاحيته 12 ساعة
- المستخدم الافتراضي عند أول تشغيل: azoom / Azoom@2026 — غيّرها فوراً من الإعدادات
"""
import base64
import hashlib
import hmac
import secrets
import time

from .database import get_db, get_settings, now_iso, update_settings

SESSION_COOKIE = "azoom_session"
SESSION_HOURS = 12
DEFAULT_ADMIN = ("azoom", "Azoom@2026")

USERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name TEXT DEFAULT '',
    role TEXT DEFAULT 'admin',
    created_at TEXT NOT NULL
);
"""


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"{salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$", 1)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 200_000)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def _auth_secret() -> bytes:
    # سر المنصة يعيش في إعدادات الشركة 1 دائماً — التحقق من الرمز يسبق حل الشركة
    settings = get_settings(company_id=1)
    secret = settings.get("auth_secret", "")
    if not secret:
        secret = secrets.token_hex(32)
        update_settings({"auth_secret": secret}, company_id=1)
    return secret.encode()


def init_auth():
    from .database import ensure_memberships
    with get_db() as db:
        db.executescript(USERS_SCHEMA)
        has_users = db.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
        if not has_users:
            username, password = DEFAULT_ADMIN
            db.execute(
                "INSERT INTO users (username, password_hash, display_name, role, created_at) "
                "VALUES (?, ?, ?, 'admin', ?)",
                (username, _hash_password(password), "مدير النظام", now_iso()),
            )
    ensure_memberships()
    _auth_secret()


def get_user(username: str) -> dict | None:
    with get_db() as db:
        row = db.execute(
            "SELECT id, username, display_name, is_platform_admin, last_login_at "
            "FROM users WHERE username = ?", (username.strip(),)).fetchone()
    return dict(row) if row else None


def create_user(username: str, password: str, display_name: str = "") -> dict:
    """إنشاء مستخدم منصة (بلا عضويات) — يُستخدم في دعوات الشركات."""
    if len(password) < 8:
        raise ValueError("كلمة المرور 8 أحرف على الأقل")
    with get_db() as db:
        db.execute(
            "INSERT INTO users (username, password_hash, display_name, role, created_at) "
            "VALUES (?, ?, ?, 'member', ?)",
            (username.strip(), _hash_password(password), display_name, now_iso()),
        )
        row = db.execute("SELECT id, username, display_name FROM users WHERE username = ?",
                         (username.strip(),)).fetchone()
    return dict(row)


def authenticate(username: str, password: str) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
    if row and _verify_password(password, row["password_hash"]):
        with get_db() as db:
            db.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now_iso(), row["id"]))
        return {"id": row["id"], "username": row["username"],
                "display_name": row["display_name"], "role": row["role"]}
    return None


def change_password(username: str, old_password: str, new_password: str) -> bool:
    if len(new_password) < 8:
        return False
    if not authenticate(username, old_password):
        return False
    with get_db() as db:
        db.execute("UPDATE users SET password_hash = ? WHERE username = ?",
                   (_hash_password(new_password), username))
    return True


def create_session_token(username: str) -> str:
    expiry = int(time.time()) + SESSION_HOURS * 3600
    payload = f"{username}|{expiry}"
    sig = hmac.new(_auth_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}|{sig}".encode()).decode()


def verify_session_token(token: str | None) -> str | None:
    if not token:
        return None
    try:
        payload = base64.urlsafe_b64decode(token.encode()).decode()
        username, expiry, sig = payload.rsplit("|", 2)
        expected = hmac.new(_auth_secret(), f"{username}|{expiry}".encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected) or int(expiry) < time.time():
            return None
        return username
    except Exception:
        return None


LOGIN_PAGE = """<!DOCTYPE html>
<html lang="ar" dir="rtl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title id="pt">الدخول — نظام عزوم</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"Segoe UI",Tahoma,sans-serif;min-height:100vh;display:flex;align-items:center;
  justify-content:center;background:linear-gradient(160deg,#175934,#2E9E5B)}
.box{background:#fff;border-radius:18px;padding:40px 36px;width:min(400px,92vw);
  box-shadow:0 20px 60px rgba(0,0,0,.35);text-align:center;position:relative}
.lang-btn{position:absolute;top:14px;inset-inline-end:14px;background:#EAF4EC;color:#175934;
  border:none;border-radius:16px;padding:4px 12px;font-size:11px;font-weight:700;cursor:pointer;font-family:inherit}
.logo{width:64px;height:64px;margin:0 auto 12px;border-radius:17px;background:#EAF4EC;color:#175934;
  display:flex;align-items:center;justify-content:center;font-size:30px;font-weight:800}
h1{font-size:22px;color:#175934;letter-spacing:1px}
p.sub{color:#888;font-size:12.5px;margin:6px 0 24px}
input{width:100%;padding:12px 14px;border:1px solid #ddd;border-radius:10px;font-family:inherit;
  font-size:14.5px;margin-bottom:12px;background:#faf8f4}
input:focus{outline:2px solid #2E9E5B;border-color:transparent}
button[type=submit]{width:100%;padding:13px;border:none;border-radius:10px;background:#1E6B3C;color:#fff;
  font-size:15px;font-weight:700;cursor:pointer;font-family:inherit}
button[type=submit]:hover{opacity:.92}
.err{color:#a33;font-size:13px;margin-top:12px;min-height:18px}
</style></head><body>
<form class="box" id="f">
  <button type="button" class="lang-btn" id="langBtn">EN</button>
  <div class="logo">⬡</div>
  <h1>AZOOM United Co.</h1>
  <p class="sub" id="sub">نظام العروض الفنية والمالية — الدخول للمصرح لهم فقط</p>
  <input type="text" id="u" autocomplete="username" required>
  <input type="password" id="p" autocomplete="current-password" required>
  <button type="submit" id="submitBtn">تسجيل الدخول</button>
  <div class="err" id="e"></div>
  <a href="/signup" style="color:#2E9E5B;font-size:13px;display:block;margin-top:14px">شركة جديدة؟ سجّلوا تجربة مجانية 14 يوماً</a>
</form>
<script>
const L = {
  title: {ar:"الدخول — نظام عزوم", en:"Login — AZOOM"},
  sub: {ar:"نظام العروض الفنية والمالية — الدخول للمصرح لهم فقط", en:"Technical & Financial Proposals System — authorized access only"},
  user: {ar:"اسم المستخدم", en:"Username"},
  pass: {ar:"كلمة المرور", en:"Password"},
  submit: {ar:"تسجيل الدخول", en:"Log In"},
  err: {ar:"اسم المستخدم أو كلمة المرور غير صحيحة", en:"Incorrect username or password"},
  toggle: {ar:"English", en:"العربية"},
};
function lang() { return localStorage.getItem("azoom_lang") || "ar"; }
function applyLang() {
  const l = lang();
  document.documentElement.lang = l;
  document.documentElement.dir = l === "ar" ? "rtl" : "ltr";
  document.getElementById("pt").textContent = L.title[l];
  document.getElementById("sub").textContent = L.sub[l];
  document.getElementById("u").placeholder = L.user[l];
  document.getElementById("p").placeholder = L.pass[l];
  document.getElementById("submitBtn").textContent = L.submit[l];
  document.getElementById("langBtn").textContent = l === "ar" ? "EN" : "AR";
}
document.getElementById("langBtn").addEventListener("click", () => {
  localStorage.setItem("azoom_lang", lang() === "ar" ? "en" : "ar");
  applyLang();
});
applyLang();

document.getElementById("f").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const res = await fetch("/api/login", {method:"POST",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify({username:document.getElementById("u").value,
                          password:document.getElementById("p").value})});
  if (res.ok) location.href = "/";
  else document.getElementById("e").textContent = L.err[lang()];
});
</script></body></html>"""


SIGNUP_PAGE = """<!DOCTYPE html>
<html lang="ar" dir="rtl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>تسجيل شركة جديدة — منصة بصير</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"Segoe UI",Tahoma,sans-serif;min-height:100vh;display:flex;align-items:center;
  justify-content:center;background:linear-gradient(160deg,#175934,#2E9E5B);padding:20px}
.box{background:#fff;border-radius:18px;padding:36px 34px;width:min(460px,94vw);
  box-shadow:0 20px 60px rgba(0,0,0,.35)}
h1{font-size:20px;color:#175934;text-align:center;margin-bottom:4px}
p.sub{color:#888;font-size:12.5px;margin-bottom:20px;text-align:center;line-height:1.8}
label{font-size:12.5px;color:#4A5B51;display:block;margin:10px 0 4px}
input{width:100%;padding:11px 13px;border:1px solid #ddd;border-radius:10px;font-family:inherit;
  font-size:14px;background:#faf8f4}
input:focus{outline:2px solid #2E9E5B;border-color:transparent}
button{width:100%;padding:13px;border:none;border-radius:10px;background:#1E6B3C;color:#fff;
  font-size:15px;font-weight:700;cursor:pointer;font-family:inherit;margin-top:18px}
button:hover{opacity:.92}
.msg{font-size:13px;margin-top:12px;min-height:18px;text-align:center}
.msg.err{color:#a33}.msg.ok{color:#1E7D4F}
a{color:#2E9E5B;font-size:13px;display:block;text-align:center;margin-top:12px}
.powered{color:#6E9B7F;font-size:10px;text-align:center;margin-top:16px;direction:ltr}
</style></head><body>
<form class="box" id="f">
  <h1>تسجيل شركة جديدة</h1>
  <p class="sub">تجربة مجانية 14 يوماً — نظام العروض الفنية والمالية بعزل كامل لبيانات شركتك</p>
  <label>اسم الشركة *</label><input id="name" required>
  <label>السجل التجاري *</label><input id="cr" required>
  <label>النشاط</label><input id="sector" placeholder="مثال: المقاولات العامة">
  <label>اسم مستخدم مالك الحساب *</label><input id="user" autocomplete="off" required>
  <label>كلمة المرور * (8 أحرف فأكثر)</label><input id="pw" type="password" autocomplete="new-password" required>
  <button type="submit">إنشاء الحساب التجريبي</button>
  <div class="msg" id="m"></div>
  <a href="/login">لديكم حساب؟ تسجيل الدخول</a>
  <div class="powered">powered by Bassir Technology Company</div>
</form>
<script>
document.getElementById("f").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const m = document.getElementById("m");
  m.className = "msg";
  const res = await fetch("/api/signup", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({name: name.value, cr_no: cr.value, sector: sector.value,
                          owner_username: user.value, owner_password: pw.value})});
  const data = await res.json();
  if (res.ok) { m.className = "msg ok"; m.textContent = data.message; setTimeout(() => location.href = "/login", 1800); }
  else { m.className = "msg err"; m.textContent = data.detail || "تعذر التسجيل"; }
});
</script></body></html>"""
