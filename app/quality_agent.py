"""وكيل الجودة والمراجعة — بوابة الاعتماد الأخيرة قبل خروج العرض.

مهمته أن يخرج العرض بصوت الشركة نفسها لا بصياغة القوالب العامة، نظيفاً
واحترافياً ومتسقاً:
1) أصالة الصوت: نسبة الأقسام المبنية من بنك فقرات الشركة (المكتوبة بشرياً
   من عروضها الحقيقية)، ورصد عبارات الصياغة القالبية الشائعة وإزالتها جراحياً.
2) النظافة: لا نصوص placeholder، لا أقسام فارغة أو قصيرة، لا فقرات مكررة،
   لا مقاطع إنجليزية شاذة داخل النص العربي.
3) الاتساق المالي: إعادة حساب مستقلة للجدول والإجماليات ومطابقة التسعير
   الموجه للعميل مع الإجمالي قبل الضريبة إلى الهللة.
4) نظافة خصائص الملفات: مؤلف Word/Excel هو الشركة نفسها لا اسم مكتبة برمجية
   (تُطبَّق في المصدّرات نفسها).

ملاحظة صريحة: لا يَعِد هذا الوكيل بأن «كواشف الذكاء» لن تشك مطلقاً — لا أحد
يضمن ذلك بصدق. قوته أنه يرفع نسبة المحتوى الآتي من نصوص الشركة البشرية
ويحذف البصمات القالبية والتقنية، وهذا أقصى ما يفعله أي نظام محترم.
"""
import re

from .proposal_builder import client_facing_pricing, compute_financials
from .style_engine import DEFAULT_BANNED, scrub_banned

# عبارات الصياغة القالبية الشائعة (تكملة للقائمة السوداء في محرك الأسلوب)
TEMPLATE_CLICHES = DEFAULT_BANNED + [
    "مما لا شك فيه", "علاوة على ذلك", "وفي هذا السياق", "بشكل عام",
    "يُعد من أهم", "في هذا العصر", "بيئة ديناميكية", "قيمة مضافة حقيقية",
    "استناداً إلى ما سبق", "وبناءً على ما تقدم", "جدير بالذكر",
]

_PLACEHOLDER_RE = re.compile(r"\[[^\]]{0,40}\]|X{3,}|_{3,}|\{\{|\}\}|%s|TBD|TODO|lorem|لوريم", re.I)
_LATIN_RE = re.compile(r"[A-Za-z]")


def _sections(data: dict) -> list[dict]:
    return data.get("technical_sections", []) or []


def _latin_ratio(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for ch in letters if _LATIN_RE.match(ch)) / len(letters)


def review_proposal(data: dict) -> dict:
    """تقرير الوكيل: درجة 0-100 + قائمة ملاحظات قابلة للإصلاح."""
    issues = []
    sections = _sections(data)
    total = len(sections)
    bank = sum(1 for s in sections if s.get("source") == "bank")

    # 1) أصالة الصوت
    cliche_hits = 0
    for s in sections:
        body = s.get("body", "")
        hits = [b for b in TEMPLATE_CLICHES if b in body]
        if hits:
            cliche_hits += len(hits)
            issues.append({"level": "warn", "kind": "cliche", "section": s.get("title", ""),
                           "text": "عبارات قالبية: " + "، ".join(hits[:4]),
                           "fixable": True})
    generic = [s.get("title", "") for s in sections if s.get("source") == "new"]
    if total and bank / total < 0.4:
        issues.append({"level": "warn", "kind": "voice", "section": "",
                       "text": f"{bank} فقط من {total} قسماً مبني من بنك فقرات الشركة — "
                               "ارفع عروضاً فنية سابقة من معالج التهيئة ليرتفع صوت الشركة.",
                       "fixable": False})

    # 2) النظافة
    seen_bodies = {}
    for s in sections:
        title, body = s.get("title", ""), (s.get("body") or "").strip()
        if len(body) < 60:
            issues.append({"level": "error", "kind": "short", "section": title,
                           "text": "قسم فارغ أو قصير جداً — أكمله أو احذفه قبل التقديم.",
                           "fixable": False})
        if _PLACEHOLDER_RE.search(body):
            issues.append({"level": "error", "kind": "placeholder", "section": title,
                           "text": "نص مؤقت/placeholder داخل القسم — راجعه يدوياً.",
                           "fixable": False})
        if _latin_ratio(body) > 0.25 and len(body) > 120:
            issues.append({"level": "warn", "kind": "latin", "section": title,
                           "text": "نسبة عالية من الأحرف اللاتينية داخل قسم عربي — تأكد أنها مقصودة.",
                           "fixable": False})
        key = body[:180]
        if key and key in seen_bodies:
            issues.append({"level": "warn", "kind": "duplicate", "section": title,
                           "text": f"محتوى مكرر مع قسم «{seen_bodies[key]}».", "fixable": False})
        seen_bodies.setdefault(key, title)

    # 3) الاتساق المالي — إعادة حساب مستقلة
    boq = data.get("boq", []) or []
    fin = data.get("financial", {}) or {}
    if boq and fin:
        import copy
        recomputed = compute_financials(copy.deepcopy(boq))
        for key in ("direct_cost", "subtotal", "vat", "grand_total"):
            a, b = float(fin.get(key) or 0), float(recomputed.get(key) or 0)
            if abs(a - b) > 1:
                issues.append({"level": "error", "kind": "finance", "section": key,
                               "text": f"عدم اتساق مالي في {key}: المخزن {a:,.2f} والمحسوب {b:,.2f}.",
                               "fixable": False})
                break
        loaded = client_facing_pricing(copy.deepcopy(boq), fin)
        loaded_sum = round(sum(l.get("total", 0) for l in loaded), 2)
        if abs(loaded_sum - float(fin.get("subtotal") or 0)) > 0.05:
            issues.append({"level": "error", "kind": "finance", "section": "client_pricing",
                           "text": "مجموع التسعير الموجه للعميل لا يطابق الإجمالي قبل الضريبة.",
                           "fixable": False})
        unpriced = [l.get("name", "") for l in boq if not l.get("unit_price")]
        if unpriced:
            issues.append({"level": "warn", "kind": "finance", "section": "boq",
                           "text": "بنود بلا سعر: " + "، ".join(unpriced[:5]), "fixable": False})

    errors = sum(1 for i in issues if i["level"] == "error")
    warns = sum(1 for i in issues if i["level"] == "warn")
    voice = (bank / total) if total else 0
    score = max(0, min(100, round(100 - errors * 18 - warns * 6 + voice * 10 - min(cliche_hits, 5) * 2)))
    return {
        "score": score,
        "ready": errors == 0 and score >= 70,
        "bank_sections": bank, "total_sections": total,
        "voice_ratio": round(voice, 2),
        "generic_sections": generic,
        "errors": errors, "warnings": warns,
        "issues": issues,
    }


def polish_proposal(data: dict) -> dict:
    """الإصلاح التلقائي الآمن: إزالة الجمل القالبية جراحياً (لا يلمس الأرقام).

    يعيد {changed_sections, removed_phrases} ويعدّل data في مكانها."""
    changed, removed = [], []
    for s in _sections(data):
        body = s.get("body", "")
        cleaned, hits = scrub_banned(body, TEMPLATE_CLICHES)
        if hits and cleaned and len(cleaned) >= 40:
            s["body"] = cleaned
            changed.append(s.get("title", ""))
            removed.extend(hits)
    return {"changed_sections": changed, "removed_phrases": sorted(set(removed))}


def clean_file_properties(settings: dict):
    """قيم خصائص الملفات الاحترافية: المؤلف هو الشركة لا مكتبة برمجية."""
    company = settings.get("company_name", "") or "—"
    return {"author": company, "last_modified_by": company, "company": company}
