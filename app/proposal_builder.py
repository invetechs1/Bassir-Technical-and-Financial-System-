"""بناء العرض الفني والمالي — الحسابات المالية ومحرك القوالب الاحتياطي.

نموذج التسعير (يتوافق مع الممارسات المتبعة في المنافسات الحكومية):
  التكلفة المباشرة (جدول الكميات)
+ المصاريف الإدارية والعمومية (نسبة من التكلفة المباشرة)
+ احتياطي المخاطر (نسبة من التكلفة المباشرة)
+ هامش الربح (نسبة من مجموع ما سبق)
= الإجمالي قبل الضريبة
+ ضريبة القيمة المضافة 15% (تُعرض في بند مستقل وفق الممارسة السعودية)
= الإجمالي النهائي
"""
import re

from .database import get_settings, list_price_items, list_library


def compute_financials(boq: list[dict], settings: dict | None = None) -> dict:
    s = settings or get_settings()
    overhead_pct = float(s.get("overhead_pct", 12))
    risk_pct = float(s.get("risk_pct", 3))
    profit_pct = float(s.get("profit_pct", 15))
    vat_rate = float(s.get("vat_rate", 15))
    bid_bond_pct = float(s.get("bid_bond_pct", 1))

    for line in boq:
        line["qty"] = float(line.get("qty", 1) or 1)
        children = line.get("children") or []
        if children:
            # بند مقسّم إلى أجزاء فرعية: لكل جزء كميته ووحدته وسعره وإجماليه
            # المستقل، وإجمالي البند الأب = مجموع إجماليات أجزائه (لا يُحرَّر يدوياً).
            for c in children:
                c["qty"] = float(c.get("qty") or line["qty"] or 1)
                c["unit"] = c.get("unit") or line.get("unit", "")
                c["unit_price"] = float(c.get("unit_price", 0) or 0)
                c["total"] = round(c["qty"] * c["unit_price"], 2)
            line["total"] = round(sum(c["total"] for c in children), 2)
            line["unit_price"] = round(line["total"] / line["qty"], 2) if line["qty"] else 0.0
        else:
            line["unit_price"] = float(line.get("unit_price", 0) or 0)
            line["total"] = round(line["qty"] * line["unit_price"], 2)

    direct_cost = round(sum(l["total"] for l in boq), 2)
    overhead = round(direct_cost * overhead_pct / 100, 2)
    risk = round(direct_cost * risk_pct / 100, 2)
    profit = round((direct_cost + overhead + risk) * profit_pct / 100, 2)
    subtotal = round(direct_cost + overhead + risk + profit, 2)
    vat = round(subtotal * vat_rate / 100, 2)
    grand_total = round(subtotal + vat, 2)

    return {
        "direct_cost": direct_cost,
        "overhead_pct": overhead_pct, "overhead": overhead,
        "risk_pct": risk_pct, "risk": risk,
        "profit_pct": profit_pct, "profit": profit,
        "subtotal": subtotal,
        "vat_rate": vat_rate, "vat": vat,
        "grand_total": grand_total,
        "bid_bond_pct": bid_bond_pct,
        "bid_bond": round(grand_total * bid_bond_pct / 100, 2),
    }


def client_facing_pricing(boq: list[dict], financial: dict) -> list[dict]:
    """توزيع المصاريف الإدارية والمخاطر والربح داخل أسعار البنود.

    العميل يرى أسعاراً محمَّلة فقط — لا سطر ربح ولا مخاطر في الملف المصدَّر.
    مجموع البنود بعد التحميل يساوي «الإجمالي قبل الضريبة» تماماً؛ فرق
    التقريب يُمتص في أكبر بند."""
    direct = float(financial.get("direct_cost") or 0)
    subtotal = float(financial.get("subtotal") or 0)
    factor = (subtotal / direct) if direct else 1.0
    loaded = []
    for l in boq:
        qty = float(l.get("qty") or 0)
        unit = round(float(l.get("unit_price") or 0) * factor, 2)
        row = {**l, "unit_price": unit, "total": round(unit * qty, 2)}
        if l.get("children"):
            kids = []
            for c in l["children"]:
                c_qty = float(c.get("qty") or qty or 1)
                c_price = round(float(c.get("unit_price") or 0) * factor, 2)
                kids.append({**c, "qty": c_qty, "unit_price": c_price,
                             "total": round(c_price * c_qty, 2)})
            row["children"] = kids
            row["total"] = round(sum(k["total"] for k in kids), 2)
            row["unit_price"] = round(row["total"] / qty, 4) if qty else 0.0
        loaded.append(row)
    diff = round(subtotal - sum(l["total"] for l in loaded), 2)
    if loaded and abs(diff) >= 0.01:
        big = max(loaded, key=lambda l: l["total"])
        big["total"] = round(big["total"] + diff, 2)
        if big.get("qty"):
            big["unit_price"] = round(big["total"] / float(big["qty"]), 4)
    return loaded


def flatten_boq_rows(boq: list[dict]) -> list[tuple]:
    """يفكك جدول الكميات إلى صفوف مسطّحة للتصدير (Word/Excel) — كل بند أب
    مقسّم إلى مراحل فرعية يظهر متبوعاً بصفوفه الفرعية مرقّمة (1.1، 1.2 ...)
    وبادئة ↳، بنفس الكمية والوحدة، وسعر/إجمالي خاص بكل مرحلة."""
    rows = []
    for i, l in enumerate(boq, 1):
        rows.append((str(i), l.get("code", ""), l["name"], l["unit"], l["qty"],
                     l["unit_price"], l["total"]))
        for j, c in enumerate(l.get("children") or [], 1):
            c_qty = float(c.get("qty") or l["qty"] or 1)
            c_unit = c.get("unit") or l["unit"]
            total = c.get("total", round(c_qty * float(c.get("unit_price", 0) or 0), 2))
            rows.append((f"{i}.{j}", "", f"↳ {c['name']}", c_unit, c_qty,
                         c["unit_price"], total))
    return rows


def match_price_catalog(boq: list[dict]) -> list[dict]:
    """مطابقة بنود جدول الكميات مع قاعدة الأسعار (بالكود ثم بتشابه الاسم)."""
    catalog = list_price_items()
    by_code = {item["code"]: item for item in catalog}
    for line in boq:
        matched = by_code.get(line.get("code", ""))
        if not matched:
            matched = _best_name_match(line.get("name", ""), catalog)
        if matched:
            line["code"] = matched["code"]
            line["unit"] = line.get("unit") or matched["unit"]
            if not line.get("unit_price"):
                line["unit_price"] = matched["unit_price"]
            line["source"] = "قاعدة الأسعار"
        else:
            line["source"] = line.get("source", "تقدير")
    return boq


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[\s،,/|()-]+", text) if len(t) > 2}


def _best_name_match(name: str, catalog: list[dict]) -> dict | None:
    target = _tokens(name)
    if not target:
        return None
    best, best_score = None, 0.0
    for item in catalog:
        overlap = len(target & _tokens(item["name"]))
        score = overlap / max(len(target), 1)
        if overlap >= 2 and score > best_score:
            best, best_score = item, score
    return best


# ---------------------------------------------------------------------------
# محرك القوالب — يعمل بدون مفتاح API ويُنتج عرضاً كاملاً قابلاً للتحرير
# ---------------------------------------------------------------------------

_KEYWORD_MAP = [
    (["نظام", "برمج", "تطبيق", "بوابة", "إلكترون", "رقمن", "منصة"],
     ["IT-001", "IT-003", "IT-004", "IT-006", "IT-007", "HR-010", "HR-011", "HR-012", "HR-001"]),
    (["إنشاء", "مبنى", "خرسان", "بناء", "تشييد", "مبان"],
     ["GN-001", "CV-001", "CV-002", "CV-003", "CV-004", "CV-005", "CV-006", "CV-007",
      "EM-001", "EM-002", "EM-003", "EM-006", "HR-001", "HR-002", "HR-005", "GN-003", "GN-004", "GN-005"]),
    (["طرق", "أسفلت", "رصف", "سفلت"],
     ["GN-001", "CV-001", "CV-008", "CV-009", "EM-004", "EQ-001", "HR-002", "HR-007", "GN-003", "GN-005"]),
    (["صيانة", "تشغيل", "نظافة"],
     ["OM-001", "OM-002", "OM-003", "OM-004", "HR-001", "HR-007", "GN-003"]),
    (["كهرباء", "إنارة", "تيار"],
     ["EM-001", "EM-002", "EM-003", "EM-004", "HR-003", "HR-007"]),
    (["كاميرا", "أمن", "مراقبة", "إنذار"],
     ["EM-008", "EM-009", "IT-005", "HR-003", "IT-007"]),
]

_DEFAULT_CODES = ["GN-001", "HR-001", "HR-002", "HR-007", "GN-003", "GN-004", "GN-005"]


def build_template_proposal(title: str, client: str, entity_type: str, files_text: str,
                            similar_refs: list[dict] | None = None) -> dict:
    """توليد عرض متكامل بمحرك القوالب (بديل عند غياب مفتاح Claude API).

    عند وجود عروض سابقة مشابهة (similar_refs) يُبنى جدول الكميات من بنود
    أقرب عرض مطابق بدلاً من المطابقة بالكلمات المفتاحية فقط.
    """
    text = f"{title}\n{files_text}"
    boq: list[dict] = []
    matched_ref_note = ""

    # فئة المشروع تُقرأ من ملفاته أولاً: إنشاءات / صيانة وتشغيل / نظافة / توريد /
    # تصميم وإشراف — فتُبنى الأقسام من فقرات الفئة نفسها والخطة الزمنية بنمطها
    project_kind = "إنشاءات وتشطيبات"
    try:
        from .style_engine import detect_project_kind
        project_kind, _kind_scores = detect_project_kind(text)
    except Exception:
        pass

    # أولاً: البناء من أقرب عرض سابق مشابه إن وُجد تطابق قوي
    if similar_refs:
        best = similar_refs[0]
        ref_boq = best.get("data", {}).get("boq", [])
        if ref_boq:
            matched_ref_note = f"{best['title']} ({best['ref_no']})"
            for l in ref_boq:
                boq.append({
                    "code": l.get("code", ""), "name": l["name"], "unit": l.get("unit", "وحدة"),
                    "qty": l.get("qty", 1), "unit_price": l.get("unit_price", 0),
                    "source": l.get("source") or ("قاعدة الأسعار" if l.get("code") else "من عرض سابق"),
                })

    # ثانياً: المطابقة بالكلمات المفتاحية عند غياب مرجع مشابه
    if not boq:
        codes: list[str] = []
        for keywords, item_codes in _KEYWORD_MAP:
            if any(k in text for k in keywords):
                for c in item_codes:
                    if c not in codes:
                        codes.append(c)
        if not codes:
            codes = _DEFAULT_CODES
        catalog = {i["code"]: i for i in list_price_items()}
        for code in codes:
            item = catalog.get(code)
            if item:
                boq.append({
                    "code": item["code"], "name": item["name"], "unit": item["unit"],
                    "qty": 1, "unit_price": item["unit_price"], "source": "قاعدة الأسعار",
                })

    library = {e["title"]: e["body"] for e in list_library()}
    settings_letter = get_settings()
    _company = settings_letter.get("company_name", "شركة عزوم المتحدة للمقاولات")
    _validity = settings_letter.get("validity_days", "90")
    _cr = settings_letter.get("company_cr", "")
    cover_letter = (
        "السلام عليكم ورحمة الله وبركاته، وبعد:\n"
        f"إشارةً إلى مشروع «{title}» المطروح من قِبلكم، يسرّ {_company} أن تتقدم لسعادتكم "
        "بعرضها الفني والمالي لتنفيذ الأعمال المذكورة وفق الشروط والمواصفات الواردة في وثائق المشروع.\n"
        "ونؤكد لسعادتكم جاهزيتنا للمباشرة فور الترسية، والتزامنا بتنفيذ الأعمال حسب المواصفات "
        f"والبرنامج الزمني المعتمد، مع سريان عرضنا هذا لمدة {_validity} يوماً من تاريخه.\n"
        "وتفضلوا سعادتكم بقبول خالص التحية والتقدير،\n"
        f"{_company}" + (f" — سجل تجاري رقم {_cr}" if _cr else ""))
    # هيكل العرض الفني — يطابق بنية عروض عزوم الفعلية (معلومات الشركة، الملخص،
    # من نحن، مشاريع سابقة، نطاق العمل، الفريق، المنهجية، المخاطر، الوثائق،
    # السلامة، الجودة، ...) بضمير المتكلم الجمع كما تكتب الشركة
    company_info = "\n".join(x for x in (
        f"اسم الشركة: {_company}",
        f"عنوان الشركة: {settings_letter.get('company_address', '')}",
        "الخدمات: المقاولات الإنشائية، الأعمال المدنية، أعمال العزل، الترميمات وصيانة المباني، "
        "خدمات النظافة والصيانة العامة، وأعمال التشطيبات والتوريدات.",
        "تاريخ التأسيس: 2017م",
        "الوضع القانوني: شركة ذات مسؤولية محدودة",
        f"رقم السجل التجاري: {_cr}" if _cr else "",
        f"الرقم الضريبي: {settings_letter.get('company_vat_no', '')}" if settings_letter.get('company_vat_no') else "",
        f"الهاتف: {settings_letter.get('company_phone', '')}" if settings_letter.get('company_phone') else "",
        f"البريد الإلكتروني: {settings_letter.get('company_email', '')}" if settings_letter.get('company_email') else "",
    ) if x)
    sections = [
        {"title": "خطاب التقديم", "body": cover_letter},
        {"title": "السرية وحقوق الملكية", "body": library.get("السرية وحقوق الملكية", "")},
        {"title": "معلومات الشركة", "body": company_info},
        {"title": "الملخص", "body": library.get("الملخص التنفيذي القياسي", "")},
        {"title": "من نحن", "body": library.get("نبذة عن شركة عزوم", "")},
        {"title": "مشاريع سابقة",
         "body": (f"نفذت الشركة وقدمت عروضاً لمشاريع مماثلة مباشرة لنطاق هذا المشروع، أقربها: "
                  f"{matched_ref_note}، وقد بُني جدول الكميات في هذا العرض على خبرة التسعير الفعلية "
                  f"لذلك المشروع.\n" + library.get("الخبرات والمشاريع المماثلة", ""))
         if matched_ref_note else library.get("الخبرات والمشاريع المماثلة", "")},
        {"title": "نطاق العمل",
         "body": f"اطلعنا على وثائق مشروع «{title}» الخاص بـ{client}، وحللنا متطلباته وحصرنا بنود "
                 "أعماله. يغطي هذا العرض جميع البنود المذكورة في نطاق المشروع، ويُعد جدول الكميات "
                 "المرفق ترجمة تفصيلية له بنداً ببند كميةً وسعراً، وسيشمل العمل كافة التوريدات "
                 "والتركيبات والتشوينات اللازمة لإتمام الأعمال حسب الأصول الفنية."},
        {"title": "فريق العمل", "body":
            "يُدار المشروع بفريق مقيم بقيادة مدير مشروع يمثل الشركة أمام الجهة المالكة والمهندس "
            "المشرف، يسانده مهندس موقع ومسؤول جودة ومشرف سلامة ومساح كميات، مع الكوادر الفنية "
            "والعمالة حسب طبيعة كل مرحلة. تُرفق السير الذاتية للكوادر الأساسية ضمن ملاحق العرض."},
        {"title": "النهج والمنهجية", "body": library.get("منهجية إدارة المشروع", "")},
        {"title": "خطة إدارة المخاطر", "body": library.get("منهجية إدارة المخاطر", "")},
        {"title": "إدارة الوثائق",
         "body": (library.get("إدارة الوثائق", "") or "").replace("الجهة المالكة", client or "الجهة المالكة")},
        {"title": "التأثير البيئي والصحة والسلامة المهنية", "body": library.get("خطة السلامة والصحة المهنية", "")},
        {"title": "معايير الجودة", "body": library.get("خطة ضمان الجودة", "")},
        {"title": "خطة المحتوى المحلي والسعودة والتدريب", "body": library.get("خطة المحتوى المحلي والسعودة والتدريب", "")},
        {"title": "الضمانات والالتزامات", "body": library.get("الضمانات والالتزامات", "")},
    ]

    compliance_matrix = [
        {"requirement": "تغطية كامل نطاق العمل الوارد في كراسة الشروط", "response": "ملتزمون", "reference": "قسم فهم نطاق العمل + جدول الكميات"},
        {"requirement": "الالتزام بالجدول الزمني المحدد", "response": "ملتزمون", "reference": "الخطة التنفيذية"},
        {"requirement": "تقديم الضمان الابتدائي والنهائي وفق النظام", "response": "ملتزمون", "reference": "قسم الضمانات"},
        {"requirement": "متطلبات المحتوى المحلي والتوطين", "response": "ملتزمون", "reference": "خطة المحتوى المحلي"},
    ]

    if project_kind in ("صيانة وتشغيل", "نظافة"):
        plan = [
            {"phase": "مرحلة الاستلام والجرد والتعبئة", "duration_weeks": 2,
             "description": "استلام المواقع والأصول وجردها وتوثيق حالتها الراهنة، وتجهيز الكوادر "
                            "والمعدات والمواد، واعتماد خطة التشغيل والصيانة السنوية وسجلات الأصول.",
             "deliverables": ["محاضر استلام المواقع", "سجل الأصول والحالة الراهنة", "خطة التشغيل والصيانة المعتمدة"]},
            {"phase": "التشغيل والصيانة الدورية", "duration_weeks": 44,
             "description": "تنفيذ أعمال التشغيل اليومية وبرامج الصيانة الوقائية وفق الجداول المعتمدة، "
                            "ومعالجة البلاغات والأعطال ضمن أزمنة الاستجابة المحددة، مع تقارير شهرية "
                            "بنسب الإنجاز ومؤشرات الأداء.",
             "deliverables": ["سجلات الصيانة الوقائية", "تقارير معالجة البلاغات", "تقارير شهرية بمؤشرات الأداء"]},
            {"phase": "الصيانة التصحيحية والتحسين", "duration_weeks": 4,
             "description": "حصر الأعمال التصحيحية الكبرى وتنفيذها بالتنسيق مع الجهة المالكة، "
                            "وتحديث سجلات الأصول وقطع الغيار.",
             "deliverables": ["محاضر الأعمال التصحيحية", "سجل قطع الغيار المحدث"]},
            {"phase": "التقييم السنوي والتسليم", "duration_weeks": 2,
             "description": "تقييم أداء العقد السنوي وإقفال السجلات وتسليم التقارير الختامية، "
                            "والتجهيز للتجديد أو التسليم النهائي.",
             "deliverables": ["التقرير السنوي الختامي", "محضر إقفال/تجديد العقد"]},
        ]
    else:
        plan = [
        {"phase": "مرحلة التجهيز والتعبئة", "duration_weeks": 2,
         "description": "استلام الموقع/المتطلبات، تجهيز فريق العمل، اعتماد الخطة الزمنية التفصيلية وخطط الجودة والسلامة.",
         "deliverables": ["خطة زمنية معتمدة", "خطة جودة وسلامة", "تشكيل فريق المشروع"]},
        {"phase": "مرحلة التنفيذ الأساسية", "duration_weeks": 12,
         "description": "تنفيذ بنود نطاق العمل وفق جدول الكميات مع تقارير إنجاز أسبوعية وشهرية.",
         "deliverables": ["تقارير إنجاز دورية", "محاضر فحص واعتماد", "نسب إنجاز موثقة"]},
        {"phase": "مرحلة الفحص والتسليم الابتدائي", "duration_weeks": 3,
         "description": "الفحوصات النهائية، معالجة الملاحظات، التسليم الابتدائي.",
         "deliverables": ["محضر استلام ابتدائي", "إغلاق الملاحظات"]},
        {"phase": "مرحلة الإغلاق والتسليم النهائي", "duration_weeks": 2,
         "description": "تسليم الوثائق النهائية والمخططات كما نُفذت ونقل المعرفة والإغلاق المالي والإداري.",
         "deliverables": ["وثائق As-Built", "محضر استلام نهائي", "تقرير إغلاق المشروع"]},
    ]

    # طبقة الأسلوب: أقسام العرض تُبنى من فقرات الشركة المعتمدة متى وُجدت،
    # والباقي يُنقّى من عبارات القوالب المكشوفة — انظر style_engine.py
    style_meta: dict = {}
    try:
        import json as _json
        from .style_engine import (_canonical_for, build_from_bank, get_style_profile,
                                   scrub_banned, style_report)
        bank = build_from_bank(text, project_kind)
        profile = get_style_profile()
        banned = _json.loads(profile.get("banned_json") or "[]") or None
        _keep_dynamic = {"scope"}  # نص نطاق العمل خاص بكل مشروع — لا يُستبدل ببنك الفقرات
        for sec in sections:
            canonical = _canonical_for(sec["title"])
            if canonical and canonical in bank and canonical not in _keep_dynamic:
                sec["body"] = bank[canonical]["body"]
                sec["source"] = "bank"
                sec["source_ref"] = bank[canonical]["ref"]
            else:
                sec["body"], _ = scrub_banned(sec["body"], banned)
                sec["source"] = "new"
        style_meta = style_report(sections, profile)
    except Exception:
        style_meta = {}

    settings = get_settings()
    return {
        "summary": f"عرض فني ومالي مقدم من شركة عزوم لتنفيذ مشروع «{title}» لصالح {client}.",
        "scope": ["راجع قسم فهم نطاق العمل وجدول الكميات."],
        "technical_sections": sections,
        "compliance_matrix": compliance_matrix,
        "boq": boq,
        "financial": compute_financials(boq, settings),
        "plan": plan,
        "duration_weeks": sum(p["duration_weeks"] for p in plan),
        "assumptions": [
            "الأسعار بالريال السعودي وتشمل كافة الالتزامات ما لم يُذكر خلاف ذلك.",
            f"سريان العرض {settings.get('validity_days', '90')} يوماً من تاريخ تقديمه.",
            "الكميات الواردة في جدول الكميات تقديرية، وتُحاسب الأعمال على الكميات الفعلية المنفذة والمعتمدة من الاستشاري.",
        ],
        "team": [{"role": "مدير مشروع PMP", "count": 1}, {"role": "مهندس موقع", "count": 1},
                 {"role": "مهندس جودة وسلامة", "count": 1}],
        "style": style_meta,
        "project_kind": project_kind,
        "engine": "template",
    }
