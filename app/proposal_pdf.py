"""العرض الفني والعرض المالي بصيغة PDF احترافية — طبق تصميم «مكين 100 R1».

ملفان مستقلان كما تسلّمهما الشركات الكبرى:
- العرض الفني: غلاف داكن بخطوط الهوية، خطاب تقديم بمؤشرات، محتويات، ملخص تنفيذي
  (مؤشرات + لماذا نحن + محاور الحل)، فاصل الجزء الأول، عن الشركة، القيم والاستدامة،
  الإنجازات، الخبرات (لمحة، بطاقات مشاريع مماثلة بصورها، سجل المشاريع، العملاء،
  المعدات)، فهم المشروع، النطاق، المنهجية، البرنامج الزمني (مخطط + منحنى S + معالم)،
  الهيكل التنظيمي والفريق والمعدات والموردون، الجودة والسلامة والمخاطر، صفحة الشكر.
- العرض المالي: غلاف، خطاب، محتويات، فاصل، نموذج التسعير، أساس التسعير، الهندسة
  القيمية، الشروط والتحفظات والإقرار، قائمة متطلبات التقديم، الملحق (أ) جدول الكميات
  المسعّر بأقسامه وملخصه، صفحة الشكر.

HTML بخطوط مضمّنة ثم Chromium (Playwright) يطبعه PDF بهوامش صفحات مسمّاة: لكل قسم
ترويسته («ABOUT AZOOM · عن عزوم») وتذييله ورقم «صفحة» — والغلاف والفواصل بلا هوامش.
أرقام صفحات المحتويات تُحسب بتمريرتين (علامات خفية تُقرأ من PDF الأول).

المحتوى الغني (data["structure"] بمخطط v2) يُرسم بتخطيطاته الكاملة؛ وما غاب منه يُرسم
من كتل proposal_structure نفسها — فلا يخرج قسم فارغ في وضع القوالب.
"""
import base64
import html
import io
import re
from pathlib import Path

from .proposal_structure import (build_structure, duration_view, money, pricing_view,
                                 qty_fmt, _parse_date)
from .arabic_numbers import amount_in_words

FONTS = Path(__file__).resolve().parent / "static" / "fonts"
INK = "121A16"


def _e(v) -> str:
    return html.escape(str(v if v is not None else ""))


def _font_faces() -> str:
    faces = []
    for w in (300, 400, 500, 600, 700):
        for sub, rng in (("arabic", "U+0600-06FF, U+0750-077F, U+08A0-08FF, U+FB50-FDFF, U+FE70-FEFF, U+200C-200F"),
                         ("latin", "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215")):
            f = FONTS / f"plex-{sub}-{w}.woff2"
            if f.exists():
                b64 = base64.b64encode(f.read_bytes()).decode()
                faces.append(f"@font-face{{font-family:Plex;font-weight:{w};src:url(data:font/woff2;base64,{b64}) format('woff2');unicode-range:{rng}}}")
    for w in (300, 400, 600):
        f = FONTS / f"montserrat-{w}.woff2"
        if f.exists():
            b64 = base64.b64encode(f.read_bytes()).decode()
            faces.append(f"@font-face{{font-family:Mont;font-weight:{w};src:url(data:font/woff2;base64,{b64}) format('woff2')}}")
    return "\n".join(faces)


def _short(v) -> str:
    """قيمة مؤشر مختصرة من نص الملف التعريفي: «+240 موظفاً ومهندساً» ← «+240»."""
    v = str(v or "").strip()
    if not v:
        return ""
    g = re.search(r"Grade\s*\d", v, re.I)
    if g:
        return g.group(0).title()
    m = re.match(r"[+]?[\d.,]+\s*[KMkم]?[+]?", v)
    if m:
        return m.group(0).strip()
    return v.split()[0][:14]


def _mix(hexv: str, mix: float) -> str:
    r, g, b = (int(hexv[i:i + 2], 16) for i in (0, 2, 4))
    f = lambda c: int(c + (255 - c) * mix)
    return f"{f(r):02X}{f(g):02X}{f(b):02X}"


def _img_uri(path_or_bytes, mime="image/jpeg") -> str:
    try:
        data = path_or_bytes if isinstance(path_or_bytes, (bytes, bytearray)) else Path(path_or_bytes).read_bytes()
    except Exception:
        return ""
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def _logo_uris(settings: dict) -> tuple[str, str, float]:
    """(شعار للخلفية الفاتحة، شعار أبيض للخلفية الداكنة، نسبة العرض/الارتفاع)."""
    path = settings.get("_logo_path") or ""
    if not path:
        return "", "", 1.0
    try:
        from PIL import Image
        img = Image.open(path).convert("RGBA")
        ratio = img.width / max(1, img.height)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        light = _img_uri(buf.getvalue(), "image/png")
        alpha = img.getchannel("A")
        transparent = sum(alpha.histogram()[:40]) / (img.width * img.height)
        dark = light
        if transparent >= 0.12:
            solid = Image.new("RGBA", img.size, (255, 255, 255, 255))
            solid.putalpha(alpha)
            b2 = io.BytesIO()
            solid.save(b2, format="PNG")
            dark = _img_uri(b2.getvalue(), "image/png")
        return light, dark, ratio
    except Exception:
        return "", "", 1.0


def _svg_logo(uri: str, ratio: float, h: int = 40) -> str:
    """شعار الترويسة داخل SVG بحجم ثابت ومصدر عالي الدقة — صندوق الهامش يعرض الصورة
    بحجمها الذاتي، فالغلاف المتجهي يحفظ الحدة عند الطباعة."""
    w = int(h * ratio)
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' xmlns:xlink='http://www.w3.org/1999/xlink' width='{w}' height='{h}'>"
           f"<image width='{w}' height='{h}' xlink:href='{uri}'/></svg>")
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


CSS = r"""
:root{--p:#__P__;--a:#__A__;--ink:#__INK__;--tint:#__T__;--tint2:#__T2__;--line:#E2E7E4;--mut:#5E6B64;--txt:#1F2723}
*{box-sizing:border-box}
html{-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{margin:0;font-family:Plex,'Segoe UI',sans-serif;color:var(--txt);font-size:9.6pt;line-height:1.75;direction:rtl}
@page{size:A4;margin:24mm 16mm 18mm 16mm;
 @top-left{content:__LOGO__;vertical-align:bottom;padding-bottom:3mm;border-bottom:.6pt solid #E2E7E4}
 @top-center{content:"";border-bottom:.6pt solid #E2E7E4}
 @top-right{content:"__TR__";white-space:pre;font:600 6.5pt Mont,Plex;letter-spacing:1.6pt;color:#__A__;vertical-align:bottom;padding-bottom:3mm;border-bottom:.6pt solid #E2E7E4;text-align:left}
 @bottom-left{content:counter(page, decimal-leading-zero);font:600 7pt Mont,Plex;color:#fff;background:#__A__;width:9mm;height:5mm;vertical-align:middle;text-align:center;border-radius:1.2mm;margin-top:5mm}
 @bottom-center{content:"__REF__";font:400 6.5pt Mont,Plex;color:#8A958F;vertical-align:middle;margin-top:5mm}
 @bottom-right{content:"__FOOT__";font:400 6.5pt Plex;color:#8A958F;vertical-align:middle;margin-top:5mm;text-align:right}}
@page bleed{margin:0;@top-left{content:none;border:0}@top-center{content:none;border:0}@top-right{content:none;border:0}
 @bottom-left{content:none;background:none}@bottom-center{content:none}@bottom-right{content:none}}
__NAMED__
.bleed{page:bleed;break-before:page;height:297mm;width:210mm;position:relative;overflow:hidden;background:var(--ink);color:#fff}
.bleed:first-child{break-before:auto}
.chev{position:absolute;top:0;left:0;height:297mm;width:118mm}
.bl-in{position:absolute;right:16mm;left:16mm;top:0;bottom:0}
.bl-logo{position:absolute;top:18mm;right:0;height:13mm}
.eyebrow{font:400 7pt Mont,Plex;letter-spacing:3pt;color:var(--a);text-transform:uppercase}
.cv-ey{position:absolute;top:62mm;right:0;text-align:right}
.cv-ey .ar{display:block;font:400 11pt Plex;color:#DCE5E0;margin-top:2mm;letter-spacing:0}
.cv-title{position:absolute;top:84mm;right:0;width:118mm;text-align:right}
.cv-title h1{margin:0;font:700 25pt/1.32 Plex;color:#fff}
.cv-title h1 .g{color:#__A2__}
.cv-title .loc{font:400 10pt Plex;color:#C9D3CE;margin-top:3mm}
.cv-title .bar{width:22mm;height:1.4mm;background:var(--a);margin:7mm 0 0 auto}
.cv-meta{position:absolute;top:166mm;right:0;width:150mm;display:grid;grid-template-columns:1fr 1fr;gap:5mm 8mm}
.cv-meta div{border-right:.9mm solid var(--a);padding-right:3mm}
.cv-meta small{display:block;font:400 6.8pt Plex;color:#9DABA4}
.cv-meta b{font:600 8.6pt/1.5 Plex;color:#fff}
.cv-ph{position:absolute;bottom:26mm;right:0;left:0;display:grid;grid-template-columns:1fr 1fr 1fr;gap:4mm}
.cv-ph img{width:100%;height:40mm;object-fit:cover;border-radius:1.5mm;display:block}
.cv-ft{position:absolute;bottom:9mm;right:0;left:0;border-top:.5pt solid #2E3A34;padding-top:3mm;display:flex;justify-content:space-between;font:400 6.6pt Plex;color:#8C9A93}
.cv-ft b{color:#E6ECE9;font-weight:600}
.dv-num{position:absolute;top:58mm;right:0;font:300 64pt Mont;color:var(--a);line-height:1}
.dv-t{position:absolute;top:100mm;right:0;text-align:right}
.dv-t h1{margin:0;font:700 30pt Plex;color:#fff}
.dv-t .en{font:400 8pt Mont;letter-spacing:4pt;color:#C9D3CE;margin-top:3mm}
.dv-list{position:absolute;top:142mm;right:0;width:100mm}
.dv-list div{display:flex;justify-content:space-between;border-bottom:.5pt solid #2E3A34;padding:2.6mm 0;font:400 8.6pt Plex;color:#E6ECE9}
.dv-list div span{font:400 6.3pt Mont;letter-spacing:.6pt;color:#8C9A93}
.ty h1{position:absolute;top:118mm;right:0;margin:0;font:700 40pt Plex;color:#fff}
.ty .en{position:absolute;top:140mm;right:0;font:300 18pt Mont;color:#DCE5E0}
.ty .tg{position:absolute;top:154mm;right:0;font:500 12pt Plex;color:#__A2__}
.ty .bar{position:absolute;top:168mm;right:0;width:20mm;height:1.3mm;background:var(--a)}
.ty .ct{position:absolute;top:176mm;right:0;text-align:right;font:400 8.4pt/2.1 Plex;color:#DCE5E0}
.ty .ct .w{color:#__A2__}
.sec{break-before:page}
.sec.flow{break-before:auto;margin-top:9mm}
.sh{text-align:right;margin:2mm 0 6mm}
.sh .eyebrow{display:block;margin-bottom:1mm}
.sh h2{margin:0;font:700 19pt/1.35 Plex;color:var(--ink)}
.sh h2 .n{color:var(--a);font:300 21pt Mont;margin-left:2.4mm}
.sh .u{width:16mm;height:1.1mm;background:var(--a);margin:2.5mm 0 0 auto}
.mk{font-size:1.5pt;color:#fff;line-height:0}
h3.h3{font:700 11.5pt Plex;color:var(--p);margin:6mm 0 2.5mm;padding-right:2.6mm;border-right:1.1mm solid var(--a);break-after:avoid}
p{margin:0 0 2.6mm;text-align:justify}
.lead{font-size:10.2pt;line-height:1.85}
ul.dia,ol.num{margin:0 0 3mm;padding:0}
ul.dia li{list-style:none;position:relative;padding-right:5mm;margin-bottom:1.6mm;text-align:justify}
ul.dia li:before{content:"";position:absolute;right:.6mm;top:2.1mm;width:1.8mm;height:1.8mm;background:var(--a);transform:rotate(45deg)}
ol.num{counter-reset:n}
ol.num li{list-style:none;position:relative;padding-right:6mm;margin-bottom:1.6mm;text-align:justify;counter-increment:n}
ol.num li:before{content:counter(n) ".";position:absolute;right:0;font-weight:700;color:var(--p)}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:3mm;margin:4mm 0 5mm}
.kpis.k3{grid-template-columns:repeat(3,1fr)}
.kpi{border:.6pt solid var(--line);border-radius:2mm;padding:3.2mm 3.6mm 2.6mm;text-align:right;background:#fff;break-inside:avoid}
.kpi .v{font:300 19pt/1.1 Mont;color:var(--a);direction:ltr;text-align:right}
.kpi .l{font:700 8pt Plex;color:var(--ink);margin-top:1.2mm}
.kpi .en{font:400 5.6pt Mont;letter-spacing:1.4pt;color:#8A958F;text-transform:uppercase}
.kpi.dk{background:var(--ink);border-color:var(--ink)}.kpi.dk .l{color:#fff}
.kpi.gr{background:var(--a);border-color:var(--a)}.kpi.gr .v,.kpi.gr .l,.kpi.gr .en{color:#fff}
.cards{display:grid;grid-template-columns:1fr 1fr;gap:3mm;margin:3mm 0 4mm}
.cards.c3{grid-template-columns:1fr 1fr 1fr}
.card{border:.6pt solid var(--line);border-radius:2mm;padding:3.4mm 4mm;background:#fff;break-inside:avoid;position:relative}
.card .no{position:absolute;left:4mm;top:3mm;font:300 15pt Mont;color:var(--a)}
.card h4{margin:0 0 1.4mm;font:700 10pt Plex;color:var(--ink);padding-left:10mm}
.card p{margin:0;font-size:8.3pt;color:var(--mut);line-height:1.7;text-align:right}
.card .tag{font:400 5.8pt Mont;letter-spacing:1.5pt;color:var(--a);text-transform:uppercase;margin-bottom:1mm}
.card.dk{background:var(--ink);border-color:var(--ink)}.card.dk h4{color:#fff}.card.dk p{color:#C9D3CE}
.card.gr{background:var(--a);border-color:var(--a)}.card.gr h4,.card.gr p,.card.gr .tag{color:#fff}
table{width:100%;border-collapse:collapse;margin:2mm 0 4mm;font-size:8.2pt;break-inside:auto}
thead{display:table-header-group}
tr{break-inside:avoid}
th{background:var(--ink);color:#fff;font:600 7.8pt Plex;text-align:right;padding:2.2mm 2.4mm}
td{padding:1.9mm 2.4mm;border-bottom:.5pt solid var(--line);vertical-align:top;text-align:right}
tbody tr:nth-child(even) td{background:var(--tint2)}
td.n,th.n{text-align:left;direction:ltr;white-space:nowrap;font-variant-numeric:tabular-nums}
tr.tot td{background:var(--p)!important;color:#fff;font-weight:700;border:0}
tr.sub td{background:var(--tint)!important;color:var(--p);font-weight:700}
tr.div td{background:var(--tint)!important;color:var(--p);font-weight:700}
td.out{color:#C0392B;font-weight:700}
table.kv td:first-child{background:var(--tint)!important;color:var(--p);font-weight:700;width:30%}
table.kv td{background:#fff}
.note{background:var(--tint);border-right:1.1mm solid var(--a);padding:3mm 4mm;border-radius:1mm;font-size:8.3pt;color:#3D4A43;margin:3mm 0 4mm;break-inside:avoid}
.box{border:.6pt solid var(--line);border-radius:2mm;padding:3.6mm 4mm;background:#fff;break-inside:avoid}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:4mm;margin:3mm 0}
.vm{display:grid;grid-template-columns:1fr 1fr;gap:3mm;margin:4mm 0}
.vm>div{border-radius:2mm;padding:4mm}
.vm .v1{background:var(--a);color:#fff}.vm .v2{border:.6pt solid var(--line);background:#fff}
.vm h4{margin:0 0 1.5mm;font:700 11pt Plex}.vm p{margin:0;font-size:8.4pt;line-height:1.75;text-align:right}
.vals{display:grid;grid-template-columns:repeat(5,1fr);gap:2.4mm;margin:3mm 0 5mm}
.vals>div{border-radius:2mm;padding:3mm;font-size:7.6pt;line-height:1.6;break-inside:avoid}
.vals>div:nth-child(odd){background:var(--ink);color:#fff}.vals>div:nth-child(even){background:var(--a);color:#fff}
.vals>div:nth-child(3){background:#fff;border:.6pt solid var(--line);color:var(--txt)}
.vals .en{font:400 5.4pt Mont;letter-spacing:1.2pt;opacity:.85;text-transform:uppercase}
.vals h4{margin:.6mm 0 1mm;font:700 9.6pt Plex}
.esg{display:grid;grid-template-columns:1fr 1fr 1fr;gap:3mm}
.esg>div{border-radius:2mm;padding:3.4mm 4mm;color:#fff;font-size:7.8pt;break-inside:avoid}
.esg>div:nth-child(1){background:var(--p)}.esg>div:nth-child(2){background:var(--a)}.esg>div:nth-child(3){background:var(--ink)}
.esg h4{margin:.5mm 0 1.4mm;font:700 10pt Plex}.esg .en{font:400 5.6pt Mont;letter-spacing:1.4pt;opacity:.85}
.esg ul{margin:0;padding-right:4mm}
.bars .r{display:grid;grid-template-columns:44mm 1fr 14mm;align-items:center;gap:3mm;font-size:7.8pt;margin:1.4mm 0}
.bars .t{height:3.2mm;background:var(--tint);border-radius:1mm;overflow:hidden;direction:rtl}
.bars .t i{display:block;height:100%;background:var(--a);border-radius:1mm}
.bars .r b{font:400 7.4pt Mont;text-align:left;direction:ltr}
.chips{display:flex;flex-wrap:wrap;gap:1.6mm;direction:rtl}
.chips span{border:.6pt solid var(--line);border-radius:5mm;padding:.6mm 3mm;font-size:7.6pt;background:#fff}
.chips span.on{background:var(--a);color:#fff;border-color:var(--a)}
.pcard{display:grid;grid-template-columns:1fr 62mm;border:.6pt solid var(--line);border-radius:2mm;overflow:hidden;margin:0 0 4mm;background:#fff;break-inside:avoid;min-height:56mm}
.pcard .body{padding:3.6mm 4.4mm}
.pcard .ph{position:relative;background:var(--tint)}
.pcard .ph img{width:100%;height:100%;object-fit:cover;display:block;position:absolute;inset:0}
.pcard .ph .no{position:absolute;bottom:0;left:0;background:var(--a);color:#fff;font:300 13pt Mont;padding:2mm 3.4mm}
.pcard h4{margin:.6mm 0 0;font:700 11pt Plex;color:var(--ink)}
.pcard .en{font:400 7pt Mont;color:#8A958F;margin-bottom:2mm;direction:ltr;text-align:right}
.pcard .meta{font-size:7.8pt;border-top:.5pt solid var(--line);border-bottom:.5pt solid var(--line);padding:1.6mm 0;margin-bottom:2mm}
.pcard .meta b{color:var(--a);margin-left:2mm}
.pcard ul.dia{columns:2;column-gap:5mm;font-size:7.8pt;margin:0}
.pcard .rel{display:inline-block;background:var(--tint);color:var(--p);font:600 7pt Plex;padding:.8mm 2.6mm;border-radius:1mm;margin-top:1.6mm}
.eqg{display:grid;grid-template-columns:repeat(4,1fr);gap:2.4mm}
.eqg>div{display:flex;align-items:center;gap:2.4mm;border:.6pt solid var(--line);border-radius:2mm;padding:2.4mm;background:#fff;font-size:7.6pt;line-height:1.4}
.eqg .c{flex:none;width:8.5mm;height:8.5mm;border-radius:50%;background:var(--a);color:#fff;display:flex;align-items:center;justify-content:center;font:600 8pt Mont}
.eqg small{display:block;font:400 5.8pt Mont;color:#8A958F}
.phases{display:grid;grid-template-columns:repeat(6,1fr);gap:2mm;margin:3mm 0 4mm}
.phases>div{border-radius:2mm;padding:2.6mm 2mm;text-align:center;color:#fff;break-inside:avoid}
.phases>div:nth-child(odd){background:var(--a)}.phases>div:nth-child(even){background:var(--ink)}
.phases .nn{font:300 13pt Mont;line-height:1}.phases b{display:block;font:700 8.4pt Plex;margin-top:1mm}
.phases .en{font:400 5pt Mont;letter-spacing:1pt;opacity:.8;text-transform:uppercase}
table.gantt{table-layout:fixed;margin-top:1mm}
table.gantt td{padding:0;height:6.2mm;border-bottom:.5pt solid #fff;border-left:.5pt solid #fff;background:#F0F3F1}
table.gantt td.lb{background:#fff!important;font-size:7.4pt;padding:0 2mm;vertical-align:middle;border-left:0}
table.gantt td.on{background:var(--a)!important}
table.gantt td.cr{background:var(--ink)!important}
table.gantt th{font:600 7pt Mont;text-align:center;padding:1.6mm 0}
.valuebox{background:var(--ink);color:#fff;border-radius:2mm;padding:6mm 7mm;display:flex;justify-content:space-between;align-items:center;margin:2mm 0 4mm;break-inside:avoid}
.valuebox .t b{font:700 11pt Plex;display:block}.valuebox .t small{font-size:7.6pt;color:#B9C6BF}
.valuebox .amt{font:300 27pt Mont;color:var(--a);direction:ltr}.valuebox .amt span{font:400 9pt Mont;color:#B9C6BF;margin-left:2mm}
.words{font-size:8.3pt;padding:2.6mm 2.4mm;border-bottom:.5pt solid var(--line)}
.org{display:flex;flex-direction:column;align-items:center;gap:3mm;margin:2mm 0 5mm}
.org .row{display:flex;gap:2.6mm;justify-content:center;flex-wrap:wrap}
.org .nd{border:.6pt solid var(--line);border-top:.8mm solid var(--a);border-radius:1.6mm;padding:1.6mm 3mm;text-align:center;background:#fff;min-width:33mm;font:600 7.8pt Plex}
.org .nd small{display:block;font:400 5.8pt Plex;color:#8A958F}
.org .nd.dk{background:var(--ink);color:#fff;border-color:var(--ink)}.org .nd.dk small{color:#B9C6BF}
.org .nd.gr{background:var(--a);color:#fff;border-color:var(--a)}.org .nd.gr small{color:#E6F2EA}
.org .base{background:var(--ink);color:#fff;border-radius:1.6mm;padding:2mm 5mm;text-align:center;font:600 7.6pt Plex;width:100%}
.org .base small{display:block;font-weight:400;color:#B9C6BF;font-size:6pt}
.letter-h{display:flex;justify-content:space-between;font-size:8.6pt;margin:2mm 0 6mm}
.letter-h .to b{font-size:10pt}
.letter-h .meta{text-align:left;color:var(--p);direction:rtl}
.subj{background:var(--tint);border-right:1.1mm solid var(--a);padding:3mm 4mm;font-size:8.6pt;margin:4mm 0 5mm}
.sig{width:62%;margin:5mm 0 0 auto}
.sig td{height:9mm}
.decl{background:var(--tint);border-right:1.1mm solid var(--a);padding:3mm 4mm;font-size:8.4pt;margin:4mm 0;break-inside:avoid}
.toc .part{background:var(--ink);color:#fff;border-radius:1.6mm;padding:2.4mm 4mm;display:flex;justify-content:space-between;margin:4mm 0 1mm;font:600 9pt Plex}
.toc .part span{font:400 6.4pt Mont;letter-spacing:1.4pt;color:#B9C6BF}
.toc .it{display:flex;align-items:baseline;gap:3mm;border-bottom:.5pt solid var(--line);padding:2.8mm 0;font-size:9.6pt}
.toc .it .n{color:var(--a);font:400 10pt Mont;width:7mm}
.toc .it .d{flex:1;border-bottom:.8pt dotted #B8C2BC;transform:translateY(-1mm)}
.toc .it .pg{font:600 9pt Mont;direction:ltr}
.toc .lead-it{color:var(--txt)}
.photos3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:3mm;margin:5mm 0 1mm}
.photos3 img{width:100%;height:34mm;object-fit:cover;border-radius:1.6mm;display:block}
.cap{font-size:6.6pt;color:#8A958F;margin-top:1mm}
.ab{display:grid;grid-template-columns:1fr 70mm;gap:5mm;align-items:start}
.ab img{width:100%;height:52mm;object-fit:cover;border-radius:2mm;display:block}
.ach{display:grid;grid-template-columns:1fr 62mm;gap:5mm;align-items:stretch;margin:2mm 0 4mm}
.ach .tot{background:var(--ink);border-radius:2mm;color:#fff;text-align:center;padding:5mm 4mm;display:flex;flex-direction:column;justify-content:center}
.ach .tot .v{font:300 30pt Mont;color:var(--a)}
.ach .rows .r{display:grid;grid-template-columns:1fr 70mm;align-items:center;gap:3mm;margin:1.4mm 0}
.ach .rows .r i{display:block;background:var(--p);color:#fff;border-radius:1mm;padding:1.4mm 3mm;font:400 8pt Mont;font-style:normal;direction:ltr;text-align:left}
.ach .rows .r small{display:block;font:400 5.6pt Mont;letter-spacing:1.2pt;color:var(--a)}
.svc{display:grid;grid-template-columns:repeat(4,1fr);gap:2.4mm}
.svc>div{border:.6pt solid var(--line);border-radius:2mm;padding:3mm;background:#fff;font-size:7.3pt;line-height:1.6;position:relative;break-inside:avoid}
.svc h4{margin:0 0 .4mm;font:700 9pt Plex;padding-left:8mm}.svc .en{font:400 5.2pt Mont;letter-spacing:1pt;color:var(--a);text-transform:uppercase}
.svc .c{position:absolute;left:2.6mm;top:2.6mm;background:var(--p);color:#fff;font:600 7pt Mont;border-radius:1mm;padding:.8mm 1.6mm}
.acts{display:grid;grid-template-columns:repeat(3,1fr);gap:2.4mm;margin-bottom:4mm}
.acts>div{border-radius:2mm;padding:3.2mm;text-align:center;color:#fff;font:700 9pt Plex}
.acts>div:nth-child(odd){background:var(--a)}.acts>div:nth-child(even){background:var(--p)}
.acts small{display:block;font:400 5.6pt Mont;letter-spacing:1.4pt;opacity:.85;margin-top:1mm}
.lc{display:flex;align-items:center;justify-content:center;gap:2mm;margin:4mm 0}
.lc div{width:26mm;height:26mm;border-radius:50%;border:.8pt solid var(--a);display:flex;flex-direction:column;align-items:center;justify-content:center;font:700 9pt Plex}
.lc div.on{background:var(--a);color:#fff}
.lc div small{font:400 5.4pt Mont;letter-spacing:1pt;color:#8A958F}.lc div.on small{color:#E6F2EA}
.lc i{flex:1;max-width:14mm;border-top:.8pt solid var(--a);position:relative}
.logos{border:.6pt solid var(--line);border-radius:2mm;padding:3mm;background:#fff}
.logos img{width:100%;display:block}
.sm{font-size:7.6pt;color:#7A8680}
.compact table{font-size:7pt;line-height:1.45}.compact td{padding:.75mm 2mm}.compact th{padding:1.4mm 2mm}
"""


def _chevrons(color: str) -> str:
    lines = []
    for i in range(9):
        x = -60 + i * 26
        lines.append(f'<polyline points="{x},-40 {x + 250},561 {x},1162" fill="none" stroke="#{color}" stroke-width="13"/>')
    for i in range(3):
        x = 180 + i * 26
        lines.append(f'<polyline points="{x},-40 {x + 110},230" fill="none" stroke="#{color}" stroke-width="13"/>')
    return ('<svg class="chev" viewBox="0 0 446 1123" preserveAspectRatio="xMinYMin slice" '
            f'xmlns="http://www.w3.org/2000/svg">{"".join(lines)}</svg>')


class _Doc:
    def __init__(self, kind, proposal, settings):
        self.kind = kind
        self.p = proposal
        self.s = settings
        self.data = proposal.get("data") or {}
        self.st = self.data.get("structure") or {}
        self.parts: list[str] = []
        self.named: list[str] = []
        self.toc: list[tuple] = []
        self.pages: dict = {}
        self.sec_no = 0

    # --------------------------- أدوات ---------------------------
    def section(self, key, title, en, header_ar, number=True, flow=False, toc=True) -> str:
        name = f"s{len(self.named)}"
        label = (en.upper() + "\\A " + header_ar).replace('"', "'")
        self.named.append(f'@page {name}{{@top-right{{content:"{label}"}}}}')
        num = ""
        if number:
            self.sec_no += 1
            num = str(self.sec_no)
        if toc:
            self.toc.append((num, title, name))
        pg = f" ZQ{name}QZ" if toc else ""
        cls = "sec flow" if flow else "sec"
        return (f'<section class="{cls}" style="page:{name}"><div class="sh"><span class="eyebrow">{_e(en)}</span>'
                f'<h2>{"<span class=n>" + num + "</span>" if num else ""}{_e(title)}</h2><div class="u"></div>'
                f'<span class="mk">{pg}</span></div>')

    def sub(self, en, title, header_ar, flow=True) -> str:
        """قسم فرعي بلا رقم ولا مدخل محتويات (مثل «قيمنا» تحت «عن الشركة»)."""
        name = f"s{len(self.named)}"
        label = (en.upper() + "\\A " + header_ar).replace('"', "'")
        self.named.append(f'@page {name}{{@top-right{{content:"{label}"}}}}')
        cls = "sec flow" if flow else "sec"
        return (f'<section class="{cls}" style="page:{name}"><div class="sh"><span class="eyebrow">{_e(en)}</span>'
                f'<h2>{_e(title)}</h2><div class="u"></div></div>')

    @staticmethod
    def kpis(items, dark_first=False, cls="") -> str:
        out = []
        for i, k in enumerate(items):
            c = k.get("style") or ("dk" if dark_first and i == 0 else "")
            out.append(f'<div class="kpi {c}"><div class="v">{_e(k.get("value"))}</div><div class="l">{_e(k.get("label"))}</div>'
                       f'<div class="en">{_e(k.get("en"))}</div></div>')
        return f'<div class="kpis {cls}">{"".join(out)}</div>' if out else ""

    @staticmethod
    def table(headers, rows, num_cols=(), total=None, widths=None, row_classes=None) -> str:
        num_cols = set(num_cols)
        cols = "".join(f'<col style="width:{w}%">' for w in widths) if widths else ""
        th = "".join(f'<th class="{"n" if i in num_cols else ""}">{_e(h)}</th>' for i, h in enumerate(headers))
        body = []
        for r_i, r in enumerate(rows):
            rc = (row_classes or {}).get(r_i, "")
            if rc in ("div", "sub"):
                body.append(f'<tr class="{rc}"><td colspan="{len(headers)}">{_e(r[0])}</td></tr>'
                            if rc == "div" else
                            '<tr class="sub">' + "".join(
                                f'<td class="{"n" if i in num_cols else ""}">{_e(v)}</td>' for i, v in enumerate(r)) + "</tr>")
                continue
            tds = []
            for i, v in enumerate(r):
                cls = "n" if i in num_cols else ""
                if isinstance(v, tuple):
                    v, extra = v
                    cls += f" {extra}"
                tds.append(f'<td class="{cls}">{_e(v)}</td>')
            body.append("<tr>" + "".join(tds) + "</tr>")
        if total:
            body.append('<tr class="tot">' + "".join(
                f'<td class="{"n" if i in num_cols else ""}">{_e(v)}</td>' for i, v in enumerate(total)) + "</tr>")
        return f'<table><colgroup>{cols}</colgroup><thead><tr>{th}</tr></thead><tbody>{"".join(body)}</tbody></table>'

    @staticmethod
    def bullets(items, numbered=False) -> str:
        if not items:
            return ""
        lis = []
        for it in items:
            if isinstance(it, (list, tuple)):
                lead, text = it
                lis.append(f"<li>{'<b>' + _e(lead) + ':</b> ' if lead else ''}{_e(text)}</li>")
            else:
                lis.append(f"<li>{_e(it)}</li>")
        tag = "ol class=num" if numbered else "ul class=dia"
        return f"<{tag}>{''.join(lis)}</{tag.split()[0]}>"

    def blocks(self, blocks) -> str:
        """كتل proposal_structure (وضع القوالب) بتنسيق الـ PDF."""
        out = []
        for b in blocks:
            t = b["type"]
            if t == "p":
                out.append(f"<p>{_e(b['text'])}</p>")
            elif t == "rich":
                out.append("<p>" + "".join(f"<b>{_e(x)}</b>" if bold else _e(x) for x, bold in b["runs"]) + "</p>")
            elif t == "h3":
                out.append(f'<h3 class="h3">{_e(re.sub(r"^[0-9.]+ ", "", b["text"]))}</h3>')
            elif t == "bullets":
                out.append(self.bullets(b["items"]))
            elif t == "numbered":
                out.append(self.bullets(b["items"], numbered=True))
            elif t == "kv":
                out.append('<table class="kv"><tbody>' + "".join(
                    f"<tr><td>{_e(k)}</td><td>{_e(v)}</td></tr>" for k, v in b["rows"]) + "</tbody></table>")
            elif t == "table":
                n = len(b["headers"])
                w = b.get("widths")
                widths = [round(x / sum(w) * 100, 1) for x in w] if w and len(w) == n else None
                out.append(self.table(b["headers"], b["rows"], b.get("num_cols") or (), b.get("total"), widths))
            elif t == "note":
                out.append(f'<div class="note">{_e(b["text"])}</div>')
            elif t == "gantt":
                out.append(self.gantt([{"task": x[0], "start_month": x[1], "end_month": x[2]} for x in b["bars"]],
                                      int(b["months"])))
            elif t == "valuebox":
                out.append(f'<div class="valuebox"><div class="t"><b>{_e(b["label"])}</b><small>{_e(b["sub"])}</small></div>'
                           f'<div class="amt">{_e(b["amount"])}<span>SAR</span></div></div>')
            elif t == "declaration":
                out.append(f'<div class="decl"><b>الإقرار:</b> {_e(b["text"])}</div>')
                out.append('<table class="kv sig"><tbody>' + "".join(
                    f"<tr><td>{_e(k)}</td><td>{_e(v)}</td></tr>" for k, v in b["rows"]) + "</tbody></table>")
        return "".join(out)

    def gantt(self, bars, months) -> str:
        months = max(1, int(months or 1))
        if months > 24:
            group = -(-months // 24)
        else:
            group = 1
        cols = -(-months // group)
        head = "".join(f"<th>{i * group + 1 if group == 1 else f'{i * group + 1}–{min(months, (i + 1) * group)}'}</th>"
                       for i in range(cols))
        rows = []
        for b in bars:
            try:
                s0, e0 = float(b.get("start_month") or 0), float(b.get("end_month") or 0)
            except (TypeError, ValueError):
                continue
            cells = []
            for c in range(cols):
                c0, c1 = c * group, (c + 1) * group
                on = min(e0, c1) - max(s0, c0) > group * 0.3
                cells.append(f'<td class="{("cr" if b.get("critical") else "on") if on else ""}"></td>')
            rows.append(f'<tr><td class="lb">{_e(b.get("task"))}</td>{"".join(cells)}</tr>')
        lw = 44 if cols <= 12 else 34
        cw = round((100 - lw) / cols, 2)
        colg = f'<col style="width:{lw}%">' + "".join(f'<col style="width:{cw}%">' for _ in range(cols))
        return (f'<table class="gantt"><colgroup>{colg}</colgroup><thead><tr><th style="text-align:right;padding-right:2mm">'
                f'النشاط / الشهر</th>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table>')

    @staticmethod
    def scurve(values) -> str:
        vals = [max(0.0, min(100.0, float(v))) for v in values if v is not None]
        if len(vals) < 2:
            return ""
        w, h, pad = 300, 130, 18
        n = len(vals)
        pts = [(pad + i * (w - 2 * pad) / n, h - pad - v / 100 * (h - 2 * pad)) for i, v in enumerate([0.0] + vals)]
        poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        grid = "".join(f'<line x1="{pad}" x2="{w - pad}" y1="{h - pad - g / 100 * (h - 2 * pad):.1f}" y2="{h - pad - g / 100 * (h - 2 * pad):.1f}" stroke="#E2E7E4" stroke-width=".6"/>'
                       f'<text x="{pad - 3}" y="{h - pad - g / 100 * (h - 2 * pad) + 2:.1f}" font-size="5" fill="#9AA59F" text-anchor="end">{g}%</text>'
                       for g in (25, 50, 75, 100))
        dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="1.6" fill="#121A16"/>' for x, y in pts)
        labels = "".join(f'<text x="{x:.1f}" y="{h - 6}" font-size="5" fill="#9AA59F" text-anchor="middle">{i}</text>'
                         for i, (x, _) in enumerate(pts) if i)
        return (f'<svg viewBox="0 0 {w} {h}" style="width:100%;direction:ltr" xmlns="http://www.w3.org/2000/svg">{grid}'
                f'<polyline points="{poly}" fill="none" stroke="var(--a)" stroke-width="1.6"/>{dots}{labels}</svg>')

    # --------------------------- الصفحات الكاملة ---------------------------
    def cover(self, en, ar, photos):
        st, s = self.st, self.s
        info = dict(self.view["cover"]["info"])
        title = st.get("scope_title") or self.view["cover"]["title"]
        sub = st.get("subtitle") or self.view["cover"]["subtitle"]
        loc = st.get("location") or ""
        meta = [("مقدّم إلى", st.get("addressee") or info.get("مقدّم إلى", "")),
                ("المالك / المطوّر", st.get("owner") or ""),
                ("رقم المرجع", self.p.get("ref_no", "")),
                ("تاريخ التقديم", info.get("تاريخ التقديم", "")),
                ("نوع العقد", st.get("contract_type") or ("مبلغ مقطوع ثابت (Lump Sum)" if self.pv["lump"]
                                                          else "إعادة قياس وفق جدول الكميات")),
                ("مدة التنفيذ", self.duration)]
        meta_html = "".join(f"<div><small>{_e(k)}</small><b>{_e(v)}</b></div>" for k, v in meta if v)
        ph = "".join(f'<img src="{u}">' for u in photos[:3])
        logo = f'<img class="bl-logo" src="{self.logo_dark}">' if self.logo_dark else \
            f'<div class="bl-logo" style="font:700 16pt Plex">{_e(s.get("company_name"))}</div>'
        foot_l = " · ".join(x for x in (s.get("company_website"), s.get("company_phone")) if x)
        foot_r = f'<b>{_e(s.get("company_name"))}</b>' + "".join(
            f" · {_e(x)}" for x in (s.get("company_classification"), s.get("company_tagline_ar") or "") if x)
        self.parts.append(
            f'<div class="bleed">{_chevrons(self.accent)}<div class="bl-in">{logo}'
            f'<div class="cv-ey"><span class="eyebrow">{_e(en)}</span><span class="ar">{_e(ar)}</span></div>'
            f'<div class="cv-title"><h1>{_e(title)}{"<br><span class=g>" + _e(sub) + "</span>" if sub else ""}</h1>'
            f'{"<div class=loc>" + _e(loc) + "</div>" if loc else ""}<div class="bar"></div></div>'
            f'<div class="cv-meta">{meta_html}</div>'
            f'{"<div class=cv-ph>" + ph + "</div>" if ph else ""}'
            f'<div class="cv-ft"><span>{_e(foot_l)}</span><span>{foot_r}</span></div></div></div>')

    def divider(self, num, ar, en, items):
        lst = "".join(f"<div>{_e(a)}<span>{_e(b)}</span></div>" for a, b in items)
        logo = f'<img class="bl-logo" src="{self.logo_dark}">' if self.logo_dark else ""
        self.parts.append(f'<div class="bleed">{_chevrons(self.accent)}<div class="bl-in">{logo}'
                          f'<div class="dv-num">{_e(num)}</div><div class="dv-t"><h1>{_e(ar)}</h1>'
                          f'<div class="en">{_e(en)}</div></div><div class="dv-list">{lst}</div></div></div>')

    def thanks(self):
        s = self.s
        logo = f'<img class="bl-logo" style="top:88mm;height:15mm" src="{self.logo_dark}">' if self.logo_dark else ""
        lines = [x for x in (s.get("company_address_short") or "", s.get("company_phone"), s.get("company_email")) if x]
        site = s.get("company_website", "")
        ct = "<br>".join(_e(x) for x in lines) + (f'<br><span class="w">{_e(site)}</span>' if site else "") + (
            f'<br><span style="font-size:7pt;color:#9DABA4">{_e(s.get("company_address"))}</span>' if s.get("company_address") else "")
        tag = s.get("company_tagline_ar") or s.get("company_tagline") or ""
        self.parts.append(f'<div class="bleed ty">{_chevrons(self.accent)}<div class="bl-in">{logo}<h1>شكراً لكم</h1>'
                          f'<div class="en">Thank you</div><div class="tg">{_e(tag)}</div><div class="bar"></div>'
                          f'<div class="ct">{ct}</div></div></div>')

    def letter(self):
        st, s, p = self.st, self.s, self.p
        L = self.view["letter"]
        created = _parse_date(p.get("created_at"))
        city = "الرياض في" if "الرياض" in (s.get("company_address") or "") else "التاريخ"
        to = (f'<div class="to"><b>السادة / {_e(p.get("client"))}</b><br>المحترمين'
              f'{"<br><span class=sm>عناية: " + _e(st["attention"]) + "</span>" if st.get("attention") else ""}</div>')
        meta = (f'<div class="meta">{city}: {created.day} / {created.month} / {created.year}م<br>'
                f'المرجع: {_e(p.get("ref_no"))}'
                f'{"<br>إشارة: " + _e(st["request_ref"]) if st.get("request_ref") else ""}</div>')
        subj = L["subject"].replace("الموضوع: ", "")
        paras = list(st.get("letter_paragraphs") or [])
        if paras and re.match(r"\s*الموضوع\s*[:：]", paras[0]):
            subj = re.sub(r"^\s*الموضوع\s*[:：]\s*", "", paras.pop(0))
        paras = [x for x in paras if not re.match(r"\s*(السلام عليكم|وتفضلوا)", x)]
        if paras:
            body = "".join(f"<p class=lead>{_e(x)}</p>" for x in paras)
        else:
            body = "".join("<p class=lead>" + "".join(f"<b>{_e(x)}</b>" if b else _e(x) for x, b in runs) + "</p>"
                           for runs in L["paragraphs"][:-1])
        kp = st.get("letter_kpis") or [
            {"value": str(self.months or "—"), "label": "أشهر مدة التنفيذ" if self.months else "مدة التنفيذ", "en": "MONTHS"},
            {"value": money(self.pv["subtotal"]) if self.pv["subtotal"] else "—", "label": "ريال قيمة العرض قبل الضريبة", "en": "VALUE"},
            {"value": str(len([l for l in self.data.get("boq") or [] if not l.get("extra")])), "label": "بند في جدول الكميات", "en": "BOQ ITEMS"},
            {"value": str(int(float(s.get("validity_days") or 90))), "label": "يوماً سريان العرض", "en": "VALIDITY"}]
        sig = [("عن الشركة", s.get("company_name", "")), ("المنصب", s.get("signer_title") or "المدير العام"),
               ("التوقيع", ""), ("الختم", "")]
        self.parts.append(
            self.sub("COVER LETTER", "", "خطاب التقديم", flow=False).replace('<div class="sh"><span class="eyebrow">COVER LETTER</span><h2></h2><div class="u"></div></div>', "")
            + f'<div class="letter-h">{to}{meta}</div><p>السلام عليكم ورحمة الله وبركاته،</p>'
              f'<div class="subj"><b>الموضوع:</b> {_e(subj)}</div>{body}{self.kpis(kp)}'
              f'<p>وتفضلوا بقبول فائق الاحترام والتقدير،</p><table class="kv sig"><tbody>'
            + "".join(f"<tr><td>{_e(k)}</td><td>{_e(v)}</td></tr>" for k, v in sig) + "</tbody></table></section>")

    def contents(self, part_label, part_en, lead=None):
        rows = []
        if lead:
            rows.append(f'<div class="it lead-it"><span class="n">—</span>{_e(lead[0])}<span class="d"></span>'
                        f'<span class="pg">__PG_{lead[1]}__</span></div>')
        rows.append(f'<div class="part">{_e(part_label)}<span>{_e(part_en)}</span></div>')
        for num, title, name in self.toc:
            if lead and name == lead[1]:
                continue
            rows.append(f'<div class="it"><span class="n">{_e(num)}</span>{_e(title)}<span class="d"></span>'
                        f'<span class="pg">__PG_{name}__</span></div>')
        ph = "".join(f'<img src="{u}">' for u in self.photos[3:6] or self.photos[:3])
        return (self.sub("CONTENTS", "المحتويات", "المحتويات", flow=False) + f'<div class="toc">{"".join(rows)}</div>'
                + (f'<div class="photos3">{ph}</div>' if ph else "") + "</section>")


def _profile(settings: dict) -> dict:
    try:
        from .company_profile import get_profile
        return get_profile(settings.get("_company_id"))
    except Exception:
        return {}


def _media(settings: dict) -> list[dict]:
    try:
        from .company_profile import list_media
        return list_media(settings.get("_company_id"))
    except Exception:
        return []


def _prepare(kind, proposal, settings) -> _Doc:
    d = _Doc(kind, proposal, settings)
    d.view = build_structure(proposal, settings)
    d.pv = pricing_view(d.data, settings)
    d.weeks, d.months, d.duration = duration_view(d.data)
    d.prof = _profile(settings)
    d.media = _media(settings)
    d.photos = [m["uri"] for m in d.media if m.get("kind") in ("hero", "project", "site") and m.get("uri")]
    d.logo_light, d.logo_dark, d.logo_ratio = _logo_uris(settings)
    from .export_docx import _resolve_brand
    d.primary, d.accent = _resolve_brand(settings)
    d.blocks_by_key = {x["key"]: x["blocks"] for x in d.view["sections"]}
    return d


def _css(d: _Doc, header_name: str) -> str:
    s = d.s
    foot = f'{s.get("company_name", "")} · {header_name} · {d.st.get("subtitle") or d.p.get("title", "")}'
    css = (CSS.replace("__P__", d.primary).replace("__A__", d.accent).replace("__INK__", INK)
           .replace("__T__", _mix(d.accent, .88)).replace("__T2__", _mix(d.accent, .95))
           .replace("__A2__", _mix(d.accent, .25))
           .replace("__REF__", (d.p.get("ref_no") or "").replace('"', ""))
           .replace("__FOOT__", foot.replace('"', "'")[:120])
           .replace("__TR__", "")
           .replace("__LOGO__", f'url("{_svg_logo(d.logo_light, d.logo_ratio, 38)}")' if d.logo_light else
                    f'"{(s.get("company_name") or "").replace(chr(34), "")}"')
           .replace("__NAMED__", "\n".join(d.named)))
    return css


def _wrap(d: _Doc, title: str, header_name: str) -> str:
    return (f'<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>{_e(title)}</title>'
            f"<style>{_font_faces()}\n{_css(d, header_name)}</style></head><body>{''.join(d.parts)}</body></html>")


# =============================== العرض الفني ===============================

def _technical(d: _Doc):
    st, s, prof = d.st, d.s, d.prof
    company = s.get("company_name", "")
    short = prof.get("name_ar") or company
    d.cover("TECHNICAL PROPOSAL", "العرض الفني", d.photos)
    d.letter()
    body = []

    # ----- الملخص التنفيذي
    exec_sum = st.get("exec_summary") or (
        f"تتقدم {company} بعرض متكامل لتنفيذ {d.view['cover']['title']} لصالح {d.p.get('client', '')}، "
        f"خلال {d.duration}، وفق وثائق المشروع وجدول الكميات المرفق، والقيمة في العرض المالي المرفق.")
    kp = st.get("kpis") or []
    if not kp:
        n_items = len([l for l in d.data.get("boq") or [] if not l.get("extra")])
        team_n = sum(int(float(t.get("count") or 0)) for t in d.data.get("team") or []) or ""
        kp = [x for x in (
            {"value": str(d.months), "label": "أشهر متصلة", "en": "DURATION", "style": "gr"} if d.months else None,
            {"value": str(n_items), "label": "بنداً في جدول الكميات", "en": "BOQ ITEMS"} if n_items else None,
            {"value": str(team_n), "label": "من الكوادر الأساسية", "en": "KEY STAFF"} if team_n else None,
            {"value": _short(prof.get("classification")), "label": "التصنيف", "en": "CLASSIFICATION"}
            if prof.get("classification") else None) if x]
    why = st.get("why_us") or _why_fallback(d)
    pillars = st.get("pillars") or []
    x = d.section("exec", "الملخص التنفيذي", "EXECUTIVE SUMMARY", "الملخص التنفيذي", number=False)
    x += f"<p class=lead>{_e(exec_sum)}</p>{d.kpis(kp, dark_first=bool(st.get('kpis')))}"
    if why:
        x += f'<h3 class="h3">لماذا {_e(short.split()[0] if short else "نحن")} لهذا المشروع</h3><div class="cards">' + "".join(
            f'<div class="card"><span class="no">{i:02d}</span><h4>{_e(w.get("title"))}</h4><p>{_e(w.get("text"))}</p></div>'
            for i, w in enumerate(why, 1)) + "</div>"
    if pillars:
        x += '<h3 class="h3">محاور الحل المقترح</h3><div class="cards c3">' + "".join(
            f'<div class="card"><div class="tag">{_e(pl.get("tag"))}</div><h4 style="padding:0">{_e(pl.get("title"))}</h4>'
            f'<p>{_e(pl.get("text"))}</p></div>' for pl in pillars) + "</div>"
    ph = (d.photos[6:9] or d.photos[:3]) if not (why and pillars) else []
    if ph:
        x += '<div class="photos3">' + "".join(f'<img src="{u}">' for u in ph) + "</div>"
    body.append(x + "</section>")
    exec_name = d.toc[-1][2]

    # ----- 1 عن الشركة
    x = d.section("about", f"عن {short}", "ABOUT " + (s.get("company_name_en") or prof.get("name_en") or "US").split()[0].upper(),
                  "عن الشركة")
    about = [a for a in prof.get("about") or [] if len(re.findall(r"[\u0600-\u06FF]", a)) > len(a) * .3] or [
        p for p in (s.get("company_intro"),) if p]
    hero = next((m["uri"] for m in d.media if m.get("kind") == "team"), "") or (d.photos[0] if d.photos else "")
    paras = "".join(f"<p class=lead>{_e(a)}</p>" for a in about)
    x += f'<div class="ab"><div>{paras}</div>{"<img src=" + chr(34) + hero + chr(34) + ">" if hero else ""}</div>' if hero else paras
    stats = [k for k in (
        {"value": _short(prof.get("founded")), "label": "سنة التأسيس", "en": "ESTABLISHED", "style": "gr"},
        {"value": _short(prof.get("staff")), "label": "موظفاً ومهندساً", "en": "STAFF & ENGINEERS", "style": "dk"},
        {"value": _short(prof.get("cities")), "label": "مدينة ومحافظة", "en": "CITIES WITH PROJECTS", "style": "dk"},
        {"value": _short(prof.get("classification")), "label": "مصنّفة بالدرجة الأولى" if "1" in _short(
            prof.get("classification")) else "التصنيف", "en": "CLASSIFICATION", "style": "gr"}) if k["value"]]
    x += d.kpis(stats)
    if prof.get("vision") or prof.get("mission"):
        x += (f'<div class="vm"><div class="v1"><div class="eyebrow" style="color:#E6F2EA">VISION</div><h4>رؤيتنا</h4>'
              f'<p>{_e(prof.get("vision"))}</p></div><div class="v2"><div class="eyebrow">MISSION</div><h4>رسالتنا</h4>'
              f'<p>{_e(prof.get("mission"))}</p></div></div>')
    if not prof:
        facts = [(k, v) for k, v in (("السجل التجاري", s.get("company_cr")), ("التصنيف", s.get("company_classification")),
                                     ("مجالات العمل", s.get("company_services")),
                                     ("المجموعة الداعمة", s.get("company_support_group"))) if v]
        if facts:
            x += '<table class="kv"><tbody>' + "".join(f"<tr><td>{_e(k)}</td><td>{_e(v)}</td></tr>" for k, v in facts) + "</tbody></table>"
    body.append(x + "</section>")
    if prof.get("values") or prof.get("strategy") or prof.get("esg"):
        x = d.sub("OUR VALUES · STRATEGY · ESG", "قيمنا واستراتيجيتنا", "عن الشركة", flow=False)
        if prof.get("values"):
            x += '<div class="vals">' + "".join(
                f'<div><div class="en">{i:02d} · {_e(v.get("en"))}</div><h4>{_e(v.get("title"))}</h4>{_e(v.get("text"))}</div>'
                for i, v in enumerate(prof["values"][:5], 1)) + "</div>"
        if prof.get("strategy"):
            x += '<h3 class="h3">استراتيجية النمو</h3>' + d.table(["المحور", "التوجه"], [[r.get("axis"), r.get("direction")]
                                                                                    for r in prof["strategy"]], widths=[30, 70])
        esg = prof.get("esg") or {}
        if any(esg.values()):
            x += '<h3 class="h3">الاستدامة (ESG)</h3><div class="esg">' + "".join(
                f'<div><div class="en">{en}</div><h4>{ar}</h4><ul>{"".join("<li>" + _e(i) + "</li>" for i in esg.get(k) or [])}</ul></div>'
                for k, ar, en in (("environmental", "الاستراتيجية البيئية", "E · ENVIRONMENTAL"),
                                  ("social", "الاستراتيجية الاجتماعية", "S · SOCIAL"),
                                  ("governance", "استراتيجية الحوكمة", "G · GOVERNANCE"))) + "</div>"
        body.append(x + "</section>")
    ach = prof.get("achievements") or {}
    if ach.get("items") or prof.get("services") or prof.get("activities"):
        x = d.sub("OUR ACHIEVEMENTS", "إنجازاتنا بالأرقام", "عن الشركة", flow=False)
        if ach.get("items"):
            rows = "".join(f'<div class="r"><div><b>{_e(i.get("label"))}</b><small>{_e(i.get("en"))}</small></div>'
                           f'<i style="width:{max(30, 100 - n * 18)}%">{_e(i.get("value"))}</i></div>'
                           for n, i in enumerate(ach["items"][:5]))
            x += (f'<div class="ach"><div class="rows">{rows}</div><div class="tot"><div class="eyebrow" style="color:#B9C6BF">'
                  f'TOTAL m² DELIVERED</div><div class="v">{_e(ach.get("total_m2"))}</div><div>{_e(ach.get("total_label"))}</div>'
                  f'{"<div class=sm style=color:#B9C6BF;margin-top:2mm>" + _e(ach.get("note")) + "</div>" if ach.get("note") else ""}</div></div>')
        if prof.get("activities"):
            x += '<h3 class="h3">الأنشطة الرئيسية ومجال الأعمال</h3><div class="acts">' + "".join(
                f'<div>{_e(a.get("title"))}<small>{_e(a.get("en"))}</small></div>' for a in prof["activities"][:6]) + "</div>"
        if prof.get("services"):
            x += '<h3 class="h3">خدماتنا</h3><div class="svc">' + "".join(
                f'<div><span class="c">{i:02d}</span><h4>{_e(v.get("title"))}</h4><div class="en">{_e(v.get("en"))}</div>{_e(v.get("text"))}</div>'
                for i, v in enumerate(prof["services"][:8], 1)) + "</div>"
        body.append(x + "</section>")

    # ----- 2 الخبرات
    projects = [pr for pr in prof.get("projects") or [] if not re.match(r"\s*H\d{2}", pr.get("relevance") or "")]
    refs_rows = ([[f"{i:02d}", pr.get("name"), pr.get("client"), pr.get("location"), pr.get("sector")]
                  for i, pr in enumerate(projects, 1)] if projects else
                 [[f"{i:02d}", *r] for i, r in enumerate(_settings_refs(s), 1)])
    if projects or refs_rows:
        pf = prof.get("portfolio") or {}
        x = d.section("exp", "الخبرات والمشاريع السابقة", "PORTFOLIO AT A GLANCE", "الخبرات")
        x += d.kpis([k for k in ({"value": _short(pf.get("projects")) or (str(len(projects)) if projects else ""), "label": "مشروعاً منفذاً", "en": "PROJECTS"},
                                 {"value": _short(pf.get("sectors")), "label": "قطاعات", "en": "SECTORS"},
                                 {"value": _short(pf.get("building_m2")), "label": "م² أعمال بناء", "en": "BUILDING WORKS"},
                                 {"value": _short(pf.get("cities")), "label": "مدينة ومحافظة", "en": "CITIES"}) if k["value"]])
        sc = pf.get("sector_counts") or []
        cities = pf.get("cities_list") or []
        if sc or cities:
            mx = max([int(c.get("count") or 0) for c in sc] or [1])
            bars = "".join(f'<div class="r"><span>{_e(c.get("sector"))}</span><div class="t"><i style="width:{int(c.get("count") or 0) / mx * 100:.0f}%"></i></div>'
                           f'<b>{_e(c.get("count"))}</b></div>' for c in sc)
            chips = "".join(f'<span class="{"on" if i < 3 else ""}">{_e(c)}</span>' for i, c in enumerate(cities))
            x += (f'<div class="grid2"><div><h3 class="h3">التوزيع حسب القطاع</h3><div class="bars">{bars}</div></div>'
                  f'<div><h3 class="h3">مواقع المشاريع</h3><div class="chips">{chips}</div>'
                  f'{"<div class=note>" + _e(pf.get("note")) + "</div>" if pf.get("note") else ""}</div></div>')
        site_ph = [m for m in d.media if m.get("kind") in ("site", "team")][:3]
        if site_ph:
            x += '<h3 class="h3">صور من مواقعنا</h3><div class="photos3">' + "".join(
                f'<div><img src="{m["uri"]}"><div class="cap">{_e(m.get("caption"))}</div></div>' for m in site_ph) + "</div>"
        body.append(x + "</section>")
        featured = _relevant_projects(d, projects)
        if featured:
            x = d.sub("RELEVANT EXPERIENCE", "مشاريع مماثلة", "الخبرات", flow=False)
            for pr in featured:
                ph = pr.get("_uri", "")
                meta = "".join(f"<div><b>{lab}</b>{_e(pr.get(k))}</div>" for k, lab in (("location", "الموقع"), ("client", "العميل"),
                                                                                       ("owner", "المالك"), ("type", "النوع")) if pr.get(k))
                x += (f'<div class="pcard"><div class="body"><div class="eyebrow">{_e(pr.get("sector"))}</div><h4>{_e(pr.get("name"))}</h4>'
                      f'<div class="en">{_e(pr.get("name_en"))}</div><div class="meta">{meta}</div>{d.bullets((pr.get("scope") or [])[:6])}'
                      f'{"<span class=rel>صلة بالمشروع: " + _e(pr.get("relevance")) + "</span>" if pr.get("relevance") else ""}</div>'
                      f'<div class="ph">{"<img src=" + chr(34) + ph + chr(34) + ">" if ph else ""}<span class="no">{int(pr.get("id") or 0):02d}</span></div></div>')
            body.append(x + "</section>")
        x = d.sub("PROJECT REFERENCES", "سجل المشاريع المنفذة", "الخبرات", flow=False)
        x += '<div class="compact">' + d.table(["#", "المشروع", "العميل / الجهة", "الموقع", "القطاع"], refs_rows,
                                               widths=[5, 37, 27, 16, 15]) + "</div>"
        body.append(x + "</section>")
        if prof.get("clients") or (prof.get("equipment") or {}).get("categories"):
            x = d.sub("CLIENTS & PARTNERS", "عملاؤنا وشركاؤنا", "الخبرات", flow=False)
            logos = next((m["uri"] for m in d.media if m.get("kind") == "logos"), "")
            if prof.get("clients"):
                x += (f'<div class="grid2"><div><p>جهات حكومية وشركات كبرى ومقاولون رئيسيون عملنا معهم.</p>{d.bullets(prof["clients"][:12])}</div>'
                      f'{"<div class=logos><img src=" + chr(34) + logos + chr(34) + "></div>" if logos else "<div></div>"}</div>')
            eq = prof.get("equipment") or {}
            if eq.get("categories"):
                x += (f'<h3 class="h3">معداتنا — أسطول مملوك ({_e(eq.get("total"))} معدة)</h3>'
                      f'{"<p>" + _e(eq.get("note")) + "</p>" if eq.get("note") else ""}<div class="eqg">' + "".join(
                          f'<div><span class="c">{_e(c.get("count"))}</span><div>{_e(c.get("name"))}<small>{_e(c.get("en"))}</small></div></div>'
                          for c in eq["categories"]) + "</div>")
            body.append(x + "</section>")

    # ----- 3 فهم المشروع
    if st.get("documents_studied") or st.get("parties_rows") or st.get("tech_notes"):
        x = d.section("und", "فهم المشروع ودراسة المستندات", "PROJECT UNDERSTANDING", "العرض الفني")
        x += f"<p class=lead>{_e(st.get('documents_studied'))}</p>{d.kpis(st.get('project_facts') or [])}"
        if st.get("parties_rows"):
            x += d.table(["البيان", "التفاصيل"], [[r.get("label"), r.get("value")] for r in st["parties_rows"]], widths=[22, 78])
        if st.get("tech_notes"):
            x += '<h3 class="h3">ملاحظات فنية مؤثرة على التنفيذ والتسعير</h3><div class="cards">' + "".join(
                f'<div class="card"><h4 style="padding:0">{_e(n.get("title"))}</h4><p>{_e(n.get("text"))}</p></div>'
                for n in st["tech_notes"]) + "</div>"
        body.append(x + "</section>")

    # ----- 4 النطاق
    x = d.section("scope", "نطاق الأعمال المشمول" + (" بالمبلغ المقطوع" if d.pv["lump"] else ""), "SCOPE OF WORKS", "نطاق الأعمال")
    if st.get("scope_rows"):
        x += f"<p class=lead>{_e(st.get('scope_intro'))}</p>" + d.table(
            ["#", "البند", "ما يشمله العرض"], [[str(i), r.get("item"), r.get("text")] for i, r in enumerate(st["scope_rows"], 1)],
            widths=[5, 17, 78])
        if st.get("excluded"):
            x += '<h3 class="h3">خارج النطاق</h3>' + d.bullets(st["excluded"])
    else:
        x += d.blocks(d.blocks_by_key.get("scope", []))
    body.append(x + "</section>")

    # ----- 5 المنهجية
    x = d.section("method", "منهجية التنفيذ", "METHOD STATEMENT", "منهجية التنفيذ")
    if st.get("method_phases"):
        x += '<div class="phases">' + "".join(
            f'<div><div class="nn">{i:02d}</div><b>{_e(ph.get("title"))}</b><div class="en">{_e(ph.get("en"))}</div></div>'
            for i, ph in enumerate(st["method_phases"][:6], 1)) + "</div>"
    if st.get("method_sections"):
        if st.get("method_intro"):
            x += f"<p class=lead>{_e(st['method_intro'])}</p>"
        for ms in st["method_sections"]:
            x += f'<h3 class="h3">{_e(ms.get("title"))}</h3>' + "".join(f"<p>{_e(t)}</p>" for t in ms.get("paragraphs") or [])
            x += d.bullets(ms.get("steps") or [])
        if st.get("cycle_rows"):
            x += f'<h3 class="h3">{_e(st.get("cycle_title") or "الدورة النموذجية")}</h3>' + d.table(
                ["اليوم", "النشاط"], [[r.get("label"), r.get("activity")] for r in st["cycle_rows"]], widths=[12, 88])
    else:
        x += d.blocks(d.blocks_by_key.get("method", []))
    body.append(x + "</section>")

    # ----- 6 البرنامج الزمني
    x = d.section("sched", "البرنامج الزمني المبدئي" + (f" — {d.duration.split(' ميلادية')[0]}" if d.months else ""),
                  "PROJECT SCHEDULE", "البرنامج الزمني")
    bars = st.get("schedule_bars") or [{"task": b[0], "start_month": b[1], "end_month": b[2]}
                                       for blk in d.blocks_by_key.get("schedule", []) if blk["type"] == "gantt"
                                       for b in blk["bars"]]
    x += f"<p class=lead>{_e(st.get('schedule_intro') or next((b['text'] for b in d.blocks_by_key.get('schedule', []) if b['type'] == 'p'), ''))}</p>"
    if bars:
        x += d.gantt(bars + [{"task": "التسليم", "start_month": max(0, (d.months or 1) - 0.9), "end_month": d.months or 1,
                              "critical": True}], d.months or 1)
    curve = st.get("s_curve") or _s_curve(bars, d.months)
    ms = st.get("milestones") or []
    if ms or curve:
        x += (f'<div class="grid2"><div><h3 class="h3">معدل الإنجاز والمعالم</h3>'
              f'{d.table(["المعلم / المعدل", "القيمة"], [[m.get("label"), m.get("value")] for m in ms], widths=[62, 38]) if ms else ""}</div>'
              f'<div><h3 class="h3">منحنى الإنجاز التراكمي المخطط (S-Curve)</h3>{d.scurve(curve)}</div></div>')
    note = st.get("schedule_note") or next((b["text"] for b in d.blocks_by_key.get("schedule", [])[1:] if b["type"] == "p"), "")
    if note:
        x += f'<div class="note">{_e(note)}</div>'
    body.append(x + "</section>")

    # ----- 7 التنظيم والفريق والموارد
    x = d.section("team", "الهيكل التنظيمي والفريق الفني المتفرغ", "ORGANISATION & RESOURCES", "الفريق")
    org = st.get("org_chart") or {}
    staff = st.get("staff") or [{"role": t.get("role"), "count": qty_fmt(t.get("count") or 1), "note": ""}
                                for t in d.data.get("team") or []]
    if org or staff:
        x += _org_html(org, staff, company, d.p.get("client", ""))
    if staff:
        x += d.table(["الوظيفة (الحد الأدنى المطلوب)", "العدد", "ملاحظات"],
                     [[r.get("role"), r.get("count"), r.get("note")] for r in staff], widths=[40, 18, 42])
    for k in ("staff_note", "labor_note"):
        if st.get(k):
            x += f"<p>{_e(st[k])}</p>"
    if st.get("equipment"):
        x += '<h3 class="h3">المعدات المخصصة للمشروع (مملوكة أو مستأجرة)</h3>' + d.table(
            ["المعدة", "العدد", "المصدر"], [[r.get("item"), r.get("count"), r.get("ownership")] for r in st["equipment"]],
            widths=[46, 14, 40])
    if st.get("suppliers"):
        x += '<h3 class="h3">الموردون ومقاولو الباطن المقترحون (يُعتمدون من المالك والاستشاري)</h3>' + d.table(
            ["البند", "المقترح (أو ما يعادله)"], [[r.get("item"), r.get("proposal")] for r in st["suppliers"]], widths=[22, 78])
    body.append(x + "</section>")

    # ----- 8 الجودة والسلامة والمخاطر
    x = d.section("qhse", "الجودة والسلامة وإدارة المخاطر", "QUALITY · HSE · RISK", "الجودة والسلامة")
    qb = d.blocks_by_key.get("qhse", [])
    quality = st.get("quality") or next((b["items"] for b in qb if b["type"] == "bullets"), [])
    safety = st.get("safety") or ([b["items"] for b in qb if b["type"] == "bullets"][1:2] or [[]])[0]
    x += (f'<div class="grid2"><div class="box"><div class="eyebrow">QUALITY</div><h3 class="h3" style="border:0;padding:0;margin-top:1mm">ضبط الجودة</h3>{d.bullets(quality)}</div>'
          f'<div class="box"><div class="eyebrow">HEALTH & SAFETY</div><h3 class="h3" style="border:0;padding:0;margin-top:1mm">السلامة في الموقع</h3>{d.bullets(safety)}</div></div>')
    risks = st.get("risks") or _risk_fallback(d)
    if risks:
        x += '<h3 class="h3">إدارة المخاطر</h3>' + d.table(["الخطر", "الأثر", "إجراء المعالجة"],
                                                         [[r.get("risk"), r.get("impact"), r.get("mitigation")] for r in risks],
                                                         widths=[30, 10, 60])
    body.append(x + "</section>")

    # المحتويات بعد الخطاب
    part_items = [(t, "") for _, t, _n in d.toc if _n != exec_name]
    d.parts.append(d.contents("الجزء 01 — العرض الفني", "PART 01", lead=("الملخص التنفيذي", exec_name)))
    d.parts.append(body[0])
    d.divider("01", "العرض الفني", "TECHNICAL PROPOSAL", [(t, e) for t, e in zip(
        [t for t, _ in part_items], ["ABOUT", "EXPERIENCE", "UNDERSTANDING", "SCOPE", "METHOD", "SCHEDULE", "TEAM & RESOURCES", "QHSE & RISK"])])
    d.parts.extend(body[1:])
    d.thanks()


def _why_fallback(d: _Doc) -> list[dict]:
    prof, s = d.prof, d.s
    out = []
    if prof.get("classification") or s.get("company_classification"):
        out.append({"title": "مقاول عام مصنّف", "text": f"{prof.get('classification') or s.get('company_classification')}"
                                                     + (f" منذ {prof['founded']}" if prof.get("founded") else "") + "."})
    if prof.get("staff"):
        out.append({"title": "كوادر وطنية متخصصة", "text": f"{prof['staff']} موظفاً ومهندساً، وعمالة نظامية بالكامل."})
    pf = prof.get("portfolio") or {}
    if pf.get("projects"):
        out.append({"title": "سجل مشاريع موثّق", "text": f"{pf['projects']} مشروعاً في {pf.get('cities') or ''} مدينة ومحافظة، "
                                                     "مع جهات حكومية وشركات كبرى."})
    eq = prof.get("equipment") or {}
    if eq.get("total"):
        out.append({"title": "أسطول معدات مملوك", "text": f"{eq['total']} معدة ثقيلة مملوكة تقلل الاعتماد على سوق التأجير."})
    out.append({"title": "التزام كامل بشروط الطلب", "text": f"تنفيذ خلال {d.duration}، وفريق متفرغ، وبرنامج زمني تفصيلي بعد الترسية."})
    out.append({"title": "جودة وسلامة بلا استثناء", "text": "خطة جودة وخطة سلامة معتمدتان قبل البدء، ومسؤول سلامة متفرغ."})
    return out[:6]


def _risk_fallback(d: _Doc) -> list[dict]:
    if d.data.get("project_kind") in ("صيانة وتشغيل", "نظافة"):
        return [{"risk": "تأخر الاستجابة للبلاغات", "impact": "متوسط", "mitigation": "فرق مناوبة ومؤشرات زمن استجابة شهرية"},
                {"risk": "نقص قطع الغيار", "impact": "متوسط", "mitigation": "مخزون استراتيجي لقطع الغيار الحرجة واتفاقيات توريد"}]
    return [{"risk": "تأخر اعتماد المواد والمخططات", "impact": "مرتفع", "mitigation": "تقديم الاعتمادات خلال أسبوعين من الترسية ومتابعة أسبوعية"},
            {"risk": "تقلب أسعار الحديد والأسمنت", "impact": "متوسط", "mitigation": "شراء مبكر واتفاقيات توريد مع الموردين المعتمدين"},
            {"risk": "اختلاف ظروف الموقع عن الوثائق", "impact": "متوسط", "mitigation": "معاينة الموقع وتوثيق حالته في محضر الاستلام"},
            {"risk": "حوادث العمل والسلامة", "impact": "مرتفع", "mitigation": "مسؤول سلامة متفرغ وتصاريح عمل وتوعية يومية"}]


def _s_curve(bars, months) -> list:
    if not bars or not months:
        return []
    months = int(months)
    load = [0.0] * months
    for b in bars:
        try:
            s0, e0 = float(b.get("start_month") or 0), float(b.get("end_month") or 0)
        except (TypeError, ValueError):
            continue
        span = max(e0 - s0, .25)
        for m in range(months):
            ov = max(0.0, min(e0, m + 1) - max(s0, m))
            load[m] += ov / span
    tot = sum(load) or 1
    acc, out = 0.0, []
    for v in load:
        acc += v
        out.append(round(acc / tot * 100))
    out[-1] = 100
    return out


def _org_html(org, staff, company, client) -> str:
    def nd(n, cls=""):
        return f'<div class="nd {cls}">{_e(n.get("title"))}<small>{_e(n.get("sub"))}</small></div>'
    top = org.get("top") or [{"title": f"إدارة {company.split()[0] if company else 'الشركة'} العليا", "sub": "Corporate Management"},
                             {"title": client, "sub": "Client"}]
    lead = org.get("lead") or {"title": "مدير المشروع", "sub": "Project Manager"}
    rows = org.get("rows") or []
    if not rows and staff:
        roles = [s.get("role") for s in staff if s.get("role") and "مدير مشروع" not in s.get("role", "")]
        rows = [[{"title": r, "sub": ""} for r in roles[i:i + 4]] for i in range(0, min(len(roles), 8), 4)]
    base = org.get("base") or {"title": "مشرف عام · رؤساء العمال · العمالة الفنية", "sub": "General Foreman · Skilled Workforce"}
    html_rows = "".join('<div class="row">' + "".join(nd(n) for n in r) + "</div>" for r in rows)
    return (f'<div class="org"><div class="row">{nd(top[0], "dk")}{"".join(nd(t) for t in top[1:])}</div>'
            f'<div class="row">{nd(lead, "gr")}</div>{html_rows}<div class="base">{_e(base.get("title"))}<small>{_e(base.get("sub"))}</small></div></div>')


def _settings_refs(s: dict) -> list:
    out = []
    for line in (s.get("company_references") or "").split("\n"):
        parts = [p.strip() for p in line.split("|")]
        if len([p for p in parts if p]) >= 2:
            parts = (parts + ["", "", ""])[:3]
            out.append([parts[0], parts[1], "", parts[2]])
    return out


def _relevant_projects(d: _Doc, projects: list) -> list:
    """أقرب 3 مشاريع لنطاق هذا المشروع (تقاطع مفردات النطاق مع قطاع المشروع ونطاقه)."""
    if not projects:
        return []
    text = " ".join([d.p.get("title", ""), d.st.get("scope_title", ""), d.data.get("project_kind", "")]
                    + [l.get("name", "") for l in (d.data.get("boq") or [])[:40]])
    words = {w for w in re.split(r"\W+", text) if len(w) > 3}
    media = {m.get("file"): m.get("uri") for m in d.media}
    scored = []
    for pr in projects:
        blob = " ".join([pr.get("name", ""), pr.get("type", ""), pr.get("sector", ""), pr.get("relevance", "")]
                        + list(pr.get("scope") or []))
        score = len(words & {w for w in re.split(r"\W+", blob) if len(w) > 3}) + (2 if pr.get("featured") else 0) + (
            1 if pr.get("photo") else 0)
        if re.search(r"خرسان|إنشائ|هيكل|عظم", text) and re.search(r"خرسان|إنشائ|هيكل", blob):
            score += 4
        scored.append((score, pr))
    scored.sort(key=lambda x: -x[0])
    out = []
    for _, pr in scored[:3]:
        out.append({**pr, "_uri": media.get(pr.get("photo"), "")})
    return out


# =============================== العرض المالي ===============================

def _financial(d: _Doc, start_no: int):
    st, s, pv = d.st, d.s, d.pv
    d.sec_no = start_no
    d.cover("FINANCIAL PROPOSAL", "العرض المالي", d.photos)
    d.letter()
    body = []
    lump = pv["lump"]
    sub, vat, grand = pv["subtotal"], pv["vat"], pv["grand"]
    loaded = pv["loaded"]

    # ----- نموذج التسعير
    x = d.section("form", "نموذج التسعير بالمبلغ المقطوع" if lump else "نموذج التسعير", "LUMP SUM PRICING FORM" if lump
                  else "PRICING FORM", "العرض المالي")
    lab = "المبلغ المقطوع — العرض الأساسي" if lump else "قيمة العرض — غير شاملة الضريبة"
    note = st.get("lump_note") or ("ثابت ونهائي غير خاضع لإعادة القياس" if lump else "تُحاسب الأعمال على الكميات المنفذة فعلياً")
    x += (f'<div class="valuebox"><div class="t"><b>{lab}</b><small>{_e(note)}</small></div>'
          f'<div class="amt">{money(sub)}<span>SAR</span></div></div>')
    x += d.table(["م", "البند", "المبلغ (ر.س)"],
                 [["1", ("المبلغ المقطوع لكامل الأعمال وفق المخططات والمواصفات — العرض الأساسي" if lump
                         else "إجمالي أعمال جدول الكميات المسعّر"), money(sub)],
                  ["2", f"ضريبة القيمة المضافة {pv['vat_rate']:g}%", money(vat)]],
                 num_cols=(2,), total=["", "الإجمالي شامل الضريبة", money(grand)], widths=[6, 70, 24])
    x += (f'<div class="words"><b>المبلغ كتابةً:</b> {_e(amount_in_words(sub).replace(" فقط", ""))} (غير شامل الضريبة) — '
          f'{_e(amount_in_words(grand))} شاملة الضريبة</div>')
    groups = _fin_groups(d, loaded, sub)
    if len(groups) >= 2:
        tot = sum(v for _, v in groups) or 1
        x += '<h3 class="h3">تفصيل استرشادي ' + ("للمبلغ المقطوع" if lump else "لقيمة العرض") + " (لأغراض التحليل فقط)</h3>"
        x += d.table(["م", "المكوّن", "المبلغ (ر.س)", "% النسبة"],
                     [[str(i), n, money(v), f"{v / tot * 100:.1f}%"] for i, (n, v) in enumerate(groups, 1)],
                     num_cols=(2, 3), total=["", "الإجمالي" + (" (= المبلغ المقطوع)" if lump else ""), money(sub), "100%"],
                     widths=[6, 60, 20, 14])
        x += '<div class="bars">' + "".join(
            f'<div class="r"><span>{_e(n[:40])}</span><div class="t"><i style="width:{v / tot * 100:.1f}%"></i></div><b>{v / tot * 100:.1f}%</b></div>'
            for n, v in groups) + "</div>"
    if st.get("separate_items"):
        x += '<h3 class="h3">بنود تُسعّر منفصلة' + (" (خارج المبلغ المقطوع)" if lump else "") + "</h3>" + d.table(
            ["البند", "الوحدة", "السعر (ر.س)"], [[r.get("name"), r.get("unit"), money(r.get("price") or 0)] for r in st["separate_items"]],
            num_cols=(2,), widths=[66, 14, 20])
    body.append(x + "</section>")

    # ----- أساس التسعير
    if st.get("cost_basis_rows") or st.get("cost_kpis"):
        x = d.sub("COST BASIS", "أساس التسعير ومؤشرات الكميات", "أساس التسعير", flow=False)
        x += f"<p class=lead>{_e(st.get('cost_basis_intro'))}</p>{d.kpis(st.get('cost_kpis') or [], dark_first=False)}"
        if st.get("cost_basis_rows"):
            x += d.table(["المكوّن", "أساس التسعير"], [[r.get("component"), r.get("basis")] for r in st["cost_basis_rows"]],
                         widths=[24, 76])
        if st.get("cost_basis_note"):
            x += f'<div class="note">{_e(st["cost_basis_note"])}</div>'
        body.append(x + "</section>")

    # ----- الهندسة القيمية
    ve = st.get("ve_items") or []
    if ve:
        total = sum(float(v.get("saving") or 0) for v in ve)
        x = d.section("ve", "مقترحات الهندسة القيمية (منفصلة واختيارية)", "VALUE ENGINEERING", "الهندسة القيمية")
        x += f"<p class=lead>{_e(st.get('ve_intro') or '')}</p>"
        x += d.table(["م", "المقترح", "البنود المتأثرة", "الوصف الفني المختصر", "الوفر (ر.س)", "المدة (يوم)", "ملاحظات"],
                     [[str(i), v.get("title"), v.get("affected"), v.get("description"), money(v.get("saving") or 0),
                       v.get("days") or "—", v.get("note")] for i, v in enumerate(ve, 1)],
                     num_cols=(4, 5), total=["", "إجمالي الوفر المقترح", "", "", money(total), _days_total(ve), ""],
                     widths=[4, 18, 11, 33, 11, 8, 15])
        days = _days_total(ve)
        x += d.kpis([{"value": money(total), "label": "ريال وفر تقديري", "en": "TOTAL SAVING", "style": "gr"},
                     {"value": f"{total / sub * 100:.1f}%" if sub else "—", "label": "من قيمة العرض", "en": "OF BASE OFFER"},
                     {"value": days, "label": "يوماً من المدة", "en": "TIME SAVING", "style": "dk"}], cls="k3")
        body.append(x + "</section>")

    # ----- الشروط والتحفظات
    tb = d.blocks_by_key.get("terms", [])
    x = d.section("terms", "الشروط والتحفظات", "TERMS & QUALIFICATIONS", "الشروط والإقرار")
    acc = st.get("acceptance") or next((b["text"] for b in tb if b["type"] == "p"), "")
    if acc:
        x += f'<h3 class="h3">القبول بشروط الطلب</h3><p>{_e(acc)}</p>'
    res = [(r.get("lead", ""), r.get("text", "")) for r in st.get("reservations") or []] or next(
        (b["items"] for b in tb if b["type"] == "numbered" and b["items"] and isinstance(b["items"][0], (list, tuple))), [])
    assumptions = d.data.get("assumptions") or []
    if assumptions and not st.get("reservations"):
        x += '<h3 class="h3">الافتراضات</h3>' + d.bullets(assumptions, numbered=True)
    if res:
        x += '<h3 class="h3">التوضيحات والتحفظات</h3>' + d.bullets(res, numbered=True)
    rows = st.get("bid_rows") or [
        {"label": "قيمة العرض", "value": f"{money(sub)} ريال غير شامل الضريبة — {money(grand)} ريال شاملة الضريبة"},
        {"label": "مدة التنفيذ / سريان العرض", "value": f"{d.duration} / {int(float(s.get('validity_days') or 90))} يوماً من تاريخ التقديم"},
        {"label": "العملة", "value": "ريال سعودي"}]
    x += '<table class="kv"><tbody>' + "".join(f"<tr><td>{_e(r.get('label'))}</td><td>{_e(r.get('value'))}</td></tr>" for r in rows) + "</tbody></table>"
    decl = st.get("declaration") or next((b["text"] for b in tb if b["type"] == "declaration"), "")
    x += f'<div class="decl"><b>الإقرار:</b> {_e(decl)}</div>' + _sig_table(d)
    body.append(x + "</section>")

    # ----- قائمة متطلبات التقديم
    chk = st.get("checklist") or _checklist_fallback(d)
    x = d.section("check", "قائمة متطلبات تقديم العرض", "SUBMISSION CHECKLIST", "متطلبات التقديم")
    x += d.table(["#", "المتطلب", "موضعه في العرض", "الحالة"],
                 [[str(i), r.get("req"), r.get("where"), ("✔ " if "مشمول" in (r.get("status") or "") else "📎 ") + (r.get("status") or "")]
                  for i, r in enumerate(chk, 1)], widths=[5, 55, 25, 15])
    x += '<div class="note">المستندات النظامية والمالية والسير الذاتية تُرفق مع النسخة المختومة على مطبوعات الشركة.</div>'
    body.append(x + "</section>")

    # ----- الملحق (أ): جدول الكميات
    if loaded:
        client = [(i, l) for i, l in enumerate(loaded) if not l.get("extra")]
        extra = [(i, l) for i, l in enumerate(loaded) if l.get("extra")]
        x = d.section("boq", "الملحق (أ): جدول الكميات المسعّر" + (" — (1) بنود جدول الطرف الأول" if extra else ""),
                      "APPENDIX A · PRICED BOQ", "جدول الكميات", number=False)
        x += _boq_table(d, client, "إجمالي جدول الكميات" + (" — يُرحَّل للملخص" if extra else ""))
        if pv["lump"] and not extra and abs(pv["indicative"] - sub) >= 1:
            x += (f'<div class="note">الفرق بين الإجمالي الاسترشادي والمبلغ المقطوع {money(abs(pv["indicative"] - sub))} ريال، '
                  "ناتج عن تقريب الأسعار. المبلغ المقطوع هو الملزم.</div>")
        body.append(x + "</section>")
        if extra:
            by_div: dict = {}
            for i, l in extra:
                by_div.setdefault(l.get("division") or "بنود مكملة", []).append((i, l))
            x = d.sub("APPENDIX A · PRICED BOQ", "الملحق (أ): جدول الكميات المسعّر — (2) البنود المكملة للنطاق", "جدول الكميات", flow=False)
            x += _boq_table(d, extra, None)
            body.append(x + "</section>")
        # الملخص
        x = d.sub("APPENDIX A · SUMMARY", "الملحق (أ): ملخص جدول الكميات المسعّر", "ملخص الأسعار", flow=False)
        divs: dict = {}
        for l in loaded:
            divs[l.get("division") or "بنود جدول الكميات"] = divs.get(l.get("division") or "بنود جدول الكميات", 0) + float(l.get("total") or 0)
        summ = [[str(i), k, money(v)] for i, (k, v) in enumerate(divs.items(), 1)]
        x += d.table(["#", "البيان", "المبلغ (ر.س)"], summ, num_cols=(2,),
                     total=["", "الإجمالي" + (" = المبلغ المقطوع" if lump else "") + " (غير شامل الضريبة)", money(sub)], widths=[8, 68, 24])
        x += d.table(["", "البيان", "المبلغ (ر.س)"], [["", f"ضريبة القيمة المضافة {pv['vat_rate']:g}%", money(vat)]],
                     num_cols=(2,), total=["", "الإجمالي شامل الضريبة", money(grand)], widths=[8, 68, 24])
        x += f'<div class="words"><b>المبلغ كتابةً:</b> {_e(amount_in_words(grand))} شاملة الضريبة</div>'
        boq_note = st.get("boq_note") or ("أسعار الوحدات أعلاه تُستخدم لتقييم أوامر التغيير بالزيادة أو النقص فقط، والمبلغ المقطوع ثابت غير خاضع لإعادة القياس."
                                          if lump else "تُحاسب الأعمال على الكميات المنفذة فعلياً والمعتمدة بأسعار الوحدات أعلاه.")
        x += f'<div class="note">{_e(boq_note)}</div>' + _sig_table(d)
        body.append(x + "</section>")

    d.parts.append(d.contents("الجزء 02 — العرض المالي", "PART 02"))
    d.divider("02", "العرض المالي", "FINANCIAL PROPOSAL", [
        (t, e) for (_, t, _n), e in zip(d.toc, ["PRICING FORM", "VALUE ENGINEERING" if ve else "QUALIFICATIONS",
                                               "QUALIFICATIONS", "CHECKLIST", "PRICED BOQ"])])
    d.parts.extend(body)
    d.thanks()


def _days_total(ve) -> str:
    tot = 0
    for v in ve:
        m = re.search(r"-?\d+", str(v.get("days") or "").replace("−", "-"))
        if m:
            tot += int(m.group())
    return str(tot) if tot else "—"


def _sig_table(d: _Doc) -> str:
    created = _parse_date(d.p.get("created_at"))
    rows = [("عن الشركة", d.s.get("company_name", "")), ("الاسم / المنصب", d.s.get("signer_title") or "المدير العام"),
            ("التوقيع والختم", ""), ("التاريخ", f"{created.day} / {created.month} / {created.year}م")]
    return '<table class="kv sig"><tbody>' + "".join(f"<tr><td>{_e(k)}</td><td>{_e(v)}</td></tr>" for k, v in rows) + "</tbody></table>"


def _fin_groups(d: _Doc, loaded, sub) -> list:
    st = d.st
    if st.get("breakdown_amounts"):
        return [(g.get("name", ""), float(g.get("amount") or 0)) for g in st["breakdown_amounts"]]
    if any(l.get("division") for l in loaded):
        groups: dict = {}
        for l in loaded:
            k = l.get("division") or "بنود أخرى"
            groups[k] = groups.get(k, 0) + float(l.get("total") or 0)
        tot = sum(groups.values()) or 1
        return [(k, v * sub / tot) for k, v in groups.items()]
    fb = d.blocks_by_key.get("financial", [])
    tbl = next((b for b in fb if b["type"] == "table" and "النسبة %" in b["headers"]), None)
    if tbl:
        return [(r[1], float(str(r[2]).replace(",", ""))) for r in tbl["rows"]]
    return []


def _boq_table(d: _Doc, items, total_label) -> str:
    rows, classes = [], {}
    cur_div, div_sum, grand = None, 0.0, 0.0
    has_div = any(l.get("division") for _, l in items)

    def close():
        if has_div and cur_div is not None:
            classes[len(rows)] = "sub"
            rows.append(["", f"إجمالي {cur_div}", "", "", "", money(div_sum)])

    for idx, l in items:
        div = l.get("division") or ""
        if has_div and div != cur_div:
            close()
            cur_div, div_sum = div, 0.0
            classes[len(rows)] = "div"
            rows.append([div or "بنود أخرى"])
        tot = float(l.get("total") or 0)
        div_sum += tot
        grand += tot
        if l.get("excluded"):
            rows.append([l.get("ref") or str(idx + 1), l.get("name"), l.get("unit"), qty_fmt(l.get("qty")), "—", ("خارج النطاق", "out")])
        else:
            rows.append([l.get("ref") or str(idx + 1), l.get("name"), l.get("unit"), qty_fmt(l.get("qty")),
                         money(l.get("unit_price")), money(tot)])
        for j, c in enumerate(l.get("children") or [], 1):
            rows.append([f"{l.get('ref') or idx + 1}.{j}", "↳ " + str(c.get("name", "")), c.get("unit", ""), qty_fmt(c.get("qty")),
                         money(c.get("unit_price")), money(c.get("total"))])
    close()
    total = ["", total_label, "", "", "", money(grand)] if total_label else None
    return d.table(["البند", "الوصف", "الوحدة", "الكمية", "سعر الوحدة", "الإجمالي"], rows, num_cols=(3, 4, 5), total=total,
                   widths=[8, 52, 8, 10, 10, 12], row_classes=classes)


def _checklist_fallback(d: _Doc) -> list:
    has_ve = bool(d.st.get("ve_items"))
    rows = [{"req": "نموذج التسعير معبأً (غير شامل وشامل الضريبة) مع التفصيل الاسترشادي", "where": "نموذج التسعير", "status": "مشمول"},
            {"req": "جدول الكميات مسعّراً بأسعار الوحدات", "where": "الملحق (أ)", "status": "مشمول"}]
    if has_ve:
        rows.append({"req": "مقترحات الهندسة القيمية", "where": "الهندسة القيمية", "status": "مشمول"})
    rows += [{"req": "السجل التجاري، الشهادة الضريبية، شهادة التصنيف، الزكاة، التأمينات الاجتماعية", "where": "مرفقة منفصلة", "status": "مرفق منفصل"},
             {"req": "سابقة الأعمال مع جهات التواصل", "where": "العرض الفني — الخبرات", "status": "مشمول"},
             {"req": "الهيكل التنظيمي والسير الذاتية للفريق الفني", "where": "العرض الفني — الفريق", "status": "مشمول"},
             {"req": "البرنامج الزمني المبدئي", "where": "العرض الفني — البرنامج الزمني", "status": "مشمول"},
             {"req": "منهجية التنفيذ", "where": "العرض الفني — المنهجية", "status": "مشمول"},
             {"req": "القوائم المالية لآخر سنتين وخطاب الاستعداد البنكي", "where": "مرفقة منفصلة", "status": "مرفق منفصل"},
             {"req": "إقرار بمعاينة الموقع وقبول الشروط مع التحفظات كتابةً", "where": "الشروط والتحفظات", "status": "مشمول"}]
    return rows


# =============================== التجميع والطباعة ===============================

def build_html(proposal: dict, settings: dict, kind: str, pages: dict | None = None) -> str:
    """HTML العرض (kind = technical | financial). pages: أرقام الصفحات من تمريرة سابقة."""
    if kind == "financial":
        tech = _prepare("technical", proposal, settings)
        _technical(tech)
        start = tech.sec_no
        d = _prepare("financial", proposal, settings)
        _financial(d, start)
        out = _wrap(d, f"العرض المالي — {proposal.get('title', '')}", "العرض المالي")
    else:
        d = _prepare("technical", proposal, settings)
        _technical(d)
        out = _wrap(d, f"العرض الفني — {proposal.get('title', '')}", "العرض الفني")
    pages = pages or {}
    return re.sub(r"__PG_(s\d+)__", lambda m: f"{pages.get(m.group(1), 0):02d}" if pages.get(m.group(1)) else "", out)


def _chromium_pdf(html_text: str) -> bytes:
    import os
    from playwright.sync_api import sync_playwright
    exe = os.environ.get("AZOOM_CHROMIUM_PATH") or None
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(html_text, wait_until="load")
            return page.pdf(format="A4", print_background=True, prefer_css_page_size=True)
        finally:
            browser.close()


def render_pdf(proposal: dict, settings: dict, kind: str) -> bytes:
    """تمريرتان: الأولى لمعرفة صفحة كل قسم من العلامات الخفية، والثانية بأرقام المحتويات."""
    first = _chromium_pdf(build_html(proposal, settings, kind))
    pages = {}
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(first))
        for i, pg in enumerate(reader.pages, 1):
            for m in re.finditer(r"ZQ(s\d+)QZ", pg.extract_text() or ""):
                pages.setdefault(m.group(1), i)
    except Exception:
        return first
    if not pages:
        return first
    return _chromium_pdf(build_html(proposal, settings, kind, pages))
