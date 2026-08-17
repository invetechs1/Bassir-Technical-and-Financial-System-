"""إعدادات نظام عزوم للعروض الفنية والمالية."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
EXPORTS_DIR = DATA_DIR / "exports"
DB_PATH = DATA_DIR / "azoom.db"

for d in (DATA_DIR, UPLOADS_DIR, EXPORTS_DIR):
    d.mkdir(parents=True, exist_ok=True)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
CLAUDE_MODEL = "claude-opus-4-8"

# الهوية البصرية الرسمية — AZOOM United Co. (الشعار السداسي الأخضر)
BRAND = {
    "name_ar": "شركة عزوم المتحدة للمقاولات",
    "name_en": "AZOOM United Co.",
    "primary": "1E6B3C",   # أخضر مؤسسي عميق
    "accent": "2E9E5B",    # أخضر الشعار
    "light": "EAF4EC",     # أخضر فاتح
    "footer_phone": "+966114880122",
    "footer_address": "Saudi Arabia - Riyadh - 12623 Post Code",
    "footer_cr": "1010467099",
}

# القيم الافتراضية المالية (قابلة للتعديل من شاشة الإعدادات)
DEFAULT_SETTINGS = {
    # بيانات عزوم الرسمية — مستخرجة من وثائق الشركة في Google Drive
    "company_name": "شركة عزوم المتحدة للمقاولات",
    "company_cr": "1010467099",                    # السجل التجاري
    "company_vat_no": "311917527400003",           # الرقم الضريبي
    "company_address": "الرياض — حي الضباط — طريق صلاح الدين الأيوبي — 12623",
    "company_bank": "بنك الرياض",
    "company_iban": "SA4920000002863132619941",
    "company_chamber_no": "414250",                # عضوية الغرفة التجارية (درجة رابعة)
    "company_phone": "+966114880122",
    "company_email": "yahya@azoomunited.com",   # م. يحيى آل سلامة — الرئيس التنفيذي
    "vat_rate": "15",            # ضريبة القيمة المضافة %
    "overhead_pct": "12",        # المصاريف الإدارية والعمومية %
    "risk_pct": "3",             # احتياطي المخاطر %
    "profit_pct": "15",          # هامش الربح %
    "validity_days": "90",       # مدة سريان العرض (المتعارف عليه في المنافسات الحكومية)
    "bid_bond_pct": "1",         # الضمان الابتدائي % (نظام المنافسات: لا يقل عن 1%)
    # نمط الدفعات الفعلي المعتمد في عروض عزوم
    "payment_terms": "دفعة مقدمة 20% من قيمة العرض عند توقيع العقد، ويُقسَّم باقي المبلغ على دفعات (مستخلصات) وفقاً لنسب الإنجاز الفعلية بالموقع، مع سداد الفواتير خلال مدة أقصاها 15 يوماً من تاريخ الاستلام.",
    # رقم الهوية لدخول منصة اعتماد عبر نفاذ — يُحفظ محلياً في قاعدة بياناتك فقط
    "etimad_national_id": "",
}
