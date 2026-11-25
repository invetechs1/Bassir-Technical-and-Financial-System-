"""ملف التأهيل المسبق بصيغة PDF — بنفس هوية وتصميم العرض الفني والمالي (proposal_pdf).

نسختان من نفس البيانات:
- dossier: ملف التأهيل الذي يُقدَّم للجهة (لا يذكر النواقص ولا الدرجات الداخلية).
- assessment: تقرير الجاهزية الداخلي (الدرجة المتوقعة لكل معيار، النواقص وخطة سدها،
  ملاحظات فريق الخبراء) — للمراجعة قبل التقديم ولا يُرسل.
"""
import io
import re
from datetime import datetime

from .proposal_pdf import (CSS, INK, _Doc, _chevrons, _chromium_pdf, _e, _font_faces, _logo_uris, _media, _mix,
                           _profile, _svg_logo)

_STATUS_AR = {"valid": "سارية", "expiring": "تنتهي قبل الموعد", "expired": "منتهية", "missing": "غير مسجلة",
              "number_only": "الرقم فقط"}
_CRIT = [("experience", "الخبرة السابقة في أعمال مماثلة", "EXPERIENCE"),
         ("financial", "الملاءة والقدرة المالية", "FINANCIAL CAPACITY"),
         ("staff", "الجهاز الفني والكوادر الرئيسية", "KEY PERSONNEL"),
         ("equipment", "المعدات والموارد", "EQUIPMENT & RESOURCES"),
         ("quality", "أنظمة الجودة والسلامة والبيئة", "QHSE SYSTEMS"),
         ("legal", "الوثائق النظامية والتصنيف", "LEGAL & CLASSIFICATION"),
         ("local", "المحتوى المحلي والتوطين", "LOCAL CONTENT")]

_EXTRA_CSS = """
.scorebar{display:flex;align-items:center;gap:8px;margin:2px 0}
.scorebar .t{flex:1;height:7px;background:#E6ECE9;border-radius:6px;overflow:hidden}
.scorebar .t i{display:block;height:100%;background:__A__}
.verdict{border-radius:10px;padding:14px 18px;margin:0 0 14px;color:#fff;display:flex;justify-content:space-between;align-items:center}
.verdict.green{background:#1E7A46}.verdict.amber{background:#B7791F}.verdict.red{background:#B03A2E}
.verdict b{font-size:17pt}.verdict span{font-size:28pt;font-weight:700}
.internal{border:2px dashed #B03A2E;color:#7a1f14;border-radius:8px;padding:8px 12px;margin:0 0 12px;font-size:9.5pt}
"""


def _doc(dossier: dict, settings: dict, kind: str) -> _Doc:
    inv = dossier["invitation"]
    p = {"title": inv["name"], "client": inv["agency"], "created_at": dossier.get("built_at", ""),
         "ref_no": f"PQ-{datetime.now():%Y%m%d}-{inv.get('id') or ''}", "data": {}}
    d = _Doc(kind, p, settings)
    d.prof = _profile(settings)
    d.media = _media(settings)
    d.photos = [m["uri"] for m in d.media if m.get("kind") in ("hero", "project", "site") and m.get("uri")]
    d.logo_light, d.logo_dark, d.logo_ratio = _logo_uris(settings)
    from .export_docx import _resolve_brand
    d.primary, d.accent = _resolve_brand(settings)
    d.dossier = dossier
    return d


def _css(d: _Doc, header: str) -> str:
    s = d.s
    foot = f'{s.get("company_name", "")} · {header} · {d.p.get("title", "")}'
    return (CSS.replace("__P__", d.primary).replace("__A__", d.accent).replace("__INK__", INK)
            .replace("__T__", _mix(d.accent, .88)).replace("__T2__", _mix(d.accent, .95)).replace("__A2__", _mix(d.accent, .25))
            .replace("__REF__", (d.p.get("ref_no") or "").replace('"', "")).replace("__FOOT__", foot.replace('"', "'")[:120])
            .replace("__TR__", "")
            .replace("__LOGO__", f'url("{_svg_logo(d.logo_light, d.logo_ratio, 38)}")' if d.logo_light else
                     f'"{(s.get("company_name") or "").replace(chr(34), "")}"')
            .replace("__NAMED__", "\n".join(d.named))) + _EXTRA_CSS.replace("__A__", d.accent)


def _cover(d: _Doc, en: str, ar: str):
    inv, s = d.dossier["invitation"], d.s
    meta = [("مقدّم إلى", inv["agency"]), ("نوع الدعوة", inv.get("type") or "تأهيل مسبق"),
            ("آخر موعد للتقديم", inv.get("deadline", "")), ("تاريخ الإعداد", f"{datetime.now():%Y-%m-%d}"),
            ("فئة الأعمال", d.dossier.get("category_label", ""))]
    meta_html = "".join(f"<div><small>{_e(k)}</small><b>{_e(v)}</b></div>" for k, v in meta if v)
    ph = "".join(f'<img src="{u}">' for u in d.photos[:3])
    logo = f'<img class="bl-logo" src="{d.logo_dark}">' if d.logo_dark else \
        f'<div class="bl-logo" style="font:700 16pt Plex">{_e(s.get("company_name"))}</div>'
    d.parts.append(
        f'<div class="bleed">{_chevrons(d.accent)}<div class="bl-in">{logo}'
        f'<div class="cv-ey"><span class="eyebrow">{_e(en)}</span><span class="ar">{_e(ar)}</span></div>'
        f'<div class="cv-title"><h1>{_e(inv["name"])}<br><span class=g>{_e(s.get("company_name", ""))}</span></h1>'
        f'<div class="bar"></div></div><div class="cv-meta">{meta_html}</div>'
        f'{"<div class=cv-ph>" + ph + "</div>" if ph else ""}'
        f'<div class="cv-ft"><span>{_e(s.get("company_website", ""))}</span><span><b>{_e(s.get("company_name"))}</b>'
        f'{" · " + _e(s.get("company_classification")) if s.get("company_classification") else ""}</span></div></div></div>')


def _letter(d: _Doc):
    inv, s, w = d.dossier["invitation"], d.s, d.dossier["writing"]
    exp, res = d.dossier["experience"], d.dossier["resources"]
    now = datetime.now()
    to = f'<div class="to"><b>السادة / {_e(inv["agency"])}</b><br>المحترمين</div>'
    meta = f'<div class="meta">التاريخ: {now.day} / {now.month} / {now.year}م<br>المرجع: {_e(d.p["ref_no"])}</div>'
    body = "".join(f"<p class=lead>{_e(x)}</p>" for x in w.get("letter") or [])
    kp = [x for x in (
        {"value": str(exp["relevant_count"]), "label": "مشروعاً مماثلاً موثقاً", "en": "SIMILAR PROJECTS"},
        {"value": res["staff_text"] or "—", "label": "موظفاً ومهندساً", "en": "STAFF"},
        {"value": str(res["equipment_total"] or "—"), "label": "معدة وآلية", "en": "EQUIPMENT"},
        {"value": f"{exp['largest_value_m']:,.0f}م" if exp.get("largest_value_m") else "—", "label": "ريال أكبر عقد منفذ", "en": "LARGEST CONTRACT"},
    ) if x]
    sig = [("عن الشركة", s.get("company_name", "")), ("المنصب", s.get("signer_title") or "المدير العام"),
           ("التوقيع", ""), ("الختم", "")]
    d.parts.append(
        d.sub("COVER LETTER", "", "خطاب التقديم", flow=False).replace(
            '<div class="sh"><span class="eyebrow">COVER LETTER</span><h2></h2><div class="u"></div></div>', "")
        + f'<div class="letter-h">{to}{meta}</div><p>السلام عليكم ورحمة الله وبركاته،</p>'
          f'<div class="subj"><b>الموضوع:</b> طلب التأهيل المسبق لمشروع «{_e(inv["name"])}»</div>{body}{d.kpis(kp)}'
          f'<p>وتفضلوا بقبول فائق الاحترام والتقدير،</p><table class="kv sig"><tbody>'
        + "".join(f"<tr><td>{_e(k)}</td><td>{_e(v)}</td></tr>" for k, v in sig) + "</tbody></table></section>")


def _dossier_body(d: _Doc) -> list[str]:
    ds, w = d.dossier, d.dossier["writing"]
    exp, res, comp = ds["experience"], ds["resources"], ds["compliance"]
    nar = w.get("narratives") or {}
    prof = d.prof or {}
    body = []

    x = d.section("summary", "الملخص التنفيذي", "EXECUTIVE SUMMARY", "ملف التأهيل")
    x += f"<p class=lead>{_e(w.get('summary', ''))}</p>"
    if w.get("win_themes"):
        x += '<h3 class="h3">لماذا نحن الأجدر بالتأهيل</h3>' + d.bullets(w["win_themes"])
    body.append(x + "</section>")

    x = d.section("about", "نبذة عن الشركة", "COMPANY PROFILE", "ملف التأهيل")
    about = prof.get("about")
    about = about if isinstance(about, str) else " ".join(about or []) if isinstance(about, list) else ""
    x += f"<p class=lead>{_e(about or d.s.get('company_intro', ''))}</p>"
    rows = [[k, v] for k, v in (("الاسم", d.s.get("company_name", "")), ("سنة التأسيس", res["founded"]),
                                ("التصنيف", res["classification"]), ("السجل التجاري", d.s.get("company_cr", "")),
                                ("الرقم الضريبي", d.s.get("company_vat_no", "")), ("الكوادر", res["staff_text"]),
                                ("نطاق العمل الجغرافي", res["cities"] if isinstance(res["cities"], str) else "، ".join(res["cities"])))
            if v]
    x += d.table(["البيان", "التفاصيل"], rows, widths=[30, 70])
    if exp["clients"]:
        x += '<h3 class="h3">من عملائنا</h3>' + d.bullets(exp["clients"][:12])
    body.append(x + "</section>")

    x = d.section("experience", "الخبرات والمشاريع المماثلة", "SIMILAR PROJECTS", "ملف التأهيل")
    x += f"<p class=lead>{_e(nar.get('experience', ''))}</p>"
    rows = []
    for i, p in enumerate(exp["selected"], 1):
        val = f"{p['value_m']:,.1f} م ريال" if p.get("value_m") else "—"
        scope = p.get("type") or "، ".join(p.get("scope") or [])[:90]
        rows.append([str(i), p["name"], p.get("client") or "—", scope or "—", val, p.get("years") or p.get("status") or "—"])
    x += d.table(["م", "المشروع", "العميل / المالك", "طبيعة الأعمال", "القيمة", "الفترة"], rows,
                 widths=[5, 25, 20, 26, 12, 12])
    body.append(x + "</section>")

    x = d.section("financial", "القدرة المالية", "FINANCIAL CAPACITY", "ملف التأهيل")
    x += f"<p class=lead>{_e(nar.get('financial', ''))}</p>"
    kp = [k for k in (
        {"value": f"{exp['largest_value_m']:,.0f}م" if exp.get("largest_value_m") else "", "label": "ريال أكبر عقد منفذ", "en": "LARGEST CONTRACT"},
        {"value": f"{exp['portfolio_value_m']:,.0f}م" if exp.get("portfolio_value_m") else "", "label": "ريال محفظة الأعمال الموثقة", "en": "PORTFOLIO"},
    ) if k["value"]]
    x += d.kpis(kp)
    x += d.bullets(["القوائم المالية المدققة لآخر ثلاث سنوات — مرفقة", "خطاب الاستعداد/الملاءة البنكية — مرفق",
                    "شهادة الزكاة والدخل السارية — مرفقة"])
    body.append(x + "</section>")

    x = d.section("staff", "الجهاز الفني والكوادر الرئيسية", "KEY PERSONNEL", "ملف التأهيل")
    x += f"<p class=lead>{_e(nar.get('staff', ''))}</p>"
    mgmt = res.get("management") or []
    if mgmt:
        x += d.table(["الاسم", "المنصب", "الخبرة"], [[m.get("name", ""), m.get("title") or m.get("role", ""),
                                                     m.get("experience") or m.get("bio", "")[:80]] for m in mgmt],
                     widths=[28, 32, 40])
    x += '<h3 class="h3">الهيكل الوظيفي للمشروع</h3>' + d.bullets([
        "مدير المشروع — مهندس معتمد من الهيئة السعودية للمهندسين بخبرة في مشاريع مماثلة",
        "مهندس التخطيط والمتابعة (Primavera P6) ومهندس الجودة ومهندس السلامة المعتمد",
        "مهندسو الموقع والمراقبون الفنيون حسب حجم الأعمال ومراحلها",
        "إدارة العقود والمشتريات وإدارة الوثائق والمخططات التنفيذية"])
    body.append(x + "</section>")

    x = d.section("equipment", "المعدات والموارد", "EQUIPMENT & RESOURCES", "ملف التأهيل")
    x += f"<p class=lead>{_e(nar.get('equipment', ''))}</p>"
    if res["equipment"]:
        x += d.table(["الفئة", "العدد"], [[e["name"], str(e["count"])] for e in res["equipment"]], num_cols=(1,),
                     total=["الإجمالي", str(res["equipment_total"])] if res["equipment_total"] else None, widths=[80, 20])
    body.append(x + "</section>")

    x = d.section("quality", "الجودة والسلامة والبيئة", "QHSE SYSTEMS", "ملف التأهيل")
    x += f"<p class=lead>{_e(nar.get('quality', ''))}</p>"
    certs = res.get("certifications") or []
    if certs:
        x += d.bullets([c if isinstance(c, str) else (c.get("name") or c.get("title") or "") for c in certs])
    x += '<h3 class="h3">المحتوى المحلي والتوطين</h3>' + f"<p class=lead>{_e(nar.get('local', ''))}</p>"
    body.append(x + "</section>")

    comp_rows = w.get("compliance") or []
    if comp_rows:
        x = d.section("matrix", "مصفوفة الامتثال لمتطلبات الدعوة", "COMPLIANCE MATRIX", "ملف التأهيل")
        x += d.table(["م", "متطلب الجهة", "استيفاء الشركة والدليل"],
                     [[str(i), r["requirement"], r["response"]] for i, r in enumerate(comp_rows, 1)], widths=[5, 47, 48])
        body.append(x + "</section>")

    x = d.section("docs", "الوثائق النظامية المرفقة", "STATUTORY DOCUMENTS", "ملف التأهيل")
    x += f"<p class=lead>{_e(nar.get('legal', ''))}</p>"
    x += d.table(["م", "الوثيقة", "الرقم", "الحالة"],
                 [[str(i), c["label"], c.get("number") or "—", "مرفقة"] for i, c in enumerate(
                     [c for c in comp if c["status"] in ("valid", "number_only")], 1)], widths=[6, 52, 24, 18])
    body.append(x + "</section>")
    return body


def _assessment_body(d: _Doc) -> list[str]:
    ds = d.dossier
    a, wts = ds["assessment"], ds["weights"]
    body = []
    x = d.section("verdict", "تقرير جاهزية التأهيل", "READINESS ASSESSMENT", "تقرير داخلي")
    x += '<div class="internal">تقرير داخلي — لا يُرسل للجهة. محاكاة لتقييم لجنة التأهيل من بيانات الشركة المسجلة.</div>'
    x += (f'<div class="verdict {a["tone"]}"><div><b>{_e(a["verdict"])}</b><br>'
          f'<small>{_e(ds["fit"]["note"])}</small></div><span>{a["total"]}%</span></div>')
    rows = []
    for k, ar, _ in _CRIT:
        sc = a["scores"].get(k, 0)
        rows.append([ar, f"{wts.get(k, 0)}%", f"{sc}%", f"{sc * wts.get(k, 0) / 100:.1f}"])
    x += d.table(["المعيار", "الوزن", "الدرجة المتوقعة", "النقاط"], rows, num_cols=(1, 2, 3),
                 total=["الإجمالي", "100%", "", f"{a['total']}"], widths=[46, 14, 20, 20])
    if ds.get("days_left") is not None:
        x += f"<p class=lead>المتبقي على موعد التقديم: <b>{ds['days_left']} يوماً</b> — مصدر المعايير: {_e(ds['requirements_source'])}.</p>"
    body.append(x + "</section>")

    x = d.section("gaps", "النواقص وخطة سدها قبل التقديم", "GAP CLOSURE PLAN", "تقرير داخلي")
    gaps = a["gaps"]
    x += d.table(["م", "الأولوية", "الملاحظة", "الإجراء المطلوب"],
                 [[str(i), g["priority"], g["gap"], g["action"]] for i, g in enumerate(gaps, 1)],
                 widths=[5, 11, 40, 44]) if gaps else "<p class=lead>لا نواقص — الملف جاهز للتقديم.</p>"
    risks = ds["writing"].get("risks") or []
    if risks:
        x += '<h3 class="h3">مخاطر التأهيل وتخفيفها</h3>' + d.table(
            ["الخطر", "التخفيف"], [[r["risk"], r["mitigation"]] for r in risks], widths=[45, 55])
    body.append(x + "</section>")

    x = d.section("panel", "ملاحظات فريق المراجعة", "EXPERT PANEL REVIEW", "تقرير داخلي")
    x += d.table(["الخبير", "الملاحظة"], [[p["role"], p["note"]] for p in ds["panel"]], widths=[30, 70])
    x += '<h3 class="h3">حالة الوثائق النظامية</h3>' + d.table(
        ["الوثيقة", "إلزامية", "الحالة", "التفاصيل"],
        [[c["label"], "نعم" if c["mandatory"] else "—", _STATUS_AR.get(c["status"], c["status"]), c["detail"]] for c in ds["compliance"]],
        widths=[34, 10, 16, 40])
    body.append(x + "</section>")
    return body


def build_html(dossier: dict, settings: dict, kind: str = "dossier", pages: dict | None = None) -> str:
    d = _doc(dossier, settings, kind)
    if kind == "assessment":
        header = "تقرير جاهزية التأهيل (داخلي)"
        _cover(d, "READINESS ASSESSMENT — INTERNAL", "تقرير جاهزية التأهيل — داخلي")
        d.parts.extend(_assessment_body(d))
    else:
        header = "ملف التأهيل المسبق"
        _cover(d, "PRE-QUALIFICATION SUBMITTAL", "ملف التأهيل المسبق")
        _letter(d)
        body = _dossier_body(d)
        d.parts.append(d.contents("ملف التأهيل المسبق", "PRE-QUALIFICATION"))
        d.parts.extend(body)
        d.thanks()
    out = (f'<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>{_e(header)}</title>'
           f"<style>{_font_faces()}\n{_css(d, header)}</style></head><body>{''.join(d.parts)}</body></html>")
    pages = pages or {}
    return re.sub(r"__PG_(s\d+)__", lambda m: f"{pages.get(m.group(1), 0):02d}" if pages.get(m.group(1)) else "", out)


def render_pdf(dossier: dict, settings: dict, kind: str = "dossier") -> bytes:
    first = _chromium_pdf(build_html(dossier, settings, kind))
    pages = {}
    try:
        from pypdf import PdfReader
        for i, pg in enumerate(PdfReader(io.BytesIO(first)).pages, 1):
            for m in re.finditer(r"ZQ(s\d+)QZ", pg.extract_text() or ""):
                pages.setdefault(m.group(1), i)
    except Exception:
        return first
    return _chromium_pdf(build_html(dossier, settings, kind, pages)) if pages else first
