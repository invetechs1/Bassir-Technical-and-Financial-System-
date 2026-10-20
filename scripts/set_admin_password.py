"""تعيين كلمة مرور جديدة لمستخدم من سطر الأوامر على الخادم (الافتراضي: azoom).

يُستخدم لإغلاق ثغرة كلمة المرور الافتراضية المعروفة، أو لاستعادة الدخول إن نُسيت.
تُطلب الكلمة مخفيةً مرتين (لا تظهر في سجل الأوامر):
    python scripts/set_admin_password.py
    python scripts/set_admin_password.py --user someone
"""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth import DEFAULT_ADMIN_USER, _hash_password, _verify_password  # noqa: E402
from app.config import DATA_DIR  # noqa: E402
from app.database import get_db  # noqa: E402

KNOWN_WEAK = {"Azoom@2026", "azoom", "password", "12345678", "admin123"}


def main() -> int:
    ap = argparse.ArgumentParser(description="تعيين كلمة مرور مستخدم")
    ap.add_argument("--user", default=DEFAULT_ADMIN_USER)
    args = ap.parse_args()
    with get_db() as db:
        row = db.execute("SELECT password_hash FROM users WHERE username = ?",
                         (args.user,)).fetchone()
    if not row:
        print(f"❌ لا يوجد مستخدم باسم {args.user}"); return 1
    pw = getpass.getpass("كلمة المرور الجديدة (12 حرفاً على الأقل): ")
    if len(pw) < 12 or pw in KNOWN_WEAK:
        print("❌ كلمة ضعيفة — 12 حرفاً على الأقل وليست من الكلمات المعروفة"); return 1
    if pw != getpass.getpass("أعد كتابتها: "):
        print("❌ الكلمتان غير متطابقتين"); return 1
    if _verify_password(pw, row["password_hash"]):
        print("❌ هي نفس الكلمة الحالية"); return 1
    with get_db() as db:
        db.execute("UPDATE users SET password_hash = ? WHERE username = ?",
                   (_hash_password(pw), args.user))
    note = DATA_DIR / "INITIAL_ADMIN_PASSWORD.txt"
    if note.exists():
        note.unlink()
        print("🧹 حُذف ملف كلمة المرور الأولى")
    print(f"✅ تغيّرت كلمة مرور {args.user}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
