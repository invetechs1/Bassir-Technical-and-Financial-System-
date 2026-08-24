"""وحدة الربط مع منصة فرصة (forsah.sa).

تسجّل الدخول بحساب الشركة (البريد وكلمة المرور تُحفظان محلياً في إعدادات
قاعدة بياناتك فقط — لا تُكتبان في الكود أبداً)، ثم تسحب المشاريع المطروحة
في تصنيفات نشاط عزوم الستة وتخزنها محلياً مع درجة ملاءمة من الذاكرة المرجعية.

المحرك مبني بمرونة: يكتشف نموذج الدخول ورابط كل تصنيف من صفحات الموقع
نفسها، ويجرب مسارات الدخول الشائعة (نموذج HTML ثم JSON API) — فإن تغيّرت
بنية المنصة أو كان الدخول عبر JavaScript فقط، يعيد تشخيصاً عربياً واضحاً
بدل الفشل الصامت.

ملاحظة: بعض البيئات السحابية تحجب النطاق — الجلب يعمل من خادمكم/جهازكم.
"""
import http.cookiejar
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

from .database import get_db, get_settings, now_iso

BASE = "https://forsah.sa"

# تصنيفات نشاط عزوم المطلوب سحبها — تُطابَق مع نصوص روابط الموقع
CATEGORIES = [
    "المقاولات",
    "الصيانة والتشغيل",
    "النظافة",
    "توريد العمالة",
    "التصميم الهندسي",
    "الإشراف الهندسي",
]
# كلمات مساعدة للمطابقة المرنة (الموقع قد يكتب التصنيف بصيغة مختلفة قليلاً)
_CAT_KEYWORDS = {
    "المقاولات": ("مقاولات", "مقاولة", "انشاءات", "إنشاءات", "بناء"),
    "الصيانة والتشغيل": ("صيانة", "تشغيل"),
    "النظافة": ("نظافة", "تنظيف"),
    "توريد العمالة": ("عمالة", "توريد عمالة", "قوى عاملة"),
    "التصميم الهندسي": ("تصميم"),
    "الإشراف الهندسي": ("اشراف", "إشراف"),
}

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "ar,en;q=0.8",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS forsah_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_key TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    category TEXT DEFAULT '',
    city TEXT DEFAULT '',
    budget TEXT DEFAULT '',
    deadline TEXT DEFAULT '',
    details_url TEXT DEFAULT '',
    relevance INTEGER DEFAULT 0,
    matched_ref TEXT DEFAULT '',
    status TEXT DEFAULT 'جديد',
    raw TEXT DEFAULT '',
    fetched_at TEXT NOT NULL
);
"""


def init_forsah_table():
    with get_db() as db:
        db.executescript(SCHEMA)


class _Session:
    """جلسة HTTP بكوكيز — بديل خفيف عن requests بلا اعتماديات إضافية."""

    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        ctx = ssl.create_default_context()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar),
            urllib.request.HTTPSHandler(context=ctx),
        )

    def request(self, url: str, data: bytes | None = None,
                headers: dict | None = None, timeout: int = 30) -> tuple[int, str, str]:
        req = urllib.request.Request(url, data=data, headers={**_HEADERS, **(headers or {})})
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return resp.status, resp.url, body
        except urllib.error.HTTPError as e:
            return e.code, url, e.read().decode("utf-8", errors="replace")

    def get(self, url, **kw):
        return self.request(url, **kw)

    def post_form(self, url, fields: dict, **kw):
        data = urllib.parse.urlencode(fields).encode()
        return self.request(url, data=data,
                            headers={"Content-Type": "application/x-www-form-urlencoded"}, **kw)

    def post_json(self, url, payload: dict, **kw):
        data = json.dumps(payload).encode()
        return self.request(url, data=data,
                            headers={"Content-Type": "application/json",
                                     "Accept": "application/json"}, **kw)


# ------------------------- اكتشاف نموذج الدخول -------------------------

_FORM_RE = re.compile(r"<form\b[^>]*>.*?</form>", re.S | re.I)
_ATTR_RE = re.compile(r"""(\w[\w-]*)\s*=\s*("([^"]*)"|'([^']*)')""")
_INPUT_RE = re.compile(r"<input\b[^>]*>", re.I)


def _attrs(tag: str) -> dict:
    return {m.group(1).lower(): (m.group(3) if m.group(3) is not None else m.group(4) or "")
            for m in _ATTR_RE.finditer(tag)}


def _find_login_form(html: str) -> dict | None:
    """أول نموذج يحوي حقل كلمة مرور: يعيد action وأسماء الحقول والقيم المخفية."""
    for form_html in _FORM_RE.findall(html):
        inputs = [_attrs(t) for t in _INPUT_RE.findall(form_html)]
        pw = next((i for i in inputs if i.get("type", "").lower() == "password"), None)
        if not pw:
            continue
        user_field = next(
            (i for i in inputs
             if i.get("type", "").lower() in ("email", "text", "tel")
             or any(k in i.get("name", "").lower() for k in ("email", "user", "phone", "login"))),
            None)
        form_attrs = _attrs(form_html.split(">", 1)[0] + ">")
        hidden = {i["name"]: i.get("value", "") for i in inputs
                  if i.get("type", "").lower() == "hidden" and i.get("name")}
        return {
            "action": form_attrs.get("action", ""),
            "password_field": pw.get("name", "password"),
            "user_field": (user_field or {}).get("name", "email"),
            "hidden": hidden,
        }
    return None


def _csrf_from_meta(html: str) -> str:
    m = re.search(r'<meta\s+name="csrf-token"\s+content="([^"]+)"', html, re.I)
    return m.group(1) if m else ""


def _logged_in(html: str) -> bool:
    markers = ("logout", "تسجيل الخروج", "خروج", "dashboard", "لوحة", "حسابي", "ملفي")
    return any(m in html.lower() or m in html for m in markers)


def login(session: _Session, email: str, password: str) -> tuple[bool, str]:
    """تسجيل الدخول: نموذج HTML أولاً ثم مسارات JSON الشائعة. يعيد (نجح؟، تشخيص)."""
    login_urls = (f"{BASE}/login", f"{BASE}/ar/login", f"{BASE}/auth/login", f"{BASE}/signin", BASE)
    last_err = ""
    for url in login_urls:
        try:
            status, final_url, html = session.get(url)
        except Exception as exc:
            last_err = str(exc)
            continue
        if status >= 500:
            continue
        form = _find_login_form(html)
        if form:
            action = urllib.parse.urljoin(final_url, form["action"] or final_url)
            fields = {**form["hidden"],
                      form["user_field"]: email,
                      form["password_field"]: password}
            csrf = _csrf_from_meta(html)
            headers = {"Referer": final_url}
            if csrf and not any("csrf" in k.lower() or "token" in k.lower() for k in fields):
                fields["_token"] = csrf
            try:
                s2, u2, body2 = session.request(
                    action, data=urllib.parse.urlencode(fields).encode(),
                    headers={**headers, "Content-Type": "application/x-www-form-urlencoded"})
            except Exception as exc:
                last_err = f"إرسال النموذج: {exc}"
                continue
            if s2 < 400 and ("login" not in u2.lower() or _logged_in(body2)):
                return True, "تم الدخول عبر نموذج الموقع"
            last_err = "رُفض الدخول عبر النموذج — تحقق من البريد وكلمة المرور"
    # مسارات JSON الشائعة (تطبيقات SPA)
    for api in (f"{BASE}/api/login", f"{BASE}/api/auth/login", f"{BASE}/api/v1/login",
                f"{BASE}/api/users/login"):
        for payload in ({"email": email, "password": password},
                        {"username": email, "password": password}):
            try:
                s3, _, body3 = session.post_json(api, payload)
            except Exception as exc:
                last_err = str(exc)
                continue
            if s3 in (200, 201) and ("token" in body3.lower() or "success" in body3.lower()
                                     or _logged_in(body3)):
                # لو أعاد رمز JWT نضيفه للترويسات القادمة
                m = re.search(r'"(?:token|access_token)"\s*:\s*"([^"]+)"', body3)
                if m:
                    _HEADERS["Authorization"] = f"Bearer {m.group(1)}"
                return True, "تم الدخول عبر واجهة JSON"
    return False, last_err or "لم يُعثر على نموذج دخول في الموقع (قد يكون الدخول عبر JavaScript فقط)"


# ------------------------- سحب المشاريع -------------------------

_A_RE = re.compile(r'<a\b[^>]*href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.S | re.I)
_TAG_STRIP = re.compile(r"<[^>]+>")
_DATE_RE = re.compile(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{4}")
_MONEY_RE = re.compile(r"[\d,.]+\s*(?:ريال|ر\.س|SAR)")
_PROJECT_HREF = re.compile(r"(project|tender|opportunit|مشروع|منافس)", re.I)


def _clean_text(html_fragment: str) -> str:
    return re.sub(r"\s+", " ", _TAG_STRIP.sub(" ", html_fragment)).strip()


def _category_links(html: str, base_url: str) -> dict:
    """روابط التصنيفات الستة كما يكتبها الموقع نفسه."""
    found = {}
    for href, inner in _A_RE.findall(html):
        text = _clean_text(inner)
        if not text or len(text) > 60:
            continue
        for cat in CATEGORIES:
            kws = _CAT_KEYWORDS[cat]
            kws = (kws,) if isinstance(kws, str) else kws
            if cat == text or any(k in text for k in kws):
                found.setdefault(cat, urllib.parse.urljoin(base_url, href))
    return found


def _extract_projects(html: str, base_url: str) -> list[dict]:
    """بطاقات المشاريع في صفحة: روابط تفاصيل + العنوان + ما حولها من تاريخ/قيمة."""
    projects, seen = [], set()
    for href, inner in _A_RE.findall(html):
        if not _PROJECT_HREF.search(href):
            continue
        title = _clean_text(inner)
        if len(title) < 10 or title in ("عرض التفاصيل", "التفاصيل", "المزيد"):
            # الرابط زر وليس عنواناً — نحاول العنوان من السياق المحيط
            idx = html.find(href)
            ctx = _clean_text(html[max(0, idx - 600):idx])
            title = ctx[-120:].strip() if len(ctx) > 10 else ""
        if len(title) < 10:
            continue
        url = urllib.parse.urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)
        idx = html.find(href)
        around = _clean_text(html[max(0, idx - 800): idx + 1200])
        date_m = _DATE_RE.search(around)
        money_m = _MONEY_RE.search(around)
        projects.append({
            "key": url, "title": title[:200], "url": url,
            "deadline": date_m.group(0) if date_m else "",
            "budget": money_m.group(0) if money_m else "",
            "raw": around[:1500],
        })
    return projects


def fetch_projects(max_pages_per_cat: int = 5) -> dict:
    """الدخول بحساب الشركة وسحب مشاريع التصنيفات الستة وتخزين الجديد منها."""
    from .similarity import find_similar

    init_forsah_table()
    settings = get_settings()
    email = settings.get("forsah_email", "").strip()
    password = settings.get("forsah_password", "").strip()
    if not email or not password:
        return {"ok": False, "added": 0,
                "error": "أدخل بريد وكلمة مرور منصة فرصة في الحقول أعلاه واحفظهما أولاً "
                         "(تُخزَّن محلياً في قاعدة بيانات نظامك فقط)."}

    session = _Session()
    try:
        status, home_url, home_html = session.get(BASE)
    except Exception as exc:
        return {"ok": False, "added": 0,
                "error": "تعذر الوصول لمنصة فرصة (forsah.sa) من هذا الجهاز — تأكد أن الخادم "
                         f"يسمح بالاتصال بالنطاق ثم أعد المحاولة. التفاصيل: {exc}"}

    ok, diag = login(session, email, password)
    if not ok:
        return {"ok": False, "added": 0,
                "error": f"فشل تسجيل الدخول لمنصة فرصة: {diag}. "
                         "إن كانت البيانات صحيحة والدخول يتم عبر متصفح فقط، أخبرنا لنضيف "
                         "مسار دخول بالمتصفح مثل نفاذ."}

    # صفحة ما بعد الدخول قد تحوي روابط التصنيفات — نجمعها من الرئيسية ولوحة الحساب
    _, dash_url, dash_html = session.get(BASE)
    cat_links = _category_links(home_html, home_url)
    cat_links.update(_category_links(dash_html, dash_url))
    # مسارات شائعة احتياطاً إن لم نجد روابط بالنص
    for cat, slug in (("المقاولات", "contracting"), ("الصيانة والتشغيل", "maintenance"),
                      ("النظافة", "cleaning"), ("توريد العمالة", "manpower"),
                      ("التصميم الهندسي", "design"), ("الإشراف الهندسي", "supervision")):
        cat_links.setdefault(cat, f"{BASE}/projects?category={slug}")

    added, scanned = 0, 0
    per_category, problems = {}, []
    for cat in CATEGORIES:
        url = cat_links.get(cat)
        cat_added = 0
        for page in range(1, max_pages_per_cat + 1):
            page_url = url if page == 1 else (
                f"{url}{'&' if '?' in url else '?'}page={page}")
            try:
                s, final, html = session.get(page_url)
            except Exception as exc:
                problems.append(f"{cat}: {exc}")
                break
            if s >= 400:
                if page == 1:
                    problems.append(f"{cat}: الصفحة أعادت {s}")
                break
            projects = _extract_projects(html, final)
            if not projects:
                break
            new_in_page = 0
            for p in projects:
                scanned += 1
                matches = find_similar(f"{p['title']} {cat}", top_n=1)
                relevance = matches[0]["score"] if matches else 0
                matched_ref = matches[0]["title"][:80] if matches else ""
                with get_db() as db:
                    cur = db.execute(
                        "INSERT OR IGNORE INTO forsah_projects "
                        "(project_key, title, category, city, budget, deadline, details_url, "
                        " relevance, matched_ref, raw, fetched_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (p["key"], p["title"], cat, "", p["budget"], p["deadline"],
                         p["url"], relevance, matched_ref, p["raw"], now_iso()),
                    )
                    if cur.rowcount:
                        added += 1
                        cat_added += 1
                        new_in_page += 1
            if new_in_page == 0:
                break  # لا جديد — توقف عن التصفح
        per_category[cat] = cat_added

    result = {"ok": True, "added": added, "scanned": scanned, "by_category": per_category}
    if scanned == 0:
        result["ok"] = False
        result["error"] = ("تم الدخول بنجاح لكن لم تُرصد مشاريع في صفحات التصنيفات — "
                           "غالباً تُحمَّل القوائم عبر JavaScript. أرسل لنا لقطة من صفحة "
                           "المشاريع بعد الدخول لنضبط المحلل على بنيتها الفعلية."
                           + (f" ملاحظات: {'؛ '.join(problems[:3])}" if problems else ""))
    elif problems:
        result["note"] = "؛ ".join(problems[:3])
    return result


def list_projects(category: str = "", status: str = "", q: str = "") -> list[dict]:
    init_forsah_table()
    query = ("SELECT id, project_key, title, category, city, budget, deadline, details_url, "
             "relevance, matched_ref, status, fetched_at FROM forsah_projects WHERE 1=1")
    params: list = []
    if category:
        query += " AND category = ?"
        params.append(category)
    if status:
        query += " AND status = ?"
        params.append(status)
    if q:
        query += " AND title LIKE ?"
        params.append(f"%{q}%")
    query += " ORDER BY relevance DESC, id DESC LIMIT 400"
    with get_db() as db:
        rows = db.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def update_project_status(pid: int, status: str):
    with get_db() as db:
        db.execute("UPDATE forsah_projects SET status = ? WHERE id = ?", (status, pid))
