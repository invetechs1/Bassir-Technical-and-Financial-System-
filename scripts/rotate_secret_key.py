"""تدوير مفتاح التشفير data/secret.key — يفك كل الأسرار المخزّنة بالمفتاح القديم
ويعيد تشفيرها بمفتاح جديد عشوائي، في معاملة واحدة.

لماذا؟ نسخة من secret.key كانت مرفوعة في المستودع؛ كل من قرأ المستودع يستطيع فك
الأسرار المشفّرة به (كلمة مرور SMTP، رمز واتساب، كلمة مرور فرصة). بعد التدوير يصبح
المفتاح المسرَّب بلا قيمة.

التشغيل على الخادم (خذ نسخة احتياطية أولاً — السكربت يحفظ القديم أيضاً):
    .venv/bin/python scripts/backup_data.py
    .venv/bin/python scripts/rotate_secret_key.py
    sudo systemctl restart azoom
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptography.fernet import Fernet, InvalidToken  # noqa: E402

from app.config import DATA_DIR  # noqa: E402
from app.database import _ENC_PREFIX, _SECRET_KEYS, get_db  # noqa: E402


def rotate(data_dir: Path = DATA_DIR) -> tuple[int, int]:
    """يُرجع (عدد الأسرار المُعاد تشفيرها، عدد غير القابلة للفك وتُركت كما هي)."""
    key_file = data_dir / "secret.key"
    if not key_file.exists():
        raise SystemExit("❌ لا يوجد data/secret.key — لا شيء لتدويره")
    old = Fernet(key_file.read_bytes().strip())
    new_key = Fernet.generate_key()
    new = Fernet(new_key)
    done = bad = 0
    marks = ",".join("?" * len(_SECRET_KEYS))
    with get_db() as db:
        rows = db.execute(f"SELECT company_id, key, value FROM settings WHERE key IN ({marks})",
                          tuple(_SECRET_KEYS)).fetchall()
        for r in rows:
            val = r["value"] or ""
            if not val.startswith(_ENC_PREFIX):
                continue
            try:
                plain = old.decrypt(val[len(_ENC_PREFIX):].encode())
            except InvalidToken:
                bad += 1
                continue
            db.execute("UPDATE settings SET value = ? WHERE company_id = ? AND key = ?",
                       (_ENC_PREFIX + new.encrypt(plain).decode(), r["company_id"], r["key"]))
            done += 1
        # المفتاح الجديد يُكتب قبل إنهاء المعاملة: إن فشلت الكتابة تُلغى التحديثات كلها
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        retired = data_dir / f"secret.key.retired-{stamp}"
        key_file.rename(retired)
        retired.chmod(0o600)
        tmp = data_dir / "secret.key.new"
        tmp.write_bytes(new_key)
        tmp.chmod(0o600)
        tmp.rename(key_file)
    return done, bad


if __name__ == "__main__":
    done, bad = rotate()
    print(f"✅ دُوِّر المفتاح — أُعيد تشفير {done} سراً")
    if bad:
        print(f"⚠️ {bad} سراً لم يُفك بالمفتاح القديم (كانت تالفة أصلاً) — أعد إدخالها من الإعدادات")
    print("احذف secret.key.retired-* بعد التأكد من عمل الإشعارات، ثم أعد تشغيل الخدمة.")
