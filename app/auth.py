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
    settings = get_settings()
    secret = settings.get("auth_secret", "")
    if not secret:
        secret = secrets.token_hex(32)
        update_settings({"auth_secret": secret})
    return secret.encode()


def init_auth():
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
    _auth_secret()


def authenticate(username: str, password: str) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
    if row and _verify_password(password, row["password_hash"]):
        return {"username": row["username"], "display_name": row["display_name"], "role": row["role"]}
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
<title>الدخول — نظام عزوم</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"Segoe UI",Tahoma,sans-serif;min-height:100vh;display:flex;align-items:center;
  justify-content:center;background:linear-gradient(160deg,#175934,#2E9E5B)}
.box{background:#fff;border-radius:18px;padding:40px 36px;width:min(400px,92vw);
  box-shadow:0 20px 60px rgba(0,0,0,.35);text-align:center}
.logo{width:64px;height:64px;margin:0 auto 12px;border-radius:17px;background:#EAF4EC;color:#175934;
  display:flex;align-items:center;justify-content:center;font-size:30px;font-weight:800}
h1{font-size:22px;color:#175934;letter-spacing:1px}
p.sub{color:#888;font-size:12.5px;margin:6px 0 24px}
input{width:100%;padding:12px 14px;border:1px solid #ddd;border-radius:10px;font-family:inherit;
  font-size:14.5px;margin-bottom:12px;background:#faf8f4}
input:focus{outline:2px solid #2E9E5B;border-color:transparent}
button{width:100%;padding:13px;border:none;border-radius:10px;background:#1E6B3C;color:#fff;
  font-size:15px;font-weight:700;cursor:pointer;font-family:inherit}
button:hover{opacity:.92}
.err{color:#a33;font-size:13px;margin-top:12px;min-height:18px}
</style></head><body>
<form class="box" id="f">
  <div class="logo">⬡</div>
  <h1>AZOOM United Co.</h1>
  <p class="sub">نظام العروض الفنية والمالية — الدخول للمصرح لهم فقط</p>
  <input type="text" id="u" placeholder="اسم المستخدم" autocomplete="username" required>
  <input type="password" id="p" placeholder="كلمة المرور" autocomplete="current-password" required>
  <button type="submit">تسجيل الدخول</button>
  <div class="err" id="e"></div>
</form>
<script>
document.getElementById("f").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const res = await fetch("/api/login", {method:"POST",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify({username:document.getElementById("u").value,
                          password:document.getElementById("p").value})});
  if (res.ok) location.href = "/";
  else document.getElementById("e").textContent = "اسم المستخدم أو كلمة المرور غير صحيحة";
});
</script></body></html>"""
