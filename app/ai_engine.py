"""محرك التوليد الذكي — يحلل وثائق المشروع ويولّد العرض الفني والمالي عبر Claude API.

عند غياب مفتاح ANTHROPIC_API_KEY يتولى محرك القوالب (proposal_builder) المهمة.
"""
import json

from .config import ANTHROPIC_API_KEY, CLAUDE_MODEL


def _active_model() -> str:
    """الموديل الفعال: المحدَّث تلقائياً من منصة Claude إن وُجد، وإلا الافتراضي."""
    try:
        from .model_updater import get_active_model
        return get_active_model()
    except Exception:
        return CLAUDE_MODEL
from .database import get_settings, list_price_items, list_library
from .proposal_builder import (apply_style_layer, compute_financials, detect_kind,
                               match_price_catalog)

def _obj(props: dict) -> dict:
    """كائن صارم: كل الحقول مطلوبة وبلا حقول إضافية (شرط المخرجات المهيكلة)."""
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


_S = {"type": "string"}
_N = {"type": "number"}
_STRS = {"type": "array", "items": _S}

# هيكل العرض المعتمد (نموذج برج مكين 100) — محتوى محدد من وثائق المشروع لكل قسم
STRUCTURE_SCHEMA = _obj({
    "scope_title": {"type": "string", "description": "عنوان الأعمال على الغلاف، مثل: أعمال الهيكل الإنشائي (العظم بالمواد)"},
    "subtitle": {"type": "string", "description": "اسم المشروع والمدينة، مثل: مشروع برج مكين (100) الفندقي — الرياض"},
    "pricing_mode": {"type": "string", "enum": ["lump_sum", "remeasured"],
                     "description": "lump_sum إن طلبت الوثائق مبلغاً مقطوعاً، وإلا remeasured"},
    "request_ref": {"type": "string", "description": "مرجع الطلب كما في الوثائق (طلب عرض السعر المؤرخ ...، رقم المنافسة ...) أو فارغ"},
    "addressee": {"type": "string", "description": "الجهة المقدَّم إليها بصفتها، مثل: شركة ... — المقاول الرئيسي"},
    "scope_intro": {"type": "string", "description": "فقرة قصيرة بأرقام المشروع الفعلية (المساحات، الأدوار، الأقبية...)"},
    "included": {**_STRS, "description": "ما يشمله العرض، نقطة محددة لكل بند رئيسي بمواصفاته (الرتب، الموردين...)"},
    "excluded": {**_STRS, "description": "ما هو خارج النطاق صراحةً"},
    "method_intro": {"type": "string", "description": "محاور المنهجية والهدف (مثل دورة دور متكرر من 6 أيام)"},
    "method_sections": {"type": "array", "items": _obj({
        "title": _S, "paragraphs": _STRS, "steps": _STRS})},
    "cycle_title": {"type": "string", "description": "عنوان جدول الدورة النموذجية إن وُجد، وإلا فارغ"},
    "cycle_rows": {"type": "array", "items": _obj({"label": _S, "activity": _S})},
    "duration_months": {"type": "number", "description": "المدة الإجمالية بالأشهر"},
    "schedule_intro": _S,
    "schedule_note": {"type": "string", "description": "البرنامج التفصيلي وأداته وتحديثه"},
    "schedule_bars": {"type": "array", "description": "أنشطة المخطط الزمني بأشهر البداية والنهاية (0 = بداية المشروع، وتتداخل الأنشطة المتوازية)",
                      "items": _obj({"task": _S, "start_month": _N, "end_month": _N})},
    "staff": {"type": "array", "items": _obj({"role": _S, "count": _N, "note": _S})},
    "labor_note": {"type": "string", "description": "العمالة المباشرة في الذروة وتخصصاتها"},
    "equipment": {"type": "array", "items": _obj({"item": _S, "count": _S, "ownership": _S})},
    "suppliers": {"type": "array", "items": _obj({"item": _S, "proposal": _S})},
    "quality": {**_STRS, "description": "إجراءات جودة محددة بالاختبارات والمعايير"},
    "safety": {**_STRS, "description": "إجراءات سلامة محددة لمخاطر هذا المشروع"},
    "breakdown": {"type": "array", "description": "مجموعات التفصيل الاسترشادي للمبلغ: اسم المجموعة وأرقام بنود boq التابعة لها (تبدأ من 1)",
                  "items": _obj({"name": _S, "item_numbers": {"type": "array", "items": {"type": "integer"}}})},
    "separate_items": {"type": "array", "description": "بنود تُسعَّر منفصلة خارج القيمة الأساسية",
                       "items": _obj({"name": _S, "unit": _S, "price": _N})},
    "ve_intro": {"type": "string", "description": "شروط مقترحات الهندسة القيمية، أو فارغ إن لم توجد"},
    "ve_items": {"type": "array", "description": "مقترحات هندسة قيمية واقعية اختيارية بوفرها التقديري",
                 "items": _obj({"title": _S, "affected": _S, "description": _S, "saving": _N, "days": _S, "note": _S})},
    "reservations": {"type": "array", "description": "تحفظات تجارية وفنية محددة بعنوان قصير",
                     "items": _obj({"lead": _S, "text": _S})},
    "attachments": _STRS,
    # --- مستوى العروض الاحترافية (نموذج مكين 100 R1)
    "location": {"type": "string", "description": "المدينة والحي ورقم المخطط والقطع إن وُجدت"},
    "owner": {"type": "string", "description": "المالك / المطوّر إن ذُكر"},
    "attention": {"type": "string", "description": "عناية: الإدارة المعنية إن ذُكرت"},
    "contract_type": _S,
    "letter_paragraphs": {**_STRS, "description": "فقرات خطاب التقديم: ما دُرس من وثائق، ما يشمله العرض، الهندسة القيمية، الختام — بلا تحية ولا توقيع"},
    "letter_kpis": {"type": "array", "items": _obj({"value": _S, "label": _S, "en": _S})},
    "exec_summary": {"type": "string", "description": "ملخص تنفيذي بأرقام المشروع الفعلية في 3-4 أسطر"},
    "kpis": {"type": "array", "description": "4 مؤشرات كمية للمشروع (كميات رئيسية، المدة...)", "items": _obj({"value": _S, "label": _S, "en": _S})},
    "why_us": {"type": "array", "description": "6 أسباب محددة لاختيار الشركة لهذا المشروع بالذات من خبراتها الفعلية", "items": _obj({"title": _S, "text": _S})},
    "pillars": {"type": "array", "description": "3 محاور للحل الفني المقترح", "items": _obj({"tag": _S, "title": _S, "text": _S})},
    "documents_studied": {"type": "string", "description": "ما درسه الفريق: الطلب، اللوحات وعددها وإصدارها، التقارير..."},
    "project_facts": {"type": "array", "description": "4 حقائق رقمية للمشروع (مساحة، أدوار، سماكات، مناسيب...)", "items": _obj({"value": _S, "label": _S, "en": _S})},
    "parties_rows": {"type": "array", "description": "جدول فهم المشروع: الأطراف، المكونات، المسطحات، الأساسات، الرتب، التسليح، البلاطات...", "items": _obj({"label": _S, "value": _S})},
    "tech_notes": {"type": "array", "description": "ملاحظات فنية مؤثرة على التنفيذ والتسعير (المياه الجوفية، ضيق الموقع...)", "items": _obj({"title": _S, "text": _S})},
    "scope_rows": {"type": "array", "description": "جدول النطاق: بند ← ما يشمله العرض بالمواصفات", "items": _obj({"item": _S, "text": _S})},
    "method_phases": {"type": "array", "description": "6 مراحل تنفيذ مختصرة بعنوان عربي وإنجليزي", "items": _obj({"title": _S, "en": _S})},
    "milestones": {"type": "array", "items": _obj({"label": _S, "value": _S})},
    "s_curve": {"type": "array", "description": "نسبة الإنجاز التراكمية نهاية كل شهر (آخرها 100)", "items": _N},
    "org_chart": _obj({"lead": _obj({"title": _S, "sub": _S}),
                       "rows": {"type": "array", "items": {"type": "array", "items": _obj({"title": _S, "sub": _S})}},
                       "base": _obj({"title": _S, "sub": _S})}),
    "staff_note": _S,
    "risks": {"type": "array", "description": "سجل مخاطر المشروع: الخطر، الأثر (مرتفع/متوسط/منخفض)، إجراء المعالجة", "items": _obj({"risk": _S, "impact": _S, "mitigation": _S})},
    "lump_note": {"type": "string", "description": "سطر تحت قيمة العرض، مثل: ثابت ونهائي غير خاضع لإعادة القياس"},
    "cost_basis_intro": _S,
    "cost_kpis": {"type": "array", "description": "مؤشرات أساس التسعير (خرسانة م³، حديد طن، شدات م²، معدل الحديد...) إن أمكن حسابها", "items": _obj({"value": _S, "label": _S, "en": _S})},
    "cost_basis_rows": {"type": "array", "description": "أساس تسعير كل مكوّن (الحديد، الخرسانة، الشدات، العزل، التجهيزات العامة...)", "items": _obj({"component": _S, "basis": _S})},
    "cost_basis_note": _S,
    "acceptance": {"type": "string", "description": "فقرة القبول بشروط الطلب"},
    "declaration": _S,
    "checklist": {"type": "array", "description": "متطلبات تقديم العرض الواردة في الطلب وموضع كل منها في العرض", "items": _obj({"req": _S, "where": _S, "status": _S})},
    "boq_note": _S,
})

PROPOSAL_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "ملخص تنفيذي موجز للعرض"},
        "scope": {"type": "array", "items": {"type": "string"}, "description": "بنود نطاق العمل المستخلصة من الوثائق"},
        "technical_sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["title", "body"],
                "additionalProperties": False,
            },
        },
        "compliance_matrix": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "requirement": {"type": "string", "description": "متطلب من كراسة الشروط"},
                    "response": {"type": "string", "description": "ملتزمون / ملتزمون مع توضيح / غير منطبق"},
                    "reference": {"type": "string", "description": "القسم الذي يغطي المتطلب في العرض"},
                },
                "required": ["requirement", "response", "reference"],
                "additionalProperties": False,
            },
        },
        "boq": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "كود البند من قاعدة الأسعار إن وُجد، وإلا فارغ"},
                    "name": {"type": "string"},
                    "unit": {"type": "string"},
                    "qty": {"type": "number"},
                    "unit_price": {"type": "number", "description": "من قاعدة الأسعار، أو تقدير مبرر إن لم يوجد البند"},
                },
                "required": ["code", "name", "unit", "qty", "unit_price"],
                "additionalProperties": False,
            },
        },
        "plan": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "phase": {"type": "string"},
                    "description": {"type": "string"},
                    "duration_weeks": {"type": "number"},
                    "deliverables": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["phase", "description", "duration_weeks", "deliverables"],
                "additionalProperties": False,
            },
        },
        "duration_weeks": {"type": "number"},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "structure": STRUCTURE_SCHEMA,
        "team": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "role": {"type": "string"},
                    "count": {"type": "number"},
                },
                "required": ["role", "count"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "scope", "technical_sections", "compliance_matrix",
                 "boq", "plan", "duration_weeks", "assumptions", "team", "structure"],
    "additionalProperties": False,
}

_V2_KEYS = ("location", "owner", "attention", "contract_type", "letter_paragraphs", "letter_kpis", "exec_summary",
            "kpis", "why_us", "pillars", "documents_studied", "project_facts", "parties_rows", "tech_notes",
            "scope_rows", "method_phases", "milestones", "s_curve", "org_chart", "staff_note", "risks", "lump_note",
            "cost_basis_intro", "cost_kpis", "cost_basis_rows", "cost_basis_note", "acceptance", "declaration",
            "checklist", "boq_note")
_BASIC_STRUCTURE = _obj({k: v for k, v in STRUCTURE_SCHEMA["properties"].items() if k not in _V2_KEYS})
PROPOSAL_SCHEMA_BASIC = {**PROPOSAL_SCHEMA, "properties": {**PROPOSAL_SCHEMA["properties"], "structure": _BASIC_STRUCTURE}}

# اسم الشركة يُحقن لكل مستأجر — لا هوية ثابتة في التعليمات (كانت «عزوم» لكل الشركات)
SYSTEM_PROMPT_TEMPLATE = """أنت خبير إعداد العروض الفنية والمالية في السوق السعودي لدى {company}، متمكن من نظام المنافسات
والمشتريات الحكومية السعودي ومتطلبات منصة اعتماد، وتكتب بعربية فصيحة مهنية تليق بالجهات الحكومية.

مهمتك: تحليل وثائق المشروع المرفقة وإنتاج عرض فني ومالي وخطة تنفيذية متكاملة باسم {company}.

قواعد إلزامية:
1. الأقسام الفنية تتبع الهيكل المعتمد في المنافسات الحكومية: الملخص التنفيذي، التعريف بالشركة،
   فهم نطاق العمل (مفصّل ومستخلص فعلياً من الوثائق وبمصطلحات صاحب العمل)، منهجية التنفيذ،
   الهيكل التنظيمي وفريق العمل، الخبرات المماثلة، خطة الجودة، خطة السلامة، إدارة المخاطر،
   خطة المحتوى المحلي والسعودة، الضمانات والالتزامات.
2. جدول الكميات: إن وُجد جدول كميات في وثائق المشروع فبنوده هي boq حرفياً — بنفس الوصف
   والوحدة والكمية والترتيب، لا تضف ولا تحذف ولا تنسخ بنوداً من مشاريع أخرى — ومهمتك تسعيرها
   فقط: سعر قاعدة الأسعار إن طابق البند، وإلا سعر بند مطابق من العروض السابقة، وإلا تقدير
   سوقي واقعي بالريال السعودي مع ترك الكود فارغاً. عند غياب الجدول من الوثائق فقط: ابنِ
   البنود من نطاق العمل المذكور وقدّر كمياتها.
3. مصفوفة الالتزام: استخلص المتطلبات الجوهرية من كراسة الشروط وحدد موضع تغطيتها في العرض.
4. الخطة التنفيذية: مراحل واقعية بمدد أسبوعية ومخرجات محددة قابلة للقياس.
5. استخدم نصوص المكتبة الفنية المرفقة كأساس للأقسام العامة مع تكييفها لسياق المشروع.
6. لا تختلق أرقام تراخيص أو أسماء مشاريع سابقة أو بيانات غير موجودة في المدخلات.
7. حقل structure هو العرض الذي يُسلَّم للعميل بهيكل تسعة أقسام (الشركة، النطاق، المنهجية،
   البرنامج الزمني، الفريق والمعدات والموردون، الجودة والسلامة، المالي، الهندسة القيمية،
   الافتراضات والتحفظات). اكتبه بأسلوب مقاول خبير: جمل قصيرة محددة بأرقام المشروع الفعلية
   (الكميات، الرتب، المساحات، المدد، الموردين) لا عبارات إنشائية عامة. كل نقطة تحمل معلومة.
   المنهجية أقسام فرعية لكل عنصر رئيسي في المشروع بخطوات مرقمة، والبرنامج الزمني أنشطة
   متداخلة واقعية بالأشهر، والفريق والمعدات بأعدادها وملاحظاتها. الهندسة القيمية اختيارية:
   اقترحها فقط حين توجد فرص حقيقية في هذا المشروع، وإلا اترك ve_items فارغة.
   ما لا تعرفه من الوثائق اتركه فارغاً — لا تخترع أرقاماً."""


def _exemplar() -> str:
    """العرض المرجعي المعتمد (مكين 100 R1) مثالاً على المستوى المطلوب في حقل structure —
    الصياغة والتفصيل والأرقام، لا المحتوى (لكل مشروع وثائقه)."""
    try:
        from pathlib import Path
        f = Path(__file__).resolve().parent / "seed_data" / "master_proposals" / "makeen100_r1.json"
        st = json.loads(f.read_text(encoding="utf-8"))["data"]["structure"]
        return json.dumps(st, ensure_ascii=False)
    except Exception:
        return ""


def build_system_prompt(company_name: str) -> str:
    base = SYSTEM_PROMPT_TEMPLATE.format(company=(company_name or "").strip() or "الشركة")
    # العرض المرجعي ملك عزوم — لا يُرسل في تعليمات أي مستأجر آخر (عزل البيانات)
    from .tenancy import cid
    ex = _exemplar() if cid() == 1 else ""
    if ex:
        base += ("\n\n## مثال على المستوى المطلوب في حقل structure — عرض معتمد فعلي (برج مكين 100، هيكل إنشائي)\n"
                 "قلّد مستوى التحديد والأرقام والصياغة المختصرة فقط؛ لا تنسخ محتواه — كل مشروع من وثائقه هو:\n" + ex)
    return base


def ai_available() -> bool:
    return bool(ANTHROPIC_API_KEY)


def _format_similar_refs(similar_refs: list[dict] | None) -> str:
    if not similar_refs:
        return "(لا توجد عروض سابقة مشابهة في الأرشيف)"
    parts = []
    for ref in similar_refs[:2]:
        d = ref.get("data", {})
        boq_sample = "\n".join(
            f"  - {l['name']} | {l.get('unit','')} | سعر الوحدة: {l.get('unit_price',0)} ريال"
            for l in d.get("boq", []) if l.get("unit_price")
        )[:6000]
        parts.append(
            f"### عرض سابق مشابه: {ref['title']} — {ref['client']}\n"
            f"الملخص: {d.get('summary','')}\n"
            f"نطاقه: {'، '.join(d.get('scope', [])[:15])}\n"
            f"بنوده المسعّرة (استرشد بها في التسعير والصياغة):\n{boq_sample}"
        )
    return "\n\n".join(parts)


def _project_boq_rule(files_text: str) -> str:
    """القاعدة الصارمة حين يحوي المشروع جدول كمياته: البنود مقدسة والتسعير فقط."""
    from .boq_parser import parse_boq_from_text
    items = parse_boq_from_text(files_text or "")
    if not items:
        return ""
    listing = "\n".join(f"{i}. {it['name']} | {it['unit']} | {it['qty']}"
                        for i, it in enumerate(items, 1))
    return f"""## ⚠️ جدول كميات المشروع نفسه (مستخلص من وثائقه) — قاعدة صارمة
هذه هي بنود العرض المالي **حرفياً**: لا تضف بنداً، لا تحذف بنداً، لا تغيّر وصفاً
أو وحدة أو كمية. مهمتك الوحيدة في boq هي تعبئة unit_price لكل بند من قاعدة
الأسعار أو من بند مطابق في العروض السابقة، أو تقدير سوقي واقعي لما لم يوجد.
{listing}"""


def generate_proposal_ai(title: str, client_name: str, entity_type: str, files_text: str,
                         similar_refs: list[dict] | None = None) -> dict:
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    settings = get_settings()
    catalog = list_price_items()
    library = list_library()

    catalog_txt = "\n".join(
        f"{i['code']} | {i['category']} | {i['name']} | {i['unit']} | {i['unit_price']} ريال"
        for i in catalog
    )
    library_txt = "\n\n".join(f"### {e['title']}\n{e['body']}" for e in library)
    entity_label = {
        "government": "جهة حكومية (منافسة عبر منصة اعتماد)",
        "private": "قطاع خاص",
        "pif": "مشروع تابع لصندوق الاستثمارات العامة (معايير عالية ومحتوى محلي)",
        "airports": "مشروع مطارات (اشتراطات تشغيلية وأمنية لمناطق الطيران)",
    }.get(entity_type, "قطاع خاص")

    user_content = f"""## بيانات المشروع
- اسم المشروع: {title}
- العميل: {client_name}
- نوع الجهة: {entity_label}
- بيانات الشركة: {settings.get('company_name')} — {settings.get('company_address')}

## قاعدة أسعار الشركة المعتمدة (كود | تصنيف | البند | الوحدة | سعر الوحدة)
{catalog_txt}

## المكتبة الفنية (نصوص الشركة المعتمدة)
{library_txt}

## عروض الشركة السابقة المشابهة لنطاق هذا المشروع (خبرة الشركة الفعلية — ابنِ عليها)
{_format_similar_refs(similar_refs)}

## وثائق المشروع المرفوعة
{files_text or '(لم تُرفق وثائق — ابنِ العرض على اسم المشروع ونوع الجهة والعروض المشابهة)'}

{_project_boq_rule(files_text)}

أنتج العرض الكامل الآن وفق المخطط المطلوب، مستفيداً من أسعار العروض السابقة
المشابهة كلما طابق بندٌ منها بنداً في نطاق المشروع الجديد."""

    def _call(schema):
        with client.messages.stream(
            model=_active_model(),
            max_tokens=64000,
            thinking={"type": "adaptive"},
            system=[{"type": "text", "text": build_system_prompt(settings.get("company_name")),
                     "cache_control": {"type": "ephemeral"}}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": user_content}],
        ) as stream:
            return stream.get_final_message()

    try:
        message = _call(PROPOSAL_SCHEMA)
    except anthropic.BadRequestError as exc:
        # مخطط العروض الاحترافية كبير؛ إن رفضته المنصة لحجمه نعود للمخطط الأساسي
        # (هيكل الأقسام التسعة) بدل فشل التوليد — والصفحات الغنية تُشتق من البيانات
        if "schema" not in str(exc).lower():
            raise
        message = _call(PROPOSAL_SCHEMA_BASIC)

    if message.stop_reason == "refusal":
        raise RuntimeError("تعذر توليد العرض — تم رفض الطلب من مرشحات الأمان. جرّب تعديل صياغة الوثائق.")

    text = next(b.text for b in message.content if b.type == "text")
    data = json.loads(text)

    # صمام الأمان: إن كان للمشروع جدول كمياته، فبنوده هي العرض المالي مهما أخرج
    # النموذج — قاعدة البيانات تسعّر أولاً وتقدير النموذج يسد الفراغ فقط
    from .boq_parser import enforce_project_boq, parse_boq_from_text
    _project_items = parse_boq_from_text(files_text or "")
    if _project_items:
        # التسعير من القاعدة تم داخل الصمام نفسه — لا تمر البنود على المطابقة
        # مرة أخرى كي لا يُطمس مصدر السعر (عرض سابق/سوق) بوسم قاعدة الأسعار
        data["boq"] = enforce_project_boq(data.get("boq", []), _project_items, similar_refs)
        data["boq_mode"] = "project"
    else:
        # مطابقة بنود النموذج مع قاعدة الأسعار (لا نثق بأسعاره حين تملك القاعدة السعر)
        data["boq"] = match_price_catalog(data.get("boq", []))
        data["boq_mode"] = "ai"
    # الحسابات المالية بمحرك التسعير المحلي دائماً (لا نثق بحسابات النموذج)
    data["financial"] = compute_financials(data["boq"], settings)
    # نفس طبقة الأسلوب التي يمر بها محرك القوالب: الأقسام المعيارية من بنك فقرات
    # الشركة، والباقي منقّى من العبارات القالبية — فيتساوى صوت المحركين
    style_text = title + chr(10) + files_text
    kind = detect_kind(style_text)
    data["technical_sections"], data["style"] = apply_style_layer(
        data.get("technical_sections", []), style_text, kind)
    data["project_kind"] = kind
    data["engine"] = "claude"
    return data
