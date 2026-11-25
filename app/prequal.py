"""وكيل التأهيل المسبق — يبني ملف تأهيل لكل دعوة من بيانات الشركة المخزنة.

يعمل كفريق خبراء، كل «خبير» دالة مستقلة تُخرج أدلة موثقة من قاعدة البيانات لا نصاً عاماً:

1. محلل المتطلبات — يستخرج اشتراطات الجهة من كراسة التأهيل المرفوعة (إن وُجدت) ويحدد
   فئة المشروع ومعايير التقييم وأوزانها (الأوزان المعتادة في دعوات التأهيل الحكومية).
2. مدقق ملاءمة النطاق — هل المشروع ضمن نشاط الشركة أصلاً؟ (لا نوصي بالتقدم خارج النطاق).
3. خبير الخبرات — أقرب مشاريع الشركة للدعوة من ملفها التعريفي وسجل أعمالها بقيمها.
4. مدقق الامتثال — كل وثيقة نظامية: سارية حتى موعد التقديم / تنتهي قبله / منتهية / ناقصة.
5. المحلل المالي، 6. خبير الموارد البشرية، 7. خبير المعدات، 8. مدير الجودة والسلامة،
9. خبير المحتوى المحلي — كلٌّ يبني دليله من الملف التعريفي ووثائق الشركة.
10. المقيّم — يحتسب الدرجة المتوقعة لكل معيار كما تحتسبها لجنة التأهيل، والنواقص وخطة سدها.

ثم «الكاتب» يصوغ الملف: بالذكاء الاصطناعي (Claude) إن توفر المفتاح — بمخرجات مهيكلة صارمة
ومن الأدلة المعطاة فقط — وإلا بقالب احترافي. لا يُختلق رقم أو مشروع أو شهادة غير مخزنة.
"""
import json
import re
from datetime import datetime

from .database import get_db, get_settings, list_company_docs, list_library, now_iso
from .tenancy import cid

SCHEMA = """
CREATE TABLE IF NOT EXISTS prequal_dossiers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    tender_id INTEGER NOT NULL,
    data TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
"""

# ---------------------------------------------------------------- فئات المشاريع
_CATEGORIES = {
    "construction": ("إنشاءات ومباني وبنية تحتية",
                     ("إنشاء", "انشاء", "مبنى", "مباني", "تشييد", "أرصفة", "ارصفة", "سفلتة", "طرق", "جسور",
                      "خرسان", "بنية تحتية", "درء", "سيول", "تصريف", "ترميم", "توسعة", "تطوير موقع", "مستودع",
                      "مدرسة", "مستشفى", "مجمع", "construction", "building")),
    "om": ("تشغيل وصيانة ونظافة",
           ("تشغيل", "صيانة", "نظافة", "مرافق", "مباني", "facility", "maintenance")),
    "landscape": ("مسطحات خضراء وتشجير ومشهد حضري",
                  ("مسطحات", "تشجير", "حدائق", "زراعة", "مشهد حضري", "المداخل", "landscape")),
    "electrical": ("أعمال كهربائية وإنارة", ("كهرباء", "كهربائ", "إنارة", "انارة", "محولات")),
    "it": ("تقنية معلومات وتحول رقمي",
           ("رقمي", "تقني", "سحاب", "حوسبة", "بيانات", "حوكمة", "تطبيقات", "أنظمة", "برمج", "أمن سيبراني")),
    "catering": ("إعاشة وضيافة", ("إعاشة", "اعاشة", "أعاشة", "ضيافة", "تغذية", "مطابخ")),
    "security": ("حراسات أمنية", ("حراسات", "حراسة", "الأمنية")),
    "transport": ("نقل وخدمات لوجستية", ("نقل", "لوجست", "شحن")),
}
# عبارات تخصصية تُثبت النشاط في الفئات الواقعة خارج المقاولات
_CORE = {
    "it": ("تقنية المعلومات", "تحول رقمي", "التحول الرقمي", "برمجيات", "حوسبة سحابية", "أمن سيبراني"),
    "catering": ("إعاشة", "اعاشة", "تغذية", "مطابخ مركزية"),
    "security": ("حراسات أمنية", "حراسة أمنية", "الحراسات"),
    "transport": ("نقل وتخزين", "خدمات لوجستية", "لوجستي"),
}
# الفئات التي تقع في نشاط شركات المقاولات العامة (عزوم وأمثالها)
_CONTRACTOR_SCOPE = {"construction", "om", "landscape", "electrical"}

# معايير التقييم المعتادة في دعوات التأهيل المسبق الحكومية وأوزانها الافتراضية لكل فئة.
# تُستبدل بأوزان الجهة إن وردت في الكراسة المرفوعة.
_CRITERIA = [
    ("experience", "الخبرة السابقة في أعمال مماثلة", "EXPERIENCE"),
    ("financial", "الملاءة والقدرة المالية", "FINANCIAL CAPACITY"),
    ("staff", "الجهاز الفني والكوادر الرئيسية", "KEY PERSONNEL"),
    ("equipment", "المعدات والموارد", "EQUIPMENT & RESOURCES"),
    ("quality", "أنظمة الجودة والسلامة والبيئة", "QHSE SYSTEMS"),
    ("legal", "الوثائق النظامية والتصنيف", "LEGAL & CLASSIFICATION"),
    ("local", "المحتوى المحلي والتوطين", "LOCAL CONTENT"),
]
_WEIGHTS = {
    "construction": {"experience": 35, "financial": 20, "staff": 15, "equipment": 12, "quality": 8, "legal": 5, "local": 5},
    "om": {"experience": 30, "financial": 15, "staff": 25, "equipment": 10, "quality": 10, "legal": 5, "local": 5},
    "default": {"experience": 35, "financial": 20, "staff": 20, "equipment": 8, "quality": 7, "legal": 5, "local": 5},
}

# ---------------------------------------------------------------- الوثائق النظامية
_REQUIRED_DOCS = [
    ("cr", "السجل التجاري", ("سجل تجاري", "السجل التجاري"), True),
    ("zakat", "شهادة الزكاة والدخل", ("زكاة",), True),
    ("vat", "شهادة التسجيل في ضريبة القيمة المضافة", ("ضريب", "القيمة المضافة"), True),
    ("gosi", "شهادة التأمينات الاجتماعية", ("تأمينات",), True),
    ("saudization", "شهادة السعودة / نطاقات", ("سعودة", "نطاقات"), True),
    ("chamber", "شهادة عضوية الغرفة التجارية", ("غرفة",), True),
    ("classification", "شهادة تصنيف المقاولين", ("تصنيف",), False),
    ("local_content", "شهادة المحتوى المحلي", ("محتوى محلي", "المحتوى المحلي"), False),
    ("financials", "القوائم المالية المدققة لآخر 3 سنوات", ("قوائم مالية", "القوائم المالية", "ميزانية"), True),
    ("bank", "خطاب الاستعداد البنكي / الملاءة", ("بنك", "بنكي", "مصرف"), False),
    ("iso9001", "شهادة نظام إدارة الجودة ISO 9001", ("9001",), False),
    ("iso45001", "شهادة السلامة والصحة المهنية ISO 45001", ("45001", "18001"), False),
    ("iso14001", "شهادة الإدارة البيئية ISO 14001", ("14001",), False),
]

_REQ_TRIGGERS = re.compile(r"يجب|يشترط|يُشترط|على المتقدم|على المتنافس|المتقدم|إرفاق|ارفاق|تقديم|شهادة|تصنيف|خبرة|"
                           r"لا تقل|لا يقل|سنوات|مشاريع مماثلة|القوائم المالية|ضمان|الأيزو|ISO|معيار|وزن|درجة",
                           re.I)
_CRIT_KEYWORDS = {
    "experience": ("خبرة", "مشاريع مماثلة", "سابقة الأعمال", "مشروع مماثل", "أعمال مماثلة", "خطابات إنجاز", "شهادات إنجاز"),
    "financial": ("مالية", "القوائم", "ميزانية", "رأس المال", "ملاءة", "بنك", "حجم الأعمال", "إيرادات", "ضمان"),
    "staff": ("كادر", "الكوادر", "مهندس", "سيرة ذاتية", "السير الذاتية", "الهيكل التنظيمي", "موظف", "عمالة", "فريق"),
    "equipment": ("معدات", "آليات", "أسطول", "أجهزة", "موارد"),
    "quality": ("جودة", "سلامة", "بيئة", "ISO", "أيزو", "الأيزو", "HSE", "QHSE"),
    "legal": ("سجل تجاري", "زكاة", "ضريب", "تأمينات", "غرفة", "تصنيف", "رخصة", "ترخيص", "شهادة"),
    "local": ("محتوى محلي", "سعودة", "نطاقات", "توطين"),
}


def init_prequal_tables():
    with get_db() as db:
        db.executescript(SCHEMA)


# ================================================================ الخبير 1: محلل المتطلبات
def detect_category(text: str) -> tuple[str, str]:
    low = (text or "").lower()
    best, best_n = "default", 0
    for key, (label, kws) in _CATEGORIES.items():
        n = sum(1 for k in kws if k.lower() in low)
        if n > best_n:
            best, best_n = key, n
    return (best, _CATEGORIES[best][0]) if best != "default" else ("default", "أعمال عامة")


def extract_requirements(doc_text: str, limit: int = 45) -> list[dict]:
    """اشتراطات الجهة الصريحة من كراسة التأهيل: جمل تحمل إلزاماً أو معياراً، مصنفة بمعيارها."""
    out, seen = [], set()
    text = re.sub(r"[ \t]+", " ", doc_text or "")
    for raw in re.split(r"[\n\r]+|(?<=[.؛:])\s+(?=\d+[-.)]|[•●▪-])", text):
        line = raw.strip(" -•●▪\t")
        if not (18 <= len(line) <= 320) or not _REQ_TRIGGERS.search(line):
            continue
        if not re.search(r"[؀-ۿ]{3,}", line):
            continue
        key = re.sub(r"\W+", "", line)[:80]
        if key in seen:
            continue
        seen.add(key)
        crit = next((c for c, kws in _CRIT_KEYWORDS.items() if any(k.lower() in line.lower() for k in kws)), "legal")
        weight = None
        m = re.search(r"(\d{1,2})\s*(?:%|٪|درجة|نقطة)", line)
        if m and 2 <= int(m.group(1)) <= 60:
            weight = int(m.group(1))
        out.append({"text": line, "criterion": crit, "weight": weight})
        if len(out) >= limit:
            break
    return out


def _weights(category: str, requirements: list[dict]) -> dict:
    base = dict(_WEIGHTS.get(category) or _WEIGHTS["default"])
    stated = {}
    for r in requirements:
        if r.get("weight"):
            stated.setdefault(r["criterion"], r["weight"])
    if len(stated) >= 3 and 80 <= sum(stated.values()) <= 120:     # أوزان الجهة المعلنة تحلّ محل الافتراضية
        total = sum(stated.values())
        return {k: round(stated.get(k, 0) * 100 / total) for k in base}
    return base


# ================================================================ الخبير 2: ملاءمة النطاق
def scope_fit(category: str, profile: dict, settings: dict) -> dict:
    services = " ".join([s.get("title", "") + " " + s.get("text", "") for s in profile.get("services") or []]
                        + [str(a) for a in profile.get("activities") or []]
                        + [settings.get("company_services", ""), settings.get("company_classification", "")])
    contractor = bool(re.search(r"مقاول|مقاولات|إنشاء|انشاء", services))
    if category in _CONTRACTOR_SCOPE or category == "default":
        hits = [k for k in _CATEGORIES.get(category, ("", ()))[1] if k and k in services]
        in_scope = bool(hits) or contractor or category == "default"
    else:
        # خارج المقاولات (تقنية، إعاشة، حراسات، نقل): كلمات عامة مثل «أنظمة» و«بيانات» تظهر في
        # خدمات أي مقاول — النشاط لا يثبت إلا بعبارة تخصصية صريحة
        hits = [k for k in _CORE.get(category, ()) if k in services]
        in_scope = bool(hits)
    return {"in_scope": in_scope, "evidence": hits[:6],
            "note": ("ضمن نشاط الشركة المسجّل" if in_scope else
                     "خارج النشاط الأساسي للشركة — التأهيل يتطلب سجلاً ونشاطاً وخبرات في هذا المجال؛ "
                     "يُنصح بعدم التقدم منفرداً أو بالتحالف مع شركة متخصصة")}


# ================================================================ الخبير 3: الخبرات
# مجالات المشاريع — لجان التأهيل تقيس «المماثلة» بالمجال وطبيعة الأعمال لا بتطابق الكلمات
_DOMAINS = {
    "عسكري": ("عسكري", "العسكري", "قاعدة", "جنود", "الحرس", "القوات", "مهاجع", "أسلحة", "اسلحة", "كتيبة", "معسكر", "دفاع"),
    "بحري": ("ميناء", "بحري", "بحرية", "رصيف", "مرسى", "الساحل"),
    "صحي": ("مستشفى", "طبي", "طبية", "صحي", "صحية", "عيادات"),
    "سكني": ("سكني", "سكنية", "فلل", "فيلا", "مهاجع", "إسكان", "اسكان", "شقق"),
    "فندقي": ("فندق", "فندقي", "منتجع", "ضيافة"),
    "مطارات": ("مطار", "مطارات", "الطيران"),
    "طرق وبنية تحتية": ("طرق", "سفلتة", "جسور", "أنفاق", "تصريف", "سيول", "شبكات", "بنية تحتية"),
    "مستودعات وصناعي": ("مستودع", "مستودعات", "مصنع", "صناعي", "ورش"),
    "تعليمي": ("مدرسة", "مدارس", "جامعة", "كلية", "تعليمي"),
    "حكومي وإداري": ("مبنى إداري", "مقر", "وزارة", "أمانة", "إداري", "حكومي"),
    "تشغيل وصيانة": ("تشغيل", "صيانة", "نظافة"),
    "تجاري وترفيهي": ("مول", "تجاري", "ترفيه", "مجمع تجاري", "أسواق"),
}


def _domains(text: str) -> set:
    low = text or ""
    return {d for d, kws in _DOMAINS.items() if any(k in low for k in kws)}


def _similarity(inv_text: str, inv_tokens: set, inv_domains: set, cat_kws: tuple, text: str) -> int:
    """درجة المماثلة 0-100: طبيعة الأعمال (الفئة) + المجال + تقاطع المفردات."""
    score = 0
    if any(k.lower() in text.lower() for k in cat_kws):
        score += 35
    score += min(45, 30 * len(inv_domains & _domains(text)))
    overlap = len(inv_tokens & _tok(text))
    score += min(30, overlap * 8)
    return min(100, score)


# كلمات عامة لا تثبت أن مشروعين هما المشروع نفسه («إنشاء وتشطيب» تجمع عشرات المشاريع)
_GENERIC = {"انشاء", "تشطيب", "اعمال", "مشروع", "توريد", "تركيب", "صيانة", "منطقة", "بمنطقة", "تنفيذ",
            "بناء", "شركة", "مجمعات", "مباني", "تطوير"}


def _tok(text: str) -> set:
    from .similarity import _tokens
    return _tokens(text)


def _track_record(settings: dict) -> list[dict]:
    """سجل الأعمال بالقيم من المكتبة («• المشروع — العميل (73م ريال، 2023-2025)»)."""
    body = ""
    for e in list_library():
        if "الخبرات" in (e.get("category") or "") or "المشاريع المماثلة" in (e.get("title") or ""):
            body += "\n" + (e.get("body") or "")
    out = []
    for line in body.splitlines():
        line = line.strip(" •-\t")
        if len(line) < 12 or "—" not in line:
            continue
        m = re.search(r"\(([^)]*)\)\s*$", line)
        meta = m.group(1) if m else ""
        head = line[: m.start()].strip() if m else line
        name, _, client = head.partition("—")
        val = re.search(r"([\d.,]+)\s*م\s*ريال", meta)
        years = re.search(r"(20\d\d)(?:\s*-\s*(20\d\d))?", meta)
        out.append({"name": name.strip(), "client": client.strip(), "value_m": float(val.group(1).replace(",", "")) if val else None,
                    "years": years.group(0) if years else "", "status": "تحت التنفيذ" if "تحت التنفيذ" in meta else "منجز"})
    for line in (settings.get("company_references") or "").splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 2 and parts[0] and not any(r["name"] == parts[0] for r in out):
            out.append({"name": parts[0], "client": parts[1], "value_m": None, "years": "",
                        "status": "منجز", "scope": parts[2] if len(parts) > 2 else ""})
    return out


def match_experience(query: str, profile: dict, settings: dict, top: int = 8, category: str = "default") -> dict:
    q = _tok(query)
    qd = _domains(query)
    cat_kws = _CATEGORIES.get(category, ("", ()))[1]
    projects = []
    for p in profile.get("projects") or []:
        if str(p.get("relevance") or "").startswith("H"):        # مشاريع تراثية للعرض لا للخبرة المماثلة
            continue
        text = " ".join([p.get("name", ""), p.get("type", ""), p.get("sector", ""), p.get("client", ""),
                         " ".join(p.get("scope") or [])])
        score = _similarity(query, q, qd, cat_kws, text)
        projects.append({"name": p.get("name", ""), "client": p.get("client", ""), "type": p.get("type", ""),
                         "sector": p.get("sector", ""), "location": p.get("location", ""),
                         "scope": (p.get("scope") or [])[:5], "score": score, "source": "الملف التعريفي"})
    record = _track_record(settings)
    for r in record:
        score = _similarity(query, q, qd, cat_kws, f"{r['name']} {r['client']} {r.get('scope', '')}")
        # قيمة موثقة تُلحق بمشروع الملف التعريفي المطابق بالاسم بدل تكراره
        rt = _tok(r["name"]) - _GENERIC
        cands = [(len((_tok(p["name"]) - _GENERIC) & rt), p) for p in projects if not p.get("value_m")]
        cands = [c for c in cands if c[0] >= 2]
        twin = max(cands, key=lambda c: c[0])[1] if cands else None
        if twin:
            twin.update(value_m=r["value_m"], years=r["years"], status=r["status"])
            twin["score"] = max(twin["score"], score)
        else:
            projects.append({"name": r["name"], "client": r["client"], "type": r.get("scope", ""), "sector": "",
                             "location": "", "scope": [], "score": score, "value_m": r["value_m"],
                             "years": r["years"], "status": r["status"], "source": "سجل الأعمال"})
    projects.sort(key=lambda p: (-p["score"], -(p.get("value_m") or 0)))
    relevant = [p for p in projects if p["score"] >= 50]
    values = [r["value_m"] for r in record if r.get("value_m")]
    return {"selected": (relevant or projects)[:top], "relevant_count": len(relevant), "total_projects": len(projects),
            "domains": sorted(qd),
            "largest_value_m": max(values) if values else None, "portfolio_value_m": round(sum(values), 1) if values else None,
            "clients": (profile.get("clients") or [])[:14]}


# ================================================================ الخبير 4: الامتثال والوثائق
def check_compliance(deadline: str, settings: dict) -> list[dict]:
    docs = list_company_docs()
    try:
        due = datetime.strptime((deadline or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        due = datetime.now().date()
    today = datetime.now().date()
    known_numbers = {"cr": settings.get("company_cr"), "vat": settings.get("company_vat_no"),
                     "classification": settings.get("company_classification")}
    out = []
    for key, label, pats, mandatory in _REQUIRED_DOCS:
        # عدة نسخ من الوثيقة (قديمة ومجددة): تُعتمد الأحدث انتهاءً
        same = [d for d in docs if any(p in f"{d.get('name', '')} {d.get('notes', '')}" for p in pats)]
        doc = max(same, key=lambda d: d.get("expiry_date") or "9999") if same else None
        status, detail = "missing", "غير مسجلة في «وثائق الشركة»"
        if doc:
            exp = (doc.get("expiry_date") or "")[:10]
            try:
                exp_d = datetime.strptime(exp, "%Y-%m-%d").date() if exp else None
            except ValueError:
                exp_d = None
            if exp_d is None:
                status, detail = "valid", "مسجلة (بلا تاريخ انتهاء)"
            elif exp_d < today:
                status, detail = "expired", f"منتهية منذ {exp}"
            elif exp_d < due:
                status, detail = "expiring", f"تنتهي {exp} قبل موعد التقديم {due}"
            else:
                status, detail = "valid", f"سارية حتى {exp}"
        elif known_numbers.get(key):
            status, detail = "number_only", f"الرقم مسجل في الإعدادات ({known_numbers[key]}) — أرفق صورة الشهادة"
        out.append({"key": key, "label": label, "mandatory": mandatory, "status": status, "detail": detail,
                    "number": (doc or {}).get("number") or known_numbers.get(key) or ""})
    return out


# ================================================================ الخبراء 5-9: المال، الكوادر، المعدات، الجودة، المحتوى المحلي
def _num(text) -> int:
    m = re.search(r"\d[\d,]*", str(text or ""))
    return int(m.group(0).replace(",", "")) if m else 0


def resources(profile: dict, settings: dict) -> dict:
    eq = profile.get("equipment") or {}
    return {
        "staff_text": profile.get("staff") or "",
        "staff_count": _num(profile.get("staff")),
        "management": profile.get("management") or [],
        "support_group": settings.get("company_support_group", ""),
        "equipment_total": _num(eq.get("total")),
        "equipment": [{"name": c.get("name", ""), "count": c.get("count", "")} for c in eq.get("categories") or []],
        "certifications": profile.get("certifications") or [],
        "founded": profile.get("founded") or settings.get("company_founded", ""),
        "classification": profile.get("classification") or settings.get("company_classification", ""),
        "cities": profile.get("cities") or "",
        "achievements": (profile.get("achievements") or {}).get("items") or [],
    }


# ================================================================ الخبير 10: المقيّم
def assess(category: str, weights: dict, fit: dict, exp: dict, comp: list[dict], res: dict) -> dict:
    """الدرجة المتوقعة لكل معيار كما تحتسبها لجنة التأهيل، مع الدليل والنواقص وخطة السد."""
    st = {d["key"]: d["status"] for d in comp}
    ok = lambda k: st.get(k) == "valid"
    scores, gaps = {}, []

    strong = [p for p in exp["selected"] if p["score"] >= 60]
    s = 35 + min(45, len(strong) * 12) + min(20, (exp["relevant_count"] or 0) * 3)
    if exp.get("largest_value_m"):
        s += 5
    scores["experience"] = min(100, s)
    if len(strong) < 3:
        gaps.append(("experience", "عالية", "مشاريع مماثلة موثقة أقل من 3",
                     "أضف للملف التعريفي مشاريع مماثلة بنطاقها وقيمتها وأرفق شهادات/خطابات إنجازها من الملاك"))

    s = 40 + (20 if exp.get("largest_value_m") else 0) + (10 if (exp.get("portfolio_value_m") or 0) >= 100 else 0)
    s += 25 if ok("financials") else 0
    s += 5 if ok("bank") else 0
    scores["financial"] = min(100, s)
    if not ok("financials"):
        gaps.append(("financial", "حرجة", "القوائم المالية المدققة غير مسجلة أو غير سارية",
                     "أرفق القوائم المالية المدققة لآخر 3 سنوات (شرط في معظم دعوات التأهيل)"))
    if not ok("bank"):
        gaps.append(("financial", "متوسطة", "لا يوجد خطاب ملاءة/استعداد بنكي",
                     "اطلب من البنك خطاب ملاءة باسم الجهة المالكة قبل موعد التقديم"))

    n = res["staff_count"]
    s = 40 + (30 if n >= 200 else 20 if n >= 80 else 10 if n >= 30 else 0)
    s += 15 if res["management"] else 0
    s += 10 if res["support_group"] else 0
    scores["staff"] = min(100, s)
    if not res["management"]:
        gaps.append(("staff", "عالية", "السير الذاتية للكوادر الرئيسية غير مسجلة في الملف التعريفي",
                     "أضف مدير المشروع ومهندسي التخطيط والجودة والسلامة بسيرهم الذاتية وشهادات هيئة المهندسين"))

    eqn = res["equipment_total"]
    s = 40 + (45 if eqn >= 50 else 30 if eqn >= 20 else 15 if eqn else 0) + (10 if res["equipment"] else 0)
    scores["equipment"] = min(100, s if category in ("construction", "default", "landscape", "electrical") else s + 10)

    s = 40 + min(40, len(res["certifications"]) * 15)
    s += 10 if ok("iso9001") else 0
    s += 10 if ok("iso45001") or ok("iso14001") else 0
    scores["quality"] = min(100, s)
    if not res["certifications"] and not ok("iso9001"):
        gaps.append(("quality", "عالية", "لا توجد شهادات أيزو مسجلة",
                     "أرفق شهادات ISO 9001 و45001 و14001 السارية، أو خطة الجودة والسلامة المعتمدة للمشروع"))

    mand = [d for d in comp if d["mandatory"]]
    valid = [d for d in mand if d["status"] == "valid"]
    scores["legal"] = round(100 * len(valid) / max(1, len(mand)))
    for d in comp:
        if d["key"] == "financials":          # مغطاة في محور القدرة المالية
            continue
        if d["status"] in ("missing", "expired", "expiring", "number_only") and (d["mandatory"] or d["key"] == "classification"):
            pr = "حرجة" if d["status"] in ("expired", "expiring") or d["key"] in ("cr", "zakat", "gosi") else "عالية"
            act = {"expired": "جدّدها فوراً", "expiring": "جدّدها قبل موعد التقديم",
                   "number_only": "ارفع صورة الشهادة في «وثائق الشركة»"}.get(d["status"], "استخرجها وسجّلها في «وثائق الشركة»")
            gaps.append(("legal", pr, f"{d['label']}: {d['detail']}", act))

    scores["local"] = 80 if ok("saudization") else 55
    scores["local"] += 15 if ok("local_content") else 0
    scores["local"] = min(100, scores["local"])
    if not ok("local_content"):
        gaps.append(("local", "متوسطة", "لا توجد شهادة محتوى محلي",
                     "استخرج شهادة المحتوى المحلي من هيئة المحتوى المحلي (يرفع التقييم في المشاريع الحكومية)"))

    total = round(sum(scores[k] * weights.get(k, 0) for k in scores) / max(1, sum(weights.values())))
    if not fit["in_scope"]:
        total = min(total, 40)
        gaps.insert(0, ("scope", "حرجة", "المشروع خارج النشاط الأساسي للشركة", fit["note"]))
    critical = sum(1 for g in gaps if g[1] == "حرجة")
    if not fit["in_scope"]:
        verdict, tone = "لا يُنصح بالتقدم منفرداً", "red"
    elif total >= 80 and not critical:
        verdict, tone = "جاهزية عالية للتأهيل", "green"
    elif total >= 65:
        verdict, tone = "قابل للتأهيل بعد سد النواقص", "amber"
    else:
        verdict, tone = "مخاطرة عالية — يحتاج استكمالاً جوهرياً", "red"
    order = {"حرجة": 0, "عالية": 1, "متوسطة": 2}
    gaps.sort(key=lambda g: order.get(g[1], 3))
    return {"scores": scores, "total": total, "verdict": verdict, "tone": tone,
            "gaps": [{"criterion": g[0], "priority": g[1], "gap": g[2], "action": g[3]} for g in gaps]}


# ================================================================ الكاتب
def _template_writing(inv: dict, company: str, cat_label: str, fit: dict, exp: dict, res: dict,
                      assessment: dict, reqs: list[dict]) -> dict:
    top = exp["selected"][:3]
    names = "، ".join(p["name"] for p in top)
    val = f"، بمحفظة أعمال موثقة تتجاوز {exp['portfolio_value_m']:,.0f} مليون ريال" if exp.get("portfolio_value_m") else ""
    themes = [x for x in (
        f"خبرة مباشرة في {cat_label}: {names}" if names else "",
        f"تصنيف {res['classification']}" if res["classification"] else "",
        f"{res['staff_text']} من الكوادر الفنية والإدارية" if res["staff_text"] else "",
        f"أسطول من {res['equipment_total']} معدة وآلية مملوكة" if res["equipment_total"] else "",
        f"عملاء كبار منهم: {'، '.join(exp['clients'][:4])}" if exp["clients"] else "",
    ) if x]
    letter = [
        f"إشارةً إلى دعوتكم للتأهيل المسبق لمشروع «{inv['name']}»، يسرّ {company} أن تتقدم بملف تأهيلها "
        f"مستوفياً متطلبات الدعوة، مؤكدةً قدرتها الفنية والمالية والإدارية على تنفيذ الأعمال وفق أعلى المعايير.",
        f"تمتلك الشركة خبرة مباشرة في {cat_label}{val}، وتعرض في هذا الملف مشاريعها المماثلة وجهازها الفني "
        f"ومعداتها وأنظمة الجودة والسلامة لديها، مع مصفوفة امتثال تربط كل متطلب من متطلباتكم بدليله.",
        "ونتطلع إلى تأهيلنا ودعوتنا للمنافسة، مؤكدين التزامنا الكامل بنظام المنافسات والمشتريات الحكومية ولائحته التنفيذية.",
    ]
    summary = (f"تتقدم {company} للتأهيل المسبق لمشروع «{inv['name']}» لصالح {inv['agency']}. "
               f"يُظهر الملف ملاءمة الشركة لنطاق المشروع ({cat_label}) من خلال {exp['relevant_count']} مشروعاً مماثلاً موثقاً"
               f"{val}، وجهازاً فنياً وأسطول معدات يغطيان متطلبات التنفيذ، ووثائق نظامية سارية.")
    narratives = {
        "experience": f"نفذت الشركة {exp['total_projects']} مشروعاً في محفظتها، منها {exp['relevant_count']} مشروعاً مماثلاً لنطاق هذه الدعوة؛ "
                      f"أبرزها: {names}.",
        "financial": ("تتمتع الشركة بملاءة مالية تدعمها محفظة أعمال منفذة"
                      + (f" يبلغ أكبر عقودها {exp['largest_value_m']:,.0f} مليون ريال" if exp.get("largest_value_m") else "")
                      + "، وتُرفق قوائمها المالية المدققة وخطاب الاستعداد البنكي."),
        "staff": f"يضم الجهاز الفني والإداري للشركة {res['staff_text'] or 'كوادر هندسية وفنية متخصصة'}"
                 + (f"، مدعوماً بمجموعة الدعم الفني: {res['support_group']}" if res["support_group"] else "") + ".",
        "equipment": (f"تمتلك الشركة أسطولاً من {res['equipment_total']} معدة وآلية تغطي احتياجات التنفيذ"
                      if res["equipment_total"] else "توفر الشركة المعدات اللازمة للتنفيذ ملكاً أو استئجاراً من موردين معتمدين") + ".",
        "quality": "تطبق الشركة نظاماً متكاملاً لإدارة الجودة والسلامة والصحة المهنية والبيئة (QHSE) يشمل خطة جودة "
                   "معتمدة للمشروع، وخطة سلامة وفق اشتراطات الجهة والدفاع المدني، وتقارير دورية.",
        "legal": "تُرفق الشركة وثائقها النظامية السارية: السجل التجاري، وشهادات الزكاة والضريبة والتأمينات والسعودة والغرفة التجارية وشهادة التصنيف.",
        "local": "تلتزم الشركة بسياسات التوطين والمحتوى المحلي، وتعطي الأولوية للموردين والمصنعين المحليين ومقاولي الباطن السعوديين.",
    }
    sec = {"experience": "الخبرات والمشاريع المماثلة", "financial": "القدرة المالية", "staff": "الجهاز الفني والكوادر",
           "equipment": "المعدات والموارد", "quality": "الجودة والسلامة والبيئة", "legal": "الوثائق النظامية المرفقة",
           "local": "المحتوى المحلي والتوطين"}
    rows = reqs or [{"text": t, "criterion": c} for t, c in _STANDARD_REQS]
    compliance = [{"requirement": r["text"], "criterion": r["criterion"],
                   "response": f"مستوفى — {_STANDARD_RESP.get(r['criterion'], '')} الدليل: قسم «{sec.get(r['criterion'], 'الوثائق النظامية المرفقة')}»."}
                  for r in rows]
    return {"engine": "template", "letter": letter, "summary": summary, "win_themes": themes,
            "narratives": narratives, "compliance": compliance, "risks": []}


# المتطلبات المعتادة في دعوات التأهيل الحكومية — تُستخدم حين لا تُرفق الكراسة
_STANDARD_REQS = [
    ("تقديم بيان بالمشاريع المماثلة المنفذة خلال السنوات الماضية مع قيمها وشهادات إنجازها", "experience"),
    ("تقديم القوائم المالية المدققة لآخر ثلاث سنوات", "financial"),
    ("تقديم ما يثبت الملاءة المالية (خطاب بنكي / حجم الأعمال)", "financial"),
    ("تقديم الهيكل التنظيمي للمشروع والسير الذاتية للكوادر الرئيسية", "staff"),
    ("تقديم قائمة بالمعدات والآليات المملوكة والمستأجرة", "equipment"),
    ("تقديم خطة الجودة وخطة السلامة والصحة المهنية وشهادات الأيزو إن وجدت", "quality"),
    ("تقديم السجل التجاري وشهادات الزكاة والضريبة والتأمينات والسعودة والغرفة التجارية سارية", "legal"),
    ("تقديم شهادة تصنيف المقاولين في المجال والدرجة المطلوبين", "legal"),
    ("الالتزام بمتطلبات المحتوى المحلي وتوطين الوظائف", "local"),
    ("الإقرار بصحة البيانات المقدمة والالتزام بنظام المنافسات والمشتريات الحكومية", "legal"),
]
_STANDARD_RESP = {
    "experience": "أرفقنا بيان المشاريع المماثلة بعملائها وقيمها وفتراتها.",
    "financial": "أرفقنا القوائم المالية المدققة وما يثبت الملاءة.",
    "staff": "أرفقنا الهيكل الوظيفي للمشروع والكوادر الرئيسية.",
    "equipment": "أرفقنا قائمة المعدات المملوكة بفئاتها وأعدادها.",
    "quality": "نطبق نظاماً متكاملاً للجودة والسلامة والبيئة مع خطط معتمدة للمشروع.",
    "legal": "أرفقنا الوثائق النظامية السارية.",
    "local": "نلتزم بسياسات المحتوى المحلي والتوطين.",
}


_AI_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["letter", "summary", "win_themes", "narratives", "compliance", "risks"],
    "properties": {
        "letter": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
        "win_themes": {"type": "array", "items": {"type": "string"}},
        "narratives": {"type": "object", "additionalProperties": False,
                       "required": [k for k, _, _ in _CRITERIA],
                       "properties": {k: {"type": "string"} for k, _, _ in _CRITERIA}},
        "compliance": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["requirement", "response", "criterion"],
            "properties": {"requirement": {"type": "string"}, "response": {"type": "string"},
                           "criterion": {"type": "string", "enum": [k for k, _, _ in _CRITERIA]}}}},
        "risks": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["risk", "mitigation"],
            "properties": {"risk": {"type": "string"}, "mitigation": {"type": "string"}}}},
    },
}

_AI_SYSTEM = """أنت فريق من كبار خبراء إعداد ملفات التأهيل المسبق للمشاريع الحكومية في المملكة العربية السعودية:
مدير عروض، ومهندس عقود، ومحلل مالي، ومدير جودة وسلامة، وخبير محتوى محلي — خبرة كل منكم تتجاوز عشرين عاماً
في نظام المنافسات والمشتريات الحكومية ومنصة اعتماد ولجان التأهيل.

مهمتكم: صياغة ملف تأهيل مسبق مقنع يجعل لجنة التأهيل تمنح الشركة أعلى درجة ممكنة.

قواعد صارمة:
- استخدموا الأدلة المعطاة فقط (مشاريع الشركة، قيمها، كوادرها، معداتها، وثائقها). لا تختلقوا مشروعاً أو رقماً
  أو شهادة أو اسماً غير موجود في الأدلة. إن كان دليل ناقصاً فاذكروا الالتزام بتقديمه لا وجوده.
- اكتبوا بعربية فصيحة مهنية بضمير المتكلم الجمع باسم الشركة، بجمل محددة ومدعومة بالأرقام، بلا مبالغات فارغة.
- الردود في مصفوفة الامتثال تذكر كيف تستوفي الشركة المتطلب وأين دليله في الملف.
- المخاطر: مخاطر تأهيل حقيقية (نواقص) مع إجراء تخفيف عملي."""


def _ai_writing(inv: dict, company: str, cat_label: str, evidence: dict, reqs: list[dict]) -> dict | None:
    from .ai_engine import _active_model, ai_available
    from .config import ANTHROPIC_API_KEY
    if not ai_available():
        return None
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    user = (f"## دعوة التأهيل\n- المشروع: {inv['name']}\n- الجهة: {inv['agency']}\n- آخر موعد للتقديم: {inv.get('deadline', '')}\n"
            f"- فئة المشروع: {cat_label}\n- اسم الشركة المتقدمة: {company}\n\n"
            f"## اشتراطات الجهة المستخرجة من كراسة التأهيل ({len(reqs)})\n"
            + ("\n".join(f"- [{r['criterion']}] {r['text']}" for r in reqs) or "(لم تُرفق الكراسة — اعتمدوا المعايير المعتادة)")
            + "\n\n## أدلة الشركة (لا تستخدموا غيرها)\n" + json.dumps(evidence, ensure_ascii=False)[:60000]
            + "\n\nاكتبوا ملف التأهيل وفق المخطط: خطاب التقديم (3-4 فقرات)، ملخص تنفيذي، محاور التميز (5-7)، "
              "سرد لكل معيار من المعايير السبعة، رد لكل اشتراط في مصفوفة الامتثال (بنفس ترتيبها؛ وإن لم تُرفق "
              "الكراسة فاكتبوا 10 ردود على المتطلبات المعتادة)، ومخاطر التأهيل وتخفيفها.")
    try:
        with client.messages.stream(
            model=_active_model(), max_tokens=32000, thinking={"type": "adaptive"},
            output_config={"effort": "high", "format": {"type": "json_schema", "schema": _AI_SCHEMA}},
            system=[{"type": "text", "text": _AI_SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
        ) as stream:
            msg = stream.get_final_message()
    except anthropic.APIError:
        return None
    if msg.stop_reason in ("refusal", "max_tokens"):
        return None
    text = next((b.text for b in msg.content if b.type == "text"), "")
    try:
        data = json.loads(text)
    except ValueError:
        return None
    data["engine"] = "claude"
    return data


# ================================================================ التنسيق
def build_dossier(tender: dict, doc_text: str = "", notes: str = "") -> dict:
    """ملف التأهيل الكامل لدعوة واحدة: الأدلة + التقييم + النصوص."""
    from .company_profile import get_profile
    settings = get_settings()
    profile = get_profile(cid()) or {}
    company = settings.get("company_name") or profile.get("name_ar") or "الشركة"
    inv = {"id": tender.get("id"), "name": tender.get("name", ""), "agency": tender.get("agency", ""),
           "deadline": tender.get("deadline", ""), "published": tender.get("published", ""),
           "url": tender.get("details_url", ""), "type": tender.get("tender_type") or "تأهيل مسبق",
           "activity": tender.get("activity", "")}
    query = f"{inv['name']} {inv['activity']} {(doc_text or '')[:3000]}"
    category, cat_label = detect_category(f"{inv['name']} {inv['activity']} {(doc_text or '')[:2000]}")
    reqs = extract_requirements(doc_text)
    weights = _weights(category, reqs)
    fit = scope_fit(category, profile, settings)
    exp = match_experience(query, profile, settings, category=category)
    comp = check_compliance(inv["deadline"], settings)
    res = resources(profile, settings)
    assessment = assess(category, weights, fit, exp, comp, res)
    try:
        days_left = (datetime.strptime(inv["deadline"][:10], "%Y-%m-%d").date() - datetime.now().date()).days
    except ValueError:
        days_left = None
    evidence = {"company": company, "about": profile.get("about") or settings.get("company_intro", ""),
                "founded": res["founded"], "classification": res["classification"], "staff": res["staff_text"],
                "cities": res["cities"], "support_group": res["support_group"],
                "similar_projects": exp["selected"], "largest_contract_million_sar": exp["largest_value_m"],
                "portfolio_million_sar": exp["portfolio_value_m"], "clients": exp["clients"],
                "equipment_total": res["equipment_total"], "equipment": res["equipment"],
                "certifications": res["certifications"], "management": res["management"],
                "documents": [{"doc": d["label"], "status": d["status"], "detail": d["detail"]} for d in comp],
                "achievements": res["achievements"], "gaps": assessment["gaps"], "user_notes": notes}
    writing = _ai_writing(inv, company, cat_label, evidence, reqs) or _template_writing(
        inv, company, cat_label, fit, exp, res, assessment, reqs)
    return {
        "version": 1, "built_at": now_iso(), "invitation": inv, "company": company,
        "category": category, "category_label": cat_label, "weights": weights,
        "requirements": reqs, "requirements_source": "كراسة التأهيل المرفوعة" if reqs else "المعايير المعتادة لدعوات التأهيل",
        "fit": fit, "experience": exp, "compliance": comp, "resources": res, "assessment": assessment,
        "days_left": days_left, "writing": writing, "notes": notes,
        "panel": _panel(fit, exp, comp, res, assessment),
    }


def _panel(fit, exp, comp, res, assessment) -> list[dict]:
    """توقيع فريق المراجعة — ملاحظة كل خبير على محوره (تظهر في صفحة المراجعة الداخلية)."""
    bad_docs = [d["label"] for d in comp if d["status"] in ("missing", "expired", "expiring") and d["mandatory"]]
    sc = assessment["scores"]
    return [
        {"role": "مدير العروض والتأهيل", "note": f"الحكم: {assessment['verdict']} — الدرجة المتوقعة {assessment['total']}%."},
        {"role": "مدقق ملاءمة النطاق", "note": fit["note"]},
        {"role": "خبير الخبرات والمشاريع", "note": f"{exp['relevant_count']} مشروعاً مماثلاً من {exp['total_projects']} — درجة {sc['experience']}%."},
        {"role": "المحلل المالي", "note": f"أكبر عقد موثق: {exp['largest_value_m'] or '—'} م ريال — درجة {sc['financial']}%."},
        {"role": "مهندس العقود والامتثال", "note": ("وثائق ناقصة/منتهية: " + "، ".join(bad_docs)) if bad_docs else "الوثائق الإلزامية سارية."},
        {"role": "خبير الموارد البشرية", "note": f"{res['staff_text'] or '—'} — درجة {sc['staff']}%."},
        {"role": "خبير المعدات", "note": f"{res['equipment_total'] or 0} معدة — درجة {sc['equipment']}%."},
        {"role": "مدير الجودة والسلامة", "note": f"شهادات مسجلة: {len(res['certifications'])} — درجة {sc['quality']}%."},
        {"role": "خبير المحتوى المحلي", "note": f"درجة {sc['local']}%."},
        {"role": "المقيّم (محاكاة لجنة التأهيل)", "note": f"{len(assessment['gaps'])} ملاحظة، منها {sum(1 for g in assessment['gaps'] if g['priority'] == 'حرجة')} حرجة."},
    ]


def save_dossier(tender_id: int, data: dict) -> int:
    init_prequal_tables()
    with get_db() as db:
        cur = db.execute("INSERT INTO prequal_dossiers (company_id, tender_id, data, created_at) VALUES (?, ?, ?, ?)",
                         (cid(), int(tender_id), json.dumps(data, ensure_ascii=False), now_iso()))
        return cur.lastrowid


def latest_dossier(tender_id: int) -> dict | None:
    init_prequal_tables()
    with get_db() as db:
        r = db.execute("SELECT id, data, created_at FROM prequal_dossiers WHERE company_id = ? AND tender_id = ? "
                       "ORDER BY id DESC LIMIT 1", (cid(), int(tender_id))).fetchone()
    if not r:
        return None
    d = json.loads(r["data"])
    d["dossier_id"] = r["id"]
    return d


def dossier_tender_ids() -> set:
    init_prequal_tables()
    with get_db() as db:
        return {r["tender_id"] for r in db.execute("SELECT DISTINCT tender_id FROM prequal_dossiers WHERE company_id = ?", (cid(),))}
