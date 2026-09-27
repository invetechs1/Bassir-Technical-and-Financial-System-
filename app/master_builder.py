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


def rank_masters(brief_text: str, project_kind: str) -> list[dict]:
    """القوالب مرتبة قرباً: فئة المشروع نفسها أولاً (علاوة +6 في الدرجة)
    ثم أعلى تقاطع محتوى مع الموجز — الكل مرشح ليبقى بديل عند تشوه الأقرب."""
    candidates = list_masters()
    if not candidates:
        return []
    brief = _tokens(brief_text[:6000])
    scored = []
    for doc in candidates:
        overlap = len(brief & _tokens(_doc_text_sample(doc["id"])))
        score = overlap + (6 if doc["project_kind"] == project_kind else 0) \
            + min(doc["sections_count"], 30) / 30.0
        scored.append((score, doc))
    scored.sort(key=lambda x: -x[0])
    return [doc for _, doc in scored]


def pick_master(brief_text: str, project_kind: str) -> dict | None:
    """أقرب عرض كامل — أول قالب تصمد أقسامه بعد تنقية نصوص الاستخراج المشوهة.

    قالب امتلأ بنص PDF ممزق قد لا يبقى منه ما يكفي — عندها يُجرَّب التالي
    بدل الرجوع لبنك الفقرات مباشرة."""
    for doc in rank_masters(brief_text, project_kind):
        if len(load_master_sections(doc["id"])) >= MIN_MASTER_SECTIONS:
            return doc
    return None


def _junk_title(title: str) -> bool:
    """عنوان مشوه من استخراج PDF (سطر طويل أو كلمات ملتصقة) — ليس عنوان قسم حقيقياً."""
    t = title.strip()
    return len(t) > 45 or (len(t) > 22 and " " not in t)


def _squashed(text: str) -> bool:
    """نص فقد مسافاته أثناء استخراج PDF (كلمات عربية ملتصقة في سطر واحد).

    الكلمة العربية السليمة لا تتجاوز ~15 حرفاً؛ غلبة «كلمات» أطول من 18
    تعني نصاً مشوهاً لا يصلح للظهور في عرض مُصدَّر."""
    words = [w for w in text.split() if w.strip("•-—.،")]
    if not words:
        return False
    long_runs = sum(1 for w in words if len(w) > 18)
    return long_runs / len(words) > 0.3


# أدوات عربية قصيرة مشروعة — لا تُحسب دليلاً على تمزق النص
_AR_SHORT_OK = {"في", "من", "ما", "لا", "أو", "او", "إن", "ان", "عن",
                "لم", "لن", "قد", "كل", "ثم", "بل", "هل", "لو", "ذا", "أن"}
_AR_LETTER = re.compile(r"[؀-ۿ]")


def _shredded(text: str) -> bool:
    """نص تمزقت كلماته أثناء استخراج PDF (حروف وأشلاء كلمات متناثرة).

    العتبات معايرة على بيانات حقيقية: النص العربي السليم لا تتجاوز نسبة
    أحرفه المفردة 5% ولا أشلاؤه القصيرة 7%، والممزق يتجاوز 9% و25%."""
    toks = [t.strip("،,.:؛()•-—/\\؟!") for t in text.split()]
    ar = [t for t in toks if t and _AR_LETTER.search(t)]
    if len(ar) < 6:
        return False
    singles = sum(1 for t in ar if len(t) == 1 and t != "و")
    shorts = sum(1 for t in ar if len(t) <= 2 and t != "و" and t not in _AR_SHORT_OK)
    return singles / len(ar) > 0.08 or shorts / len(ar) > 0.22


def _garbled(text: str) -> bool:
    return _squashed(text) or _shredded(text)


def _fix_rotated_title(title: str) -> str:
    """إصلاح عنوان دوّره استخراج PDF: «هج والمنهجيةالن» → «النهج والمنهجية».

    يعمل فقط حين يبدأ العنوان بشظية يتيمة (حرفان فأقل ليست أداة) وتنتهي
    نهايته بشظية «ال...» ملتصقة — عندها تُعاد الشظية إلى الصدارة."""
    toks = title.split()
    if len(toks) < 2 or len(toks[0]) > 2 or toks[0] in _AR_SHORT_OK or toks[0] == "و":
        return title
    for i in range(2, 5):
        frag = title[-i:]
        if frag.startswith("ال") and " " not in frag:
            cand = (frag + title[:-i]).strip()
            if all(len(x) >= 2 for x in cand.split()):
                return cand
    return title


def load_master_sections(doc_id: int) -> list[dict]:
    """أقسام القالب كاملةً بترتيبها — النص يُعاد تجميعه من فقراته المخزنة.

    الأقسام ذات العناوين المشوهة (سطور PDF ملتصقة اعتُبرت عناوين عند الاستخراج)
    تُدمج نصاً في القسم السابق فلا يتسرب عنوان ركيك إلى العرض المولد،
    والفقرات التي فقدت مسافاتها عند الاستخراج تُستبعد كلياً — نص ملتصق
    غير مقروء أسوأ في عرض مُقدَّم من غيابه."""
    with get_db() as db:
        secs = db.execute(
            "SELECT id, title, ordinal FROM tech_sections WHERE document_id = ? "
            "ORDER BY ordinal", (doc_id,)).fetchall()
        out = []
        for s in secs:
            paras = db.execute(
                "SELECT body FROM tech_paragraphs WHERE section_id = ? ORDER BY ordinal",
                (s["id"],)).fetchall()
            raw = "\n".join(p["body"] for p in paras).strip()
            body = "\n".join(p["body"] for p in paras
                             if not _garbled(p["body"])).strip()
            # قسم أكله التشويه ولم يبق منه إلا شذرة — يُسقط كله بدل صفحة شبه
            # فارغة (القسم القصير السليم أصلاً — جدول بيانات عقد مثلاً — يبقى)
            had_garbage = len(body) < len(raw)
            if had_garbage and (len(body) < 150 or
                                (len(body) < 400 and len(body) < 0.25 * len(raw))):
                body = ""
            if not body and not s["title"].strip():
                continue
            # رقم صفحة تسرب لنهاية العنوان عند استخراج PDF («... المهنية 24»)
            title = re.sub(r"\s+\d{1,3}$", "", s["title"].strip())
            title = _fix_rotated_title(title)
            if _junk_title(title) and out:
                merged = "" if _garbled(title) else title
                out[-1]["body"] = "\n".join(x for x in (out[-1]["body"], merged, body) if x).strip()
                continue
            if body:
                out.append({"title": title, "body": body})
    return out


# سنة في سياق زمني صريح («عام 2024» لا أرقام العقود والأكواد)
_YEAR_RE = re.compile(r"(عام|لعام|سنة|لسنة)\s*(20\d{2})")
# سياقات تاريخية ثابتة لا تُحدَّث سنتها أبداً (سنة تأسيس الشركة مثلاً)
_YEAR_KEEP_CONTEXT = ("تأسس", "التأسيس", "أُسس", "انطلق", "منذ")


def _adapt_year(m: re.Match, new_year: str) -> str:
    """تُحدَّث سنة العرض وحدها: السنة القديمة حقيقة تاريخية (تأسيس، سابقة
    أعمال) تبقى، والحديثة تُحدَّث إلا إذا سبقها سياق تأسيس مباشرة."""
    if int(m.group(2)) < int(new_year) - 3:
        return m.group(0)
    tight = m.string[max(0, m.start() - 25):m.start()]
    if any(k in tight for k in _YEAR_KEEP_CONTEXT):
        return m.group(0)
    return f"{m.group(1)} {new_year}"


def _adapt_text(text: str, old_client: str, new_client: str, new_year: str) -> str:
    """الأقلمة الجراحية: العميل والسنة فقط — لا إعادة صياغة إطلاقاً.

    التواريخ الثابتة (سنة تأسيس الشركة ونحوها) تبقى كما هي."""
    if old_client and new_client and len(old_client) >= 4:
        text = text.replace(old_client, new_client)
    text = _YEAR_RE.sub(lambda m: _adapt_year(m, new_year), text)
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
