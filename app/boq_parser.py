"""مستخلص جدول كميات المشروع + محرك تسعير البنود.

القاعدة الذهبية للعرض المالي: **بنود المشروع مقدسة**. جدول الكميات الذي أرفقه
العميل (وصف البنود، وحداتها، كمياتها، ترتيبها) يُستخلص من ملفات المشروع كما هو
حرفياً، ودور النظام هو التسعير فقط — لكل بند يبحث عن سعره بهذا التسلسل:
1. بند مطابق في قاعدة أسعار الشركة (بالكود والاسم).
2. بند مطابق/مشابه من جداول كميات عروض الشركة السابقة (خبرة تسعيرها الفعلية).
3. أسعار السوق المستخلصة في المستودع المعرفي.
4. وإلا يبقى البند بلا سعر معلَّماً «يحتاج تسعيرة يدوية» — ووكيل الجودة ينبه عليه.

نسخ بنود مشروع آخر إلى مشروع جديد ممنوع متى كان للمشروع جدوله — ذلك يبقى
احتياطاً أخيراً فقط حين لا تحوي الملفات أي جدول كميات.
"""
import re
import logging
import math

_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

# وحدات القياس المتعارف عليها في جداول الكميات السعودية
_UNITS = {
    "م2", "م²", "م3", "م³", "م.ط", "مط", "م", "متر", "متر مربع", "متر مكعب",
    "متر طولي", "عدد", "مقطوعية", "مقطوعيه", "لتر", "طن", "كجم", "كغم", "جرام",
    "ساعة", "يوم", "شهر", "سنة", "وحدة", "نقطة", "لوحة", "مجموعة", "طقم",
    "رول", "كرتون", "كيس", "حبة", "زيارة", "رحلة", "عامل", "فني", "شخص",
}
_HEADER_WORDS = ("الوصف", "وصف البند", "البند", "الكمية", "الوحدة", "بيان الأعمال")
_TOTAL_WORDS = ("الإجمالي", "الاجمالي", "المجموع", "الإجمالى", "إجمالي عام")

MIN_TABLE_ROWS = 3      # Confidence threshold only for tables without headers.
MAX_ITEMS = 500        # Warning threshold; never discard client items.


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("ـ", "").translate(_AR_DIGITS)).strip()


def _num(field: str) -> float | None:
    """قيمة رقمية إن كان الحقل رقمياً صرفاً (يقبل الأرقام العربية-الهندية والفواصل)."""
    s = _norm(field).replace(",", "").replace("٬", "").replace("٫", ".")
    # أي حرف يعني أنه ليس حقل كمية (الأوصاف قد تحوي أرقاماً مثل «بلاط 60×60»)
    if not s or re.search(r"[؀-ۿA-Za-z]", s):
        return None
    try:
        v = float(s)
        return v if 0 <= v < 10_000_000 else None
    except ValueError:
        return None


def _is_unit(field: str) -> bool:
    f = _norm(field).replace(" ", "")
    return f in {u.replace(" ", "") for u in _UNITS}


def _split_fields(line: str) -> list[str]:
    if "|" in line:
        parts = line.split("|")
    elif "\t" in line:
        parts = line.split("\t")
    else:
        parts = re.split(r"\s{2,}", line)
    # Keep internal empty cells: dropping them shifts the quantity column.
    return [p.strip() for p in parts]


def _is_total_label(field: str) -> bool:
    label = _norm(field).lower().strip(" :：*-_")
    label = label.translate(str.maketrans("أإآى", "اااي"))
    return label in {
        "اجمالي", "الاجمالي", "اجمالي عام", "الاجمالي العام",
        "المجموع", "المجموع العام", "المجموع الكلي",
        "total", "subtotal", "sub-total", "sub total", "grand total",
    }


def confirm_edited_quantities(items: list[dict], previous: list[dict]) -> None:
    """A valid manual quantity change resolves its extraction warning.

    Match unchanged item identities, including duplicate occurrences. Price edits
    and unchanged quantities must not silently confirm an unresolved quantity.
    """
    by_identity = {}
    for line in previous:
        key = (line.get("name", ""), line.get("unit", ""))
        by_identity.setdefault(key, []).append(line)
    for line in items:
        key = (line.get("name", ""), line.get("unit", ""))
        matches = by_identity.get(key, [])
        old = matches.pop(0) if matches else None
        if not old or not old.get("quantity_issue"):
            continue
        try:
            qty = float(line.get("qty"))
            old_qty = float(old.get("qty"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(qty) and 0 < qty < 10_000_000 and qty != old_qty:
            line.pop("quantity_issue", None)


def parse_boq_from_text(text: str) -> list[dict]:
    """بنود جدول كميات المشروع من نص ملفاته (Excel/PDF/نصي) كما كتبها العميل.

    Headers define column roles. Headerless rows need three items for confidence;
    ambiguous quantities are retained at zero and marked for manual review.
    """
    items: list[dict] = []
    columns = None
    explicit_table = False
    for raw in (text or "").splitlines():
        # Tabs encode empty edge cells; stripping them would shift header indices.
        line = raw.strip(" \r") if "\t" in raw else raw.strip()
        if line.lstrip().startswith(("##", "[ملف", "=====")):
            columns = None
            continue
        if not line.strip():
            continue
        fields = _split_fields(line)
        if len(fields) < 2:
            continue
        joined = " ".join(fields)
        labels = [_norm(f).lower() for f in fields]
        qty_idx = next((i for i, f in enumerate(labels) if f in
                        ("الكمية", "كمية", "الكميه", "quantity", "qty")), None)
        desc_idx = next((i for i, f in enumerate(labels) if f in
                         ("الوصف", "وصف البند", "البند", "بيان الأعمال", "description", "item")), None)
        if qty_idx is not None and desc_idx is not None:
            unit_idx = next((i for i, f in enumerate(labels) if f in
                             ("الوحدة", "وحدة", "الوحده", "unit")), None)
            columns = (desc_idx, unit_idx, qty_idx, len(fields))
            explicit_table = True
            continue
        if columns is not None:
            di, ui, qi, width = columns
            if di >= len(fields):
                continue
            name = fields[di]
            if not name or _is_total_label(name) or re.fullmatch(r"[-: ]+", name):
                continue
            qty = _num(fields[qi]) if qi < len(fields) else None
            # Space-separated extraction cannot represent an empty cell. A row
            # with fewer/more fields than its header cannot safely identify qty.
            if "|" not in line and "\t" not in line and len(fields) != width:
                qty = None
            item = {"name": name, "unit": fields[ui] if ui is not None and ui < len(fields) and fields[ui] else "وحدة",
                    "qty": qty if qty is not None else 0.0}
            if qty is None:
                item["quantity_issue"] = "كمية غير واضحة — تحتاج مراجعة يدوية"
            elif qty == 0:
                item["quantity_issue"] = "كمية صفرية — تحتاج تأكيداً قبل اعتماد العرض"
            items.append(item)
            continue
        # صف ترويسة (وصف + كمية كعناوين أعمدة) أو صف إجماليات — ليس بنداً
        if sum(1 for h in _HEADER_WORDS if h in joined) >= 2 and not any(
                _num(f) for f in fields if not _is_unit(f)):
            continue
        if any(_is_total_label(f) for f in fields):
            continue
        # الوصف: أطول حقل عربي ذي معنى (وليس وحدة قياس)
        arabic_fields = [f for f in fields
                         if re.search(r"[؀-ۿ]{3,}", f) and not _is_unit(f)]
        if not arabic_fields:
            continue
        name = max(arabic_fields, key=len).strip()
        if len(_norm(name)) < 6:
            continue
        unit = next((f for f in fields if _is_unit(f)), "")
        numbers = [(i, _num(f)) for i, f in enumerate(fields)
                   if not _is_unit(f) and f != name and _num(f) is not None]
        if not numbers:
            continue
        # إسقاط رقم التسلسل: أول رقم صحيح صغير قبل الوصف يطابق العدّاد تقريباً
        name_idx = fields.index(name)
        serialish = [n for n in numbers if n[0] < name_idx and n[1] == int(n[1]) and n[1] <= len(items) + 3]
        qty_numbers = [n for n in numbers if n not in serialish[:1]]
        if not qty_numbers:
            continue
        # ترتيب الأعمدة المتعارف عليه: م | الوصف | الوحدة | الكمية | السعر | الإجمالي
        # → الكمية أول رقم بعد الوصف/الوحدة (والسعر والإجمالي بعدها إن وُجدا)
        qty = qty_numbers[0][1] if len(qty_numbers) == 1 else 0.0
        item = {"name": name, "unit": _norm(unit) or "وحدة", "qty": qty}
        if len(qty_numbers) > 1:
            item["quantity_issue"] = "أعمدة رقمية بلا ترويسة — يجب تحديد عمود الكمية يدوياً"
        elif qty == 0:
            item["quantity_issue"] = "كمية صفرية — تحتاج تأكيداً قبل اعتماد العرض"
        items.append(item)
    if len(items) > MAX_ITEMS:
        logging.getLogger(__name__).warning("BoQ exceeds %s rows; preserving all %s items", MAX_ITEMS, len(items))
    return items if explicit_table or len(items) >= MIN_TABLE_ROWS else []


# ------------------------- التسعير -------------------------

def _tokens(text: str) -> set[str]:
    text = re.sub(r"[\u064b-\u065f\u0670]", "", _norm(text)).lower()
    text = text.translate(str.maketrans("أإآى", "اااي"))
    tokens = set()
    for token in re.split(r"[\s،,/|()×xX*-]+", text):
        if token.startswith("وال"):
            token = token[1:]
        if token.startswith("ال") and len(token) > 4:
            token = token[2:]
        # Conservative aliases; avoid stripping roots or technical specifications.
        token = {"للمواقع": "موقع", "للموقع": "موقع", "مواقع": "موقع",
                 "ونظافة": "نظافة", "وتركيب": "تركيب", "وتوريد": "توريد"}.get(token, token)
        if len(token) > 2:
            tokens.add(token)
    return tokens


def _best_match(name: str, candidates: list, key=lambda c: c.get("name", "")):
    """أقرب مرشح بتقاطع المفردات — يشترط تقاطع مفردتين فأكثر."""
    target = _tokens(name)
    if not target:
        return None, 0.0
    best, best_score = None, 0.0
    for cand in candidates:
        overlap = len(target & _tokens(key(cand)))
        score = overlap / max(len(target), 1)
        if overlap >= 2 and score > best_score:
            best, best_score = cand, score
    return best, best_score


def _market_price(name: str) -> dict | None:
    """أقرب سعر سوق من المستودع — البحث بأهم مفردات الوصف ثم المفاضلة بالتشابه."""
    from .database import search_market_prices
    seen, candidates = set(), []
    for tok in sorted(_tokens(name), key=len, reverse=True)[:3]:
        for row in search_market_prices(tok, limit=30):
            if row["id"] not in seen:
                seen.add(row["id"])
                candidates.append(row)
    best, _ = _best_match(name, candidates)
    return best


def price_project_boq(items: list[dict], similar_refs: list[dict] | None = None) -> list[dict]:
    """تسعير بنود المشروع نفسها — الوصف والوحدة والكمية تبقى كما كتبها العميل."""
    from .database import list_price_items
    catalog = list_price_items()
    past_lines = []
    for ref in similar_refs or []:
        ref_no = ref.get("ref_no", "")
        for l in ref.get("data", {}).get("boq", []):
            if float(l.get("unit_price") or 0) > 0:
                past_lines.append({"name": l.get("name", ""), "unit_price": l["unit_price"],
                                   "ref_no": ref_no})
    out = []
    for it in items:
        line = {"code": "", "name": it["name"], "unit": it.get("unit") or "وحدة",
                "qty": float(it.get("qty", 1)), "unit_price": 0.0, "source": ""}
        if it.get("quantity_issue"):
            line["quantity_issue"] = it["quantity_issue"]
        cat, _ = _best_match(it["name"], catalog)
        if cat:
            line.update(code=cat["code"], unit_price=float(cat["unit_price"]),
                        source="قاعدة الأسعار")
        else:
            past, _ = _best_match(it["name"], past_lines)
            if past:
                line.update(unit_price=float(past["unit_price"]),
                            source=f"بند مطابق من عرضكم السابق ({past['ref_no']})" if past["ref_no"]
                                   else "بند مطابق من عرض سابق")
            else:
                mk = _market_price(it["name"])
                if mk:
                    line.update(unit_price=float(mk["unit_price"]), source="سعر سوق من المستودع")
                else:
                    line["source"] = "بلا سعر — يحتاج تسعيرة يدوية"
        out.append(line)
    return out


def enforce_project_boq(ai_boq: list[dict], items: list[dict],
                        similar_refs: list[dict] | None = None) -> list[dict]:
    """صمام الأمان لمسار الذكاء الاصطناعي: مهما أخرج النموذج، جدول الكميات
    النهائي هو بنود المشروع حرفياً — وتقدير النموذج يُقبل سعراً فقط للبند
    الذي لم تجد له قاعدة البيانات سعراً."""
    base = price_project_boq(items, similar_refs)
    for line in base:
        if line["unit_price"]:
            continue
        ai_line, _ = _best_match(line["name"], ai_boq or [])
        if ai_line and float(ai_line.get("unit_price") or 0) > 0:
            line.update(unit_price=float(ai_line["unit_price"]),
                        source="تقدير سوقي (ذكاء اصطناعي) — راجعه")
    return base
