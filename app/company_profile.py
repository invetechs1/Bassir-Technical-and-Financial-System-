"""ملف الشركة التعريفي (Company Profile) ووسائطها — مصدر أقسام «عن الشركة» و«الخبرات».

لكل شركة ملف واحد (JSON بمخطط azoom_profile.json): النبذة، الرؤية والرسالة، القيم،
الاستراتيجية والاستدامة، الإنجازات، الخدمات، لمحة المشاريع، سجل المشاريع بتفاصيلها،
العملاء، أسطول المعدات. وصور المشاريع والمواقع تُحفظ في data/media/<الشركة>/ ويُشار
إليها من المشاريع بأسماء ملفاتها.

عزوم (الشركة 1) يُزرع ملفها وصورها من seed_data أول مرة؛ المستأجرون يبدؤون بملف فارغ
فتُبنى أقسامهم من إعداداتهم (النبذة وسابقة الأعمال) دون أي بيانات لعزوم.
"""
import base64
import json
import shutil
from pathlib import Path

from .config import DATA_DIR
from .database import get_db, now_iso

SEED = Path(__file__).resolve().parent / "seed_data"
SCHEMA = """
CREATE TABLE IF NOT EXISTS company_profiles (
    company_id INTEGER PRIMARY KEY,
    data TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS company_media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    file TEXT NOT NULL,
    caption TEXT DEFAULT '',
    kind TEXT DEFAULT 'project',
    project_id INTEGER,
    UNIQUE(company_id, file)
);
"""
MEDIA_KINDS = {"hero", "project", "site", "team", "equipment", "logos", "heritage"}


def media_dir(company_id: int) -> Path:
    d = DATA_DIR / "media" / str(int(company_id))
    d.mkdir(parents=True, exist_ok=True)
    return d


def init_profile_tables():
    with get_db() as db:
        db.executescript(SCHEMA)
    seed_azoom_profile()


def seed_azoom_profile():
    """ملف عزوم وصورها من seed_data — مرة واحدة، ولا يكتب فوق ملف عدّلته الشركة."""
    src = SEED / "azoom_profile.json"
    if not src.exists():
        return
    with get_db() as db:
        row = db.execute("SELECT 1 FROM company_profiles WHERE company_id = 1").fetchone()
        if not row:
            db.execute("INSERT INTO company_profiles (company_id, data, updated_at) VALUES (1, ?, ?)",
                       (src.read_text(encoding="utf-8"), now_iso()))
    captions = SEED / "azoom_media" / "captions.json"
    if not captions.exists():
        return
    dest = media_dir(1)
    with get_db() as db:
        for c in json.loads(captions.read_text(encoding="utf-8")):
            f = SEED / "azoom_media" / c["file"]
            if not f.exists():
                continue
            if not (dest / c["file"]).exists():
                shutil.copyfile(f, dest / c["file"])
            db.execute("INSERT OR IGNORE INTO company_media (company_id, file, caption, kind, project_id) "
                       "VALUES (1, ?, ?, ?, ?)", (c["file"], c.get("caption_ar", ""), c.get("kind", "project"),
                                                  c.get("project_id")))


def get_profile(company_id) -> dict:
    if not company_id:
        return {}
    try:
        with get_db() as db:
            row = db.execute("SELECT data FROM company_profiles WHERE company_id = ?", (int(company_id),)).fetchone()
        return json.loads(row["data"]) if row else {}
    except Exception:
        return {}


def save_profile(company_id: int, data: dict):
    if not isinstance(data, dict):
        raise ValueError("ملف الشركة يجب أن يكون كائن JSON")
    text = json.dumps(data, ensure_ascii=False)
    if len(text) > 400_000:
        raise ValueError("ملف الشركة أكبر من المسموح")
    with get_db() as db:
        db.execute("INSERT INTO company_profiles (company_id, data, updated_at) VALUES (?, ?, ?) "
                   "ON CONFLICT(company_id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
                   (int(company_id), text, now_iso()))


def list_media(company_id, with_data: bool = True) -> list[dict]:
    """صور الشركة؛ with_data تضيف uri (data:) للتضمين في ملفات PDF."""
    if not company_id:
        return []
    try:
        with get_db() as db:
            rows = [dict(r) for r in db.execute(
                "SELECT id, file, caption, kind, project_id FROM company_media WHERE company_id = ? ORDER BY id",
                (int(company_id),))]
    except Exception:
        return []
    base = media_dir(company_id)
    out = []
    for r in rows:
        p = base / r["file"]
        if not p.exists():
            continue
        if with_data:
            r["uri"] = "data:image/jpeg;base64," + base64.b64encode(p.read_bytes()).decode()
        out.append(r)
    return out


def add_media(company_id: int, filename: str, raw: bytes, caption: str = "", kind: str = "project",
              project_id: int | None = None) -> dict:
    """رفع صورة: تُفحص بمكتبة الصور وتُعاد ترميزاً JPEG (≤1400 بكسل) — لا يُحفظ ملف المستخدم كما هو."""
    import io
    import re
    from PIL import Image
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception:
        raise ValueError("الملف ليس صورة صالحة")
    img = img.convert("RGB")
    if img.width > 1400:
        img = img.resize((1400, int(img.height * 1400 / img.width)))
    stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", Path(filename or "photo").stem).strip("-")[:40] or "photo"
    name = f"{stem}.jpg"
    base = media_dir(company_id)
    n = 1
    while (base / name).exists():
        n += 1
        name = f"{stem}-{n}.jpg"
    img.save(base / name, format="JPEG", quality=80, optimize=True, progressive=True)
    kind = kind if kind in MEDIA_KINDS else "project"
    with get_db() as db:
        db.execute("INSERT INTO company_media (company_id, file, caption, kind, project_id) VALUES (?, ?, ?, ?, ?)",
                   (int(company_id), name, caption[:200], kind, project_id))
    return {"file": name, "caption": caption, "kind": kind, "project_id": project_id}


def delete_media(company_id: int, media_id: int) -> bool:
    with get_db() as db:
        row = db.execute("SELECT file FROM company_media WHERE id = ? AND company_id = ?",
                         (int(media_id), int(company_id))).fetchone()
        if not row:
            return False
        db.execute("DELETE FROM company_media WHERE id = ?", (int(media_id),))
    try:
        (media_dir(company_id) / row["file"]).unlink()
    except OSError:
        pass
    return True
