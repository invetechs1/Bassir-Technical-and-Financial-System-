"""هيكل العرض الفني والمالي المعتمد — طبق نموذج «عزوم / برج مكين 100».

يحوّل بيانات العرض (أقسام، جدول كميات، خطة، فريق، إعدادات الشركة) إلى هيكل
موحَّد من تسعة أقسام مرقّمة كما في العروض الاحترافية:

  الغلاف ← خطاب التقديم ← 1 نبذة عن الشركة والمؤهلات ← 2 فهم نطاق الأعمال
  ← 3 منهجية التنفيذ ← 4 البرنامج الزمني المبدئي ← 5 الفريق والمعدات والموردون
  ← 6 ضبط الجودة والسلامة ← 7 العرض المالي (+ 7.5 جدول الكميات المسعّر)
  ← 8 مقترحات الهندسة القيمية (إن وُجدت) ← 9 الافتراضات والتحفظات والإقرار

كل قسم قائمة «كتل» مجرّدة (فقرة، نقاط، جدول، مخطط زمني...) يرسمها مُصدّر Word
— فالمحتوى يُختبر مستقلاً عن التنسيق. محتوى Claude المهيكل (data["structure"])
يتقدم دائماً، وما غاب منه يُشتق من بيانات العرض نفسها فلا يخرج قسم فارغ.
"""
import math
import re
from datetime import date, datetime, timedelta

from .arabic_numbers import amount_in_words
from .proposal_builder import client_facing_pricing

_MONTHS_AR = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس",
              "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]
_SECTION_TITLES = {
    "company": "نبذة عن الشركة والمؤهلات",
    "scope": "فهم نطاق الأعمال",
    "method": "منهجية التنفيذ",
    "schedule": "البرنامج الزمني المبدئي",
    "team": "الفريق والمعدات والموردون",
    "qhse": "ضبط الجودة والسلامة",
    "financial": "العرض المالي",
    "boq": "جدول الكميات المسعّر — الملحق رقم (1)",
    "ve": "مقترحات الهندسة القيمية (منفصلة واختيارية)",
    "terms": "الافتراضات والتحفظات والإقرار",
}


# نقاط الجودة والسلامة الافتراضية حين لا يكتبها Claude — محددة وقابلة للتطبيق،
# بدل اقتطاع جمل من نصوص المكتبة (تحمل جداول مسطّحة وأرقاماً من عروض أخرى)
_QHSE_DEFAULTS = {
    "construction": (
        ["خطة جودة المشروع (PQP) وبيانات طرق التنفيذ (Method Statements) وخطة الفحص والاختبار (ITP) لكل نشاط، تُقدَّم خلال 14 يوماً من التعميد.",
         "اعتماد المواد (Material Submittals) قبل التوريد، وعدم استبدال أي مورد إلا بموافقة خطية.",
         "طلب الفحص قبل 24 ساعة من أي صب أو تغطية، وعدم المتابعة قبل اعتماد الاستشاري.",
         "اختبارات الخرسانة لكل شحنة: القوام والحرارة، وأسطوانات كسر عند 7 و28 يوماً.",
         "اختبارات العزل والتسليح والتشطيبات وفق المواصفات، بمختبر معتمد.",
         "إقفال تقارير عدم المطابقة (NCR) خلال المدة المحددة، وسجل جودة يومي موثق.",
         "مخططات تنفيذية (Shop Drawings) معتمدة قبل التنفيذ، ومخططات As-Built عند التسليم."],
        ["مسؤول سلامة متفرغ في الموقع، وتوعية يومية (Toolbox Talk) قبل بدء العمل.",
         "تصاريح عمل للأعمال الخطرة: الرفع، والعمل على ارتفاع، والحفر، والأعمال الساخنة.",
         "حواجز وحواف حماية ومنصات عمل آمنة، وشبكات حماية عند الحاجة.",
         "معدات الوقاية الشخصية إلزامية لكل العاملين والزوار.",
         "خطة رفع (Lifting Plan) لكل عملية رفع، ومشغلون معتمدون للمعدات.",
         "عمالة نظامية بالكامل، والتزام باشتراطات البلدية والدفاع المدني.",
         "نظافة يومية وترحيل المخلفات، وتسليم الموقع نظيفاً."]),
    "maintenance": (
        ["خطة تشغيل وصيانة سنوية معتمدة، وجداول صيانة وقائية لكل أصل.",
         "سجل أصول محدَّث بحالة كل أصل وتاريخ صيانته.",
         "الاستجابة للبلاغات ضمن الأزمنة المحددة في العقد، وتوثيق إغلاق كل بلاغ.",
         "مؤشرات أداء شهرية (KPIs) بنسب الإنجاز وأزمنة الاستجابة.",
         "قطع غيار أصلية أو معتمدة، ولا استبدال دون موافقة الجهة المالكة.",
         "تقارير شهرية للجهة المالكة، واجتماعات متابعة دورية."],
        ["تصاريح عمل وعزل مصادر الطاقة (LOTO) قبل أي صيانة كهربائية أو ميكانيكية.",
         "معدات الوقاية الشخصية إلزامية، وتدريب دوري للفنيين.",
         "لافتات تحذيرية وعزل مناطق العمل أثناء الصيانة في المواقع المشغولة.",
         "مواد تنظيف وكيماويات معتمدة مع صحائف بيانات السلامة (SDS).",
         "خطة طوارئ وإخلاء بالتنسيق مع إدارة المبنى."]),
}


# ------------------------------- أدوات صغيرة -------------------------------

def money(v) -> str:
    """صيغة المبالغ كما في النموذج: فواصل آلاف وبلا كسور إن كان المبلغ صحيحاً."""
    v = float(v or 0)
    return f"{v:,.0f}" if abs(v - round(v)) < 0.005 else f"{v:,.2f}"


def qty_fmt(v) -> str:
    v = float(v or 0)
    return f"{v:,.0f}" if abs(v - round(v)) < 0.005 else f"{v:,.2f}".rstrip("0").rstrip(".")


def arabic_date(d: date) -> str:
    return f"{d.day} {_MONTHS_AR[d.month - 1]} {d.year}م"


def _parse_date(value) -> date:
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except Exception:
        return date.today()


def months_text(n: int) -> str:
    if n == 1:
        return "شهر واحد"
    if n == 2:
        return "شهران"
    if 3 <= n <= 10:
        return f"{n} أشهر"
    return f"{n} شهراً"


def weeks_text(n: int) -> str:
    if n == 1:
        return "أسبوع واحد"
    if n == 2:
        return "أسبوعان"
    if 3 <= n <= 10:
        return f"{n} أسابيع"
    return f"{n} أسبوعاً"


def _first_paragraph(body: str, max_len: int = 520) -> str:
    for line in (body or "").split("\n"):
        line = line.strip()
        if len(line) >= 30:
            return line if len(line) <= max_len else line[:max_len].rsplit(" ", 1)[0] + "…"
    return ""


def _find_section(sections: list[dict], *keys: str) -> str:
    for sec in sections or []:
        title = (sec.get("title") or "").replace("ـ", "")
        if any(k in title for k in keys):
            return sec.get("body") or ""
    return ""


def _lines_pipe(text: str, cols: int) -> list[list[str]]:
    rows = []
    for line in (text or "").split("\n"):
        parts = [p.strip() for p in line.split("|")]
        if len([p for p in parts if p]) >= 2:
            rows.append((parts + [""] * cols)[:cols])
    return rows


def _lead_lines(text: str) -> list[tuple[str, str]]:
    """«العنوان: النص» لكل سطر — للتحفظات القياسية المحفوظة في الإعدادات."""
    out = []
    for line in (text or "").split("\n"):
        line = line.strip(" •-–")
        if not line:
            continue
        if ":" in line[:40]:
            lead, rest = line.split(":", 1)
            out.append((lead.strip(), rest.strip()))
        else:
            out.append(("", line))
    return out


# ------------------------------- البناء -------------------------------

def _won_references(limit: int = 6) -> list[list[str]]:
    """سابقة أعمال من أرشيف العروض الفائزة — احتياط حين لا تُضبط في الإعدادات."""
    try:
        from .database import get_db
        from .tenancy import cid
        with get_db() as db:
            rows = db.execute(
                "SELECT title, client FROM proposals WHERE company_id = ? AND status = 'فائز' "
                "ORDER BY id DESC LIMIT ?", (cid(), limit)).fetchall()
        return [[r["title"], r["client"], ""] for r in rows]
    except Exception:
        return []


def _breakdown(loaded: list[dict], st: dict, subtotal: float) -> list[list]:
    """التفصيل الاسترشادي للمبلغ: مجموعات بنود بمبالغها ونسبها من الإجمالي.

    Claude يحدد المجموعات بأرقام البنود (item_numbers) والمبالغ تُحسب هنا من
    الأسعار المحمَّلة — لا نثق بحساب النموذج. الاحتياط: التجميع بتصنيف قاعدة
    الأسعار أو بادئة كود البند."""
    groups: list[tuple[str, float]] = []
    ai_groups = st.get("breakdown") or []
    if ai_groups:
        used = set()
        for g in ai_groups:
            idx = [int(n) - 1 for n in g.get("item_numbers") or [] if 0 < int(n) <= len(loaded)]
            idx = [i for i in idx if i not in used]
            used.update(idx)
            if idx:
                groups.append((g.get("name") or "", sum(loaded[i]["total"] for i in idx)))
        rest = [i for i in range(len(loaded)) if i not in used]
        if rest and groups:
            groups.append(("بنود أخرى", sum(loaded[i]["total"] for i in rest)))
    else:
        try:
            from .database import list_price_items
            cats = {i["code"]: i.get("category") or "" for i in list_price_items()}
        except Exception:
            cats = {}
        order: dict[str, float] = {}
        for line in loaded:
            code = (line.get("code") or "").strip()
            key = cats.get(code) or (re.split(r"[.\-]", code)[0] if code else "")
            key = key or "أعمال عامة"
            if re.fullmatch(r"\d+", key):
                key = f"أعمال القسم {key}"
            order[key] = order.get(key, 0) + line["total"]
        groups = list(order.items())
    if len(groups) < 2:
        return []
    total = sum(v for _, v in groups) or 1
    # المبالغ تُقاس على قيمة العرض نفسها (قد تختلف عن مجموع البنود بتقريب المبلغ المقطوع)
    scaled = [round(v * subtotal / total) for _, v in groups]
    if scaled:
        big_i = max(range(len(scaled)), key=lambda i: scaled[i])
        scaled[big_i] += round(subtotal) - sum(scaled)
    rows = [[str(i), name, money(scaled[i - 1]), f"{v / total * 100:.1f}"]
            for i, (name, v) in enumerate(groups, 1)]
    # فرق التقريب في النسب يُمتص في أكبر مجموعة فيصبح المجموع 100 تماماً
    pct = [float(r[3]) for r in rows]
    diff = round(100 - sum(pct), 1)
    if abs(diff) >= 0.1:
        big = max(range(len(rows)), key=lambda i: pct[i])
        rows[big][3] = f"{pct[big] + diff:.1f}"
    return rows


def _gantt_bars(st: dict, plan: list[dict], months: int) -> list[tuple[str, float, float]]:
    bars = []
    for b in st.get("schedule_bars") or []:
        try:
            s, e = float(b["start_month"]), float(b["end_month"])
        except (KeyError, TypeError, ValueError):
            continue
        s, e = max(0.0, s), min(float(months), max(e, s + 0.25))
        if b.get("task"):
            bars.append((b["task"], s, e))
    if bars:
        return bars
    # احتياط: مراحل الخطة متتابعة بمددها الأسبوعية محوَّلة إلى أشهر
    cursor = 0.0
    for ph in plan or []:
        w = float(ph.get("duration_weeks") or 0)
        span = w / 4.345
        bars.append((ph.get("phase") or "", round(cursor, 2), round(min(months, cursor + span), 2)))
        cursor += span
    return bars


def build_structure(proposal: dict, settings: dict) -> dict:
    data = proposal.get("data") or {}
    st = data.get("structure") or {}
    sections_src = data.get("technical_sections") or []
    company = settings.get("company_name") or ""
    client = proposal.get("client") or ""
    title = proposal.get("title") or ""
    created = _parse_date(proposal.get("created_at") or date.today().isoformat())
    validity = int(float(settings.get("validity_days") or 90))
    vat_rate = float((data.get("financial") or {}).get("vat_rate", settings.get("vat_rate", 15)) or 15)
    lump = (st.get("pricing_mode") or "remeasured") == "lump_sum"

    fin = data.get("financial") or {}
    loaded = client_facing_pricing(data.get("boq") or [], fin) if data.get("boq") else []
    subtotal = float(fin.get("subtotal") or 0)
    vat = float(fin.get("vat") or 0)
    grand = float(fin.get("grand_total") or 0)
    indicative = subtotal
    if lump and subtotal:
        # المبلغ المقطوع رقم مستدير ملزم، وأسعار الوحدات صحيحة استرشادية — كما في
        # النموذج: الجدول المسعّر لتقييم أوامر التغيير فقط، والفرق يوضَّح بملاحظة
        for l in loaded:
            kids = l.get("children") or []
            for k in kids:
                k["unit_price"] = float(round(float(k.get("unit_price") or 0)))
                k["total"] = round(k["unit_price"] * float(k.get("qty") or 0), 2)
            if kids:
                l["total"] = round(sum(k["total"] for k in kids), 2)
                q = float(l.get("qty") or 0)
                l["unit_price"] = round(l["total"] / q, 2) if q else 0.0
            else:
                l["unit_price"] = float(round(float(l.get("unit_price") or 0)))
                l["total"] = round(l["unit_price"] * float(l.get("qty") or 0), 2)
        indicative = round(sum(l["total"] for l in loaded), 2) if loaded else subtotal
        step = 1000 if subtotal >= 100_000 else 100
        subtotal = float(round(subtotal / step) * step)
        vat = round(subtotal * vat_rate / 100, 2)
        grand = round(subtotal + vat, 2)

    plan = data.get("plan") or []
    weeks = int(round(float(data.get("duration_weeks") or sum(float(p.get("duration_weeks") or 0)
                                                               for p in plan) or 0)))
    months = int(float(st.get("duration_months") or 0))
    if not months and weeks:
        months = max(1, math.ceil(weeks / 4.345))
    if months and not (weeks and weeks < 8 and not st.get("duration_months")):
        duration = months_text(months) + (" ميلادية متصلة" if months > 2 else "")
    elif weeks:
        duration = weeks_text(weeks)
    else:
        duration = "حسب البرنامج الزمني المعتمد"

    scope_title = (st.get("scope_title") or "").strip() or title
    subtitle = (st.get("subtitle") or "").strip() or (client if scope_title == title else title)
    ve_items = st.get("ve_items") or []
    mode_line = ("بنظام المبلغ المقطوع (Lump Sum)" if lump
                 else "وفق جدول الكميات المسعّر — تُحاسب الأعمال على الكميات المنفذة فعلياً")
    if ve_items:
        mode_line += " مع مقترحات الهندسة القيمية (Value Engineering)"

    # ------------------------------ الغلاف ------------------------------
    value_line = (f"{money(subtotal)} ريال غير شامل الضريبة — {money(grand)} ريال شاملة الضريبة"
                  if subtotal else "حسب جدول الكميات المسعّر")
    info = [("مقدّم إلى", (st.get("addressee") or "").strip() or client),
            ("رقم العرض", proposal.get("ref_no") or ""),
            ("تاريخ التقديم", arabic_date(created))]
    if (st.get("request_ref") or "").strip():
        info.append(("مرجع الطلب", st["request_ref"].strip()))
    info += [("قيمة العرض", value_line), ("مدة التنفيذ", duration),
             ("سريان العرض", f"{validity} يوماً من تاريخ التقديم")]
    cover = {"badge": "العرض الفني والمالي", "title": scope_title, "subtitle": subtitle,
             "mode_line": mode_line, "info": info}

    # ------------------------------ خطاب التقديم ------------------------------
    req = (st.get("request_ref") or "").strip()
    opening = (f"إشارةً إلى {req}، " if req else f"إشارةً إلى طرحكم لمشروع «{title}»، ")
    target = scope_title + (f" — {subtitle}" if subtitle and subtitle != client else "")
    letter = {
        "date": f"{created.day} / {created.month} / {created.year}م",
        "ref": proposal.get("ref_no") or "",
        "addressee": client,
        "subject": f"الموضوع: العرض الفني والمالي لـ{target}",
        "paragraphs": [
            [(f"{opening}تتقدم {company} بعرضها لتنفيذ {target} وفق وثائق المشروع ومواصفاته.", False)],
            [("قيمة العرض " + ("مبلغ مقطوع ثابت قدره " if lump else "الإجمالية "), False),
             (f"{money(subtotal)} ريال سعودي غير شامل ضريبة القيمة المضافة", True),
             (f" ({money(grand)} ريال شاملة الضريبة)، ومدة التنفيذ ", False),
             (duration, True), (".", False)] if subtotal else
            [("أسعار العرض وفق جدول الكميات المسعّر المرفق، ومدة التنفيذ ", False), (duration, True), (".", False)],
            [("يتكون العرض من عرض أساسي مطابق لوثائق المشروع ومواصفاته"
              + ("، ومقترحات هندسة قيمية منفصلة واختيارية في القسم الثامن" if ve_items else "")
              + f". ويسري العرض {validity} يوماً من تاريخ التقديم.", False)],
            [("وتفضلوا بقبول فائق الاحترام والتقدير،", False)],
        ],
        "company": company,
        "signer": settings.get("signer_title") or "المدير العام",
    }

    sections = []

    # ------------------------------ 1. الشركة ------------------------------
    blocks = []
    intro = (settings.get("company_intro") or "").strip() or _first_paragraph(
        _find_section(sections_src, "من نحن", "نبذة", "التعريف بالشركة"))
    if intro:
        blocks.append({"type": "p", "text": intro})
    kv = [(k, v) for k, v in (
        ("السجل التجاري", settings.get("company_cr", "")),
        ("التصنيف", settings.get("company_classification", "")),
        ("مجالات العمل", settings.get("company_services", "")),
        ("المجموعة الداعمة", settings.get("company_support_group", "")),
    ) if (v or "").strip()]
    if kv:
        blocks.append({"type": "kv", "rows": kv})
    refs = _lines_pipe(settings.get("company_references", ""), 3) or _won_references()
    if refs:
        blocks.append({"type": "h3", "text": "سابقة الأعمال ذات الصلة"})
        blocks.append({"type": "table", "headers": ["المشروع", "العميل / المقاول الرئيسي", "نوع الأعمال"],
                       "rows": refs, "widths": [6.2, 5.6, 5.2]})
    if (settings.get("company_docs_note") or "").strip():
        blocks.append({"type": "note", "text": settings["company_docs_note"].strip()})
    sections.append({"num": "1", "key": "company", "title": _SECTION_TITLES["company"], "blocks": blocks})

    # ------------------------------ 2. النطاق ------------------------------
    blocks = []
    scope_intro = (st.get("scope_intro") or "").strip() or _first_paragraph(
        _find_section(sections_src, "نطاق")) or (
        f"يشمل العرض تنفيذ أعمال «{title}» لصالح {client} وفق وثائق المشروع وجدول الكميات المرفق.")
    blocks.append({"type": "p", "text": scope_intro})
    included = [s for s in st.get("included") or [] if s.strip()]
    if not included:
        scope_list = [s for s in data.get("scope") or [] if s.strip() and "راجع قسم" not in s]
        included = scope_list if len(scope_list) > 1 else [l["name"] for l in (data.get("boq") or [])[:14]]
    if included:
        blocks.append({"type": "h3", "text": "يشمل المبلغ المقطوع" if lump else "يشمل العرض"})
        blocks.append({"type": "bullets", "items": included})
    excluded = [s for s in st.get("excluded") or [] if s.strip()] or [
        "أي أعمال غير واردة صراحةً في جدول الكميات أو وثائق المشروع، وتُسعَّر عند طلبها بأمر تغيير."]
    blocks.append({"type": "h3", "text": "خارج النطاق"})
    blocks.append({"type": "bullets", "items": excluded})
    sections.append({"num": "2", "key": "scope", "title": _SECTION_TITLES["scope"], "blocks": blocks})

    # ------------------------------ 3. المنهجية ------------------------------
    blocks = []
    method_body = _find_section(sections_src, "منهج", "النهج")
    m_intro = (st.get("method_intro") or "").strip() or _first_paragraph(method_body)
    if m_intro:
        blocks.append({"type": "p", "text": m_intro})
    subs = [s for s in st.get("method_sections") or [] if (s.get("title") or "").strip()]
    k = 0
    if subs:
        for s in subs:
            k += 1
            blocks.append({"type": "h3", "text": f"3.{k} {s['title'].strip()}"})
            for para in s.get("paragraphs") or []:
                if para.strip():
                    blocks.append({"type": "p", "text": para.strip()})
            steps = [x for x in s.get("steps") or [] if x.strip()]
            if steps:
                blocks.append({"type": "numbered", "items": steps})
    else:
        for ph in plan:
            k += 1
            blocks.append({"type": "h3", "text": f"3.{k} {ph.get('phase', '')}"})
            if (ph.get("description") or "").strip():
                blocks.append({"type": "p", "text": ph["description"].strip()})
            dels = [d for d in ph.get("deliverables") or [] if d.strip()]
            if dels:
                blocks.append({"type": "bullets", "items": [f"المخرجات: {'، '.join(dels)}."]})
    cycle = [r for r in st.get("cycle_rows") or [] if (r.get("activity") or "").strip()]
    if cycle:
        k += 1
        blocks.append({"type": "h3", "text": f"3.{k} {(st.get('cycle_title') or 'الدورة النموذجية').strip()}"})
        blocks.append({"type": "table", "headers": ["اليوم", "النشاط"],
                       "rows": [[r.get("label", ""), r["activity"]] for r in cycle], "widths": [2.2, 14.8]})
    if not blocks:
        blocks.append({"type": "p", "text": "تُنفَّذ الأعمال وفق خطة تنفيذ معتمدة وبرنامج زمني تفصيلي يُقدَّم بعد الترسية."})
    sections.append({"num": "3", "key": "method", "title": _SECTION_TITLES["method"], "blocks": blocks})

    # ------------------------------ 4. البرنامج الزمني ------------------------------
    blocks = []
    g_months = months
    s_intro = (st.get("schedule_intro") or "").strip() or (
        f"تُنجز الأعمال كاملةً خلال {duration} وفق المراحل الموضحة في المخطط التالي." if g_months else "")
    if s_intro:
        blocks.append({"type": "p", "text": s_intro})
    bars = _gantt_bars(st, plan, g_months) if g_months else []
    if bars:
        blocks.append({"type": "gantt", "months": g_months, "bars": bars, "milestone": "التسليم"})
    s_note = (st.get("schedule_note") or "").strip() or (
        "يُقدَّم البرنامج الزمني التفصيلي بعد الترسية، ويُحدَّث شهرياً مع خطة استباقية للأسابيع القادمة.")
    blocks.append({"type": "p", "text": s_note})
    sections.append({"num": "4", "key": "schedule", "title": _SECTION_TITLES["schedule"], "blocks": blocks})

    # ------------------------------ 5. الفريق والمعدات ------------------------------
    blocks = [{"type": "p", "text": "فريق متفرغ للمشروع طوال مدته، ومعدات مخصصة له. تُرفق السير الذاتية للكوادر الأساسية مع العرض."}]
    staff = [s for s in st.get("staff") or [] if (s.get("role") or "").strip()]
    staff_rows = ([[s["role"], qty_fmt(s.get("count") or 1) if not isinstance(s.get("count"), str) else s["count"],
                    s.get("note", "")] for s in staff]
                  or [[t.get("role", ""), qty_fmt(t.get("count") or 1), ""] for t in data.get("team") or []])
    k = 0
    if staff_rows:
        k += 1
        blocks.append({"type": "h3", "text": f"5.{k} الفريق الفني المتفرغ"})
        blocks.append({"type": "table", "headers": ["الوظيفة", "العدد", "ملاحظة"],
                       "rows": staff_rows, "widths": [7, 4, 6]})
    if (st.get("labor_note") or "").strip():
        blocks.append({"type": "p", "text": st["labor_note"].strip()})
    equipment = [e for e in st.get("equipment") or [] if (e.get("item") or "").strip()]
    if equipment:
        k += 1
        blocks.append({"type": "h3", "text": f"5.{k} المعدات"})
        blocks.append({"type": "table", "headers": ["المعدة", "العدد", "الملكية"],
                       "rows": [[e["item"], str(e.get("count", "")), e.get("ownership", "")] for e in equipment],
                       "widths": [8, 4, 5]})
    suppliers = [s for s in st.get("suppliers") or [] if (s.get("item") or "").strip()]
    if suppliers:
        k += 1
        blocks.append({"type": "h3", "text": f"5.{k} الموردون والمقاولون المتخصصون المقترحون"})
        blocks.append({"type": "note", "text": "يُعتمدون من المالك والاستشاري قبل التوريد."})
        blocks.append({"type": "table", "headers": ["البند", "المقترح"],
                       "rows": [[s["item"], s.get("proposal", "")] for s in suppliers], "widths": [4.5, 12.5]})
    sections.append({"num": "5", "key": "team", "title": _SECTION_TITLES["team"], "blocks": blocks})

    # ------------------------------ 6. الجودة والسلامة ------------------------------
    q_def, s_def = _QHSE_DEFAULTS["maintenance" if data.get("project_kind") in ("صيانة وتشغيل", "نظافة")
                                   else "construction"]
    quality = [q for q in st.get("quality") or [] if q.strip()] or q_def
    safety = [q for q in st.get("safety") or [] if q.strip()] or s_def
    blocks = [{"type": "p", "text": "تُقدَّم خطة الجودة وخطة السلامة معتمدتين قبل البدء، وتُطبَّق متطلبات وثائق المشروع دون استثناء."}]
    if quality:
        blocks += [{"type": "h3", "text": "6.1 الجودة"}, {"type": "bullets", "items": quality}]
    if safety:
        blocks += [{"type": "h3", "text": f"6.{2 if quality else 1} السلامة والموقع"},
                   {"type": "bullets", "items": safety}]
    sections.append({"num": "6", "key": "qhse", "title": _SECTION_TITLES["qhse"], "blocks": blocks})

    # ------------------------------ 7. العرض المالي ------------------------------
    blocks = []
    if subtotal:
        blocks.append({"type": "valuebox",
                       "label": "المبلغ المقطوع غير شامل الضريبة" if lump else "قيمة العرض غير شاملة الضريبة",
                       "amount": money(subtotal), "currency": "ريال سعودي",
                       "sub": f"شامل ضريبة القيمة المضافة {vat_rate:g}%: {money(grand)} ريال"})
    blocks.append({"type": "p", "text": (
        "المبلغ المقطوع ثابت لكامل الأعمال، وغير خاضع لإعادة القياس. الدفع حسب المستخلصات الشهرية للأعمال المنفذة."
        if lump else
        "الأسعار وفق جدول الكميات المسعّر المرفق، وتُحاسب الأعمال على الكميات المنفذة فعلياً والمعتمدة من "
        "الاستشاري، ويُصرف المستحق عبر المستخلصات الشهرية.")})
    k = 1
    blocks.append({"type": "h3", "text": f"7.{k} نموذج التسعير"})
    blocks.append({"type": "table", "headers": ["م", "البند", "المبلغ (ر.س)"],
                   "rows": [["1", ("المبلغ المقطوع لكامل الأعمال وفق المخططات والمواصفات — العرض الأساسي"
                                   if lump else "إجمالي أعمال جدول الكميات المسعّر"), money(subtotal)],
                            ["2", f"ضريبة القيمة المضافة {vat_rate:g}%", money(vat)]],
                   "total": ["", "الإجمالي شامل الضريبة", money(grand)], "widths": [1, 12.5, 3.5],
                   "num_cols": [2]})
    blocks.append({"type": "rich", "runs": [("المبلغ كتابةً: ", True), (amount_in_words(grand) +
                                                                        "، شاملة ضريبة القيمة المضافة.", True)],
                   "color": "primary"})
    bd = _breakdown(loaded, st, subtotal) if len(loaded) > 4 else []
    if bd:
        k += 1
        blocks.append({"type": "h3", "text": f"7.{k} التفصيل الاسترشادي " + ("للمبلغ المقطوع" if lump else "لقيمة العرض")})
        blocks.append({"type": "table", "headers": ["م", "المكوّن", "المبلغ (ر.س)", "النسبة %"], "rows": bd,
                       "total": ["", "الإجمالي" + (" (= المبلغ المقطوع)" if lump else ""), money(subtotal), "100"],
                       "widths": [1, 10.5, 3.5, 2], "num_cols": [2, 3]})
    sep = [s for s in st.get("separate_items") or [] if (s.get("name") or "").strip()]
    if sep:
        k += 1
        blocks.append({"type": "h3", "text": f"7.{k} بنود تُسعَّر منفصلة" + (" (خارج المبلغ المقطوع)" if lump else "")})
        blocks.append({"type": "table", "headers": ["البند", "الوحدة", "السعر (ر.س)"],
                       "rows": [[s["name"], s.get("unit", ""), money(s.get("price") or 0)] for s in sep],
                       "widths": [11, 2.5, 3.5], "num_cols": [2]})
    terms = [t.strip(" •-–") for t in re.split(r"\n|(?<=\.)\s+", settings.get("payment_terms") or "")
             if t.strip(" •-–")]
    if terms:
        k += 1
        blocks.append({"type": "h3", "text": f"7.{k} شروط الدفع المقترحة"})
        blocks.append({"type": "bullets", "items": terms})
    sections.append({"num": "7", "key": "financial", "title": _SECTION_TITLES["financial"], "blocks": blocks})

    if loaded:
        rows = []
        for i, l in enumerate(loaded, 1):
            rows.append([l.get("ref") or l.get("code") or str(i), l.get("name", ""), l.get("unit", ""), qty_fmt(l.get("qty")),
                         money(l.get("unit_price")), money(l.get("total"))])
            for j, c in enumerate(l.get("children") or [], 1):
                rows.append([f"{l.get('ref') or l.get('code') or i}.{j}", f"↳ {c.get('name', '')}", c.get("unit", ""),
                             qty_fmt(c.get("qty")), money(c.get("unit_price")), money(c.get("total"))])
        blocks = [{"type": "p", "text": "أسعار الوحدات شاملة كل ما يلزم لتنفيذ البند كما في وصفه: المواد والعمالة "
                                        "والمعدات والمصاريف العامة والربح" + (
                                            "، وتُستخدم لتقييم أوامر التغيير بالزيادة أو النقص فقط." if lump else ".")},
                  {"type": "table", "headers": ["البند", "الوصف", "الوحدة", "الكمية", "سعر الوحدة (ر.س)", "الإجمالي (ر.س)"],
                   "rows": rows, "total": ["", "الإجمالي الاسترشادي" if lump else "الإجمالي غير شامل الضريبة",
                                           "", "", "", money(indicative)],
                   "widths": [1.6, 7.4, 1.5, 1.9, 2.3, 2.3], "num_cols": [3, 4, 5], "small": True}]
        if lump and abs(indicative - subtotal) >= 1:
            blocks.append({"type": "note", "text": (
                f"الفرق بين الإجمالي الاسترشادي والمبلغ المقطوع {money(abs(indicative - subtotal))} ريال، "
                "ناتج عن تقريب الأسعار. المبلغ المقطوع هو الملزم.")})
        sections.append({"num": f"7.{k + 1}", "key": "boq",
                         "title": _SECTION_TITLES["boq"], "blocks": blocks, "sub": True})

    # ------------------------------ 8. الهندسة القيمية ------------------------------
    next_num = 8
    if ve_items:
        total_saving = sum(float(v.get("saving") or 0) for v in ve_items)
        pct = (total_saving / subtotal * 100) if subtotal else 0
        blocks = [{"type": "rich", "runs": [("مجموع الوفر المقترح حوالي ", False), (f"{money(total_saving)} ريال", True),
                                            (f"، أي {pct:.1f}% من العرض الأساسي. " if pct else ". ", False),
                                            ((st.get("ve_intro") or "").strip() or
                                             "المقترحات لا تخل بالكود السعودي ولا بالسلامة الإنشائية، وتُخصم "
                                             "قيمة أي مقترح معتمد من قيمة العرض بأمر تغيير.", False)]},
                  {"type": "table", "headers": ["م", "المقترح", "البنود المتأثرة", "الوصف الفني المختصر",
                                                "الوفر (ر.س)", "الأثر على المدة", "ملاحظات"],
                   "rows": [[str(i), v.get("title", ""), v.get("affected", ""), v.get("description", ""),
                             money(v.get("saving") or 0), v.get("days", "") or "—", v.get("note", "")]
                            for i, v in enumerate(ve_items, 1)],
                   "total": ["", "إجمالي الوفر المقترح", "", "", money(total_saving), "", ""],
                   "widths": [0.8, 3, 2, 4.6, 2, 1.8, 2.8], "num_cols": [4], "small": True},
                  {"type": "note", "text": "تُرفق مذكرات فنية داعمة لكل مقترح عند الطلب. الأرقام تقديرية وتُعتمد نهائياً بعد مراجعة المخططات التفصيلية."}]
        sections.append({"num": "8", "key": "ve", "title": _SECTION_TITLES["ve"], "blocks": blocks})
        next_num = 9

    # ------------------------------ 9. الافتراضات والإقرار ------------------------------
    n = str(next_num)
    blocks = [{"type": "p", "text": f"تُقر {company} بمراجعة وثائق المشروع وقبول شروطه، مع الافتراضات والتحفظات التالية."}]
    k = 0
    assumptions = [a for a in data.get("assumptions") or [] if a.strip()]
    if assumptions:
        k += 1
        blocks += [{"type": "h3", "text": f"{n}.{k} الافتراضات"}, {"type": "numbered", "items": assumptions}]
    reservations = ([(r.get("lead", ""), r.get("text", "")) for r in st.get("reservations") or []
                     if (r.get("text") or "").strip()]
                    or _lead_lines(settings.get("proposal_reservations", "")))
    if reservations:
        k += 1
        blocks += [{"type": "h3", "text": f"{n}.{k} التحفظات"}, {"type": "numbered", "items": reservations}]
    k += 1
    until = created + timedelta(days=validity)
    blocks += [{"type": "h3", "text": f"{n}.{k} بيانات العرض"},
               {"type": "kv", "rows": [("مدة التنفيذ", duration + " من تاريخ تسليم الموقع أو التعميد، أيهما أسبق"),
                                       ("مدة سريان العرض", f"{validity} يوماً من تاريخ التقديم (حتى {arabic_date(until)})"),
                                       ("العملة", "ريال سعودي")]}]
    attachments = [a for a in st.get("attachments") or [] if a.strip()] or [
        x for x in ("جدول الكميات المسعّر — الملحق 1" if loaded else "",
                    "مقترحات الهندسة القيمية مع المذكرات الفنية" if ve_items else "",
                    "السجل التجاري، والشهادة الضريبية، وشهادة التصنيف، وشهادتا الزكاة والتأمينات",
                    "سابقة الأعمال مع جهات التواصل", "الهيكل التنظيمي والسير الذاتية",
                    "البرنامج الزمني المبدئي") if x]
    k += 1
    blocks += [{"type": "h3", "text": f"{n}.{k} المرفقات"}, {"type": "bullets", "items": attachments}]
    blocks.append({"type": "declaration",
                   "text": f"تُقر {company} بالاطلاع على وثائق المشروع ومخططاته، وبقبول شروط الطلب مع التحفظات الواردة أعلاه.",
                   "rows": [("الاسم", "............................................"),
                            ("المنصب", settings.get("signer_title") or "المدير العام"),
                            ("التوقيع", "............................................"),
                            ("الختم", ""), ("التاريخ", f"{created.day} / {created.month} / {created.year}م")]})
    sections.append({"num": n, "key": "terms", "title": _SECTION_TITLES["terms"], "blocks": blocks})

    return {"cover": cover, "letter": letter, "sections": sections, "lump_sum": lump,
            "duration": duration, "tagline": settings.get("company_tagline", "")}
