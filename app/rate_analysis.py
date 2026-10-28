"""تحليل سعر الوحدة للأعمال الخرسانية — كما يسعّر مهندسو التسعير لا بمطابقة الكلمات.

النموذج مستخلص من ورقة «تحليل الأسعار» في ملف تسعير عزوم الداخلي (مكين 100 R1):

    التكلفة المباشرة/م³ = سعر خرسانة الرتبة × (1 + هالك 2%)
                        + حديد كجم/م³ ÷ 1000 × (سعر الطن × (1 + هالك 3%) + تشغيل وتركيب)
                        + نسبة الشدات م²/م³ × سعر م² الشدة
                        + الصب والعمالة/م³ + إضافات العنصر (عزل، شد لاحق...)

النتيجة تكلفة مباشرة؛ المصاريف والمخاطر والربح تُضاف لاحقاً بنموذج التسعير العام
(compute_financials) — فلا يُحمَّل الهامش مرتين. سعر الحديد ونسبة الإضافة قابلان
للضبط من الإعدادات (rate_steel_price_t). كل سعر يخرج مع تفصيله ليراجعه المهندس.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

MODEL_FILE = Path(__file__).resolve().parent / "seed_data" / "rate_model.json"

# القواعد والسملات والميد: ليست في ورقة مكين؛ قيم هندسية متحفظة لنفس المعادلة
_FOOTING = {"key": "footing", "ar": "قواعد وسملات", "keywords": ["قواعد", "سملات", "ميد", "footing", "foundation", "pile cap"],
            "grade": "C40", "steel_kg_m3": 100, "steel_fixing_t": 560, "formwork_m2_m3": 1.6, "formwork_rate_m2": 55.0,
            "placing_m3": 55, "extras_m3": 0, "extras_note": "قيم هندسية مرجعية — راجعها بحسب المخططات"}
# ترتيب الفحص: الأخص أولاً («بلاطات لاحقة الشد» قبل «بلاطات»، «جدران الخزانات» قبل «جدران»)
_ORDER = ["lightweight_fill", "blinding", "raft", "retaining_wall", "tank_wall", "pt_slab", "stair", "ramp",
          "footing", "beam", "column", "rc_slab", "wall"]
_CONCRETE_HINT = re.compile(r"خرسان|concrete|\bRC\b|مسلح|لبشة|C\d{2}|كجم\s*/\s*سم|نيوتن|N/mm", re.I)


@lru_cache(maxsize=1)
def load_model() -> dict:
    try:
        model = json.loads(MODEL_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    types = {e["key"]: e for e in model.get("element_types", [])}
    types.setdefault("footing", _FOOTING)
    model["_types"] = types
    return model


def _grade(text: str, default: str) -> str:
    """الرتبة من الوصف: «بقوة 450 كجم/سم²» ← C45، «C35» ← C35، «35 نيوتن» ← C35."""
    t = text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    m = re.search(r"\bC\s?(\d{2})\b", t, re.I)
    if m:
        return f"C{m.group(1)}"
    m = re.search(r"(?:بقوة|قوة|رتبة|إجهاد)\D{0,12}(\d{2,3})", t)
    if m:
        v = int(m.group(1))
        return f"C{v // 10}" if v >= 100 else f"C{v}"
    m = re.search(r"(\d{3})\s*(?:كجم|كغ)\s*/\s*سم", t)
    if m:
        return f"C{int(m.group(1)) // 10}"
    return default


def concrete_price(grade: str, model: dict) -> float:
    prices = model.get("concrete_price_m3", {})
    if grade in prices:
        return float(prices[grade])
    nums = sorted((int(k[1:3]), float(v)) for k, v in prices.items() if re.fullmatch(r"C\d{2}", k))
    try:
        g = int(grade[1:3])
    except (ValueError, IndexError):
        return float(prices.get("C40", 300))
    if not nums:
        return 300.0
    if g <= nums[0][0]:
        return nums[0][1]
    if g >= nums[-1][0]:
        return nums[-1][1]
    for (g0, p0), (g1, p1) in zip(nums, nums[1:]):
        if g0 <= g <= g1:
            return round(p0 + (p1 - p0) * (g - g0) / (g1 - g0), 1)
    return 300.0


def element_type(name: str) -> dict | None:
    model = load_model()
    types = model.get("_types", {})
    low = name.lower()
    for key in _ORDER:
        e = types.get(key)
        if e and any(k.lower() in low for k in e.get("keywords", [])):
            return e
    return None


def analyze(name: str, unit: str, settings: dict | None = None) -> dict | None:
    """تكلفة مباشرة لمتر مكعب من عنصر خرساني مع تفصيلها — None لغير الخرسانة."""
    from .boq_parser import unit_family
    if unit_family(unit) != "m3" or not _CONCRETE_HINT.search(name or ""):
        return None
    model = load_model()
    e = element_type(name)
    if not model or not e:
        return None
    s = settings or {}
    if e.get("all_in_m3"):
        direct = float(e["all_in_m3"])
        return {"direct": direct, "element": e["ar"], "grade": "", "note": f"{e['ar']}: سعر شامل {direct:,.0f} ريال/م³"}
    grade = _grade(name, e.get("grade") or "C40")
    if (e.get("grade") or "").startswith(grade + "_"):
        grade = e["grade"]              # نفس الرتبة بخلطة خاصة (C50_SRC للجدران الاستنادية والخزانات)
    for vkey, v in (e.get("variants") or {}).items():
        if vkey.startswith("podium") and re.search(r"بوديوم|podium", name, re.I):
            e = {**e, **v}
    steel_t = float(s.get("rate_steel_price_t") or model.get("steel_price_t", 2850))
    conc = concrete_price(grade, model) * (1 + model.get("concrete_waste_pct", 2) / 100)
    steel_kg = float(e.get("steel_kg_m3") or 0)
    steel = steel_kg / 1000 * (steel_t * (1 + model.get("steel_waste_pct", 3) / 100) + float(e.get("steel_fixing_t") or 0))
    form = float(e.get("formwork_m2_m3") or 0) * float(e.get("formwork_rate_m2") or 0)
    placing = float(e.get("placing_m3") or 0)
    extras = float(e.get("extras_m3") or 0)
    direct = round(conc + steel + form + placing + extras, 2)
    return {"direct": direct, "element": e["ar"], "grade": grade,
            "parts": {"concrete": round(conc, 1), "steel": round(steel, 1), "formwork": round(form, 1),
                      "placing": placing, "extras": extras},
            "note": (f"تحليل سعر: {e['ar']} {grade} — خرسانة {conc:,.0f} + حديد {steel_kg:.0f} كجم ({steel:,.0f}) "
                     f"+ شدات {form:,.0f} + صب {placing:,.0f}" + (f" + إضافات {extras:,.0f}" if extras else "")
                     + f" = {direct:,.0f} ريال/م³ تكلفة مباشرة")}
