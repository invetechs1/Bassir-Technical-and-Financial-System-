"""وحدة الربط مع منصة اعتماد.

المسار الأول (يعمل فوراً بدون تسجيل دخول): جلب المنافسات المطروحة من واجهة
الزوار العامة في tenders.etimad.sa وتخزينها محلياً مع درجة ملاءمة لنشاط عزوم
محسوبة من الذاكرة المرجعية.

المسار الثاني (يتطلب دخول نفاذ من جهازك): تنزيل كراسات الشروط — راجع
scripts/etimad_nafath_login.py لحفظ جلسة الدخول.

ملاحظة: يعمل الجلب من جهازك مباشرة؛ بعض البيئات السحابية تحجب نطاق اعتماد.
"""
import json
import re
import ssl
import urllib.parse
import urllib.request
from datetime import datetime

from .config import DATA_DIR
from .database import get_db, now_iso
from .tenancy import cid

VISITOR_API = "https://tenders.etimad.sa/Tender/AllSupplierTendersForVisitorAsync"
VISITOR_API_FALLBACK = "https://tenders.etimad.sa/Tender/AllTendersForVisitorAsync"
DETAILS_URL = "https://tenders.etimad.sa/Tender/DetailsForVisitor?STenderId={}"
COOKIES_FILE = DATA_DIR / "etimad_cookies.json"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://tenders.etimad.sa/Tender/AllTendersForVisitor",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS etimad_tenders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL DEFAULT 1,
    tender_key TEXT NOT NULL,
    name TEXT NOT NULL,
    agency TEXT DEFAULT '',
    activity TEXT DEFAULT '',
    tender_type TEXT DEFAULT '',
    deadline TEXT DEFAULT '',
    booklet_price TEXT DEFAULT '',
    details_url TEXT DEFAULT '',
    relevance INTEGER DEFAULT 0,
    matched_ref TEXT DEFAULT '',
    status TEXT DEFAULT 'جديدة',
    raw TEXT DEFAULT '{}',
    fetched_at TEXT NOT NULL,
    UNIQUE (company_id, tender_key)
);
"""
_COLS = ("id, company_id, tender_key, name, agency, activity, tender_type, deadline, booklet_price, "
         "details_url, relevance, matched_ref, status, raw, fetched_at")


def init_etimad_table():
    from .database import _ensure_column
    with get_db() as db:
        db.executescript(SCHEMA)
        _ensure_column(db, "etimad_tenders", "company_id", "INTEGER NOT NULL DEFAULT 1")
        # ترقية: كان رقم المنافسة فريداً على مستوى النظام كله، فإذا جلبتها شركة أولاً
        # تتجاهلها البقية بصمت («0 جديدة» دائماً) — صار فريداً لكل شركة
        sql = (db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='etimad_tenders'")
               .fetchone() or {"sql": ""})["sql"] or ""
        if "UNIQUE (company_id, tender_key)" not in sql:
            db.executescript(f"""
                ALTER TABLE etimad_tenders RENAME TO etimad_tenders_old;
                {SCHEMA}
                INSERT OR IGNORE INTO etimad_tenders ({_COLS}) SELECT {_COLS} FROM etimad_tenders_old;
                DROP TABLE etimad_tenders_old;
            """)


def _pick(d: dict, *keys, default=""):
    """قراءة مرنة لأسماء الحقول — واجهة اعتماد قد تغيّر التسمية بين الإصدارات."""
    for k in keys:
        for variant in (k, k[0].upper() + k[1:], k.lower()):
            if variant in d and d[variant] not in (None, ""):
                return d[variant]
    return default


def _http_get(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers=_HEADERS)
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        body = resp.read().decode("utf-8", "replace")
    try:
        return json.loads(body)
    except ValueError:
        # صفحة تحقق من جدار الحماية (HTML) بدل البيانات — حجب لعنوان الخادم لا خطأ في النظام
        raise RuntimeError("المنصة أعادت صفحة HTML بدل البيانات (جدار حماية أو حجب لعنوان الخادم)")


def _parse_date(v) -> datetime | None:
    """تواريخ اعتماد بأشكالها: ISO، ‎/Date(ms)/‎، يوم/شهر/سنة."""
    t = str(v or "").strip()
    if not t:
        return None
    m = re.search(r"/Date\((-?\d+)", t)
    if m:
        return datetime.fromtimestamp(int(m.group(1)) / 1000)
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", t)
    if m:
        return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None


def _rows(data) -> list:
    if isinstance(data, list):
        return data
    for k in ("data", "Data", "items", "Items", "tenders", "result"):
        v = data.get(k) if isinstance(data, dict) else None
        if isinstance(v, list):
            return v
    return []


def _total(data) -> int:
    if isinstance(data, dict):
        for k in ("totalCount", "TotalCount", "recordsTotal", "total", "count"):
            try:
                return int(data.get(k) or 0)
            except (TypeError, ValueError):
                continue
    return 0


def _published(t: dict) -> datetime | None:
    return _parse_date(_pick(t, "submitionDate", "tenderPublishDate", "publishDate", "insertDate", "createdAt"))


def _get_page(page: int, page_size: int, errors: list):
    params = urllib.parse.urlencode({"PageSize": page_size, "PageNumber": page})
    for api in (VISITOR_API, VISITOR_API_FALLBACK):
        try:
            return _http_get(f"{api}?{params}")
        except Exception as exc:
            errors.append(f"{api.rsplit('/', 1)[-1]}: {exc}")
    return None


def fetch_tenders(pages: int = 3, page_size: int = 50) -> dict:
    """جلب أحدث المنافسات المفتوحة من واجهة الزوار وتخزين الجديد منها مع درجة الملاءمة.

    واجهة الزوار بلا فلاتر تُعيد كل منافسات المنصة (~288 ألفاً بكل حالاتها) وبترتيب لا
    نتحكم فيه؛ فكان الجلب يقرأ أول 150 نفسها كل مرة — مخزنة مسبقاً — فيُرجع «0 جديدة».
    الآن: يُكتشف الترتيب من تواريخ النشر في الصفحة الأولى؛ إن كان تصاعدياً (الأحدث في
    الآخر) تُقرأ الصفحات من النهاية، وإلا من البداية مع الاستمرار ما دامت الصفحة تأتي
    بجديد (حتى 10 صفحات). المنتهية مواعيدها لا تُخزَّن. ويُعاد تقرير يشرح النتيجة."""
    from .database import list_proposals_full
    from .similarity import find_similar

    init_etimad_table()
    pages = max(1, min(int(pages or 3), 10))
    errors: list = []
    first = _get_page(1, page_size, errors)
    if first is None:
        return {
            "ok": False, "added": 0, "scanned": 0,
            "error": "تعذر الوصول لمنصة اعتماد من الخادم. منصة اعتماد تحجب كثيراً من عناوين "
                     "الخوادم خارج المملكة أو مراكز البيانات — شغّل الجلب من خادم بعنوان سعودي "
                     f"أو من جهازك. التفاصيل: {errors[-1] if errors else ''}",
        }
    rows1, total = _rows(first), _total(first)
    if not rows1:
        keys = list(first.keys())[:8] if isinstance(first, dict) else type(first).__name__
        return {"ok": False, "added": 0, "scanned": 0,
                "error": f"منصة اعتماد ردّت بلا منافسات — قد يكون شكل الاستجابة تغيّر (الحقول: {keys})"}
    d_first, d_last = _published(rows1[0]), _published(rows1[-1])
    ascending = bool(d_first and d_last and d_first < d_last)
    last_page = max(1, -(-total // page_size)) if total else 1
    if ascending and last_page > 1:
        order = list(range(last_page, max(0, last_page - pages), -1))
    else:
        order = list(range(1, 11))

    proposals = list_proposals_full()          # مرة واحدة لا لكل منافسة
    now = datetime.now()
    stats = {"scanned": 0, "added": 0, "existing": 0, "expired": 0}
    read = 0
    for page in order:
        data = first if page == 1 else _get_page(page, page_size, errors)
        rows = _rows(data) if data is not None else []
        if not rows:
            break
        read += 1
        new_here = 0
        for t in rows:
            stats["scanned"] += 1
            key = str(_pick(t, "tenderIdString", "tenderId", "id", default=""))
            name = str(_pick(t, "tenderName", "name"))
            if not key or not name:
                continue
            deadline_raw = _pick(t, "lastOfferPresentationDate", "offersDeadline", "lastEnqueriesDate")
            dl = _parse_date(deadline_raw)
            if dl and dl.date() < now.date():
                stats["expired"] += 1
                continue
            with get_db() as db:
                if db.execute("SELECT 1 FROM etimad_tenders WHERE company_id = ? AND tender_key = ?",
                              (cid(), key)).fetchone():
                    stats["existing"] += 1
                    continue
            agency = str(_pick(t, "agencyName", "agency"))
            matches = find_similar(f"{name} {agency}", top_n=1, proposals=proposals)
            with get_db() as db:
                cur = db.execute(
                    "INSERT OR IGNORE INTO etimad_tenders "
                    "(company_id, tender_key, name, agency, activity, tender_type, deadline, booklet_price, "
                    " details_url, relevance, matched_ref, raw, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (cid(), key, name, agency,
                     str(_pick(t, "tenderActivityName", "activityName")),
                     str(_pick(t, "tenderTypeName", "tenderType")),
                     (dl.strftime("%Y-%m-%d") if dl else str(deadline_raw)[:16]),
                     str(_pick(t, "condetionalBookletPrice", "bookletPrice", "financialFees")),
                     DETAILS_URL.format(urllib.parse.quote(key)),
                     matches[0]["score"] if matches else 0,
                     matches[0]["title"][:80] if matches else "",
                     json.dumps(t, ensure_ascii=False)[:8000], now_iso()),
                )
            if cur.rowcount:
                stats["added"] += 1
                new_here += 1
        # من البداية: نكمل ما دامت الصفحات تأتي بجديد، ونقف عند أول صفحة بلا جديد بعد الحد
        if not ascending and read >= pages and new_here == 0:
            break
    parts = [f"فُحصت {stats['scanned']} منافسة من {read} صفحة"]
    if total:
        parts.append(f"إجمالي المنصة {total:,}")
    parts.append(f"جديدة {stats['added']}")
    if stats["existing"]:
        parts.append(f"موجودة مسبقاً {stats['existing']}")
    if stats["expired"]:
        parts.append(f"منتهية المواعيد (لم تُضف) {stats['expired']}")
    return {"ok": True, **stats, "total": total, "pages_read": read,
            "order": "newest_last" if ascending else "newest_first", "message": " — ".join(parts)}


def list_tenders(status: str = "", q: str = "", min_relevance: int = 0) -> list[dict]:
    init_etimad_table()
    query = ("SELECT id, tender_key, name, agency, activity, tender_type, deadline, "
             "booklet_price, details_url, relevance, matched_ref, status, fetched_at "
             "FROM etimad_tenders WHERE company_id = ? AND relevance >= ?")
    params: list = [cid(), min_relevance]
    if status:
        query += " AND status = ?"
        params.append(status)
    if q:
        query += " AND (name LIKE ? OR agency LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    query += " ORDER BY relevance DESC, id DESC LIMIT 300"
    with get_db() as db:
        rows = db.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def update_tender_status(tid: int, status: str):
    with get_db() as db:
        db.execute("UPDATE etimad_tenders SET status = ? WHERE id = ? AND company_id = ?", (status, tid, cid()))


def has_session() -> bool:
    return COOKIES_FILE.exists()
