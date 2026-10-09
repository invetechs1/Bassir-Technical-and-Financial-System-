"""وكيل تطوير الأعمال — فرص مشاريع القطاع الخاص (Lead Generation).

المنافسات الحكومية لها «اعتماد»؛ أما مشاريع القطاع الخاص فلا منصة موحدة لها،
لذا يعمل هذا الوكيل جامعاً من عدة مصادر قابلة للإعداد من الشاشة (أخبار اقتصادية
وعقارية، إعلانات مطورين) ثم:
1. يرشّح الأخبار الإنشائية ويستخلص منها بطاقة فرصة منظمة (المشروع، المطور/العميل
   الذي يُزار، المدينة، القطاع، المرحلة، القيمة إن ذُكرت) — عبر Claude إن توفر
   المفتاح، وبمستخلص كلمات مفتاحية عند غيابه.
2. يزيل التكرار (نفس المشروع من عدة مصادر = بطاقة واحدة) ويحسب درجة ملاءمة
   لنشاط الشركة من أرشيف عروضها وخدماتها.
3. خط أنابيب تسويقي: جديدة ← موكلة لمسوّق (يصله إشعار جرس/بريد/واتساب) ←
   تمت الزيارة ← طُلب عرض (تتحول لعرض في محرك العروض) ← فوز/خسارة.
4. ملخص يومي بالجديد لأصحاب الشركة وأدمنها.

الإدخال اليدوي السريع جزء أصيل: الفريق يسمع عن مشروع فيسجله بسطر واحد
والنظام يكمل تصنيفه — فلا تعتمد الوحدة على المصادر الآلية وحدها.
"""
import ipaddress
import json
import re
import socket
import ssl
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .database import get_db, get_settings, now_iso, update_settings
from .tenancy import cid

MAX_FETCH_BYTES = 900_000
MAX_ITEMS_PER_SOURCE = 40
MAX_REDIRECTS = 3


class UnsafeSourceURL(ValueError):
    """رابط مصدر يشير إلى عنوان داخلي/خاص — يُرفض لمنع SSRF."""


def _ip_is_blocked(ip: ipaddress._BaseAddress) -> bool:
    """عناوين لا يجوز لوكيل الجمع الوصول إليها — تمنع تسريب خدمات الخادم
    الداخلية وبيانات اعتماد السحابة (169.254.169.254) عبر SSRF."""
    return (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
            or ip.is_multicast or ip.is_unspecified
            or getattr(ip, "is_site_local", False)
            # IPv4-mapped IPv6 (::ffff:127.0.0.1) يُفحص عنوانه الرباعي أيضاً
            or (getattr(ip, "ipv4_mapped", None) is not None
                and _ip_is_blocked(ip.ipv4_mapped)))


def _assert_public_host(host: str):
    """يرفض المضيف متى ثبت أنه داخلي: عنوان رقمي داخلي، أو اسم يحل إلى عنوان
    داخلي (يُفحص كل النتائج لمنع الالتفاف باسم يحل لعنوانين). الاسم الذي لا
    يُحَل لا يُرفض هنا — لا هدف SSRF بلا عنوان — والفحص يُعاد قبل كل جلب فعلي
    (يمسك إعادة ربط DNS لعنوان داخلي لحظة الاتصال)."""
    host = (host or "").strip("[]")
    try:  # عنوان رقمي مباشر
        if _ip_is_blocked(ipaddress.ip_address(host)):
            raise UnsafeSourceURL("عنوان داخلي غير مسموح")
        return
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return  # لا يُحَل الآن → لا عنوان داخلي يُتصل به؛ يُعاد الفحص عند الجلب
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if _ip_is_blocked(ip):
            raise UnsafeSourceURL(f"اسم المضيف يحل إلى عنوان داخلي ({ip})")


def validate_source_url(url: str) -> str:
    """يتحقق أن الرابط http/https ومضيفه عام — يُستدعى عند الحفظ وقبل كل جلب."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UnsafeSourceURL("يُسمح فقط بروابط http/https")
    if not parts.hostname:
        raise UnsafeSourceURL("رابط بلا مضيف")
    _assert_public_host(parts.hostname)
    return url


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """يمنع إعادة التوجيه التلقائي — موقع خارجي قد يُحوِّل إلى عنوان داخلي
    للالتفاف على فحص SSRF، فنتحقق من كل قفزة يدوياً."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL DEFAULT 1,
    lead_key TEXT NOT NULL,
    title TEXT NOT NULL,
    developer TEXT DEFAULT '',
    city TEXT DEFAULT '',
    sector TEXT DEFAULT '',
    stage TEXT DEFAULT '',
    est_value TEXT DEFAULT '',
    contact TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    source_name TEXT DEFAULT '',
    source_url TEXT DEFAULT '',
    relevance INTEGER DEFAULT 0,
    status TEXT DEFAULT 'جديدة',
    assigned_to INTEGER DEFAULT 0,
    visit_notes TEXT DEFAULT '',
    origin TEXT DEFAULT 'manual',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(company_id, lead_key)
);
CREATE TABLE IF NOT EXISTS lead_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL DEFAULT 1,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    last_run TEXT DEFAULT '',
    last_result TEXT DEFAULT '',
    UNIQUE(company_id, url)
);
"""

# مراحل خط الأنابيب التسويقي — بالترتيب
LEAD_STATUSES = ["جديدة", "موكلة", "تمت الزيارة", "طُلب عرض", "فوز", "خسارة", "مستبعدة"]

# مصادر افتراضية تُزرع لكل شركة أول مرة — تُعدَّل وتُعطَّل من الشاشة لا من الكود.
# خلاصات RSS للصحف الاقتصادية السعودية؛ إن تغيّر رابط تُظهر الشاشة الخطأ ويُصحح فوراً.
DEFAULT_SOURCES = [
    ("صحيفة الاقتصادية", "https://www.aleqt.com/rss"),
    ("واس — وكالة الأنباء السعودية", "https://www.spa.gov.sa/rss.xml"),
    ("الشرق الأوسط — اقتصاد", "https://aawsat.com/feed/economy"),
]

# كلمات ترشيح الخبر الإنشائي/العقاري — يكفي ورود واحدة في العنوان أو الموجز
_CONSTRUCTION_KW = (
    "مشروع", "مشاريع", "تطوير", "إنشاء", "انشاء", "إنشاءات", "تشييد", "بناء",
    "برج", "أبراج", "ابراج", "مجمع", "وجهة", "ضاحية", "مخطط", "وحدات سكنية",
    "فندق", "فنادق", "مول", "بنية تحتية", "يوقع", "توقيع عقد", "ترسية",
    "تدشين", "يطلق", "إطلاق", "يدشن", "مقاولات", "عقاري", "عقارية", "عمراني",
)

_SAUDI_CITIES = (
    "الرياض", "جدة", "مكة", "المدينة المنورة", "الدمام", "الخبر", "الظهران",
    "الأحساء", "القطيف", "الجبيل", "ينبع", "الطائف", "أبها", "خميس مشيط",
    "جازان", "نجران", "تبوك", "حائل", "بريدة", "عنيزة", "القصيم", "الباحة",
    "عرعر", "سكاكا", "نيوم", "العلا", "القدية", "البحر الأحمر",
)

_SECTOR_KW = [
    ("سكني", ("سكني", "وحدات سكنية", "فلل", "ضاحية", "إسكان")),
    ("تجاري", ("تجاري", "مول", "مكاتب", "معارض")),
    ("سياحي وفندقي", ("فندق", "فنادق", "منتجع", "سياحي", "ترفيه")),
    ("بنية تحتية", ("بنية تحتية", "طرق", "جسور", "مياه", "صرف", "كهرباء")),
    ("صحي", ("مستشفى", "مركز صحي", "طبي")),
    ("تعليمي", ("مدرسة", "مدارس", "جامعة", "كلية")),
    ("صناعي", ("مصنع", "صناعي", "مستودعات", "لوجستي")),
]

_VALUE_RE = re.compile(r"(\d[\d,.]*)\s*(مليار|مليون|ألف)\s*(ريال|دولار)?")
_DEVELOPER_RE = re.compile(
    r"(?:شركة|مجموعة|مؤسسة|صندوق|هيئة|أمانة|وزارة)\s+[؀-ۿ][؀-ۿ\s]{2,45}")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, text/html, */*",
    "Accept-Language": "ar,en;q=0.8",
}


def init_leads_tables():
    with get_db() as db:
        db.executescript(SCHEMA)


def ensure_default_sources():
    """زرع المصادر الافتراضية للشركة الحالية إن لم يكن لها مصادر بعد."""
    with get_db() as db:
        n = db.execute("SELECT COUNT(*) AS n FROM lead_sources WHERE company_id = ?",
                       (cid(),)).fetchone()["n"]
        if n:
            return
        for name, url in DEFAULT_SOURCES:
            db.execute(
                "INSERT OR IGNORE INTO lead_sources (company_id, name, url) VALUES (?, ?, ?)",
                (cid(), name, url))


# ------------------------- الجلب والتحليل -------------------------

def _fetch_text(url: str, timeout: int = 25) -> str:
    """جلب نص المصدر بأمان: كل قفزة (الأصل وكل إعادة توجيه) تُفحص ضد العناوين
    الداخلية قبل الاتصال، فلا SSRF عبر رابط خبيث أو تحويل مُوجَّه."""
    ctx = ssl.create_default_context()
    opener = urllib.request.build_opener(_NoRedirect)
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        validate_source_url(current)
        req = urllib.request.Request(current, headers=_HEADERS)
        try:
            with opener.open(req, timeout=timeout) as resp:
                return resp.read(MAX_FETCH_BYTES).decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308) and exc.headers.get("Location"):
                current = urljoin(current, exc.headers["Location"])
                continue
            raise
    raise UnsafeSourceURL("تجاوز عدد التحويلات المسموح")


def _strip_tags(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def _parse_rss(content: str) -> list[dict]:
    """عناصر خلاصة RSS/Atom: عنوان + رابط + موجز."""
    items = []
    try:
        root = ET.fromstring(content.encode("utf-8"))
    except ET.ParseError:
        return []
    ns_atom = "{http://www.w3.org/2005/Atom}"
    for it in root.iter("item"):
        items.append({
            "title": _strip_tags((it.findtext("title") or "")),
            "link": (it.findtext("link") or "").strip(),
            "summary": _strip_tags(it.findtext("description") or "")[:500],
        })
    for it in root.iter(f"{ns_atom}entry"):
        link_el = it.find(f"{ns_atom}link")
        items.append({
            "title": _strip_tags(it.findtext(f"{ns_atom}title") or ""),
            "link": (link_el.get("href") if link_el is not None else "") or "",
            "summary": _strip_tags(it.findtext(f"{ns_atom}summary")
                                   or it.findtext(f"{ns_atom}content") or "")[:500],
        })
    return [i for i in items if i["title"]]


class _AnchorParser(HTMLParser):
    """روابط الصفحة ذات النص الطويل — عناوين أخبار مرشحة من صفحات HTML."""
    def __init__(self):
        super().__init__()
        self.anchors, self._href, self._buf = [], None, []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href", "")
            self._buf = []

    def handle_data(self, data):
        if self._href is not None:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            if len(text) >= 25:
                self.anchors.append({"title": text, "link": self._href, "summary": ""})
            self._href = None


def _parse_html(content: str, base_url: str) -> list[dict]:
    p = _AnchorParser()
    try:
        p.feed(content)
    except Exception:
        return []
    from urllib.parse import urljoin
    out, seen = [], set()
    for a in p.anchors:
        if a["title"] in seen:
            continue
        seen.add(a["title"])
        a["link"] = urljoin(base_url, a["link"])
        out.append(a)
    return out


def parse_content(content: str, base_url: str) -> list[dict]:
    """RSS إن كان XML وإلا استخلاص عناوين من HTML."""
    head = content.lstrip()[:200].lower()
    if head.startswith("<?xml") or "<rss" in head or "<feed" in head:
        return _parse_rss(content)
    return _parse_html(content, base_url)


def _is_construction(text: str) -> bool:
    return any(k in text for k in _CONSTRUCTION_KW)


# ------------------------- الاستخلاص -------------------------

# كلمات تُنهي اسم الجهة في الالتقاط البسيط («شركة X للتطوير في جدة» — يقف قبل «في»)
_DEV_STOP = {"في", "بقيمة", "لتنفيذ", "لإنشاء", "توقع", "تطلق", "تعلن", "تبدأ",
             "تدشن", "اليوم", "أمس", "خلال", "عن", "مع", "على", "إلى", "بمدينة"}


def _trim_developer(name: str) -> str:
    toks = name.split()
    for i, t in enumerate(toks[1:], 1):
        if t in _DEV_STOP:
            toks = toks[:i]
            break
    return " ".join(toks)


def _extract_heuristic(item: dict) -> dict:
    """استخلاص بلا ذكاء اصطناعي: مطور/مدينة/قطاع/قيمة من الأنماط الشائعة."""
    text = f"{item['title']} {item.get('summary', '')}"
    dev = _DEVELOPER_RE.search(text)
    city = next((c for c in _SAUDI_CITIES if c in text), "")
    sector = next((name for name, kws in _SECTOR_KW if any(k in text for k in kws)), "")
    val = _VALUE_RE.search(text)
    return {
        "title": item["title"][:200],
        "developer": _trim_developer(dev.group(0).strip())[:80] if dev else "",
        "city": city,
        "sector": sector,
        "stage": "إعلان",
        "est_value": " ".join(x for x in val.groups() if x) if val else "",
        "summary": (item.get("summary") or "")[:400],
    }


_EXTRACT_TOOL = {
    "name": "save_leads",
    "description": "حفظ الفرص الإنشائية المستخلصة من الأخبار",
    "input_schema": {
        "type": "object",
        "properties": {"leads": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "i": {"type": "integer", "description": "رقم الخبر المُدخل"},
                "is_lead": {"type": "boolean",
                            "description": "هل هو مشروع إنشائي/عقاري فيه فرصة أعمال مقاولات فعلية"},
                "title": {"type": "string", "description": "اسم المشروع مختصراً"},
                "developer": {"type": "string", "description": "المالك/المطور — الجهة التي تُزار"},
                "city": {"type": "string"},
                "sector": {"type": "string", "description": "سكني/تجاري/سياحي وفندقي/بنية تحتية/صحي/تعليمي/صناعي"},
                "stage": {"type": "string", "description": "إعلان/تصميم/طرح/تنفيذ"},
                "est_value": {"type": "string", "description": "القيمة التقديرية إن ذُكرت وإلا فارغ"},
                "summary": {"type": "string", "description": "سطران بما يهم مقاولاً يريد العمل فيه"},
            },
            "required": ["i", "is_lead", "title"],
        }}},
        "required": ["leads"],
    },
}


def _extract_ai(items: list[dict]) -> list[dict | None]:
    """استخلاص منظم عبر Claude لدفعة أخبار — يعيد قائمة بطول الدفعة (None لغير الفرصة).

    أي فشل (مفتاح، شبكة، صيغة) يرفع استثناء والمستدعي يرجع للاستخلاص البسيط."""
    import anthropic
    from .ai_engine import _active_model
    from .config import ANTHROPIC_API_KEY

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    numbered = "\n".join(f"[{i}] {it['title']} — {it.get('summary', '')[:200]}"
                         for i, it in enumerate(items))
    msg = client.messages.create(
        model=_active_model(), max_tokens=4000,
        tools=[_EXTRACT_TOOL], tool_choice={"type": "tool", "name": "save_leads"},
        messages=[{"role": "user", "content":
                   "أنت وكيل تطوير أعمال لشركة مقاولات سعودية. من الأخبار التالية حدد "
                   "المشاريع الإنشائية/العقارية التي تمثل فرصة أعمال حقيقية (مشروع سيُبنى "
                   "أو يُطور فعلاً — لا أخبار أسهم أو أرباح أو تحليلات) واستخلص بطاقاتها:\n\n"
                   + numbered}],
    )
    block = next(b for b in msg.content if b.type == "tool_use")
    got = {int(l["i"]): l for l in block.input.get("leads", []) if isinstance(l.get("i"), int)}
    out = []
    for i, it in enumerate(items):
        l = got.get(i)
        if not l or not l.get("is_lead"):
            out.append(None)
            continue
        base = _extract_heuristic(it)   # يكمل ما تركه النموذج فارغاً
        for k in ("title", "developer", "city", "sector", "stage", "est_value", "summary"):
            if (l.get(k) or "").strip():
                base[k] = str(l[k]).strip()[:400]
        out.append(base)
    return out


def extract_leads(items: list[dict]) -> list[dict | None]:
    """الاستخلاص: Claude إن توفر وإلا الأنماط — لا يفشل أبداً."""
    from .ai_engine import ai_available
    if ai_available() and items:
        try:
            return _extract_ai(items[:MAX_ITEMS_PER_SOURCE])
        except Exception:
            pass
    return [_extract_heuristic(it) if _is_construction(f"{it['title']} {it.get('summary', '')}")
            else None for it in items[:MAX_ITEMS_PER_SOURCE]]


# ------------------------- الملاءمة وإزالة التكرار -------------------------

_STOP = {"مشروع", "مشاريع", "شركة", "جديد", "جديدة", "إطلاق", "تطوير", "إنشاء", "على", "إلى"}


def _lead_key(title: str, developer: str = "") -> str:
    """مفتاح إزالة التكرار: أهم مفردات الاسم مرتبةً — نفس المشروع من مصدرين = مفتاح واحد."""
    toks = [t for t in re.split(r"[^؀-ۿA-Za-z0-9]+", f"{title} {developer}")
            if len(t) > 2 and t not in _STOP]
    return "-".join(sorted(set(toks))[:10]) or title[:60]


def _relevance(title: str, summary: str) -> int:
    """درجة ملاءمة لنشاط الشركة: أقرب عرض سابق في الأرشيف + تقاطع مع خدماتها."""
    score = 0
    try:
        from .similarity import find_similar
        matches = find_similar(f"{title}\n{summary}", top_n=1)
        if matches:
            score = matches[0]["score"]
    except Exception:
        pass
    services = get_settings().get("company_services", "")
    if services:
        s_toks = {t for t in re.split(r"[^؀-ۿ]+", services) if len(t) > 3}
        t_toks = {t for t in re.split(r"[^؀-ۿ]+", f"{title} {summary}") if len(t) > 3}
        score += min(len(s_toks & t_toks) * 8, 40)
    return min(score, 100)


# ------------------------- الجمع -------------------------

def ingest_items(source_name: str, items: list[dict]) -> int:
    """ترشيح واستخلاص وتخزين دفعة أخبار — يعيد عدد الفرص الجديدة المضافة."""
    candidates = [it for it in items
                  if _is_construction(f"{it['title']} {it.get('summary', '')}")]
    extracted = extract_leads(candidates)
    added, now = 0, now_iso()
    with get_db() as db:
        for it, lead in zip(candidates, extracted):
            if not lead:
                continue
            key = _lead_key(lead["title"], lead["developer"])
            cur = db.execute("INSERT OR IGNORE INTO leads "
                             "(company_id, lead_key, title, developer, city, sector, stage, "
                             " est_value, summary, source_name, source_url, relevance, "
                             " origin, created_at, updated_at) "
                             "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'collector', ?, ?)",
                             (cid(), key, lead["title"], lead["developer"], lead["city"],
                              lead["sector"], lead["stage"], lead["est_value"], lead["summary"],
                              source_name, it.get("link", ""),
                              _relevance(lead["title"], lead["summary"]), now, now))
            added += cur.rowcount
    return added


def collect_source(source: dict) -> dict:
    """جلب مصدر واحد وتحليله — الخطأ يُسجَّل على المصدر ولا يوقف البقية."""
    try:
        content = _fetch_text(source["url"])
        items = parse_content(content, source["url"])
        added = ingest_items(source["name"], items)
        result = f"✅ {len(items)} خبراً — {added} فرصة جديدة"
        ok = True
    except Exception as exc:
        added, result, ok = 0, f"⚠️ {str(exc)[:180]}", False
    with get_db() as db:
        db.execute("UPDATE lead_sources SET last_run = ?, last_result = ? "
                   "WHERE id = ? AND company_id = ?",
                   (now_iso(), result, source["id"], cid()))
    return {"source": source["name"], "ok": ok, "added": added, "result": result}


def collect_all() -> dict:
    ensure_default_sources()
    with get_db() as db:
        sources = [dict(r) for r in db.execute(
            "SELECT * FROM lead_sources WHERE company_id = ? AND enabled = 1", (cid(),))]
    results = [collect_source(s) for s in sources]
    return {"sources": results, "added": sum(r["added"] for r in results)}


# ------------------------- خط الأنابيب -------------------------

def list_leads(status: str = "", q: str = "", assigned_to: int = 0) -> list[dict]:
    sql = ("SELECT l.*, u.username AS assigned_name FROM leads l "
           "LEFT JOIN users u ON u.id = l.assigned_to WHERE l.company_id = ?")
    args: list = [cid()]
    if status:
        sql += " AND l.status = ?"
        args.append(status)
    if q:
        sql += " AND (l.title LIKE ? OR l.developer LIKE ? OR l.city LIKE ?)"
        args += [f"%{q}%"] * 3
    if assigned_to:
        sql += " AND l.assigned_to = ?"
        args.append(assigned_to)
    with get_db() as db:
        return [dict(r) for r in db.execute(
            sql + " ORDER BY CASE l.status WHEN 'جديدة' THEN 0 WHEN 'موكلة' THEN 1 "
                  "WHEN 'تمت الزيارة' THEN 2 WHEN 'طُلب عرض' THEN 3 ELSE 4 END, "
                  "l.relevance DESC, l.id DESC", args)]


def get_lead(lead_id: int) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM leads WHERE id = ? AND company_id = ?",
                         (lead_id, cid())).fetchone()
    return dict(row) if row else None


def add_manual(text: str, source_note: str = "") -> dict:
    """الإدخال السريع: سطر واحد عن المشروع والنظام يكمل التصنيف والملاءمة."""
    text = (text or "").strip()
    if len(text) < 8:
        raise ValueError("اكتب وصفاً أوضح للفرصة — سطر واحد يكفي")
    item = {"title": text.split("\n")[0][:200], "summary": text[:600], "link": ""}
    lead = extract_leads([item])[0] or _extract_heuristic(item)
    now = now_iso()
    with get_db() as db:
        cur = db.execute(
            "INSERT OR IGNORE INTO leads (company_id, lead_key, title, developer, city, "
            "sector, stage, est_value, summary, source_name, relevance, origin, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'manual', ?, ?)",
            (cid(), _lead_key(lead["title"], lead["developer"]), lead["title"],
             lead["developer"], lead["city"], lead["sector"], lead["stage"],
             lead["est_value"], lead["summary"] or text[:400],
             source_note or "إدخال يدوي", _relevance(lead["title"], text), now, now))
        if not cur.rowcount:
            raise ValueError("فرصة مسجلة من قبل بنفس الاسم — ابحث عنها في القائمة")
        lead_id = cur.lastrowid
    return get_lead(lead_id)


_EDITABLE = ("title", "developer", "city", "sector", "stage", "est_value",
             "contact", "summary", "visit_notes")


def update_lead(lead_id: int, fields: dict) -> dict:
    lead = get_lead(lead_id)
    if not lead:
        raise ValueError("الفرصة غير موجودة")
    sets, args = [], []
    for k in _EDITABLE:
        if k in fields:
            sets.append(f"{k} = ?")
            args.append(str(fields[k] or "").strip())
    status = (fields.get("status") or "").strip()
    if status:
        if status not in LEAD_STATUSES:
            raise ValueError("حالة غير معروفة")
        sets.append("status = ?")
        args.append(status)
    if not sets:
        return lead
    sets.append("updated_at = ?")
    args += [now_iso(), lead_id, cid()]
    with get_db() as db:
        db.execute(f"UPDATE leads SET {', '.join(sets)} WHERE id = ? AND company_id = ?", args)
    return get_lead(lead_id)


def assign_lead(lead_id: int, user_id: int, note: str = "") -> dict:
    """إيكال الفرصة لعضو التسويق — يوصله إشعار جرس + بريد/واتساب إن فُعّلت القنوات."""
    lead = get_lead(lead_id)
    if not lead:
        raise ValueError("الفرصة غير موجودة")
    with get_db() as db:
        member = db.execute(
            "SELECT u.id, u.username FROM users u JOIN memberships m ON m.user_id = u.id "
            "WHERE u.id = ? AND m.company_id = ?", (user_id, cid())).fetchone()
        if not member:
            raise ValueError("المستخدم ليس عضواً في هذه الشركة")
        db.execute("UPDATE leads SET assigned_to = ?, status = 'موكلة', updated_at = ? "
                   "WHERE id = ? AND company_id = ?", (user_id, now_iso(), lead_id, cid()))
    from .execution import notify
    body = " — ".join(x for x in (
        f"المطور/العميل: {lead['developer']}" if lead["developer"] else "",
        f"المدينة: {lead['city']}" if lead["city"] else "",
        note, lead.get("source_url", "")) if x)
    notify(user_id, f"فرصة موكلة إليك للزيارة: {lead['title'][:80]}", body,
           kind="lead", ref=f"lead:{lead_id}")
    return get_lead(lead_id)


def convert_prefill(lead_id: int) -> dict:
    """تحويل الفرصة لعرض: تُنقل لمرحلة «طُلب عرض» وتعاد بيانات تعبئة نموذج التوليد."""
    lead = get_lead(lead_id)
    if not lead:
        raise ValueError("الفرصة غير موجودة")
    with get_db() as db:
        db.execute("UPDATE leads SET status = 'طُلب عرض', updated_at = ? "
                   "WHERE id = ? AND company_id = ?", (now_iso(), lead_id, cid()))
    brief = "\n".join(x for x in (
        lead["summary"],
        f"المدينة: {lead['city']}" if lead["city"] else "",
        f"القطاع: {lead['sector']}" if lead["sector"] else "",
        f"القيمة التقديرية: {lead['est_value']}" if lead["est_value"] else "",
        f"ملاحظات الزيارة: {lead['visit_notes']}" if lead["visit_notes"] else "") if x)
    return {"title": lead["title"], "client": lead["developer"] or lead["title"],
            "entity_type": "private", "files_text": brief}


# ------------------------- المصادر -------------------------

def list_sources() -> list[dict]:
    ensure_default_sources()
    with get_db() as db:
        return [dict(r) for r in db.execute(
            "SELECT * FROM lead_sources WHERE company_id = ? ORDER BY id", (cid(),))]


def upsert_source(data: dict) -> dict:
    name, url = (data.get("name") or "").strip(), (data.get("url") or "").strip()
    if not name or not url.startswith(("http://", "https://")):
        raise ValueError("اسم المصدر ورابط يبدأ بـ https مطلوبان")
    # منع SSRF: لا يُقبل مصدر يشير إلى عنوان داخلي/خاص (خدمات الخادم أو بيانات
    # اعتماد السحابة) — يُفحص عند الحفظ وأيضاً قبل كل جلب (الاسم قد يتغيّر حله)
    try:
        validate_source_url(url)
    except UnsafeSourceURL as exc:
        raise ValueError(f"رابط غير مسموح: {exc}") from None
    with get_db() as db:
        if data.get("id"):
            db.execute("UPDATE lead_sources SET name = ?, url = ?, enabled = ? "
                       "WHERE id = ? AND company_id = ?",
                       (name, url, 1 if data.get("enabled", 1) else 0, data["id"], cid()))
            sid = data["id"]
        else:
            cur = db.execute("INSERT OR IGNORE INTO lead_sources (company_id, name, url) "
                             "VALUES (?, ?, ?)", (cid(), name, url))
            if not cur.rowcount:
                raise ValueError("المصدر مسجل من قبل بنفس الرابط")
            sid = cur.lastrowid
        row = db.execute("SELECT * FROM lead_sources WHERE id = ?", (sid,)).fetchone()
    return dict(row)


def delete_source(source_id: int):
    with get_db() as db:
        db.execute("DELETE FROM lead_sources WHERE id = ? AND company_id = ?",
                   (source_id, cid()))


# ------------------------- الملخص اليومي والجدولة -------------------------

def pipeline_stats() -> dict:
    with get_db() as db:
        rows = db.execute("SELECT status, COUNT(*) AS n FROM leads WHERE company_id = ? "
                          "GROUP BY status", (cid(),)).fetchall()
    counts = {r["status"]: r["n"] for r in rows}
    return {"counts": counts, "total": sum(counts.values()),
            "statuses": LEAD_STATUSES}


def run_daily_digest() -> int:
    """إشعار «جديد السوق اليوم» لأصحاب الشركة وأدمنها — مرة واحدة يومياً."""
    today = now_iso()[:10]
    if get_settings().get("leads_last_digest", "") == today:
        return 0
    with get_db() as db:
        fresh = [dict(r) for r in db.execute(
            "SELECT title, developer, city, relevance FROM leads "
            "WHERE company_id = ? AND status = 'جديدة' AND created_at >= ? "
            "ORDER BY relevance DESC LIMIT 5", (cid(), today))]
        admins = [r["user_id"] for r in db.execute(
            "SELECT user_id FROM memberships WHERE company_id = ? AND role IN ('owner','admin')",
            (cid(),))]
    update_settings({"leads_last_digest": today})
    if not fresh:
        return 0
    lines = [f"• {l['title'][:60]}" + (f" — {l['developer']}" if l['developer'] else "")
             + (f" ({l['city']})" if l['city'] else "") + f" · ملاءمة {l['relevance']}%"
             for l in fresh]
    from .execution import notify
    for uid in admins:
        notify(uid, f"فرص السوق اليوم: {len(fresh)} فرصة جديدة", "\n".join(lines),
               kind="lead", ref="leads")
    return len(fresh)


def scheduled_sweep():
    """دورة الخلفية: جمع + ملخص يومي لكل شركة فعّلت الجمع التلقائي."""
    from . import tenancy
    with get_db() as db:
        company_ids = [r["company_id"] for r in db.execute(
            "SELECT DISTINCT company_id FROM lead_sources WHERE enabled = 1")]
    for company_id in company_ids:
        tokens = tenancy.set_context(company_id, "owner", 0)
        try:
            if get_settings().get("leads_auto_collect", "1") == "1":
                collect_all()
                run_daily_digest()
        except Exception:
            pass
        finally:
            tenancy.reset_context(tokens)


def start_leads_scheduler():
    """خيط خلفي كل ٦ ساعات — الفرص تصل وحدها بلا زر."""
    import threading
    import time

    def _loop():
        time.sleep(120)  # لا نزاحم إقلاع الخادم
        while True:
            try:
                scheduled_sweep()
            except Exception:
                pass
            time.sleep(6 * 3600)

    threading.Thread(target=_loop, daemon=True).start()
