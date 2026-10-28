"""طبيب الخادم — يفحص بنود «قائمة مهام المبرمج» على خادم الإنتاج ويقول ما بقي منها.

قراءة فقط: لا يغيّر شيئاً في القاعدة ولا الإعدادات. يُشغَّل من مجلد المشروع:
    .venv/bin/python scripts/server_doctor.py            # تقرير كامل
    .venv/bin/python scripts/server_doctor.py --offline  # بلا اتصال بالإنترنت
رمز الخروج: 0 لا شيء حرج، 1 يوجد بند حرج (كلمة مرور افتراضية / لا نسخ احتياطي...).
"""
import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# تحميل .env إن وُجد (الخدمة تحمّله عبر systemd، والسكربت يُشغَّل يدوياً)
_env = BASE_DIR / ".env"
if _env.exists():
    for _line in _env.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.lstrip().startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

from app.config import DATA_DIR  # noqa: E402

CRIT, WARN, OK = "CRITICAL", "WARN", "OK"
REPORT: list[tuple[str, str, str, str]] = []


def add(item: str, level: str, title: str, hint: str = ""):
    REPORT.append((item, level, title, hint))


def _git(*args) -> str:
    try:
        return subprocess.run(["git", *args], cwd=BASE_DIR, capture_output=True,
                              text=True, timeout=60).stdout.strip()
    except Exception:
        return ""


def check_code(offline: bool):
    head = _git("rev-parse", "--short", "HEAD")
    if not head:
        add("1", WARN, "ليس مستودع git — تعذّر التحقق من آخر نسخة"); return
    if not offline:
        _git("fetch", "-q", "origin", "main")
    behind = _git("rev-list", "--count", "HEAD..origin/main")
    if behind and behind != "0":
        add("1", CRIT, f"الكود متأخر {behind} commit عن main (HEAD={head})",
            "شغّل: bash scripts/server_update.sh")
    else:
        add("1", OK, f"الكود على آخر main ({head})")
    dirty = _git("status", "--porcelain", "--untracked-files=no")
    if dirty:
        add("2", WARN, "تعديلات محلية غير مرفوعة على الخادم — قد تُفقد عند التحديث",
            "اعرضها: git status — وارفعها عبر PR بدل تعديل الخادم مباشرة")


def check_admin_password():
    from app.auth import DEFAULT_ADMIN_USER, _verify_password
    from app.database import get_db
    try:
        with get_db() as db:
            row = db.execute("SELECT password_hash FROM users WHERE username = ?",
                             (DEFAULT_ADMIN_USER,)).fetchone()
    except Exception as exc:
        add("3", WARN, f"تعذّر قراءة جدول المستخدمين ({exc})"); return
    if row and _verify_password("Azoom@2026", row["password_hash"]):
        add("3", CRIT, "كلمة مرور المدير ما زالت الافتراضية المعروفة Azoom@2026",
            "شغّل: .venv/bin/python scripts/set_admin_password.py")
    else:
        add("3", OK, "كلمة مرور المدير ليست الافتراضية")
    if (DATA_DIR / "INITIAL_ADMIN_PASSWORD.txt").exists():
        add("3", WARN, "ملف INITIAL_ADMIN_PASSWORD.txt ما زال في data/",
            "غيّر الكلمة ثم احذف الملف")


def check_backup(max_age_hours: int, backup_dir: str):
    key = DATA_DIR / "secret.key"
    if key.exists():
        mode = key.stat().st_mode & 0o777
        if mode & 0o077:
            add("4", WARN, f"secret.key مقروء لغير المالك (صلاحيات {oct(mode)})",
                f"chmod 600 {key}")
    dirs = [Path(backup_dir)] if backup_dir else [BASE_DIR / "backups", Path("/var/backups/azoom")]
    archives = [f for d in dirs if d.exists() for f in d.glob("azoom-data-*.tgz")]
    if not archives:
        add("4", CRIT, "لا توجد أي نسخة احتياطية لمجلد data/",
            "شغّل: .venv/bin/python scripts/backup_data.py --remote user@host:/backups/ وأضِفه إلى cron")
        return
    newest = max(archives, key=lambda f: f.stat().st_mtime)
    age_h = (time.time() - newest.stat().st_mtime) / 3600
    if age_h > max_age_hours:
        add("4", CRIT, f"آخر نسخة احتياطية عمرها {age_h:.0f} ساعة ({newest.name})",
            "تحقق من مهمة cron الليلية")
    else:
        add("4", OK, f"آخر نسخة احتياطية قبل {age_h:.0f} ساعة ({newest.name})")


def check_secrets_in_repo():
    gi = (BASE_DIR / ".gitignore").read_text(encoding="utf-8") if (BASE_DIR / ".gitignore").exists() else ""
    tracked = _git("ls-files", ".env", "data")
    if tracked:
        add("5", CRIT, f"ملفات أسرار/بيانات مُتتبَّعة في git: {tracked.splitlines()[:3]}",
            "git rm --cached لها وأضفها إلى .gitignore")
    elif ".env" not in gi or "data" not in gi:
        add("5", WARN, ".gitignore لا يستثني .env أو data/")
    else:
        add("5", OK, ".env و data/ خارج git")


def check_ai(offline: bool):
    from app.config import ANTHROPIC_API_KEY
    if not ANTHROPIC_API_KEY:
        add("6", WARN, "ANTHROPIC_API_KEY غير مضبوط — المحرك يعمل بالقوالب لا بـ Claude",
            "أضفه إلى .env ثم: sudo systemctl restart azoom")
        return
    if not ANTHROPIC_API_KEY.startswith("sk-ant-"):
        add("6", WARN, "ANTHROPIC_API_KEY لا يبدأ بـ sk-ant- — تأكد من صحته")
    if offline:
        add("6", OK, "ANTHROPIC_API_KEY مضبوط (لم يُختبر الاتصال — وضع offline)"); return
    try:
        socket.create_connection(("api.anthropic.com", 443), timeout=8).close()
        add("6", OK, "ANTHROPIC_API_KEY مضبوط و api.anthropic.com متاح")
    except OSError as exc:
        add("6", CRIT, f"المفتاح مضبوط لكن api.anthropic.com محجوب ({exc})",
            "اسمح بالاتصال الصادر HTTPS إلى api.anthropic.com في الجدار الناري")


def check_lead_sources():
    from app.database import get_db
    try:
        with get_db() as db:
            rows = [dict(r) for r in db.execute(
                "SELECT company_id, name, url, enabled, last_result FROM lead_sources")]
    except Exception:
        add("7", WARN, "جدول مصادر الفرص غير موجود بعد — يُنشأ عند أول تشغيل"); return
    from app.leads import LEGACY_BROKEN_SOURCES
    active = [r for r in rows if r["enabled"]]
    broken = [r for r in active if r["url"] in LEGACY_BROKEN_SOURCES
              or (r["last_result"] or "").startswith("⚠️")]
    if not active:
        add("7", WARN, "لا مصادر رصد مفعّلة — افتح «فرص القطاع الخاص» ليُزرع الافتراضي")
    elif broken:
        names = "، ".join(sorted({r["name"] for r in broken})[:4])
        add("7", WARN, f"{len(broken)} مصدر مفعّل يفشل: {names}",
            "افتح «فرص القطاع الخاص ← مصادر الرصد» (الترقية تعطّل القديم المعطوب تلقائياً) أو استبدلها")
    else:
        add("7", OK, f"{len(active)} مصدر رصد مفعّل بلا أخطاء")


def check_forsah():
    from app.database import get_settings
    try:
        uses = bool(get_settings(company_id=1).get("forsah_email"))
    except Exception:
        uses = False
    try:
        import playwright  # noqa: F401
        has_pw = True
    except ImportError:
        has_pw = False
    browsers = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or Path.home() / ".cache/ms-playwright")
    has_chromium = browsers.exists() and any(browsers.glob("chromium*"))
    if not uses:
        add("8", OK, "فرصة غير مستخدمة — المتصفح الخفي غير مطلوب"); return
    if has_pw and has_chromium:
        add("8", OK, "فرصة مضبوطة والمتصفح الخفي مثبّت")
    else:
        add("8", WARN, "فرصة مضبوطة لكن المتصفح الخفي غير مثبّت",
            ".venv/bin/python -m playwright install --with-deps chromium")


def check_pdf_engine():
    """العرضان الفني والمالي PDF يُطبعان بـ Chromium — بدونه تعمل المعاينة وWord فقط."""
    try:
        from app.proposal_pdf import _chromium_pdf
        ok = _chromium_pdf("<html><body>ok</body></html>")[:4] == b"%PDF"
    except Exception as exc:
        ok, err = False, str(exc)[:80]
    else:
        err = ""
    if ok:
        add("PDF", OK, "محرك PDF (Chromium) جاهز — العرضان الفني والمالي بالتصميم الاحترافي")
    else:
        add("PDF", WARN, f"محرك PDF غير مثبت — تصدير PDF معطّل ({err})",
            ".venv/bin/python -m playwright install --with-deps chromium")


def check_disk():
    free_gb = shutil.disk_usage(DATA_DIR).free / 1024 ** 3
    if free_gb < 2:
        add("—", WARN, f"المساحة الحرة {free_gb:.1f} GB فقط على قرص البيانات")


def main() -> int:
    ap = argparse.ArgumentParser(description="فحص جاهزية خادم الإنتاج")
    ap.add_argument("--offline", action="store_true", help="بلا git fetch ولا اختبار اتصال")
    ap.add_argument("--backup-dir", default="", help="مجلد النسخ الاحتياطية إن لم يكن الافتراضي")
    ap.add_argument("--max-backup-age", type=int, default=36, help="ساعات")
    args = ap.parse_args()

    for fn in (lambda: check_code(args.offline), check_admin_password,
               lambda: check_backup(args.max_backup_age, args.backup_dir),
               check_secrets_in_repo, lambda: check_ai(args.offline),
               check_lead_sources, check_forsah, check_pdf_engine, check_disk):
        try:
            fn()
        except Exception as exc:
            add("?", WARN, f"تعذّر الفحص: {exc}")

    icon = {CRIT: "🔴", WARN: "🟡", OK: "✅"}
    print("===== طبيب خادم عزوم — بنود قائمة المهام =====")
    for item, level, title, hint in sorted(REPORT, key=lambda r: r[0]):
        print(f"{icon[level]} [{item}] {title}")
        if hint and level != OK:
            print(f"      ← {hint}")
    crit = sum(1 for r in REPORT if r[1] == CRIT)
    warn = sum(1 for r in REPORT if r[1] == WARN)
    print(f"\n===== حرج: {crit} • تنبيه: {warn} • سليم: {len(REPORT) - crit - warn} =====")
    return 1 if crit else 0


if __name__ == "__main__":
    sys.exit(main())
