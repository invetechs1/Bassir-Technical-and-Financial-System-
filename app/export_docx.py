"""تصدير العرض إلى ملف Word احترافي بهوية عزوم — عربي RTL كامل."""
from contextvars import ContextVar

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor, Cm

from .config import BRAND
from .proposal_builder import client_facing_pricing, flatten_boq_rows

# هوية المستند الحالي في ContextVar — كل طلب/خيط يرى هويته وحدها. كانت متغيرات
# وحدة عامة تتبادلها الطلبات المتزامنة فيخرج ملف بلون شركة أخرى.
_BRAND_CTX: ContextVar[tuple] = ContextVar("docx_brand", default=None)


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
    """درجة فاتحة من لون الهوية لتظليل رؤوس الجداول — كما في عروض عزوم المطبوعة."""
    r, g, b = (int(hexv[i:i + 2], 16) for i in (0, 2, 4))
    f = lambda c: int(c + (255 - c) * mix)
    return f"{f(r):02X}{f(g):02X}{f(b):02X}"


def _is_azoom(settings: dict) -> bool:
    """هوية عزوم الثابتة (تذييل/اسم إنجليزي) لمستأجر عزوم نفسه (الشركة 1) فقط —
    لا بمطابقة السجل التجاري: أي مستأجر يكتب سجل عزوم لا يرث تذييلها."""
    return settings.get("_company_id") == 1


FONT = "Sakkal Majalla"
FONT_FALLBACK = "Arial"


def _set_rtl(paragraph):
    pPr = paragraph._p.get_or_add_pPr()
    bidi = OxmlElement("w:bidi")
    bidi.set(qn("w:val"), "1")
    pPr.append(bidi)


def _run(paragraph, text, size=13, bold=False, color=None):
    run = paragraph.add_run(text)
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.name = FONT_FALLBACK
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    rFonts.set(qn("w:cs"), FONT)
    rFonts.set(qn("w:ascii"), FONT_FALLBACK)
    cs_bold = OxmlElement("w:bCs")
    cs_bold.set(qn("w:val"), "1" if bold else "0")
    rPr.append(cs_bold)
    sz_cs = OxmlElement("w:szCs")
    sz_cs.set(qn("w:val"), str(size * 2))
    rPr.append(sz_cs)
    if color:
        run.font.color.rgb = color
    return run


def _para(doc, text="", size=13, bold=False, color=None, align=WD_ALIGN_PARAGRAPH.RIGHT, space_after=6):
    p = doc.add_paragraph()
    p.alignment = align
    p.paragraph_format.space_after = Pt(space_after)
    _set_rtl(p)
    if text:
        _run(p, text, size=size, bold=bold, color=color)
    return p


def _heading(doc, text, level=1):
    if level == 1:
        p = _para(doc, text, size=17, bold=True, color=_primary(), space_after=10)
        _add_bottom_border(p)
    else:
        _para(doc, text, size=14, bold=True, color=_accent(), space_after=8)


def _big_title(doc, text, color=None, size=20):
    """عنوان الصفحة كما في عروض عزوم: وسط الصفحة، عريض، ملوّن، مسطَّر."""
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(16)
    _set_rtl(p)
    run = _run(p, text, size=size, bold=True, color=color or _accent())
    run.font.underline = True
    return p


def _bookmark(paragraph, name):
    start = OxmlElement("w:bookmarkStart")
    start.set(qn("w:id"), str(abs(hash(name)) % 100000))
    start.set(qn("w:name"), name)
    end = OxmlElement("w:bookmarkEnd")
    end.set(qn("w:id"), str(abs(hash(name)) % 100000))
    paragraph._p.insert(0, start)
    paragraph._p.append(end)


def _field_run(paragraph, instr):
    """حقل Word حي (رقم صفحة / إحالة صفحة) — يتحدث عند فتح الملف أو طباعته."""
    r = paragraph.add_run()
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), instr)
    t = OxmlElement("w:r")
    txt = OxmlElement("w:t")
    txt.text = " "
    t.append(txt)
    fld.append(t)
    paragraph._p.append(fld)
    return r


def _page_header(doc, settings):
    """ترويسة كل الصفحات: الشعار ثم اسم الشركة — كما تتصدر كل صفحة في عروض عزوم."""
    logo = settings.get("_logo_path", "")
    for section in doc.sections:
        section.header_distance = Cm(0.6)
        header = section.header
        header.is_linked_to_previous = False
        p = header.paragraphs[0]
        p.text = ""
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        if logo and not logo.lower().endswith(".webp"):
            try:
                p.add_run().add_picture(logo, height=Cm(2.2))
            except Exception:
                pass
        name_p = header.add_paragraph()
        name_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        name_p.paragraph_format.space_after = Pt(2)
        if _is_azoom(settings):
            r1 = name_p.add_run("AZOOM")
            r1.font.size = Pt(24); r1.font.bold = True
            r1.font.name = FONT_FALLBACK
            r2 = name_p.add_run(" United Co.")
            r2.font.size = Pt(15)
            r2.font.color.rgb = RGBColor(0x44, 0x44, 0x44)
            r2.font.name = FONT_FALLBACK
        else:
            _set_rtl(name_p)
            _run(name_p, settings.get("company_name", ""), size=16, bold=True, color=_primary())


def _add_bottom_border(paragraph):
    pPr = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "12")
    bottom.set(qn("w:color"), _accent_hex())
    borders.append(bottom)
    pPr.append(borders)


def _shade_cell(cell, hex_color):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), hex_color)
    tcPr.append(shd)


def _table(doc, headers, rows, widths=None, money_cols=()):
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    # اتجاه الجدول من اليمين لليسار
    tblPr = table._tbl.tblPr
    bidi = OxmlElement("w:bidiVisual")
    tblPr.append(bidi)

    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = ""
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _set_rtl(p)
        _run(p, h, size=11, bold=True)
        _shade_cell(cell, _light_hex(_primary_hex()))

    for row_data in rows:
        cells = table.add_row().cells
        for i, value in enumerate(row_data):
            p = cells[i].paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _set_rtl(p)
            txt = f"{value:,.2f}" if i in money_cols and isinstance(value, (int, float)) else str(value)
            _run(p, txt, size=11)
    if widths:
        for i, w in enumerate(widths):
            for row in table.rows:
                row.cells[i].width = Cm(w)
    return table


def _footer_block(cell, main, sub):
    cell.text = ""
    p1 = cell.paragraphs[0]
    p1.paragraph_format.space_after = Pt(0)
    r = p1.add_run(main)
    r.font.size = Pt(9); r.font.bold = True
    r.font.name = FONT_FALLBACK
    p2 = cell.add_paragraph()
    p2.paragraph_format.space_after = Pt(0)
    _set_rtl(p2)
    # لون الهوية الحي لا أخضر عزوم الثابت — وإلا تسرب لون عزوم لتذييل مستأجر آخر
    _run(p2, sub, size=7, color=_primary())


def _page_footer(doc, settings=None):
    """تذييل كل الصفحات كما في عروض عزوم المطبوعة:
    الهاتف | العنوان | السجل التجاري | «الصفحة N» + زخرفة الشعار."""
    settings = settings or {}
    if _is_azoom(settings):
        phone, addr, cr = BRAND["footer_phone"], BRAND["footer_address"], BRAND["footer_cr"]
    else:
        phone = settings.get("company_phone", "")
        addr = settings.get("company_address", "") or settings.get("company_name", "")
        cr = settings.get("company_cr", "")
    logo = settings.get("_logo_path", "")
    for section in doc.sections:
        footer = section.footer
        footer.is_linked_to_previous = False
        footer.paragraphs[0].text = ""
        table = footer.add_table(rows=1, cols=4, width=Cm(17))
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        cells = table.rows[0].cells
        _footer_block(cells[0], phone, "هاتف")
        _footer_block(cells[1], addr, "العنوان")
        _footer_block(cells[2], cr, "سجل تجاري")
        pc = cells[3]
        pc.text = ""
        pp = pc.paragraphs[0]
        pp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        pp.paragraph_format.space_after = Pt(0)
        _set_rtl(pp)
        _run(pp, "الصفحة ", size=9, bold=True)
        _field_run(pp, "PAGE")
        if logo and not logo.lower().endswith(".webp"):
            try:
                mp = pc.add_paragraph()
                mp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                mp.paragraph_format.space_after = Pt(0)
                mp.add_run().add_picture(logo, height=Cm(1.0))
            except Exception:
                pass
        for i, w in enumerate((4.2, 6.4, 3.2, 3.2)):
            cells[i].width = Cm(w)


COVER_BLUE = RGBColor(0x1F, 0x4E, 0xC0)  # أزرق عنوان الغلاف كما في عروض عزوم


def _cover_page(doc, proposal, settings):
    """الغلاف طبق عينة عروض عزوم: العنوان الأزرق المسطَّر، مقدم من، الشعار،
    اسم الشركة، لصالح العميل، اسم المشروع، التاريخ والرقم."""
    doc.add_paragraph()
    tp = _big_title(doc, "«العـــرض الفــنــي والمــالــي»", color=COVER_BLUE, size=24)
    tp.paragraph_format.space_after = Pt(20)
    _para(doc, "مقدم من", size=14, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=10)
    logo = settings.get("_logo_path", "")
    if logo and not logo.lower().endswith(".webp"):
        try:
            pic = doc.add_paragraph()
            pic.alignment = WD_ALIGN_PARAGRAPH.CENTER
            pic.paragraph_format.space_after = Pt(8)
            pic.add_run().add_picture(logo, height=Cm(2.4))
        except Exception:
            pass
    company_name = settings.get("company_name") or (BRAND["name_ar"] if _is_azoom(settings) else "")
    _para(doc, company_name, size=17, bold=True, color=_accent(),
          align=WD_ALIGN_PARAGRAPH.CENTER, space_after=16)
    _para(doc, "لصالح", size=14, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=10)
    _para(doc, proposal["client"], size=20, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=18)
    ttl = _para(doc, proposal["title"], size=15, bold=True, color=_accent(),
                align=WD_ALIGN_PARAGRAPH.CENTER, space_after=16)
    for run in ttl.runs:
        run.font.underline = True
    created = (proposal.get("created_at") or "")[:10]
    if not created:
        from datetime import date
        created = date.today().isoformat()
    _para(doc, f"التاريــخ: {created.replace('-', '/')}م", size=13, bold=True,
          align=WD_ALIGN_PARAGRAPH.CENTER, space_after=8)
    _para(doc, "الرقم:", size=13, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=4)
    _para(doc, f"({proposal.get('ref_no', '')})", size=13, bold=True,
          align=WD_ALIGN_PARAGRAPH.CENTER)
    doc.add_page_break()


def _toc_page(doc, entries):
    """صفحة محتويات العرض الفني كما في العينة — أرقام الصفحات حقول PAGEREF حية
    تتحدث عند فتح Word أو الطباعة (تحديث الحقول)."""
    _big_title(doc, "محتــويــات العــرض الفــنــي")
    hp = _para(doc, "جدول محتويات العرض الفني:", size=13, bold=True, space_after=8)
    for run in hp.runs:
        run.font.underline = True
    table = doc.add_table(rows=1, cols=3)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    tblPr = table._tbl.tblPr
    bidi = OxmlElement("w:bidiVisual")
    tblPr.append(bidi)
    for i, h in enumerate(("م", "المحتوى", "رقم الصفحة")):
        cell = table.rows[0].cells[i]
        cell.text = ""
        cp = cell.paragraphs[0]
        cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _set_rtl(cp)
        _run(cp, h, size=11, bold=True)
        _shade_cell(cell, _light_hex(_primary_hex()))
    for n, (title, bkmk) in enumerate(entries, 1):
        cells = table.add_row().cells
        p0 = cells[0].paragraphs[0]
        p0.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _set_rtl(p0)
        _run(p0, str(n), size=11)
        p1 = cells[1].paragraphs[0]
        _set_rtl(p1)
        _run(p1, title, size=11)
        p2 = cells[2].paragraphs[0]
        p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _field_run(p2, f"PAGEREF {bkmk} \\h")
    for i, w in enumerate((1.2, 12.0, 2.6)):
        for row in table.rows:
            row.cells[i].width = Cm(w)
    doc.add_page_break()


_INFO_LINE = None  # يُهيأ عند أول استخدام (regex سطر «مفتاح: قيمة»)


def _company_info_table(doc, body: str) -> bool:
    """قسم «معلومات الشركة» جدولاً بخلايا تسمية ملونة كما في العينة —
    يعود False إن لم يكن النص بصيغة مفتاح: قيمة فيُطبع فقرات عادية."""
    rows = []
    for line in body.split("\n"):
        line = line.strip()
        if ":" in line and 2 <= len(line.split(":", 1)[0].split()) <= 6:
            k, v = line.split(":", 1)
            if v.strip():
                rows.append((k.strip(), v.strip()))
    if len(rows) < 3:
        return False
    table = doc.add_table(rows=0, cols=2)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    tblPr = table._tbl.tblPr
    bidi = OxmlElement("w:bidiVisual")
    tblPr.append(bidi)
    for k, v in rows:
        cells = table.add_row().cells
        kp = cells[0].paragraphs[0]
        kp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _set_rtl(kp)
        _run(kp, k, size=12, bold=True)
        _shade_cell(cells[0], "D6E4F0")  # أزرق التسمية الفاتح كما في العينة
        vp = cells[1].paragraphs[0]
        vp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _set_rtl(vp)
        _run(vp, v, size=12)
    for row in table.rows:
        row.cells[0].width = Cm(4.6)
        row.cells[1].width = Cm(11.4)
    return True


def export_proposal_docx(proposal: dict, settings: dict, path):
    """يبني ملف Word ويحفظه في `path` (مسار أو كائن ملف). آمن للتزامن."""
    token = _BRAND_CTX.set(_resolve_brand(settings))
    try:
        return _build_docx(proposal, settings, path)
    finally:
        _BRAND_CTX.reset(token)


def _build_docx(proposal: dict, settings: dict, path):
    data = proposal["data"]
    doc = Document()

    # هوامش وإعداد عام
    for section in doc.sections:
        section.top_margin = Cm(2)
        section.bottom_margin = Cm(2)
        section.right_margin = Cm(2.2)
        section.left_margin = Cm(2.2)

    # خصائص الملف باسم الشركة — لا يظهر اسم أي مكتبة برمجية في Author/Company
    from .quality_agent import clean_file_properties
    props = clean_file_properties(settings)
    doc.core_properties.author = props["author"]
    doc.core_properties.last_modified_by = props["last_modified_by"]
    doc.core_properties.title = proposal.get("title", "")
    doc.core_properties.subject = "عرض فني ومالي"
    doc.core_properties.comments = ""
    _page_header(doc, settings)
    _page_footer(doc, settings)
    _cover_page(doc, proposal, settings)

    # ---------- ترتيب الأقسام كما في عروض عزوم: السرية بعد الغلاف ثم المحتويات ----------
    tech_sections = list(data.get("technical_sections", []))
    # عناوين القوالب قد تحمل تطويلاً زخرفياً («الســرية») — تُقارن بعد نزعه
    conf_idx = next((i for i, x in enumerate(tech_sections)
                     if "السرية" in x["title"].replace("ـ", "")), None)
    if conf_idx is not None:
        conf = tech_sections.pop(conf_idx)
        _big_title(doc, conf["title"])
        for paragraph_text in conf["body"].split("\n"):
            if paragraph_text.strip():
                _para(doc, paragraph_text.strip(), size=13,
                      align=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=8)
        doc.add_page_break()

    entries = [(sec["title"], f"sec{i}") for i, sec in enumerate(tech_sections)]
    team = data.get("team") or []
    matrix = data.get("compliance_matrix") or []
    if team:
        entries.append(("فريق العمل المقترح", "secteam"))
    if matrix:
        entries.append(("مصفوفة الالتزام بالمتطلبات", "secmatrix"))
    entries.append(("الخطة التنفيذية للمشروع", "secplan"))
    entries.append(("العرض المالي", "secfin"))
    _toc_page(doc, entries)

    # ---------- العرض الفني: كل قسم بصفحته وعنوانه الأخضر المسطَّر ----------
    for i, sec in enumerate(tech_sections):
        tp = _big_title(doc, sec["title"])
        _bookmark(tp, f"sec{i}")
        if "معلومات الشركة" in sec["title"] and _company_info_table(doc, sec["body"]):
            pass
        else:
            for paragraph_text in sec["body"].split("\n"):
                if paragraph_text.strip():
                    _para(doc, paragraph_text.strip(), size=13,
                          align=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=8)
        if i < len(tech_sections) - 1 or team or matrix:
            doc.add_page_break()

    scope = data.get("scope") or []
    if scope and len(scope) > 1:
        _heading(doc, "نطاق العمل التفصيلي", level=2)
        for item in scope:
            _para(doc, f"•  {item}", size=12)

    if team:
        tp = _big_title(doc, "فريق العمل المقترح")
        _bookmark(tp, "secteam")
        _table(doc, ["الدور الوظيفي", "العدد"],
               [(t["role"], int(t["count"])) for t in team], widths=[10, 4])
        doc.add_page_break()

    if matrix:
        tp = _big_title(doc, "مصفوفة الالتزام بالمتطلبات")
        _bookmark(tp, "secmatrix")
        _table(doc, ["المتطلب", "الالتزام", "الموضع في العرض"],
               [(m["requirement"], m["response"], m["reference"]) for m in matrix],
               widths=[8, 3, 5])
        doc.add_page_break()

    # ---------- الخطة التنفيذية ----------
    tp = _big_title(doc, "الخطة التنفيذية للمشروع")
    _bookmark(tp, "secplan")
    _para(doc, f"المدة الإجمالية المقترحة: {int(data.get('duration_weeks', 0))} أسبوعاً", size=13, bold=True)
    for i, phase in enumerate(data.get("plan", []), 1):
        _heading(doc, f"المرحلة {i}: {phase['phase']} ({int(phase['duration_weeks'])} أسابيع)", level=2)
        _para(doc, phase["description"], size=12)
        for d in phase.get("deliverables", []):
            _para(doc, f"–  {d}", size=11)

    doc.add_page_break()

    # ---------- العرض المالي ----------
    # أسعار البنود محمَّلة بكامل التكاليف — لا تظهر أي نسب داخلية للعميل
    tp = _big_title(doc, "العــرض المــالــي")
    _bookmark(tp, "secfin")
    _heading(doc, "جدول الكميات والأسعار", level=2)
    boq = client_facing_pricing(data.get("boq", []), data.get("financial", {}))
    _table(
        doc,
        ["م", "الكود", "البند", "الوحدة", "الكمية", "سعر الوحدة (ر.س)", "الإجمالي (ر.س)"],
        flatten_boq_rows(boq),
        widths=[1, 2, 6, 2, 2, 3, 3],
        money_cols=(5, 6),
    )

    fin = data.get("financial", {})
    _heading(doc, "ملخص القيمة الإجمالية", level=2)
    _table(
        doc,
        ["البيان", "القيمة (ريال سعودي)"],
        [
            ("إجمالي جدول الكميات والأسعار", fin.get("subtotal", 0)),
            (f"ضريبة القيمة المضافة ({fin.get('vat_rate', 15):g}%)", fin.get("vat", 0)),
            ("الإجمالي النهائي شامل الضريبة", fin.get("grand_total", 0)),
        ],
        widths=[9, 5],
        money_cols=(1,),
    )

    if (settings.get("payment_terms") or "").strip():   # لا عنوان فارغ لمستأجر لم يحدد شروطه
        _heading(doc, "شروط الدفع", level=2)
        _para(doc, settings["payment_terms"], size=12)

    assumptions = data.get("assumptions") or []
    if assumptions:
        _heading(doc, "الافتراضات والاستثناءات", level=2)
        for a in assumptions:
            _para(doc, f"•  {a}", size=11)

    _para(doc)
    _para(doc, "وتفضلوا بقبول فائق الاحترام والتقدير،", size=12)
    _para(doc, settings.get("company_name", ""), size=13, bold=True, color=_primary())

    doc.save(path)
    return path
