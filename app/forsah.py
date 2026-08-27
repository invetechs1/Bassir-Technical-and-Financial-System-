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
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

from .config import DATA_DIR
from .database import get_db, get_settings, now_iso
from .tenancy import cid

BASE = os.environ.get("FORSAH_BASE_URL", "https://forsah.sa")
def _state_file():
    """جلسة المتصفح لكل شركة على حدة."""
    return DATA_DIR / f"forsah_state_{cid()}.json"


STATE_FILE = DATA_DIR / "forsah_state.json"  # توافق خلفي — يُستخدم _state_file() فعلياً

# تصنيفات نشاط عزوم المطلوب سحبها — تُطابَق مع تصنيفات فرصة الفعلية (UUID مكتشف من الصفحة)
CATEGORIES = [
    "المقاولات",
    "الصيانة والتشغيل",
    "التوريد",
    "التصميم الهندسي",
    "الإشراف الهندسي",
]
# كلمات مساعدة للمطابقة المرنة (الموقع قد يكتب التصنيف بصيغة مختلفة قليلاً).
# ملاحظة: تصنيفات فرصة الحقيقية مبنية على نوع السلعة/الخدمة لا على مرحلة المشروع —
# لا يوجد تصنيف عام «توريد» ولا تصنيف منفصل لـ«الإشراف الهندسي»؛ كلاهما يُقارَب هنا
# بأقرب تصنيف فعلي متاح (التوريد: عدة تصنيفات سلعية، الإشراف: الاستشارات الهندسية).
_CAT_KEYWORDS = {
    "المقاولات": ("مقاولات", "مقاولة", "انشاءات", "إنشاءات", "بناء"),
    "الصيانة والتشغيل": ("صيانة", "تشغيل"),
    "التوريد": ("توريد", "معدات", "مواد", "تجهيز"),
    "التصميم الهندسي": ("تصميم", "هندس"),
    "الإشراف الهندسي": ("اشراف", "إشراف", "هندس"),
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
    company_id INTEGER NOT NULL DEFAULT 1,
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
    from .database import _ensure_column
    with get_db() as db:
        db.executescript(SCHEMA)
        _ensure_column(db, "forsah_projects", "company_id", "INTEGER NOT NULL DEFAULT 1")


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
    visible = _strip_noise(html)
    markers = ("logout", "تسجيل الخروج", "خروج", "dashboard", "لوحة", "حسابي", "ملفي")
    return any(m in visible.lower() or m in visible for m in markers)


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

_NOISE_RE = re.compile(r"<(script|style|noscript|template)\b.*?</\1>", re.S | re.I)


def _strip_noise(html: str) -> str:
    """إزالة أكواد JavaScript والأنماط — نصوصها تخدع المستخرج وكاشف الدخول."""
    return _NOISE_RE.sub(" ", html or "")


_A_RE = re.compile(r'<a\b[^>]*href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.S | re.I)
_TAG_STRIP = re.compile(r"<[^>]+>")
_DATE_RE = re.compile(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{4}")
_MONEY_RE = re.compile(r"[\d,.]+\s*(?:ريال|ر\.س|SAR)")
_PROJECT_HREF = re.compile(r"(project|tender|opportunit|مشروع|منافس|/marketplace/[0-9a-f-]{8,})", re.I)


def _clean_text(html_fragment: str) -> str:
    return re.sub(r"\s+", " ", _TAG_STRIP.sub(" ", html_fragment)).strip()


def _category_links(html: str, base_url: str) -> dict:
    """روابط التصنيفات الستة كما يكتبها الموقع نفسه."""
    found = {}
    for href, inner in _A_RE.findall(_strip_noise(html)):
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
    html = _strip_noise(html)
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


def _default_category_urls() -> dict:
    return {cat: f"{BASE}/projects?category={slug}"
            for cat, slug in (("المقاولات", "contracting"), ("الصيانة والتشغيل", "maintenance"),
                              ("النظافة", "cleaning"), ("توريد العمالة", "manpower"),
                              ("التصميم الهندسي", "design"), ("الإشراف الهندسي", "supervision"))}


# ساحة الفرص (marketplace) تصفّي بمعرّفات UUID لتصنيفات حقيقية مرسومة كصناديق اختيار
# في نموذج الفلاتر — نكتشفها من الصفحة نفسها بدل تخمين روابط ثابتة قد تتغيّر.
_CATEGORY_UUID_RE = re.compile(
    r'label="([^"]+)"><input class="[^"]*"[^>]*name="category\.([0-9a-f-]{36})"'
)


def _discover_category_uuids(html: str) -> dict:
    """تصنيفات فرصة الحقيقية (اسم عربي -> UUID) كما تظهر في صناديق فلتر «القطاع»."""
    found = {}
    for label, uid in _CATEGORY_UUID_RE.findall(html):
        found.setdefault(label.strip(), uid)
    return found


def _match_categories_to_uuids(real_cats: dict) -> dict:
    """يطابق تصنيفات عزوم الستة مع تصنيفات فرصة الفعلية بالاسم الحرفي أولاً ثم كلمات مرنة."""
    result = {}
    for cat in CATEGORIES:
        kws = _CAT_KEYWORDS[cat]
        kws = (kws,) if isinstance(kws, str) else kws
        matched = [uid for label, uid in real_cats.items()
                   if label == cat or any(k in label for k in kws)]
        if matched:
            result[cat] = matched[:5]
    return result


class _Counter:
    def __init__(self):
        self.added = 0
        self.scanned = 0


def _store_batch(projects: list[dict], cat: str, counter: _Counter) -> int:
    """تخزين دفعة مشاريع مع درجة الملاءمة — يعيد عدد الجديد في الدفعة."""
    from .similarity import find_similar
    new_count = 0
    for p in projects:
        counter.scanned += 1
        matches = find_similar(f"{p['title']} {cat}", top_n=1)
        relevance = matches[0]["score"] if matches else 0
        matched_ref = matches[0]["title"][:80] if matches else ""
        with get_db() as db:
            cur = db.execute(
                "INSERT OR IGNORE INTO forsah_projects "
                "(company_id, project_key, title, category, city, budget, deadline, details_url, "
                " relevance, matched_ref, raw, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (cid(), p["key"], p["title"], cat, "", p["budget"], p["deadline"],
                 p["url"], relevance, matched_ref, p["raw"], now_iso()),
            )
            if cur.rowcount:
                counter.added += 1
                new_count += 1
    return new_count


# ------------------------- محرك المتصفح الخفي (مواقع JavaScript) -------------------------

def _browser_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except ImportError:
        return False


def _page_logged_in(html: str) -> bool:
    visible = _strip_noise(html)
    return any(m in visible or m in visible.lower()
               for m in ("تسجيل الخروج", "خروج", "logout", "حسابي", "ملفي", "لوحة التحكم"))


# تسجيل الدخول لفرصة يمر عبر منصة هوية موحّدة لمجموعة «تسعة أعشار» على نطاق
# منفصل تماماً عن forsah.sa (اكتُشف عبر رابط «سجل معنا» في قائمة الموقع).
# بعد الدخول تُعيد esso التوجيه لـ forsah.sa مع token في الرابط.
_SSO_LOGIN_URL = (
    "https://esso.910ths.sa/login?redirect_uri="
    + urllib.parse.quote(BASE + "/", safe="") + "&source=forsah&lang=ar&client_id=9"
)


def _browser_login(page, email: str, password: str) -> tuple[bool, str]:
    """تعبئة نموذج الدخول المرسوم بالمتصفح: حقل بريد + كلمة مرور + زر إرسال."""
    for url in (_SSO_LOGIN_URL, f"{BASE}/login", f"{BASE}/ar/login", f"{BASE}/signin", BASE):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(2_500)  # مهلة لرسم النموذج بالجافاسكربت
        except Exception:
            continue
        pw_input = page.locator("input[type='password']").first
        try:
            if not pw_input.is_visible(timeout=4_000):
                continue
        except Exception:
            continue
        user_input = None
        for sel in ("input[name='email']", "input[type='email']", "input[name*='email' i]",
                    "input[name*='user' i]", "input[placeholder*='بريد']",
                    "input[type='text']", "input[type='tel']"):
            loc = page.locator(sel).first
            try:
                if loc.is_visible(timeout=1_000):
                    user_input = loc
                    break
            except Exception:
                continue
        if user_input is None:
            continue
        user_input.fill(email)
        pw_input.fill(password)
        submitted = False
        for sel in ("button[type='submit']", "input[type='submit']",
                    "button:has-text('دخول')", "button:has-text('تسجيل الدخول')",
                    "button:has-text('Login')", "button:has-text('Sign in')"):
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=1_000):
                    btn.click()
                    submitted = True
                    break
            except Exception:
                continue
        if not submitted:
            pw_input.press("Enter")
        try:
            page.wait_for_load_state("networkidle", timeout=20_000)
        except Exception:
            pass
        page.wait_for_timeout(2_500)
        html = page.content()
        still_login_form = False
        try:
            still_login_form = page.locator("input[type='password']").first.is_visible(timeout=1_500)
        except Exception:
            pass
        if _page_logged_in(html) or not still_login_form:
            return True, "تم الدخول بالمتصفح"
        return False, "رفض الموقع بيانات الدخول — تحقق من البريد وكلمة المرور"
    return False, "لم يظهر نموذج دخول في المتصفح — أرسل لنا لقطة صفحة الدخول لنضبط المحدد"


def _browser_render(page, url: str) -> str:
    """فتح صفحة وانتظار رسمها ثم التمرير لأسفل لتحميل القوائم الكسولة."""
    page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:
        pass
    for _ in range(3):
        page.mouse.wheel(0, 2_400)
        page.wait_for_timeout(700)
    return page.content()


def _chromium_executable() -> str | None:
    """أي متصفح كروم/كروميوم متوفر على الجهاز عندما لا يجد Playwright إصداره."""
    import glob
    import shutil
    browsers_dir = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    if browsers_dir:
        for pattern in ("chromium-*/chrome-linux/chrome",
                        "chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell"):
            hits = sorted(glob.glob(str(os.path.join(browsers_dir, pattern))))
            if hits:
                return hits[-1]
    for name in ("google-chrome", "chromium", "chromium-browser"):
        path = shutil.which(name)
        if path:
            return path
    return None


def _browser_fetch(email: str, password: str, max_pages_per_cat: int, counter: _Counter,
                   per_category: dict, problems: list) -> str | None:
    """السحب الكامل بمتصفح خفي. يعيد رسالة خطأ أو None عند النجاح."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:
            exe = _chromium_executable()
            if exe:
                try:
                    browser = p.chromium.launch(headless=True, executable_path=exe)
                except Exception:
                    exe = None
            if not exe:
                return ("متصفح السحب غير مثبت على الخادم — شغّل: "
                        f"playwright install --with-deps chromium ثم أعد المحاولة. ({exc})")
        try:
            used_saved_state = STATE_FILE.exists()
            ctx_kwargs = {"locale": "ar"}
            if used_saved_state:
                ctx_kwargs["storage_state"] = str(STATE_FILE)
            context = browser.new_context(**ctx_kwargs)
            page = context.new_page()
            try:
                home_html = _browser_render(page, BASE)
            except Exception as exc:
                return ("تعذر الوصول لمنصة فرصة (forsah.sa) من هذا الخادم — "
                        f"تأكد من السماح بالاتصال بالنطاق. التفاصيل: {exc}")
            if not _page_logged_in(home_html):
                ok, diag = _browser_login(page, email, password)
                if not ok and used_saved_state:
                    # الجلسة المحفوظة قد تكون منتهية أو فاسدة وتُعطّل نموذج الدخول —
                    # نتجاهلها ونبدأ بسياق نظيف بدل التعثر دائماً حتى تُحذف يدوياً.
                    context.close()
                    context = browser.new_context(locale="ar")
                    page = context.new_page()
                    _browser_render(page, BASE)
                    ok, diag = _browser_login(page, email, password)
                if not ok:
                    return f"فشل تسجيل الدخول لمنصة فرصة: {diag}"
                context.storage_state(path=str(_state_file()))

            # ساحة الفرص (marketplace) هي صفحة القوائم الفعلية — منها نكتشف تصنيفات
            # فرصة الحقيقية (UUID) لنطابقها مع تصنيفات عزوم الستة.
            try:
                marketplace_html = _browser_render(page, f"{BASE}/marketplace")
            except Exception as exc:
                return f"تعذر الوصول لساحة الفرص بعد الدخول. التفاصيل: {exc}"

            real_cats = _discover_category_uuids(marketplace_html)
            cat_uuids = _match_categories_to_uuids(real_cats) if real_cats else {}

            for cat in CATEGORIES:
                uuids = cat_uuids.get(cat)
                if not uuids:
                    problems.append(f"{cat}: لم يُعثر على تصنيف مطابق في فرصة")
                    per_category[cat] = 0
                    continue
                query = "&".join(f"category[{i}]={uid}" for i, uid in enumerate(uuids))
                # status[]=open يقصر النتائج على المنافسات المتاحة فعلياً (غير المنتهية/المعمّدة/الملغاة)
                url = f"{BASE}/marketplace?status[0]=open&{query}"
                before = counter.added
                for pg in range(1, max_pages_per_cat + 1):
                    page_url = url if pg == 1 else f"{url}&page={pg}"
                    try:
                        html = _browser_render(page, page_url)
                    except Exception as exc:
                        problems.append(f"{cat}: {exc}")
                        break
                    projects = _extract_projects(html, page.url)
                    if not projects:
                        break
                    if _store_batch(projects, cat, counter) == 0:
                        break
                per_category[cat] = counter.added - before
            return None
        finally:
            browser.close()


def fetch_projects(max_pages_per_cat: int = 5) -> dict:
    """الدخول بحساب الشركة وسحب مشاريع التصنيفات الستة وتخزين الجديد منها.

    يبدأ بمحرك المتصفح الخفي (يتعامل مع مواقع JavaScript) إن كان Playwright
    مثبتاً، وإلا فمحرك HTTP المباشر."""
    init_forsah_table()
    settings = get_settings()
    email = settings.get("forsah_email", "").strip()
    password = settings.get("forsah_password", "").strip()
    if not email or not password:
        return {"ok": False, "added": 0,
                "error": "أدخل بريد وكلمة مرور منصة فرصة في الحقول أعلاه واحفظهما أولاً "
                         "(تُخزَّن محلياً في قاعدة بيانات نظامك فقط)."}

    counter = _Counter()
    per_category: dict = {}
    problems: list = []

    if _browser_available():
        error = _browser_fetch(email, password, max_pages_per_cat, counter, per_category, problems)
        if error:
            return {"ok": False, "added": counter.added, "error": error}
    else:
        error = _http_fetch(email, password, max_pages_per_cat, counter, per_category, problems)
        if error:
            return {"ok": False, "added": counter.added, "error": error}

    result = {"ok": True, "added": counter.added, "scanned": counter.scanned,
              "by_category": per_category}
    if counter.scanned == 0:
        result["ok"] = False
        result["error"] = ("تم الدخول لكن لم تُرصد مشاريع في صفحات التصنيفات — أرسل لنا "
                           "لقطة من صفحة المشاريع بعد الدخول لنضبط المحلل على بنيتها الفعلية."
                           + (f" ملاحظات: {'؛ '.join(problems[:3])}" if problems else ""))
    elif problems:
        result["note"] = "؛ ".join(problems[:3])
    return result


def _http_fetch(email: str, password: str, max_pages_per_cat: int, counter: _Counter,
                per_category: dict, problems: list) -> str | None:
    """محرك HTTP المباشر (المواقع التقليدية بلا JavaScript). يعيد رسالة خطأ أو None."""
    session = _Session()
    try:
        _, home_url, home_html = session.get(BASE)
    except Exception as exc:
        return ("تعذر الوصول لمنصة فرصة (forsah.sa) من هذا الجهاز — تأكد أن الخادم "
                f"يسمح بالاتصال بالنطاق ثم أعد المحاولة. التفاصيل: {exc}")

    ok, diag = login(session, email, password)
    if not ok:
        return (f"فشل تسجيل الدخول لمنصة فرصة: {diag}. الموقع يعتمد JavaScript — "
                "ثبّت محرك المتصفح على الخادم: pip install playwright ثم "
                "playwright install --with-deps chromium وأعد المحاولة.")

    _, dash_url, dash_html = session.get(BASE)
    cat_links = _category_links(home_html, home_url)
    cat_links.update(_category_links(dash_html, dash_url))
    defaults = _default_category_urls()
    for cat in CATEGORIES:
        cat_links.setdefault(cat, defaults[cat])

    for cat in CATEGORIES:
        url = cat_links[cat]
        before = counter.added
        for pg in range(1, max_pages_per_cat + 1):
            page_url = url if pg == 1 else f"{url}{'&' if '?' in url else '?'}page={pg}"
            try:
                s, final, html = session.get(page_url)
            except Exception as exc:
                problems.append(f"{cat}: {exc}")
                break
            if s >= 400:
                if pg == 1:
                    problems.append(f"{cat}: الصفحة أعادت {s}")
                break
            projects = _extract_projects(html, final)
            if not projects:
                break
            if _store_batch(projects, cat, counter) == 0:
                break
        per_category[cat] = counter.added - before
    return None


def list_projects(category: str = "", status: str = "", q: str = "") -> list[dict]:
    init_forsah_table()
    query = ("SELECT id, project_key, title, category, city, budget, deadline, details_url, "
             "relevance, matched_ref, status, fetched_at FROM forsah_projects WHERE company_id = ?")
    params: list = [cid()]
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
        db.execute("UPDATE forsah_projects SET status = ? WHERE id = ? AND company_id = ?", (status, pid, cid()))
