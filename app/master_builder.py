"""وكيل بناء العروض الفنية طبق الأصل — الاستنساخ الكامل بدل انتقاء الجمل.

بدل تجميع العرض جملةً من بنك الفقرات، يختار هذا الوكيل أقرب عرض فني كامل
سبق أن قدمته الشركة (نفس فئة المشروع ثم أعلى تشابه بالمحتوى)، وينسخ أقسامه
كاملةً بترتيبها وروحها «طبق الأصل»، ثم يؤقلمها للمشروع الجديد بتدخل جراحي
محدود فقط:
- استبدال اسم العميل القديم بالجديد أينما ورد.
- تحديث سنوات التقويم في سياقات «عام/لعام/سنة».
- إعادة بناء الأقسام الديناميكية وحدها (خطاب التقديم، معلومات الشركة) من
  بيانات الشركة الحية، وإسقاط أقسام الجدول المالي (تُبنى من محرك التسعير).

فتخرج العروض موحدة الشكل والصوت مهما تعدد المشاريع — لأنها حرفياً نسخ من
عروض الشركة الحقيقية. بنك الفقرات يبقى احتياطاً عند غياب عرض كامل صالح.
"""
import re

from .database import get_db
from .tenancy import cid

MIN_MASTER_SECTIONS = 8  # أقل عدد أقسام يجعل العرض صالحاً قالباً كاملاً

# أقسام لا تُستنسخ من القالب: المالية تُبنى من محرك التسعير الحي
_DROP_TITLES = ("جدول الكميات", "العرض المالي", "الأسعار", "جدول الأسعار", "المقايسة")
# أقسام تُعاد ديناميكياً من بيانات الشركة والمشروع الحيّين
_DYNAMIC_TITLES = {"خطاب التقديم": "cover", "معلومات الشركة": "company"}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("ـ", "")).strip()


def _tokens(text: str) -> set:
    return {t for t in re.split(r"[\s،,./|()\-:\n]+", _norm(text)) if len(t) > 2}


def list_masters(kind: str = "") -> list[dict]:
    """العروض الكاملة الصالحة قوالبَ — عروض الشركة نفسها ذات الأقسام الوافية."""
    q = ("SELECT id, filename, client, project_kind, sections_count, paragraphs_count "
         "FROM tech_documents WHERE company_id = ? AND doc_kind LIKE 'azoom%' "
         "AND is_style_source = 1 AND sections_count >= ?")
    args = [cid(), MIN_MASTER_SECTIONS]
    if kind:
        q += " AND project_kind = ?"
        args.append(kind)
    with get_db() as db:
        rows = db.execute(q + " ORDER BY sections_count DESC", args).fetchall()
    return [dict(r) for r in rows]


def _doc_text_sample(doc_id: int, limit_paras: int = 60) -> str:
    with get_db() as db:
        rows = db.execute(
            "SELECT p.body FROM tech_paragraphs p JOIN tech_sections s ON s.id = p.section_id "
            "WHERE s.document_id = ? ORDER BY s.ordinal, p.ordinal LIMIT ?",
            (doc_id, limit_paras)).fetchall()
    return " ".join(r["body"] for r in rows)


def pick_master(brief_text: str, project_kind: str) -> dict | None:
    """أقرب عرض كامل: فئة المشروع نفسها أولاً ثم أعلى تقاطع محتوى مع الموجز."""
    candidates = list_masters(project_kind) or list_masters()
    if not candidates:
        return None
    brief = _tokens(brief_text[:6000])
    best, best_score = None, -1.0
    for doc in candidates:
        overlap = len(brief & _tokens(_doc_text_sample(doc["id"])))
        score = overlap + (6 if doc["project_kind"] == project_kind else 0) \
            + min(doc["sections_count"], 30) / 30.0
        if score > best_score:
            best, best_score = doc, score
    return best


def _junk_title(title: str) -> bool:
    """عنوان مشوه من استخراج PDF (سطر طويل أو كلمات ملتصقة) — ليس عنوان قسم حقيقياً."""
    t = title.strip()
    return len(t) > 45 or (len(t) > 22 and " " not in t)


def load_master_sections(doc_id: int) -> list[dict]:
    """أقسام القالب كاملةً بترتيبها — النص يُعاد تجميعه من فقراته المخزنة.

    الأقسام ذات العناوين المشوهة (سطور PDF ملتصقة اعتُبرت عناوين عند الاستخراج)
    تُدمج نصاً في القسم السابق فلا يتسرب عنوان ركيك إلى العرض المولد."""
    with get_db() as db:
        secs = db.execute(
            "SELECT id, title, ordinal FROM tech_sections WHERE document_id = ? "
            "ORDER BY ordinal", (doc_id,)).fetchall()
        out = []
        for s in secs:
            paras = db.execute(
                "SELECT body FROM tech_paragraphs WHERE section_id = ? ORDER BY ordinal",
                (s["id"],)).fetchall()
            body = "\n".join(p["body"] for p in paras).strip()
            if not body and not s["title"].strip():
                continue
            title = s["title"].strip()
            if _junk_title(title) and out:
                out[-1]["body"] = (out[-1]["body"] + "\n" + title + "\n" + body).strip()
                continue
            if body:
                out.append({"title": title, "body": body})
    return out


def _adapt_text(text: str, old_client: str, new_client: str, new_year: str) -> str:
    """الأقلمة الجراحية: العميل والسنة فقط — لا إعادة صياغة إطلاقاً."""
    if old_client and new_client and len(old_client) >= 4:
        text = text.replace(old_client, new_client)
    # سنوات في سياق زمني صريح فقط («عام 2024» لا أرقام العقود والأكواد)
    text = re.sub(r"(عام|لعام|سنة|لسنة)\s*20\d{2}", lambda m: f"{m.group(1)} {new_year}", text)
    return text


def build_from_master(brief_text: str, project_kind: str, new_client: str,
                      dynamic_bodies: dict) -> tuple[list[dict], str] | None:
    """الاستنساخ والأقلمة — يعيد (الأقسام، مرجع القالب) أو None للرجوع للبنك.

    dynamic_bodies: {"cover": خطاب التقديم الحي, "company": معلومات الشركة الحية}"""
    from datetime import date
    master = pick_master(brief_text, project_kind)
    if not master:
        return None
    cloned = load_master_sections(master["id"])
    if len(cloned) < MIN_MASTER_SECTIONS:
        return None
    new_year = str(date.today().year)
    old_client = (master.get("client") or "").strip()
    ref = master["filename"]
    sections, has_cover = [], False
    for sec in cloned:
        title_n = _norm(sec["title"])
        if any(d in title_n for d in _DROP_TITLES):
            continue
        dyn_key = next((k for t, k in _DYNAMIC_TITLES.items() if t in title_n), None)
        if dyn_key and dynamic_bodies.get(dyn_key):
            sections.append({"title": sec["title"], "body": dynamic_bodies[dyn_key],
                             "source": "dynamic", "source_ref": ""})
            has_cover = has_cover or dyn_key == "cover"
            continue
        sections.append({
            "title": sec["title"],
            "body": _adapt_text(sec["body"], old_client, new_client, new_year),
            "source": "master", "source_ref": ref,
        })
    if not has_cover and dynamic_bodies.get("cover"):
        sections.insert(0, {"title": "خطاب التقديم", "body": dynamic_bodies["cover"],
                            "source": "dynamic", "source_ref": ""})
    return sections, ref
