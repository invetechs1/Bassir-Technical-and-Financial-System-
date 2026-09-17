"""الوكيلان: الوكيل الفني ووكيل التسعير + جاهزية تهيئة المستأجر.

الوكيل الفني: يقرأ ملفات المشروع، يصنف فئته، يجد أشبه العروض السابقة، ويبين
تغطية بنك فقرات الشركة قبل البناء — ثم يبني الأقسام بأسلوب الشركة نفسها.
وكيل التسعير: يقرأ جدول الكميات ويبين مصدر سعر كل بند (قاعدة أسعار الشركة /
عرض سابق مشابه / تقدير) قبل اعتماد التسعير.

التحليل «تشغيل جاف» لنفس خط الإنتاج الحقيقي: ما يعرضه الوكيلان في التحليل هو
حرفياً ما سيُبنى عند التوليد — لا وعود ثم مخرجات مختلفة. جلسة التحليل تُخزَّن
(agent_sessions) فيولَّد العرض منها دون إعادة رفع الملفات.
"""
import json

from .database import get_db, get_settings, now_iso
from .tenancy import cid

SESSION_TTL_HOURS = 24

AGENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL,
    client TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT 'government',
    files_text TEXT NOT NULL DEFAULT '',
    analysis TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
"""


def init_agent_tables():
    with get_db() as db:
        db.executescript(AGENT_SCHEMA)
        # تنظيف الجلسات الأقدم من يوم
        db.execute("DELETE FROM agent_sessions WHERE created_at < datetime('now', '-1 day')")


# ------------------------- جاهزية التهيئة (Onboarding) -------------------------

def has_company_logo(company: dict, logo_file_exists: bool) -> bool:
    return bool((company or {}).get("logo_url")) or logo_file_exists


def onboarding_status(company: dict, logo_file_exists: bool) -> dict:
    """جاهزية وكيلَي الشركة: الشعار، بنك الأسلوب، وقاعدة الأسعار والسوق."""
    from .style_engine import MIN_STYLE_DOCS
    c = cid()
    with get_db() as db:
        style_docs = db.execute(
            "SELECT COUNT(*) AS n FROM tech_documents WHERE company_id=? AND is_style_source=1",
            (c,)).fetchone()["n"]
        bank_paras = db.execute(
            "SELECT COUNT(*) AS n FROM tech_paragraphs WHERE company_id=? AND approved=1",
            (c,)).fetchone()["n"]
        price_items = db.execute(
            "SELECT COUNT(*) AS n FROM price_items WHERE company_id=?", (c,)).fetchone()["n"]
        market = db.execute(
            "SELECT COUNT(*) AS n FROM market_prices WHERE company_id=?", (c,)).fetchone()["n"]
        repo_files = db.execute(
            "SELECT COUNT(*) AS n FROM repo_files WHERE company_id=?", (c,)).fetchone()["n"]
        references = db.execute(
            "SELECT COUNT(*) AS n FROM proposals WHERE company_id=?", (c,)).fetchone()["n"]
    logo_ok = has_company_logo(company, logo_file_exists)
    # جاهزية الوكيل الفني: الشعار شرط، ثم مصادر الأسلوب حتى الحد الأدنى
    tech_pct = round(min(1.0, (0.3 if logo_ok else 0)
                     + 0.7 * min(style_docs / MIN_STYLE_DOCS, 1.0)) * 100)
    # جاهزية وكيل التسعير: الشعار + قاعدة أسعار (٥٠ بنداً فأكثر ممتاز) + مراجع
    fin_pct = round(min(1.0, (0.3 if logo_ok else 0)
                    + 0.5 * min(price_items / 50, 1.0)
                    + 0.2 * min((market + references) / 5, 1.0)) * 100)
    settings = get_settings()
    return {
        "logo": logo_ok,
        "brand_color": settings.get("brand_color", ""),
        "style_docs": style_docs, "style_docs_target": MIN_STYLE_DOCS,
        "bank_paragraphs": bank_paras,
        "price_items": price_items, "market_prices": market,
        "repo_files": repo_files, "proposals": references,
        "tech_readiness": tech_pct, "fin_readiness": fin_pct,
        "done": settings.get("onboarding_done") == "1",
    }


# ------------------------- التحليل (تشغيل جاف) -------------------------

def _boq_coverage(boq: list[dict]) -> dict:
    """تصنيف بنود الجدول حسب مصدر سعرها — تقرير وكيل التسعير."""
    by_source: dict[str, int] = {}
    unpriced = []
    for l in boq:
        src = l.get("source") or "تقدير"
        by_source[src] = by_source.get(src, 0) + 1
        if not l.get("unit_price"):
            unpriced.append(l.get("name", ""))
    total = len(boq)
    priced_confident = sum(n for s, n in by_source.items() if s != "تقدير")
    return {
        "total": total,
        "by_source": [{"source": s, "count": n} for s, n in
                      sorted(by_source.items(), key=lambda kv: -kv[1])],
        "confident_pct": round(priced_confident / total * 100) if total else 0,
        "unpriced": unpriced[:10],
    }


def _tech_coverage(data: dict) -> dict:
    """تغطية بنك الشركة لأقسام العرض — تقرير الوكيل الفني."""
    sections = data.get("technical_sections", [])
    from_bank = [s["title"] for s in sections if s.get("source") == "bank"]
    style = data.get("style", {}) or {}
    return {
        "sections_total": len(sections),
        "from_bank": from_bank,
        "from_bank_count": len(from_bank),
        "bank_ratio": style.get("bank_ratio"),
        "style_score": style.get("score"),
    }


def build_analysis(title: str, client: str, entity_type: str, files_text: str,
                   data: dict, matches: list[dict], onboarding: dict) -> dict:
    """تقرير الوكيلين قبل الاعتماد + التوصيات — من مخرجات التشغيل الجاف الحقيقي."""
    tech = _tech_coverage(data)
    fin = _boq_coverage(data.get("boq", []))
    recommendations = []
    if not onboarding["logo"]:
        recommendations.append({"agent": "both", "level": "blocker",
                                "text": "ارفع شعار الشركة من معالج التهيئة — لا يُعتمد أي عرض بلا هوية الشركة."})
    if onboarding["style_docs"] < onboarding["style_docs_target"]:
        recommendations.append({"agent": "tech", "level": "warn",
                                "text": f"بنك الأسلوب فيه {onboarding['style_docs']} من {onboarding['style_docs_target']} "
                                        "عروض فنية سابقة — كلما رفعت المزيد صار العرض بصوت شركتك لا بصياغة عامة."})
    if tech["from_bank_count"] == 0 and tech["sections_total"]:
        recommendations.append({"agent": "tech", "level": "warn",
                                "text": "لم يُبنَ أي قسم من بنك فقرات شركتك — سيُستخدم أسلوب الانطلاق العام حتى ترفع عروضك السابقة."})
    if not matches:
        recommendations.append({"agent": "both", "level": "info",
                                "text": "لا عروض سابقة مشابهة في الأرشيف — سيُبنى العرض من ملفات المشروع وقاعدة الأسعار مباشرة."})
    if fin["total"] and fin["confident_pct"] < 60:
        recommendations.append({"agent": "fin", "level": "warn",
                                "text": f"{100 - fin['confident_pct']}% من البنود ستُسعَّر تقديرياً — "
                                        "ارفع جداول كميات مسعرة قديمة للمستودع المعرفي لرفع دقة التسعير."})
    if fin["unpriced"]:
        recommendations.append({"agent": "fin", "level": "warn",
                                "text": "بنود بلا سعر إطلاقاً: " + "، ".join(fin["unpriced"][:5])})
    if not recommendations:
        recommendations.append({"agent": "both", "level": "ok",
                                "text": "كل المصادر جاهزة — العرضان سيُبنيان بأسلوب شركتك وأسعارها."})
    return {
        "title": title, "client": client, "entity_type": entity_type,
        "project_kind": data.get("project_kind", ""),
        "similar": [{"ref_no": m.get("ref_no"), "title": m.get("title"),
                     "score": m.get("score")} for m in matches],
        "tech": tech,
        "fin": fin,
        "financial_preview": {
            "direct_cost": data.get("financial", {}).get("direct_cost"),
            "grand_total": data.get("financial", {}).get("grand_total"),
        },
        "onboarding": onboarding,
        "can_generate": onboarding["logo"],
        "recommendations": recommendations,
    }


def save_session(title: str, client: str, entity_type: str, files_text: str,
                 analysis: dict) -> int:
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO agent_sessions (company_id, title, client, entity_type, files_text, "
            " analysis, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (cid(), title, client, entity_type, files_text,
             json.dumps(analysis, ensure_ascii=False), now_iso()),
        )
        return cur.lastrowid


def get_session(sid: int) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM agent_sessions WHERE id=? AND company_id=?",
                         (sid, cid())).fetchone()
    if not row:
        return None
    d = dict(row)
    d["analysis"] = json.loads(d["analysis"] or "{}")
    return d
