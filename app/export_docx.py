"""تصدير العرض إلى ملف Word احترافي بهوية الشركة — عربي RTL كامل.

التصميم طبق نموذج العروض المعتمد (عزوم / برج مكين 100): غلاف بشريط الهوية
الداكن وجدول بيانات العرض، خطاب تقديم، ثم أقسام مرقّمة بشارة رقم ملوّنة، وجداول
برؤوس داكنة وصفوف متناوبة، ومخطط زمني شهري، وصندوق القيمة، وصندوق الإقرار.
ترويسة داكنة بالشعار واسم الشركة، وتذييل بالعنوان والمرجع و«صفحة X من Y».

المحتوى نفسه يُبنى في proposal_structure.py كتلاً مجرّدة؛ هنا الرسم فقط.
"""
import io
from contextvars import ContextVar

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from .config import BRAND
from .proposal_structure import build_structure

# هوية المستند الحالي في ContextVar — كل طلب/خيط يرى هويته وحدها. كانت متغيرات
# وحدة عامة تتبادلها الطلبات المتزامنة فيخرج ملف بلون شركة أخرى.
_BRAND_CTX: ContextVar[tuple] = ContextVar("docx_brand", default=None)

FONT = "Segoe UI"            # عربي حديث مدمج في Windows — أقرب لخط النموذج
PAGE_W = 21.0                # A4
MARGIN = 1.8
CONTENT_W = PAGE_W - 2 * MARGIN
GRID = "D9E2DC"              # حدود الجداول الفاتحة
TEXT = RGBColor(0x22, 0x2B, 0x26)
MUTED = RGBColor(0x5F, 0x6B, 0x64)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)


def _is_azoom(settings: dict) -> bool:
    """هوية عزوم الثابتة (تذييل/اسم إنجليزي) لمستأجر عزوم نفسه (الشركة 1) فقط —
    لا تتسرب إلى وثائق شركة أخرى."""
    return settings.get("_company_id") == 1


def _resolve_brand(settings: dict) -> tuple:
    """(لون أساسي، لون مساند) كنص HEX. عزوم: أخضر الشعار المساند؛
    المستأجر: لونه هو للاثنين — لا يتسرب أخضر عزوم إلى وثائق غيرها."""
    hexv = (settings.get("_brand_color") or BRAND["primary"]).lstrip("#").upper()
    try:
        RGBColor.from_string(hexv)
    except Exception:
        hexv = BRAND["primary"]
    accent = BRAND["accent"] if _is_azoom(settings) else hexv
    return hexv, accent


def _primary_hex() -> str:
    b = _BRAND_CTX.get()
    return b[0] if b else BRAND["primary"]


def _accent_hex() -> str:
    b = _BRAND_CTX.get()
    return b[1] if b else BRAND["accent"]


def _primary() -> RGBColor:
    return RGBColor.from_string(_primary_hex())


def _accent() -> RGBColor:
    return RGBColor.from_string(_accent_hex())


def _light_hex(hexv: str, mix: float = 0.78) -> str:
    """درجة فاتحة من لون الهوية لتظليل الخلايا."""
    r, g, b = (int(hexv[i:i + 2], 16) for i in (0, 2, 4))
    f = lambda c: int(c + (255 - c) * mix)
    return f"{f(r):02X}{f(g):02X}{f(b):02X}"


def _dark_hex(hexv: str, mix: float = 0.25) -> str:
    r, g, b = (int(hexv[i:i + 2], 16) for i in (0, 2, 4))
    f = lambda c: int(c * (1 - mix))
    return f"{f(r):02X}{f(g):02X}{f(b):02X}"


# ------------------------------- أدوات OOXML -------------------------------

_PPR_AFTER_BIDI = ("w:adjustRightInd", "w:snapToGrid", "w:spacing", "w:ind", "w:contextualSpacing",
                   "w:mirrorIndents", "w:suppressOverlap", "w:jc", "w:textDirection", "w:textAlignment",
                   "w:textboxTightWrap", "w:outlineLvl", "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr",
                   "w:pPrChange")
_PPR_AFTER_BDR = ("w:shd", "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap",
                  "w:overflowPunct", "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN", "w:bidi") + _PPR_AFTER_BIDI
_TBLPR_ORDER = ("w:tblStyle", "w:tblpPr", "w:tblOverlap", "w:bidiVisual", "w:tblStyleRowBandSize",
                "w:tblStyleColBandSize", "w:tblW", "w:jc", "w:tblCellSpacing", "w:tblInd", "w:tblBorders",
                "w:shd", "w:tblLayout", "w:tblCellMar", "w:tblLook", "w:tblCaption", "w:tblDescription")
_TCPR_ORDER = ("w:cnfStyle", "w:tcW", "w:gridSpan", "w:hMerge", "w:vMerge", "w:tcBorders", "w:shd",
               "w:noWrap", "w:tcMar", "w:textDirection", "w:tcFitText", "w:vAlign", "w:hideMark")


def _set_ordered(parent, child, order):
    """يضع العنصر في موضعه الصحيح وفق ترتيب المخطط (Word صارم في الترتيب)."""
    tag = child.tag
    for old in parent.findall(tag):
        parent.remove(old)
    name = next(n for n in order if qn(n) == tag)
    after = order[order.index(name) + 1:]
    parent.insert_element_before(child, *after) if hasattr(parent, "insert_element_before") else parent.append(child)
    return child


def _set_rtl(paragraph):
    pPr = paragraph._p.get_or_add_pPr()
    if pPr.find(qn("w:bidi")) is None:
        bidi = OxmlElement("w:bidi")
        pPr.insert_element_before(bidi, *_PPR_AFTER_BIDI)


def _p_border(paragraph, side="bottom", color=None, size=12, space=4):
    pPr = paragraph._p.get_or_add_pPr()
    bdr = pPr.find(qn("w:pBdr"))
    if bdr is None:
        bdr = OxmlElement("w:pBdr")
        pPr.insert_element_before(bdr, *_PPR_AFTER_BDR)
    el = OxmlElement(f"w:{side}")
    el.set(qn("w:val"), "single")
    el.set(qn("w:sz"), str(size))
    el.set(qn("w:space"), str(space))
    el.set(qn("w:color"), color or _accent_hex())
    bdr.append(el)


def _run(paragraph, text, size=11, bold=False, color=None, font=FONT):
    run = paragraph.add_run(text)
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.name = font
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rFonts.set(qn(attr), font)
    if bold:
        rPr.get_or_add_bCs()
    szcs = OxmlElement("w:szCs")
    szcs.set(qn("w:val"), str(int(size * 2)))
    rPr.insert_element_before(szcs, "w:highlight", "w:u", "w:effect", "w:bdr", "w:shd", "w:fitText",
                              "w:vertAlign", "w:rtl", "w:cs", "w:em", "w:lang", "w:eastAsianLayout",
                              "w:specVanish", "w:oMath")
    run.font.color.rgb = color if color is not None else TEXT
    return run


def _fmt(p, align=WD_ALIGN_PARAGRAPH.RIGHT, after=6, before=0, line=1.25, rtl=True, keep=False):
    """محاذاة بلا لبس: فقرة عربية «يمين» = بدايتها الطبيعية فلا يُكتب jc أصلاً
    (Word يفسر left/right داخل الفقرات العربية تفسيراً منطقياً)، و«يسار» يُكتب
    لفقرة غير عربية (أرقام، صفحة، شعار) فيكون يساراً فعلياً."""
    if rtl and align == WD_ALIGN_PARAGRAPH.LEFT:
        rtl = False
    p.alignment = None if (rtl and align == WD_ALIGN_PARAGRAPH.RIGHT) else align
    pf = p.paragraph_format
    pf.space_after = Pt(after)
    pf.space_before = Pt(before)
    pf.line_spacing = line
    if keep:
        pf.keep_with_next = True
    if rtl:
        _set_rtl(p)
    return p


def _para(container, text="", size=11, bold=False, color=None, align=WD_ALIGN_PARAGRAPH.RIGHT,
          after=6, before=0, line=1.3, keep=False):
    p = container.add_paragraph()
    _fmt(p, align, after, before, line, keep=keep)
    if text:
        _run(p, text, size=size, bold=bold, color=color)
    return p


def _cell_para(cell, first=True):
    return cell.paragraphs[0] if first and not cell.paragraphs[0].runs else cell.add_paragraph()


def _field_run(paragraph, instr, size=8, color=None):
    """حقل Word حي (رقم الصفحة / عدد الصفحات) — يتحدث عند الفتح والطباعة."""
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), instr)
    r = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), str(size * 2))
    rpr.append(sz)
    if color:
        c = OxmlElement("w:color")
        c.set(qn("w:val"), color)
        rpr.insert(0, c)
    r.append(rpr)
    t = OxmlElement("w:t")
    t.text = "1"
    r.append(t)
    fld.append(r)
    paragraph._p.append(fld)


def _shade(cell, hex_color):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    _set_ordered(tcPr, shd, _TCPR_ORDER)


def _cell_margins(cell, top=60, bottom=60, side=110):
    tcPr = cell._tc.get_or_add_tcPr()
    mar = OxmlElement("w:tcMar")
    for k, v in (("top", top), ("left", side), ("bottom", bottom), ("right", side)):
        el = OxmlElement(f"w:{k}")
        el.set(qn("w:w"), str(v))
        el.set(qn("w:type"), "dxa")
        mar.append(el)
    _set_ordered(tcPr, mar, _TCPR_ORDER)


def _cell_borders(cell, **sides):
    """sides: top/bottom/left/right = (val, size_eighths, color)."""
    tcPr = cell._tc.get_or_add_tcPr()
    b = OxmlElement("w:tcBorders")
    for side in ("top", "left", "bottom", "right"):
        if side in sides:
            val, sz, color = sides[side]
            el = OxmlElement(f"w:{side}")
            el.set(qn("w:val"), val)
            el.set(qn("w:sz"), str(sz))
            el.set(qn("w:space"), "0")
            el.set(qn("w:color"), color)
            b.append(el)
    _set_ordered(tcPr, b, _TCPR_ORDER)


def _valign(cell, val="center"):
    tcPr = cell._tc.get_or_add_tcPr()
    v = OxmlElement("w:vAlign")
    v.set(qn("w:val"), val)
    _set_ordered(tcPr, v, _TCPR_ORDER)


def _row_height(row, cm, rule="atLeast"):
    trPr = row._tr.get_or_add_trPr()
    h = OxmlElement("w:trHeight")
    h.set(qn("w:val"), str(int(cm * 567)))
    h.set(qn("w:hRule"), rule)
    trPr.append(h)


def _no_split(row):
    trPr = row._tr.get_or_add_trPr()
    trPr.append(OxmlElement("w:cantSplit"))


def _repeat_header(row):
    trPr = row._tr.get_or_add_trPr()
    trPr.append(OxmlElement("w:tblHeader"))


def _new_table(container, rows, cols, widths, rtl=True, borders=GRID, indent=None, width=None):
    """جدول بعرض ثابت واتجاه يمين-يسار وحدود فاتحة (أو بلا حدود borders=None)."""
    if type(container).__name__ in ("_Header", "_Footer"):
        table = container.add_table(rows, cols, Cm(width or sum(widths)))
    else:
        table = container.add_table(rows=rows, cols=cols)
    tblPr = table._tbl.tblPr
    if rtl:
        _set_ordered(tblPr, OxmlElement("w:bidiVisual"), _TBLPR_ORDER)
    tw = OxmlElement("w:tblW")
    tw.set(qn("w:w"), str(int((width or sum(widths)) * 567)))
    tw.set(qn("w:type"), "dxa")
    _set_ordered(tblPr, tw, _TBLPR_ORDER)
    if indent is not None:
        ind = OxmlElement("w:tblInd")
        ind.set(qn("w:w"), str(int(indent * 567)))
        ind.set(qn("w:type"), "dxa")
        _set_ordered(tblPr, ind, _TBLPR_ORDER)
    else:
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
    bd = OxmlElement("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{side}")
        if borders:
            el.set(qn("w:val"), "single")
            el.set(qn("w:sz"), "4")
            el.set(qn("w:color"), borders)
        else:
            el.set(qn("w:val"), "nil")
        el.set(qn("w:space"), "0")
        bd.append(el)
    _set_ordered(tblPr, bd, _TBLPR_ORDER)
    lay = OxmlElement("w:tblLayout")
    lay.set(qn("w:type"), "fixed")
    _set_ordered(tblPr, lay, _TBLPR_ORDER)
    grid = table._tbl.tblGrid
    for i, gc in enumerate(grid.findall(qn("w:gridCol"))):
        gc.set(qn("w:w"), str(int(widths[i] * 567)))
    for row in table.rows:
        for i, cell in enumerate(row.cells):
            cell.width = Cm(widths[i])
    return table


# ------------------------------- الشعار -------------------------------

def _logo_variants(path: str) -> tuple:
    """(شعار أبيض للأشرطة الداكنة أو None، الأصل). الأبيض يُشتق تلقائياً حين يكون
    للشعار خلفية شفافة — كما في النموذج — وإلا يوضع الأصل على لوحة بيضاء."""
    if not path or path.lower().endswith(".webp"):
        return None, None
    try:
        from PIL import Image
        img = Image.open(path).convert("RGBA")
        alpha = img.getchannel("A")
        transparent = sum(alpha.histogram()[:40]) / (img.width * img.height)
        if transparent < 0.12:
            return None, path
        solid = Image.new("RGBA", img.size, (255, 255, 255, 255))
        solid.putalpha(alpha)
        buf = io.BytesIO()
        solid.save(buf, format="PNG")
        buf.seek(0)
        return buf, path
    except Exception:
        return None, path


def _put_logo(paragraph, variants, height_cm, on_dark=True):
    white, orig = variants
    try:
        if on_dark and white is not None:
            white.seek(0)
            paragraph.add_run().add_picture(white, height=Cm(height_cm))
            return True
        if orig:
            paragraph.add_run().add_picture(orig, height=Cm(height_cm))
            return True
    except Exception:
        pass
    return False


# ------------------------------- الترويسة والتذييل -------------------------------

def _company_lines(settings):
    azoom = _is_azoom(settings)
    phone = settings.get("company_phone") or (BRAND["footer_phone"] if azoom else "")
    cr = settings.get("company_cr") or (BRAND["footer_cr"] if azoom else "")
    return {
        "name": settings.get("company_name") or (BRAND["name_ar"] if azoom else ""),
        "phone": phone, "cr": cr,
        "address": settings.get("company_address") or (BRAND["footer_address"] if azoom else ""),
        "email": settings.get("company_email", ""),
        "site": settings.get("company_website", ""),
        "classification": settings.get("company_classification", ""),
        "tagline": settings.get("company_tagline", ""),
    }


def _header_band(section, settings, variants):
    """ترويسة داكنة بعرض الصفحة: اسم الشركة وسجلها يميناً والشعار يساراً، ثم خط مساند."""
    info = _company_lines(settings)
    header = section.header
    header.is_linked_to_previous = False
    stale = [p._p for p in header.paragraphs]
    t = _new_table(header, 2, 2, [PAGE_W * 0.62, PAGE_W * 0.38], borders=None, indent=-MARGIN, width=PAGE_W)
    for c in t.rows[0].cells:
        _shade(c, _primary_hex())
        _valign(c)
        _cell_margins(c, 120, 120, 900)
    _row_height(t.rows[0], 2.0, "exact")
    right, left = t.rows[0].cells
    p = right.paragraphs[0]
    _fmt(p, WD_ALIGN_PARAGRAPH.RIGHT, 0, line=1.0)
    _run(p, info["name"], 13, True, WHITE)
    sub = " · ".join(x for x in (f"سجل تجاري {info['cr']}" if info["cr"] else "", info["classification"]) if x)
    if sub:
        p2 = right.add_paragraph()
        _fmt(p2, WD_ALIGN_PARAGRAPH.RIGHT, 0, line=1.0)
        _run(p2, sub, 8, False, RGBColor.from_string(_light_hex(_primary_hex(), 0.7)))
    lp = left.paragraphs[0]
    lp.alignment = WD_ALIGN_PARAGRAPH.LEFT
    lp.paragraph_format.space_after = Pt(0)
    if not _put_logo(lp, variants, 1.15, on_dark=True):
        _run(lp, "", 8)
    for c in t.rows[1].cells:
        _shade(c, _accent_hex())
    _row_height(t.rows[1], 0.16, "exact")
    sp = header.add_paragraph()
    sp.paragraph_format.space_after = Pt(0)
    for el in stale:
        el.getparent().remove(el)


def _footer_lines(section, settings, ref_no):
    info = _company_lines(settings)
    footer = section.footer
    footer.is_linked_to_previous = False
    stale = [p._p for p in footer.paragraphs]
    t = _new_table(footer, 1, 2, [CONTENT_W - 2.6, 2.6], borders=None, width=CONTENT_W)
    main, page = t.rows[0].cells
    _cell_borders(main, top=("single", 8, _accent_hex()))
    _cell_borders(page, top=("single", 8, _accent_hex()))
    l1 = " · ".join(x for x in (info["address"], f"سجل تجاري {info['cr']}" if info["cr"] else "",
                                 f"المرجع {ref_no}" if ref_no else "") if x)
    l2 = " · ".join(x for x in (info["phone"], info["email"], info["site"], info["tagline"]) if x)
    p = main.paragraphs[0]
    _fmt(p, WD_ALIGN_PARAGRAPH.CENTER, 0, before=3, line=1.0)
    _run(p, l1, 7.5, False, MUTED)
    if l2:
        p2 = main.add_paragraph()
        _fmt(p2, WD_ALIGN_PARAGRAPH.CENTER, 0, line=1.0)
        _run(p2, l2, 7.5, False, _primary())
    pp = page.paragraphs[0]
    _fmt(pp, WD_ALIGN_PARAGRAPH.LEFT, 0, before=3, line=1.0)
    _run(pp, "صفحة ", 8, False, MUTED)
    _field_run(pp, "PAGE", 8, "5F6B64")
    _run(pp, " من ", 8, False, MUTED)
    _field_run(pp, "NUMPAGES", 8, "5F6B64")
    footer.add_paragraph().paragraph_format.space_after = Pt(0)
    for el in stale:
        el.getparent().remove(el)


# ------------------------------- الغلاف والخطاب -------------------------------

def _cover(doc, section, s, settings, variants):
    """غلاف كامل العرض: شريط الهوية الداكن، شارة «العرض الفني والمالي»، العنوان،
    شريط مساند، جدول بيانات العرض، ثم شريط سفلي بشعار الشركة وبياناتها."""
    cov = s["cover"]
    info = _company_lines(settings)
    band = _new_table(doc, 2, 1, [PAGE_W], borders=None, indent=0, width=PAGE_W)
    c = band.rows[0].cells[0]
    _shade(c, _primary_hex())
    _cell_margins(c, 900, 500, 1250)
    _valign(c, "top")
    _row_height(band.rows[0], 15.2, "exact")
    lp = c.paragraphs[0]
    lp.alignment = WD_ALIGN_PARAGRAPH.LEFT
    lp.paragraph_format.space_after = Pt(70)
    if not _put_logo(lp, variants, 2.4, on_dark=True):
        _fmt(lp, WD_ALIGN_PARAGRAPH.RIGHT, 70)
        _run(lp, info["name"], 20, True, WHITE)
    badge = _new_table(c, 1, 1, [5.8], borders=None, width=5.8)
    bc = badge.rows[0].cells[0]
    _shade(bc, _accent_hex())
    _cell_margins(bc, 70, 70, 140)
    bp = bc.paragraphs[0]
    _fmt(bp, WD_ALIGN_PARAGRAPH.CENTER, 0, line=1.0)
    _run(bp, cov["badge"], 12, True, WHITE)
    tp = c.add_paragraph()
    _fmt(tp, WD_ALIGN_PARAGRAPH.RIGHT, 6, before=16, line=1.1)
    _run(tp, cov["title"], 26, True, WHITE)
    if cov.get("subtitle"):
        sp = c.add_paragraph()
        _fmt(sp, WD_ALIGN_PARAGRAPH.RIGHT, 10, line=1.1)
        _run(sp, cov["subtitle"], 16, False, RGBColor.from_string(_light_hex(_primary_hex(), 0.85)))
    mp = c.add_paragraph()
    _fmt(mp, WD_ALIGN_PARAGRAPH.RIGHT, 0, line=1.1)
    _run(mp, cov["mode_line"], 10, False, RGBColor.from_string(_light_hex(_primary_hex(), 0.7)))
    bar = band.rows[1].cells[0]
    _shade(bar, _accent_hex())
    _row_height(band.rows[1], 0.32, "exact")

    _para(doc, "", after=30)
    rows = cov["info"]
    t = _new_table(doc, len(rows), 2, [5.0, CONTENT_W - 5.0])
    for i, (k, v) in enumerate(rows):
        a, b = t.rows[i].cells
        _shade(a, _light_hex(_accent_hex(), 0.9))
        for cell, txt, bold, col in ((a, k, True, _primary()), (b, v, False, TEXT)):
            _valign(cell)
            _cell_margins(cell, 80, 80, 160)
            p = cell.paragraphs[0]
            _fmt(p, WD_ALIGN_PARAGRAPH.RIGHT, 0, line=1.1)
            _run(p, txt, 10.5, bold, col)

    # الشريط السفلي في تذييل قسم الغلاف — يثبت أسفل الصفحة مهما كان طول الجدول
    footer = section.footer
    footer.is_linked_to_previous = False
    stale = [p._p for p in footer.paragraphs]
    ft = _new_table(footer, 1, 1, [PAGE_W], borders=None, indent=0, width=PAGE_W)
    fc = ft.rows[0].cells[0]
    _shade(fc, _primary_hex())
    _cell_margins(fc, 260, 260, 600)
    _row_height(ft.rows[0], 2.6, "exact")
    lines = [(info["tagline"], 11, True, RGBColor.from_string(_light_hex(_accent_hex(), 0.45))),
             (" · ".join(x for x in (info["name"], f"سجل تجاري {info['cr']}" if info["cr"] else "",
                                     info["classification"]) if x), 9, False, WHITE),
             (" · ".join(x for x in (info["address"], info["phone"], info["email"], info["site"]) if x), 8,
              False, RGBColor.from_string(_light_hex(_primary_hex(), 0.75)))]
    first = True
    for text, size, bold, color in lines:
        if not text:
            continue
        p = fc.paragraphs[0] if first else fc.add_paragraph()
        first = False
        _fmt(p, WD_ALIGN_PARAGRAPH.CENTER, 2, line=1.0)
        _run(p, text, size, bold, color)
    footer.add_paragraph().paragraph_format.space_after = Pt(0)
    for el in stale:
        el.getparent().remove(el)


def _callout(container, runs, fill=None, bar=None, size=11, color=None, after=8):
    """صندوق ملاحظة: خلفية فاتحة وشريط ملوّن على الجانب الأيمن (بداية السطر)."""
    t = _new_table(container, 1, 1, [CONTENT_W], rtl=False, borders=None)
    c = t.rows[0].cells[0]
    _shade(c, fill or _light_hex(_accent_hex(), 0.9))
    _cell_borders(c, right=("single", 24, bar or _accent_hex()))
    _cell_margins(c, 110, 110, 200)
    p = c.paragraphs[0]
    _fmt(p, WD_ALIGN_PARAGRAPH.RIGHT, 0, line=1.35)
    for text, bold in runs:
        _run(p, text, size, bold, color or TEXT)
    _para(container, "", after=after, line=0.6)


def _letter(doc, s, settings):
    L = s["letter"]
    info = _company_lines(settings)
    city = "الرياض في" if "الرياض" in (info["address"] or "") or "Riyadh" in (info["address"] or "") else "التاريخ"
    _para(doc, f"{city}: {L['date']}", 10, False, _primary(), after=2)
    _para(doc, f"المرجع: {L['ref']}", 10, False, _primary(), after=18)
    p = _para(doc, "", after=10)
    _run(p, f"السادة / {L['addressee']}", 12, True)
    _run(p, "          المحترمين", 11, False)
    _para(doc, "السلام عليكم ورحمة الله وبركاته،", 11, after=12)
    _callout(doc, [(L["subject"], True)], size=11.5, color=_primary(), after=6)
    for runs in L["paragraphs"]:
        p = _para(doc, "", align=WD_ALIGN_PARAGRAPH.JUSTIFY, after=10, line=1.45)
        for text, bold in runs:
            _run(p, text, 11.5, bold)
    _para(doc, "", after=20)
    t = _new_table(doc, 1, 3, [7.6, 5.4, CONTENT_W - 13.0], borders=None)
    a, b, stamp = t.rows[0].cells
    pa = a.paragraphs[0]
    _fmt(pa, WD_ALIGN_PARAGRAPH.RIGHT, 2)
    _run(pa, L["company"], 12, True)
    pa2 = a.add_paragraph()
    _fmt(pa2, WD_ALIGN_PARAGRAPH.RIGHT, 0)
    _run(pa2, L["signer"], 11, False)
    pb = b.paragraphs[0]
    _fmt(pb, WD_ALIGN_PARAGRAPH.RIGHT, 0)
    _run(pb, "التوقيع: ..............................", 11, False)
    _valign(stamp)
    inner = _new_table(stamp, 1, 1, [3.2], borders=None, width=3.2)
    ic = inner.rows[0].cells[0]
    dashed = ("dashed", 8, _accent_hex())
    _cell_borders(ic, top=dashed, bottom=dashed, left=dashed, right=dashed)
    _row_height(inner.rows[0], 3.0, "exact")
    _valign(ic)
    ip = ic.paragraphs[0]
    _fmt(ip, WD_ALIGN_PARAGRAPH.CENTER, 0)
    _run(ip, "الختم", 10, False, RGBColor.from_string(_light_hex(_accent_hex(), 0.35)))


# ------------------------------- الأقسام والكتل -------------------------------

def _section_heading(doc, num, title):
    """شارة الرقم الملوّنة بجانب عنوان القسم، وتحتهما خط بلون الهوية."""
    t = _new_table(doc, 1, 2, [1.6, CONTENT_W - 1.6], borders=None)
    badge, ttl = t.rows[0].cells
    _shade(badge, _primary_hex())
    _valign(badge)
    _valign(ttl)
    _cell_margins(badge, 50, 50, 60)
    _cell_margins(ttl, 30, 30, 220)
    bp = badge.paragraphs[0]
    _fmt(bp, WD_ALIGN_PARAGRAPH.CENTER, 0, line=1.0, keep=True)
    _run(bp, num, 13, True, WHITE)
    tp = ttl.paragraphs[0]
    _fmt(tp, WD_ALIGN_PARAGRAPH.RIGHT, 0, line=1.0, keep=True)
    _run(tp, title, 16, True, _primary())
    _no_split(t.rows[0])
    line = _para(doc, "", after=10, line=0.5, keep=True)
    _p_border(line, "bottom", _accent_hex(), 12, 1)


def _h3(doc, text):
    _para(doc, text, 12.5, True, _accent(), after=5, before=8, keep=True)


def _bullets(doc, items, numbered=False):
    for i, item in enumerate(items, 1):
        p = doc.add_paragraph()
        _fmt(p, WD_ALIGN_PARAGRAPH.JUSTIFY, 3, line=1.35)
        p.paragraph_format.right_indent = Cm(0.35)
        if numbered:
            _run(p, f"{i}. ", 11, True, _primary())
        else:
            _run(p, "• ", 11, True, _accent())
        if isinstance(item, (tuple, list)):
            lead, text = item
            if lead:
                _run(p, f"{lead}: ", 11, True)
            _run(p, text, 11)
        else:
            _run(p, item, 11)
    _para(doc, "", after=4, line=0.6)


def _kv(doc, rows, label_w=5.0):
    t = _new_table(doc, len(rows), 2, [label_w, CONTENT_W - label_w])
    for i, (k, v) in enumerate(rows):
        a, b = t.rows[i].cells
        _shade(a, _light_hex(_accent_hex(), 0.9))
        for cell, txt, bold, col in ((a, k, True, _primary()), (b, v, False, TEXT)):
            _valign(cell)
            _cell_margins(cell, 70, 70, 140)
            p = cell.paragraphs[0]
            _fmt(p, WD_ALIGN_PARAGRAPH.RIGHT, 0, line=1.2)
            _run(p, txt, 10, bold, col)
        _no_split(t.rows[i])
    _para(doc, "", after=6, line=0.6)


def _data_table(doc, block):
    headers = block["headers"]
    rows = block["rows"]
    total = block.get("total")
    widths = list(block.get("widths") or [CONTENT_W / len(headers)] * len(headers))
    scale = CONTENT_W / sum(widths)
    widths = [w * scale for w in widths]
    num_cols = set(block.get("num_cols") or [])
    size = 8.5 if block.get("small") else 9.5
    t = _new_table(doc, 1 + len(rows) + (1 if total else 0), len(headers), widths)
    zebra = _light_hex(_accent_hex(), 0.94)
    hdr = t.rows[0]
    _repeat_header(hdr)
    for i, h in enumerate(headers):
        c = hdr.cells[i]
        _shade(c, _primary_hex())
        _valign(c)
        _cell_margins(c, 90, 90, 100)
        p = c.paragraphs[0]
        _fmt(p, WD_ALIGN_PARAGRAPH.RIGHT if i not in num_cols else WD_ALIGN_PARAGRAPH.LEFT, 0, line=1.1)
        _run(p, h, size + 0.5, True, WHITE)
    for r, row in enumerate(rows, 1):
        tr = t.rows[r]
        _no_split(tr)
        for i, val in enumerate(row):
            c = tr.cells[i]
            if r % 2 == 0:
                _shade(c, zebra)
            _valign(c)
            _cell_margins(c, 60, 60, 100)
            p = c.paragraphs[0]
            _fmt(p, WD_ALIGN_PARAGRAPH.LEFT if i in num_cols else WD_ALIGN_PARAGRAPH.RIGHT, 0, line=1.15)
            _run(p, str(val), size, False, TEXT)
    if total:
        tr = t.rows[-1]
        _no_split(tr)
        for i, val in enumerate(total):
            c = tr.cells[i]
            _shade(c, _light_hex(_accent_hex(), 0.85))
            _cell_borders(c, top=("single", 12, _accent_hex()))
            _valign(c)
            _cell_margins(c, 80, 80, 100)
            p = c.paragraphs[0]
            _fmt(p, WD_ALIGN_PARAGRAPH.LEFT if i in num_cols else WD_ALIGN_PARAGRAPH.RIGHT, 0, line=1.1)
            _run(p, str(val), size + 0.5, True, _primary())
    _para(doc, "", after=8, line=0.6)


def _gantt(doc, block):
    """مخطط زمني شهري: عمود المهام يميناً ثم الأشهر من اليمين لليسار، وأشرطة
    متناوبة بلوني الهوية، وعلامة ◆ للتسليم."""
    months = int(block["months"])
    if months <= 6:
        sub = 4
    elif months <= 12:
        sub = 2
    else:
        sub = 1
    group = max(1, -(-months // 24))          # أكثر من 24 شهراً: عمود لكل مجموعة أشهر
    cols_m = -(-months // group)
    ncols = cols_m * sub
    label_w = 4.6
    cw = (CONTENT_W - label_w) / ncols
    bars = block["bars"]
    t = _new_table(doc, len(bars) + 2, ncols + 1, [label_w] + [cw] * ncols, borders="E6ECE8")
    hdr = t.rows[0]
    _shade(hdr.cells[0], "FFFFFF")
    for m in range(cols_m):
        a = hdr.cells[1 + m * sub]
        if sub > 1:
            a = a.merge(hdr.cells[m * sub + sub])
        _shade(a, _primary_hex())
        _cell_margins(a, 40, 40, 20)
        p = a.paragraphs[0]
        _fmt(p, WD_ALIGN_PARAGRAPH.CENTER, 0, line=1.0)
        label = f"الشهر {m * group + 1}" if group == 1 else f"{m * group + 1}–{min(months, (m + 1) * group)}"
        _run(p, label, 7 if ncols > 14 else 8, True, WHITE)
    unit = group / sub                          # أشهر لكل خلية
    for r, (task, start, end) in enumerate(bars, 1):
        tr = t.rows[r]
        _row_height(tr, 0.62, "exact")
        lc = tr.cells[0]
        _shade(lc, _light_hex(_accent_hex(), 0.94) if r % 2 else "FFFFFF")
        _valign(lc)
        _cell_margins(lc, 20, 20, 100)
        p = lc.paragraphs[0]
        _fmt(p, WD_ALIGN_PARAGRAPH.RIGHT, 0, line=1.0)
        _run(p, task, 8.5, False, TEXT)
        color = _primary_hex() if r % 2 == 0 else _accent_hex()
        for k in range(ncols):
            c0, c1 = k * unit, (k + 1) * unit
            if min(end, c1) - max(start, c0) > unit * 0.3:
                _shade(tr.cells[1 + k], color)
    last = t.rows[-1]
    _row_height(last, 0.62, "exact")
    lc = last.cells[0]
    _valign(lc)
    _cell_margins(lc, 20, 20, 100)
    p = lc.paragraphs[0]
    _fmt(p, WD_ALIGN_PARAGRAPH.RIGHT, 0, line=1.0)
    _run(p, block.get("milestone") or "التسليم", 8.5, True, _primary())
    mc = last.cells[ncols]
    _valign(mc)
    mp = mc.paragraphs[0]
    _fmt(mp, WD_ALIGN_PARAGRAPH.CENTER, 0, line=1.0)
    _run(mp, "◆", 10, True, _accent())
    _para(doc, "", after=8, line=0.6)


def _valuebox(doc, block):
    t = _new_table(doc, 1, 1, [CONTENT_W], borders=None)
    c = t.rows[0].cells[0]
    _shade(c, _primary_hex())
    _cell_borders(c, bottom=("single", 36, _accent_hex()))
    _cell_margins(c, 200, 200, 320)
    p = c.paragraphs[0]
    _fmt(p, WD_ALIGN_PARAGRAPH.RIGHT, 2, line=1.0)
    _run(p, block["label"], 10.5, False, RGBColor.from_string(_light_hex(_primary_hex(), 0.75)))
    p2 = c.add_paragraph()
    _fmt(p2, WD_ALIGN_PARAGRAPH.RIGHT, 2, line=1.0)
    _run(p2, block["amount"], 28, True, WHITE)
    _run(p2, "  " + block.get("currency", "ريال سعودي"), 13, True, WHITE)
    p3 = c.add_paragraph()
    _fmt(p3, WD_ALIGN_PARAGRAPH.RIGHT, 0, line=1.0)
    _run(p3, block["sub"], 10.5, True, WHITE)
    _para(doc, "", after=10, line=0.6)


def _declaration(doc, block):
    t = _new_table(doc, 1, 1, [CONTENT_W], borders=None)
    c = t.rows[0].cells[0]
    edge = ("single", 12, _accent_hex())
    _cell_borders(c, top=edge, bottom=edge, left=edge, right=edge)
    _cell_margins(c, 200, 200, 240)
    p = c.paragraphs[0]
    _fmt(p, WD_ALIGN_PARAGRAPH.JUSTIFY, 8, line=1.4)
    _run(p, "الإقرار: ", 11, True)
    _run(p, block["text"], 11)
    rows = block["rows"]
    inner = _new_table(c, len(rows), 2, [4.6, CONTENT_W - 5.6], width=CONTENT_W - 1.0)
    for i, (k, v) in enumerate(rows):
        a, b = inner.rows[i].cells
        _shade(a, _light_hex(_accent_hex(), 0.9))
        _row_height(inner.rows[i], 0.75)
        for cell, txt, bold, col in ((a, k, True, _primary()), (b, v, False, TEXT)):
            _valign(cell)
            _cell_margins(cell, 60, 60, 140)
            pp = cell.paragraphs[0]
            _fmt(pp, WD_ALIGN_PARAGRAPH.RIGHT, 0, line=1.0)
            _run(pp, txt, 10, bold, col)


def _render_blocks(doc, blocks):
    for b in blocks:
        kind = b["type"]
        if kind == "p":
            _para(doc, b["text"], 11, align=WD_ALIGN_PARAGRAPH.JUSTIFY, after=7, line=1.45)
        elif kind == "rich":
            p = _para(doc, "", align=WD_ALIGN_PARAGRAPH.JUSTIFY, after=8, line=1.45)
            color = _primary() if b.get("color") == "primary" else None
            for text, bold in b["runs"]:
                _run(p, text, 11, bold, color)
        elif kind == "h3":
            _h3(doc, b["text"])
        elif kind == "bullets":
            _bullets(doc, b["items"])
        elif kind == "numbered":
            _bullets(doc, b["items"], numbered=True)
        elif kind == "kv":
            _kv(doc, b["rows"])
        elif kind == "table":
            _data_table(doc, b)
        elif kind == "note":
            _callout(doc, [(b["text"], False)], size=9.5, color=MUTED)
        elif kind == "gantt":
            _gantt(doc, b)
        elif kind == "valuebox":
            _valuebox(doc, b)
        elif kind == "declaration":
            _declaration(doc, b)


# ------------------------------- التجميع -------------------------------

def export_proposal_docx(proposal: dict, settings: dict, path):
    """يبني ملف Word ويحفظه في `path` (مسار أو كائن ملف). آمن للتزامن."""
    token = _BRAND_CTX.set(_resolve_brand(settings))
    try:
        return _build_docx(proposal, settings, path)
    finally:
        _BRAND_CTX.reset(token)


def _build_docx(proposal: dict, settings: dict, path):
    s = build_structure(proposal, settings)
    doc = Document()
    variants = _logo_variants(settings.get("_logo_path", ""))

    # خصائص الملف باسم الشركة — لا يظهر اسم أي مكتبة برمجية في Author/Company
    from .quality_agent import clean_file_properties
    props = clean_file_properties(settings)
    doc.core_properties.author = props["author"]
    doc.core_properties.last_modified_by = props["last_modified_by"]
    doc.core_properties.title = proposal.get("title", "")
    doc.core_properties.subject = "عرض فني ومالي"
    doc.core_properties.comments = ""

    style = doc.styles["Normal"]
    style.font.name = FONT
    style.font.size = Pt(11)
    rpr = style.element.get_or_add_rPr()
    rpr.get_or_add_rFonts().set(qn("w:cs"), FONT)

    # قسم الغلاف: بلا هوامش ليمتد شريط الهوية بعرض الصفحة
    cover = doc.sections[0]
    cover.page_width, cover.page_height = Cm(PAGE_W), Cm(29.7)
    cover.top_margin = Cm(0)
    cover.left_margin = cover.right_margin = Cm(0)
    cover.bottom_margin = Cm(3.0)
    cover.header_distance = Cm(0)
    cover.footer_distance = Cm(0)
    cover.header.is_linked_to_previous = False
    _cover(doc, cover, s, settings, variants)

    # بقية العرض: هوامش عادية وترويسة وتذييل الهوية
    body = doc.add_section(WD_SECTION.NEW_PAGE)
    body.page_width, body.page_height = Cm(PAGE_W), Cm(29.7)
    body.top_margin = Cm(3.0)
    body.bottom_margin = Cm(2.4)
    body.left_margin = body.right_margin = Cm(MARGIN)
    body.header_distance = Cm(0)
    body.footer_distance = Cm(0.8)
    _header_band(body, settings, variants)
    _footer_lines(body, settings, proposal.get("ref_no", ""))

    _letter(doc, s, settings)
    first = True
    for sec in s["sections"]:
        # صفحة جديدة: بعد الخطاب، وقبل العرض المالي وجدول الكميات كما في النموذج
        if first or sec["key"] in ("financial", "boq"):
            # «يبدأ في صفحة جديدة» بدل فاصل صفحة: لا صفحة فارغة إن امتلأت السابقة
            brk = _para(doc, "", after=0, line=0.6)
            brk.paragraph_format.page_break_before = True
        else:
            _para(doc, "", after=6)
        first = False
        _section_heading(doc, sec["num"], sec["title"])
        _render_blocks(doc, sec["blocks"])

    doc.save(path)
    return path
