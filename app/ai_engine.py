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
                 "boq", "plan", "duration_weeks", "assumptions", "team"],
    "additionalProperties": False,
}

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
6. لا تختلق أرقام تراخيص أو أسماء مشاريع سابقة أو بيانات غير موجودة في المدخلات."""


def build_system_prompt(company_name: str) -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(company=(company_name or "").strip() or "الشركة")


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

    with client.messages.stream(
        model=_active_model(),
        max_tokens=64000,
        thinking={"type": "adaptive"},
        system=[{"type": "text", "text": build_system_prompt(settings.get("company_name")),
                 "cache_control": {"type": "ephemeral"}}],
        output_config={"format": {"type": "json_schema", "schema": PROPOSAL_SCHEMA}},
        messages=[{"role": "user", "content": user_content}],
    ) as stream:
        message = stream.get_final_message()

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
