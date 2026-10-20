"""نسخة احتياطية لمجلد data/ — قاعدة البيانات وشعارات المستأجرين ومفتاح التشفير secret.key.

data/ خارج git عمداً، وضياع secret.key يعني ضياع كل الأسرار المشفّرة (SMTP، واتساب،
فرصة) بلا رجعة. هذا السكربت:
  - يأخذ لقطة متّسقة من قاعدة SQLite (واجهة backup الرسمية — آمنة والخدمة تعمل)
  - يضغط بقية data/ (عدا المؤقتات exports/) في أرشيف واحد مؤرَّخ
  - يحذف الأرشيفات الأقدم من --keep يوماً
  - ينسخ الأرشيف خارج الخادم إن مُرِّر --remote (rsync/scp مثل user@host:/backups/)

التشغيل:
    python scripts/backup_data.py                       # إلى backups/ بجانب المشروع
    python scripts/backup_data.py --dest /var/backups/azoom --keep 30 --remote user@host:/backups/azoom/
جدولة ليلية (crontab -e):
    15 2 * * * cd /opt/azoom && .venv/bin/python scripts/backup_data.py --dest /var/backups/azoom --remote user@host:/backups/azoom/ >> /var/log/azoom-backup.log 2>&1
"""
import argparse
import os
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("AZOOM_DATA_DIR") or (BASE_DIR / "data"))
SKIP_DIRS = {"exports"}          # ملفات تصدير مؤقتة يُعاد توليدها


def make_backup(data_dir: Path, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    archive = dest / f"azoom-data-{stamp}.tgz"
    db_file = data_dir / "azoom.db"
    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / "azoom.db"
        if db_file.exists():
            src = sqlite3.connect(db_file)
            dst = sqlite3.connect(snap)
            with dst:
                src.backup(dst)
            src.close(); dst.close()
        with tarfile.open(archive, "w:gz") as tar:
            for item in sorted(data_dir.iterdir()):
                if item.name in SKIP_DIRS or item.name.startswith("azoom.db"):
                    continue
                tar.add(item, arcname=f"data/{item.name}")
            if snap.exists():
                tar.add(snap, arcname="data/azoom.db")
    archive.chmod(0o600)           # يحوي secret.key — لا يقرؤه غير المالك
    return archive


def prune(dest: Path, keep_days: int) -> int:
    cutoff = time.time() - keep_days * 86400
    removed = 0
    for f in dest.glob("azoom-data-*.tgz"):
        if f.stat().st_mtime < cutoff:
            f.unlink(); removed += 1
    return removed


def main() -> int:
    ap = argparse.ArgumentParser(description="نسخة احتياطية لمجلد data/")
    ap.add_argument("--dest", default=str(BASE_DIR / "backups"))
    ap.add_argument("--keep", type=int, default=14, help="أيام الاحتفاظ محلياً")
    ap.add_argument("--remote", default="", help="هدف rsync خارج الخادم مثل user@host:/backups/")
    args = ap.parse_args()

    if not DATA_DIR.exists():
        print(f"❌ مجلد البيانات غير موجود: {DATA_DIR}"); return 1
    if not (DATA_DIR / "secret.key").exists():
        print("⚠️ لا يوجد data/secret.key — لا أسرار مشفّرة بعد أو المسار خاطئ")
    archive = make_backup(DATA_DIR, Path(args.dest))
    size = archive.stat().st_size / 1024 / 1024
    print(f"✅ النسخة: {archive} ({size:.1f} MB)")
    removed = prune(Path(args.dest), args.keep)
    if removed:
        print(f"🧹 حُذفت {removed} نسخة أقدم من {args.keep} يوماً")
    if args.remote:
        r = subprocess.run(["rsync", "-a", str(archive), args.remote])
        if r.returncode != 0:
            print(f"❌ فشل النسخ خارج الخادم إلى {args.remote}"); return 2
        print(f"✅ نُسخت خارج الخادم إلى {args.remote}")
    else:
        print("⚠️ النسخة على الخادم نفسه فقط — مرّر --remote لحفظها خارجه")
    return 0


if __name__ == "__main__":
    sys.exit(main())
