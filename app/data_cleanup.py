"""تنظيف بيانات المعرفة (مرة واحدة لكل إصدار) — يطبَّق على قواعد البيانات القائمة أيضاً.

نتيجة تدقيق بيانات البذور (2026-10-28) — seed_data/catalog_actions.csv:
- DELETE (121): ليست بنوداً تُسعَّر — شظايا (أقطار/وسوم أبواب/طرازات بلا وصف)، نصوص
  تالفة الترميز، تكرارات، وبنود برمجيات لا علاقة لها بالمقاولات.
- FIX (152): وحدات خاطئة (mrun ← م.ط)، تصنيفات خاطئة، أوصاف مقطوعة أو ملتصقة.
- FLAG (129): بنود صحيحة لكنها خاصة بمشروع بعينها أو عالية القيمة (نوافير، شلالات،
  لوحات، مقطوعيات) — تبقى في القاعدة ولا تُستخدم في التسعير الآلي (auto_match = 0).
ومصادر الأسلوب: يُستبدل النص الرئيسي بنسخته المنظفة (بلا أسماء موظفين ولا هواتف ولا
بيانات مشاريع أخرى)، ويُحذف نص الصيانة التالف (76% منه حروف مبعثرة) من بنك الفقرات.
لا يُمس أي بند أضافته الشركة بنفسها (الحذف والتعديل بالكود فقط وللشركة 1).
"""
import csv
from pathlib import Path

from .database import get_db, get_settings, now_iso, update_settings

CLEANUP_VERSION = "2026-10-28"
SEED = Path(__file__).resolve().parent / "seed_data"
_STYLE_DOCS = ("العرض الفني النموذجي — إنشاءات وتشطيبات 2024", "العرض الفني النموذجي — عزوم 2024",
               "العرض الفني النموذجي — صيانة وتشغيل HVAC")


def _actions() -> list[dict]:
    f = SEED / "catalog_actions.csv"
    if not f.exists():
        return []
    with open(f, encoding="utf-8-sig") as fh:
        return [r for r in csv.DictReader(fh) if r.get("code")]


def _cleaned_rows() -> dict:
    f = SEED / "azoom_prices.csv"
    if not f.exists():
        return {}
    with open(f, encoding="utf-8-sig") as fh:
        return {r["code"].strip(): r for r in csv.DictReader(fh) if r.get("code")}


def flagged_codes() -> set[str]:
    return {r["code"].strip() for r in _actions() if r.get("action") == "FLAG"}


def run_cleanup() -> dict:
    """يُستدعى عند الإقلاع؛ يعمل مرة واحدة لكل CLEANUP_VERSION."""
    if get_settings(company_id=1).get("data_cleanup_version") == CLEANUP_VERSION:
        return {"skipped": True}
    acts = _actions()
    cleaned = _cleaned_rows()
    stats = {"deleted": 0, "fixed": 0, "flagged": 0, "style_docs": 0}
    ts = now_iso()
    with get_db() as db:
        for a in acts:
            code, action = a["code"].strip(), a.get("action")
            if action == "DELETE":
                stats["deleted"] += db.execute("DELETE FROM price_items WHERE company_id = 1 AND code = ?",
                                               (code,)).rowcount
            elif action == "FIX":
                row = cleaned.get(code)
                name = (row or {}).get("name") or a.get("name") or ""
                unit = a.get("new_unit") or (row or {}).get("unit") or ""
                cat = a.get("new_category") or (row or {}).get("category") or ""
                sets, vals = [], []
                for col, v in (("name", name), ("unit", unit), ("category", cat)):
                    if v.strip():
                        sets.append(f"{col} = ?")
                        vals.append(v.strip())
                if a.get("new_price"):
                    sets.append("unit_price = ?")
                    vals.append(float(a["new_price"]))
                if sets:
                    stats["fixed"] += db.execute(
                        f"UPDATE price_items SET {', '.join(sets)}, updated_at = ? WHERE company_id = 1 AND code = ?",
                        (*vals, ts, code)).rowcount
            elif action == "FLAG":
                stats["flagged"] += db.execute("UPDATE price_items SET auto_match = 0 WHERE company_id = 1 AND code = ?",
                                               (code,)).rowcount
        # بنك الفقرات: حذف مصادر الأسلوب القديمة ليُعاد زرع النسخة المنظفة فقط
        docs = [r["id"] for r in db.execute(
            f"SELECT id FROM tech_documents WHERE company_id = 1 AND filename IN ({','.join('?' * len(_STYLE_DOCS))})",
            _STYLE_DOCS)] if _has(db, "tech_documents") else []
        for doc_id in docs:
            secs = [r["id"] for r in db.execute("SELECT id FROM tech_sections WHERE document_id = ?", (doc_id,))]
            for sid in secs:
                db.execute("DELETE FROM tech_paragraphs WHERE section_id = ?", (sid,))
            db.execute("DELETE FROM tech_sections WHERE document_id = ?", (doc_id,))
            db.execute("DELETE FROM tech_documents WHERE id = ?", (doc_id,))
            stats["style_docs"] += 1
    update_settings({"data_cleanup_version": CLEANUP_VERSION}, company_id=1)
    return stats


def _has(db, table: str) -> bool:
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (table,)).fetchone())
