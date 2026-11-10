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
import json
import re
import logging
import math
from functools import lru_cache
from pathlib import Path

_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

# وحدات القياس المتعارف عليها في جداول الكميات السعودية
_UNITS = {
    "م2", "م²", "م3", "م³", "م.ط", "مط", "م", "متر", "متر مربع", "متر مكعب",
    "متر طولي", "عدد", "مقطوعية", "مقطوعيه", "لتر", "طن", "كجم", "كغم", "جرام",
    "ساعة", "يوم", "شهر", "سنة", "وحدة", "نقطة", "لوحة", "مجموعة", "طقم",
    "رول", "كرتون", "كيس", "حبة", "زيارة", "رحلة", "عامل", "فني", "شخص",
}
# عائلات الوحدات: بند بالمتر المكعب لا يُسعَّر ببند بالعدد أو بالمقطوعية أبداً
# (كان «خرسانة مسلحة للجدران» يطابق «نافورة خرسانية» بـ 90 ألف ريال للعدد)
_UNIT_FAMILIES = {
    "m3": ("م3", "م³", "م٣", "مترمكعب", "m3", "m³", "cum", "cu.m", "m3.", "cbm"),
    "m2": ("م2", "م²", "م٢", "مترمربع", "m2", "m²", "sqm", "sq.m", "m2.", "sq.m."),
    "ml": ("م.ط", "مط", "مترطولي", "م", "متر", "م.ل", "ml", "lm", "rm", "l.m", "m.l", "r.m", "mtr", "mtr.",
           "m", "lin.m", "linm"),
    "nr": ("عدد", "بالعدد", "حبة", "نقطة", "لوحة", "طقم", "مجموعة", "nr", "no", "nos", "each", "ea", "pcs",
           "no.", "nos.", "nr.", "unit", "units", "set", "sets", "pc", "pcs."),
    "ls": ("مقطوعية", "مقطوعيه", "مقطوع", "بالمقطوع", "ls", "l.s", "l.s.", "lumpsum", "item", "job", "lot"),
    "t": ("طن", "ton", "t"), "kg": ("كجم", "كغم", "kg"),
    "month": ("شهر", "month"), "day": ("يوم", "day"), "year": ("سنة", "year"),
}
_UNIT_LOOKUP = {v: fam for fam, vals in _UNIT_FAMILIES.items() for v in vals}


def unit_family(unit: str) -> str | None:
    u = re.sub(r"\s+", "", (unit or "").replace("ـ", "").translate(_AR_DIGITS)).lower()
    return _UNIT_LOOKUP.get(u)


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


# عناوين الأعمدة بعد التطبيع (حروف صغيرة، بلا نقاط ونقطتين وأقواس): «Qty.» ← «qty»
_COL_QTY = {"الكمية", "كمية", "الكميه", "الكميات", "الكمية التقديرية", "الكمية المقدرة",
            "quantity", "qty", "quantities", "est qty", "estimated qty", "qnty", "qty no"}
_COL_DESC = ("description", "item description", "description of work", "description of works",
             "particulars", "الوصف", "وصف البند", "وصف الأعمال", "وصف الاعمال", "بيان الأعمال",
             "بيان الاعمال", "البيان", "البند", "item")
_COL_UNIT = {"الوحدة", "وحدة", "الوحده", "وحدة القياس", "unit", "uom", "unit of measure", "units"}
_COL_REF = {"رقم البند", "البند رقم", "رقم", "م", "الرقم", "item no", "item", "no", "ref", "item ref",
            "s no", "sno", "sn", "sr", "sr no", "serial", "ref no", "bill ref"}
_REPO_MARK = "===== من المستودع"
_FILE_MARK = "===== الملف"


def _label(field: str) -> str:
    t = re.sub(r"[.:#()\[\]*_]+", " ", _norm(field).lower())
    return re.sub(r"\s+", " ", t).strip()


def _code_like(cell: str) -> bool:
    """رقم بند («1-1-2»، «6.1.4»، «a-»، «أ)»، «DR-04») لا نص عنوان مثل «CIVIL WORK»."""
    c = _norm(cell).strip()
    if not c or len(c) > 14:
        return False
    if re.fullmatch(r"[A-Za-z؀-ۿ]{1,2}\s*[-.)]", c):
        return True
    return bool(re.search(r"\d", c)) and " " not in c.strip()


def _known_unit(cell: str) -> bool:
    return bool(cell.strip()) and (_is_unit(cell) or unit_family(cell) is not None)


def parse_boq_from_text(text: str) -> list[dict]:
    """بنود جدول كميات المشروع من نص ملفاته (Excel/PDF/نصي) كما كتبها العميل.

    - نصوص المستودع المعرفي الملحقة بالسياق ليست ملفات المشروع: لا تُستخلص منها بنود
      (كانت أرقام فهرس عرض قديم «16 الهيكل التنظيمي» تتحول بنوداً بكمية = رقم الصفحة).
    - الترويسة تُعرف بعد التطبيع: «Item No. | Description | Unit | Qty.» كالعربية.
    - الوصف الممتد على عدة صفوف يُضم لبنده، والعنوان/الوصف الأب («Torch applied
      membrane...»، «Main Distribution Boards...») يُحفظ سياقاً للبنود الفرعية تحته
      («a- For floor»، «MDP») فتُسعَّر بمعناها الكامل ويبقى نص العميل كما هو.
    - سطر وصف التفّ على سطرين فعليين (شائع في نص مستخرج من PDF — لا خلية Excel، تلك
      تُضم في file_extract.py): سطر بأعمدة أقل من عرض الترويسة يُضم للسطر التالي قبل
      التحليل، فلا يضيع البند ولا يتحول اسمه «وحدته» بالخطأ.
    - بلا ترويسة: لا يُقبل صف بنداً إلا بوحدة قياس معروفة وثلاثة صفوف فأكثر.
    """
    items: list[dict] = []          # من جداول بترويسة صريحة
    loose: list[dict] = []          # صفوف بلا ترويسة (احتياط)
    columns = None
    explicit_table = False
    in_repo = False
    ctx, section, prev = "", "", None
    pending = None                  # سطر ناقص الأعمدة ينتظر تتمته في السطر التالي
    for raw in (text or "").splitlines():
        stripped = raw.strip()
        if stripped.startswith(_REPO_MARK):
            in_repo, columns, pending = True, None, None
            continue
        if stripped.startswith(_FILE_MARK):
            in_repo, columns, ctx, section, prev, pending = False, None, "", "", None, None
            continue
        if in_repo:
            continue
        # Tabs encode empty edge cells; stripping them would shift header indices.
        line = raw.strip(" \r") if "\t" in raw else stripped
        if line.lstrip().startswith(("##", "[ملف", "=====")):
            columns, ctx, prev, pending = None, "", None, None
            continue
        if not line.strip():
            continue
        if pending is not None:
            line, pending = f"{pending} {line}", None
        fields = _split_fields(line)
        if len(fields) < 2:
            continue
        joined = " ".join(fields)
        labels = [_label(f) for f in fields]
        qty_idx = next((i for i, f in enumerate(labels) if f in _COL_QTY), None)
        desc_idx = next((labels.index(w) for w in _COL_DESC if w in labels), None)
        if qty_idx is not None and desc_idx is not None:
            unit_idx = next((i for i, f in enumerate(labels) if f in _COL_UNIT), None)
            ref_idx = next((i for i, f in enumerate(labels) if i != desc_idx and f in _COL_REF), None)
            columns = (desc_idx, unit_idx, qty_idx, len(fields), ref_idx)
            explicit_table, ctx, section, prev = True, "", "", None
            continue
        if columns is not None:
            di, ui, qi, width, ri = columns
            # عمود الكمية نفسه غائب فعلياً عن هذا السطر (لا مجرد أعمدة اختيارية ناقصة
            # كالسعر/الإجمالي في جدول متفاوت الأعمدة — ذلك سطر صحيح مكتمل) = غالباً
            # نصف وصف انقطع بسطر PDF. نؤجله لنضمّه بسطره التالي (مرة واحدة؛ لا نسلسل
            # التأجيل كي لا يبتلع سطوراً صحيحة تالية إن كان فعلاً سطراً شاذاً لا تتمة له).
            if qi >= len(fields):
                pending = line
                continue
            cell = lambda i: fields[i].strip() if i is not None and i < len(fields) else ""
            name, unit_cell, qty_cell, ref_cell = cell(di), cell(ui), cell(qi), cell(ri)
            if not any(f.strip() for f in fields) or _is_total_label(name) or (
                    name and re.fullmatch(r"[-: ]+", name)):
                continue
            if any(_is_total_label(f) for f in fields if f.strip()) and not name:
                continue
            if ref_cell and not _code_like(ref_cell):
                # نص عنوان في عمود الرقم («CIVIL WORK»، «ELECTRICAL»)
                name = f"{ref_cell} {name}".strip()
                ref_cell = ""
            is_item = bool(unit_cell) or bool(qty_cell) if ui is not None else bool(qty_cell)
            if not is_item:
                text_ = name or " ".join(f.strip() for f in fields if f.strip())
                text_ = _norm(text_)
                if not text_ or re.fullmatch(r"[\d\s.,%-]+", text_):
                    continue
                words = text_.split()
                short_title = len(words) <= 5 and not text_.endswith(".") and (
                    text_[:1].isupper() or re.match(r"[؀-ۿ]", text_[:1]))
                open_ctx = prev in ("head", "ctx") and ctx and not ctx.rstrip().endswith((".", ":"))
                if ref_cell or (short_title and not ctx_continuing(prev, text_) and not open_ctx):
                    ctx = text_
                    # القسم الرئيسي: رقم مفرد («5 DOORS & WINDOWS») أو عنوان بحروف كبيرة بلا رقم
                    # («ELECTRICAL») أو «Division/القسم» — لا العناوين الفرعية
                    if (ref_cell and re.fullmatch(r"\d+", ref_cell) and len(words) <= 8) \
                            or (not ref_cell and text_.isupper()) \
                            or re.match(r"(division|القسم|الباب)\b", text_, re.I):
                        section = text_[:70]
                    prev = "head"
                elif prev in ("item", "cont") and items and not items[-1]["name"].rstrip().endswith((".", ":")):
                    items[-1]["name"] = f"{items[-1]['name']} {text_}"
                    prev = "cont"
                elif prev in ("head", "ctx"):
                    ctx = f"{ctx} {text_}"[:400]
                    prev = "ctx"
                else:
                    ctx, prev = text_, "ctx"
                continue
            # وحدة البند في صف عنوانه وكميته في صف وصفه («4.1 Cat Ladder | No. |» ثم وصف | 2)
            if (not ref_cell and not unit_cell and qty_cell and prev == "item" and items
                    and items[-1].get("quantity_issue", "").startswith("كمية غير واضحة")
                    and items[-1]["unit"] != "وحدة" and _num(qty_cell) is not None):
                items[-1]["name"] = f"{items[-1]['name']} — {_norm(name)}" if name else items[-1]["name"]
                items[-1]["qty"] = _num(qty_cell)
                items[-1].pop("quantity_issue", None)
                prev = "cont"
                continue
            if not name:
                name = next((f.strip() for f in fields if re.search(r"[A-Za-z؀-ۿ]{3,}", f)
                             and f.strip() not in (unit_cell, ref_cell)), "")
                if not name:
                    continue
            qty = _num(qty_cell) if qty_cell else None
            # Space-separated extraction cannot represent an empty cell. A row
            # with fewer/more fields than its header cannot safely identify qty.
            if "|" not in line and "\t" not in line and len(fields) != width:
                qty = None
            item = {"name": _norm(name), "unit": unit_cell or "وحدة",
                    "qty": qty if qty is not None else 0.0}
            if ref_cell:
                item["ref"] = _norm(ref_cell)
            if ctx:
                item["context"] = ctx
            if section:
                item["section"] = section
            if qty is None:
                item["quantity_issue"] = ("سعر وحدة فقط (Rate only) — بلا كمية" if re.search(
                    r"rate\s*only", qty_cell, re.I) else "كمية غير واضحة — تحتاج مراجعة يدوية")
            elif qty == 0:
                item["quantity_issue"] = "كمية صفرية — تحتاج تأكيداً قبل اعتماد العرض"
            items.append(item)
            prev = "item"
            continue
        # صف ترويسة (وصف + كمية كعناوين أعمدة) أو صف إجماليات — ليس بنداً
        if sum(1 for h in _HEADER_WORDS if h in joined) >= 2 and not any(
                _num(f) for f in fields if not _is_unit(f)):
            continue
        if any(_is_total_label(f) for f in fields):
            continue
        # بلا ترويسة: وحدة قياس معروفة شرط — نصوص الكراسات والفهارس المرقمة ليست بنوداً
        unit = next((f for f in fields if _known_unit(f)), "")
        if not unit:
            continue
        text_fields = [f for f in fields
                       if re.search(r"[؀-ۿA-Za-z]{3,}", f) and not _known_unit(f)]
        if not text_fields:
            continue
        name = max(text_fields, key=len).strip()
        if len(_norm(name)) < 6:
            continue
        numbers = [(i, _num(f)) for i, f in enumerate(fields)
                   if not _known_unit(f) and f != name and _num(f) is not None]
        if not numbers:
            continue
        # إسقاط رقم التسلسل: أول رقم صحيح صغير قبل الوصف يطابق العدّاد تقريباً
        name_idx = fields.index(name)
        serialish = [n for n in numbers if n[0] < name_idx and n[1] == int(n[1]) and n[1] <= len(loose) + 3]
        qty_numbers = [n for n in numbers if n not in serialish[:1]]
        if not qty_numbers:
            continue
        # ترتيب الأعمدة المتعارف عليه: م | الوصف | الوحدة | الكمية | السعر | الإجمالي
        qty = qty_numbers[0][1] if len(qty_numbers) == 1 else 0.0
        item = {"name": name, "unit": _norm(unit) or "وحدة", "qty": qty}
        if len(qty_numbers) > 1:
            item["quantity_issue"] = "أعمدة رقمية بلا ترويسة — يجب تحديد عمود الكمية يدوياً"
        elif qty == 0:
            item["quantity_issue"] = "كمية صفرية — تحتاج تأكيداً قبل اعتماد العرض"
        loose.append(item)
    if explicit_table and items:
        result = items
    else:
        result = loose if len(loose) >= MIN_TABLE_ROWS else []
    if len(result) > MAX_ITEMS:
        logging.getLogger(__name__).warning("BoQ exceeds %s rows; preserving all %s items", MAX_ITEMS, len(result))
    return result


def ctx_continuing(prev, text_: str) -> bool:
    """سطر قصير يبدأ بحرف صغير أو ينتهي بنقطة بعد بند غير مكتمل = تتمة وصف لا عنوان."""
    return prev in ("item", "cont") and (text_[:1].islower() or text_.endswith("."))


# ------------------------- التسعير -------------------------

# كلمات إنجليزية عامة لا تميّز بنداً عن آخر («Supply and install ... as per ...») — بدونها
# يتطابق بندان إنجليزيان لمجرد اشتراكهما في «and» و«the»
_EN_STOP = {"and", "the", "for", "with", "of", "to", "in", "on", "as", "per", "all", "including", "incl",
            "complete", "supply", "install", "installation", "installing", "apply", "works", "work", "item",
            "required", "necessary", "approved", "equal", "etc", "testing", "commissioning", "test", "from",
            "shall", "be", "are", "is", "or", "by", "at", "any", "other", "same", "type", "according"}


def _tokens(text: str) -> set[str]:
    text = re.sub(r"[\u064b-\u065f\u0670]", "", _norm(text)).lower()
    text = text.translate(str.maketrans("أإآى", "اااي"))
    tokens = set()
    for token in re.split(r"[\s،؛;,/|()×xX*-]+", text):
        if token.startswith("وال"):
            token = token[1:]
        if token.startswith("ال") and len(token) > 4:
            token = token[2:]
        # Conservative aliases; avoid stripping roots or technical specifications.
        token = {"للمواقع": "موقع", "للموقع": "موقع", "مواقع": "موقع",
                 "ونظافة": "نظافة", "وتركيب": "تركيب", "وتوريد": "توريد"}.get(token, token)
        if token in _EN_STOP:
            continue
        # الأرقام تبقى (قطر 25 ≠ قطر 100): كانت تُسقط فتتطابق المقاسات المختلفة
        if len(token) > 2 or (token.isdigit() and len(token) >= 2):
            tokens.add(token)
    return tokens


def _sizes(text: str) -> set[str]:
    """مقاسات صريحة ولو برقم واحد: 6" و4 بوصة و110mm و4مم."""
    t = _norm(text).lower()
    return set(re.findall(r'(\d+(?:\.\d+)?)\s*(?:"|”|inch|بوصة|mm\b|مم|ملم)', t))


def _latin(text: str) -> bool:
    """وصف إنجليزي في الغالب (حروف لاتينية أكثر من العربية)."""
    return len(re.findall(r"[A-Za-z]", text or "")) > len(re.findall(r"[؀-ۿ]", text or ""))


def _numbers(tokens: set[str]) -> set[str]:
    return {t for t in tokens if t.replace(".", "").isdigit()}


def _best_match(name: str, candidates: list, key=lambda c: c.get("name", ""), unit: str = ""):
    """أقرب مرشح بتقاطع المفردات — يشترط تقاطع مفردتين فأكثر ووحدة متوافقة.

    الترتيب بتشابه متوازن (التقاطع ÷ √(طول الوصفين)) فلا يفوز وصف طويل لبند آخر
    لمجرد احتوائه «خرسانة مسلحة»، والوحدة المعروفة المختلفة تُسقط المرشح كلياً."""
    target = _tokens(name)
    if not target:
        return None, 0.0
    fam = unit_family(unit)
    target_sizes = _sizes(name)
    best, best_score = None, 0.0
    for cand in candidates:
        if fam:
            cfam = unit_family(cand.get("unit", ""))
            if cfam and cfam != fam:
                continue
        if cand.get("auto_match", 1) == 0 or cand.get("exclude_from_pricing"):
            continue
        cand_tokens = _tokens(key(cand))
        # مقاسات مختلفة (25 مم مقابل 100 مم، 6" مقابل 110 مم) = بندان مختلفان
        tn, cn = _numbers(target) | target_sizes, _numbers(cand_tokens) | _sizes(key(cand))
        if tn and cn and not (tn & cn):
            continue
        overlap = len(target & cand_tokens)
        if overlap < 2:
            continue
        score = overlap / math.sqrt(len(target) * len(cand_tokens))
        if score > best_score:
            best, best_score = cand, score
    return best, best_score


_RATES_FILE = Path(__file__).resolve().parent / "seed_data" / "standard_rates.json"


@lru_cache(maxsize=1)
def _rate_book() -> list[dict]:
    try:
        rates = json.loads(_RATES_FILE.read_text(encoding="utf-8")).get("rates", [])
    except Exception:
        return []
    for r in rates:
        r["_all"] = [re.compile(p, re.I) for p in r.get("all", [])]
        r["_none"] = [re.compile(p, re.I) for p in r.get("none", [])]
    return rates


def standard_rate(name: str, unit: str, context: str = "") -> dict | None:
    """سعر مرجعي من دفتر أسعار السوق (seed_data/standard_rates.json) — للبنود الشائعة
    التي لا تملك الشركة لها سعراً ولا بنداً سابقاً: بالوصف أولاً ثم بالوصف وعنوانه الأب
    («a- For floor» تحت «Torch applied membrane»). الوحدة يجب أن تطابق عائلة المرجع."""
    fam = unit_family(unit)
    if not fam:
        return None
    for text in (name, f"{name} {context}" if context else None):
        if not text:
            continue
        low = _norm(text).lower()
        for r in _rate_book():
            if r["unit"] != fam:
                continue
            if all(p.search(low) for p in r["_all"]) and not any(p.search(low) for p in r["_none"]):
                return r
    return None


def _market_price(name: str, unit: str = "") -> dict | None:
    """أقرب سعر سوق من المستودع — البحث بأهم مفردات الوصف ثم المفاضلة بالتشابه."""
    from .database import search_market_prices
    seen, candidates = set(), []
    for tok in sorted(_tokens(name), key=len, reverse=True)[:3]:
        for row in search_market_prices(tok, limit=30):
            if row["id"] not in seen:
                seen.add(row["id"])
                candidates.append(row)
    best, _ = _best_match(name, candidates, unit=unit)
    return best


def price_project_boq(items: list[dict], similar_refs: list[dict] | None = None) -> list[dict]:
    """تسعير بنود المشروع نفسها — الوصف والوحدة والكمية تبقى كما كتبها العميل."""
    from .database import list_price_items
    catalog = list_price_items()
    past_lines = []
    try:
        from .database import get_settings as _gs
        _s = _gs()
        sell_factor = (1 + (float(_s.get("overhead_pct", 12)) + float(_s.get("risk_pct", 3))) / 100) * (
            1 + float(_s.get("profit_pct", 15)) / 100)
    except Exception:
        sell_factor = 1.3
    for ref in similar_refs or []:
        ref_no = ref.get("ref_no", "")
        rdata = ref.get("data", {})
        for l in rdata.get("boq", []):
            price = float(l.get("unit_price") or 0)
            # مقطوعيات بمئات الآلاف (مطار كامل) لا تسعّر بنداً آخر آلياً، والبنود
            # المستبعدة من التسعير (شظايا الأرشيف) تُتجاهل
            if price <= 0 or price >= 250_000 or l.get("exclude_from_pricing") or l.get("excluded"):
                continue
            if rdata.get("prices_are_sell"):       # أسعار بيع (عرض معتمد) ← تكلفة مباشرة
                price = round(price / sell_factor, 2)
            past_lines.append({"name": l.get("name", ""), "unit_price": price,
                               "unit": l.get("unit", ""), "ref_no": ref_no})
    try:
        from .database import get_settings
        rate_settings = get_settings()
    except Exception:
        rate_settings = {}
    out = []
    for it in items:
        line = {"code": "", "name": it["name"], "unit": it.get("unit") or "وحدة",
                "qty": float(it.get("qty", 1)), "unit_price": 0.0, "source": ""}
        if it.get("quantity_issue"):
            line["quantity_issue"] = it["quantity_issue"]
        if it.get("ref"):
            line["ref"] = it["ref"]       # رقم البند كما في جدول العميل (1.1، 2.3...)
        for k in ("context", "section"):
            if it.get(k):
                line[k] = it[k]
        if it.get("section"):
            line["division"] = it["section"]      # أقسام جدول العميل نفسها في الملحق والتفصيل
        ctx = it.get("context", "")
        unit = line["unit"]
        # الأعمال الخرسانية تُسعَّر بتحليل سعر الوحدة (خرسانة + حديد + شدات + صب)
        # كما يفعل مهندس التسعير — لا بأقرب وصف في القاعدة
        ra = None
        try:
            from .rate_analysis import analyze
            ra = analyze(it["name"], unit, rate_settings, context=ctx)
        except Exception:
            ra = None
        cat, cat_score = (None, 0.0) if ra else _best_match(it["name"], catalog, unit=unit)
        # وصف إنجليزي يطابق بنداً ثنائي اللغة بمفردتين عامتين («control panel»، «unit»)
        # فيأخذ سعر «Access Control Panel» لبند لوحة إنذار حريق — لذلك للوصف الإنجليزي
        # يتقدّم دفتر الأسعار المرجعية ما لم تكن مطابقة قاعدة الشركة قوية
        sr = standard_rate(it["name"], unit, ctx) if not ra else None
        if cat and sr and _latin(it["name"]) and cat_score < 0.4:
            cat = None
        if ra:
            line.update(unit_price=float(ra["direct"]), source="تحليل سعر الوحدة",
                        price_note=ra["note"])
        elif cat:
            line.update(code=cat["code"], unit_price=float(cat["unit_price"]),
                        source="قاعدة الأسعار")
        else:
            past, past_score = _best_match(it["name"], past_lines, unit=unit)
            if past and sr and _latin(it["name"]) and past_score < 0.4:
                past = None
            if past:
                line.update(unit_price=float(past["unit_price"]),
                            source=f"بند مطابق من عرضكم السابق ({past['ref_no']})" if past["ref_no"]
                                   else "بند مطابق من عرض سابق")
            else:
                mk = None if sr else _market_price(it["name"], unit)
                if sr and sr.get("pct"):
                    line.update(source="سعر مرجعي للسوق — راجعه", _pct=float(sr["pct"]),
                                price_note=f"دفتر الأسعار المرجعية: {sr['ar']} — {sr['pct']:g}% من قيمة بقية البنود")
                elif sr:
                    line.update(unit_price=float(sr["rate"]), source="سعر مرجعي للسوق — راجعه",
                                price_note=f"دفتر الأسعار المرجعية: {sr['ar']}"
                                           + (" (تقدير إجمالي يعتمد على المخططات)" if sr.get("confidence") == "c" else ""))
                elif mk:
                    line.update(unit_price=float(mk["unit_price"]), source="سعر سوق من المستودع")
                else:
                    line["source"] = "بلا سعر — يحتاج تسعيرة يدوية"
        out.append(line)
    # التجهيزات العامة/التعبئة: نسبة من قيمة بقية البنود (تُحسب بعد تسعيرها)
    works = sum(l["qty"] * l["unit_price"] for l in out if "_pct" not in l)
    for l in out:
        pct = l.pop("_pct", None)
        if pct is not None and l["qty"]:
            l["unit_price"] = round(works * pct / 100 / l["qty"], 2)
    return out


def boq_file_report(project_text: str) -> list[dict]:
    """لكل ملف مشروع: هل فيه جدول كميات؟ ولماذا لا؟ (ممسوح ضوئياً، تنسيق غير مدعوم،
    نص بلا ترويسة كميات...) — يُعرض للمستخدم بدل عرض ببنود مختلقة."""
    out, name, buf = [], None, []

    def close():
        if name is None:
            return
        text = "\n".join(buf)
        compact = re.sub(r"\s", "", text)
        if text.strip().startswith("[تنسيق غير مدعوم"):
            note = "تنسيق غير مدعوم"
        elif text.strip().startswith("[تعذر"):
            note = "تعذر قراءة الملف (تالف أو محمي)"
        elif len(compact) < 150:
            note = "بلا نص تقريباً — ملف ممسوح ضوئياً أو مخططات؛ يحتاج OCR أو نسخة نصية"
        elif _mojibake(text):
            note = "نص عربي بترميز تالف (خطوط PDF غير قابلة للاستخراج) — يحتاج نسخة Excel/Word أو OCR"
        elif parse_boq_from_text(f"{_FILE_MARK}: {name} =====\n{text}"):
            note = "فيه جدول كميات"
        else:
            note = "لا جدول كميات (لا ترويسة «الوصف/الوحدة/الكمية» ولا صفوف بوحدات قياس)"
        out.append({"file": name, "chars": len(compact), "note": note})

    for line in (project_text or "").splitlines():
        m = re.match(r"^=====\s*الملف:\s*(.+?)\s*=====\s*$", line.strip())
        if m:
            close()
            name, buf = m.group(1), []
        elif name is not None:
            buf.append(line)
    close()
    if not out and (project_text or "").strip():
        out.append({"file": "ملفات المشروع", "chars": len(project_text), "note": "لا جدول كميات"})
    return out


def _mojibake(text: str) -> bool:
    """نص PDF عربي مستخرج بحروف عرض/رموز (ϕΎρϧ...) بدل الحروف العربية."""
    greekish = len(re.findall(r"[\u0370-\u03ff\u02b0-\u02ff\ufe70-\ufeff]", text))
    arabic = len(re.findall(r"[\u0621-\u064a]", text))
    return greekish > 50 and greekish > arabic


def pricing_quality(boq: list[dict], boq_mode: str | None = None) -> dict:
    """جاهزية التسعير للتقديم: البنود بلا سعر، ونصيب الأسعار المرجعية من القيمة.

    عرض نصف بنوده بلا سعر ليس «عرضاً بقيمة 742 ريالاً» — هو مسودة. هذه الأرقام تظهر
    للمستخدم وتطبع المسودة بعلامة واضحة فلا يُرسل عرض ناقص للعميل."""
    lines = [l for l in boq or [] if not l.get("excluded")]
    unpriced = [l for l in lines if not float(l.get("unit_price") or 0) and not l.get("quantity_issue", "").startswith("سعر وحدة فقط")]
    total = sum(float(l.get("qty") or 0) * float(l.get("unit_price") or 0) for l in lines) or 0.0
    ref_value = sum(float(l.get("qty") or 0) * float(l.get("unit_price") or 0) for l in lines
                    if str(l.get("source", "")).startswith(("سعر مرجعي", "تقدير سوقي")))
    qty_issues = [l for l in lines if l.get("quantity_issue")]
    # بنود ليست من جدول المشروع (احتياط قديم: مرجع/كلمات/ذكاء اصطناعي) أو لا جدول أصلاً
    not_project = boq_mode in ("reference", "keywords", "ai", "missing")
    return {
        "boq_mode": boq_mode or "",
        "not_project_boq": not_project,
        "lines": len(lines), "unpriced": len(unpriced),
        "unpriced_items": [f"{l.get('ref') or ''} {l.get('name', '')}".strip()[:90] for l in unpriced[:12]],
        "quantity_issues": len(qty_issues),
        "reference_share_pct": round(ref_value / total * 100, 1) if total else 0.0,
        "ready": bool(lines) and not unpriced and not not_project,
    }


def enforce_project_boq(ai_boq: list[dict], items: list[dict],
                        similar_refs: list[dict] | None = None) -> list[dict]:
    """صمام الأمان لمسار الذكاء الاصطناعي: مهما أخرج النموذج، جدول الكميات
    النهائي هو بنود المشروع حرفياً — وتقدير النموذج يُقبل سعراً فقط للبند
    الذي لم تجد له قاعدة البيانات سعراً."""
    base = price_project_boq(items, similar_refs)
    for line in base:
        if line["unit_price"]:
            continue
        ai_line, _ = _best_match(line["name"], ai_boq or [], unit=line.get("unit", ""))
        if ai_line and float(ai_line.get("unit_price") or 0) > 0:
            line.update(unit_price=float(ai_line["unit_price"]),
                        source="تقدير سوقي (ذكاء اصطناعي) — راجعه")
    return base
