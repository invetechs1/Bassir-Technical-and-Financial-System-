"""نظام عزوم للعروض الفنية والمالية — خادم التطبيق."""
import csv
import io
import os
import re
import tempfile
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import database as db
from . import tenancy
from .auth import (LOGIN_PAGE, SESSION_COOKIE, authenticate, change_password,
                   create_session_token, init_auth, verify_session_token)
from .ai_engine import ai_available, generate_proposal_ai
from .analytics import compute_analytics
from .config import BRAND, DATA_DIR, DEFAULT_SETTINGS, EXPORTS_DIR
from . import security
from .security import enforce_rate, is_https, read_upload
from .export_docx import export_proposal_docx
from .export_xlsx import export_boq_xlsx
from .file_extract import extract_text
from .proposal_builder import build_template_proposal, compute_financials, match_price_catalog
from .etimad import fetch_tenders, has_session, list_tenders, update_tender_status
from .opportunity import analyze_opportunity
from .repository import find_relevant_repo_texts, ingest_file
from . import agents
from . import execution
from .seed import seed_if_empty
from .similarity import find_similar, get_reference_content

app = FastAPI(title="نظام عزوم للعروض الفنية والمالية", version="1.0.0")

STATIC_DIR = Path(__file__).parent / "static"


@app.on_event("startup")
def startup():
    db.init_db()
    init_auth()
    seed_if_empty()
    from .style_engine import init_style_tables, migrate_repo_to_tech
    init_style_tables()
    migrate_repo_to_tech()
    execution.init_execution_tables()
    agents.init_agent_tables()
    _convert_legacy_logos()
    _cleanup_stale_exports()
    if os.environ.get("AZOOM_DISABLE_BACKGROUND") != "1":
        from .model_updater import refresh_active_model, start_background_checker
        threading.Thread(target=refresh_active_model, daemon=True).start()  # فحص فوري عند الإقلاع
        start_background_checker()
        _start_invoice_scheduler()


def _cleanup_stale_exports():
    """ملفات التصدير المؤقتة العالقة (انقطاع أثناء التنزيل) — تُحذف بعد ساعة."""
    cutoff = time.time() - 3600
    for f in EXPORTS_DIR.glob("*"):
        try:
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass


def _start_invoice_scheduler():
    """إصدار الفواتير الشهرية آلياً: فحص كل 6 ساعات، والإصدار نفسه لا يتكرر
    (فهرس فريد لكل شركة/فترة) — فلا يعتمد الإيراد على أن يضغط أحد الزر."""
    def _loop():
        while True:
            try:
                db.issue_monthly_invoices()
            except Exception:
                pass
            time.sleep(6 * 3600)
    threading.Thread(target=_loop, daemon=True).start()


def _convert_legacy_logos():
    """شعارات WebP القديمة → PNG (Word لا يدعم WebP فكانت تخرج الوثائق بلا شعار)."""
    try:
        for f in (DATA_DIR / "branding").glob("logo_*.webp"):
            png = f.with_suffix(".png")
            png.write_bytes(_normalize_logo(f.read_bytes())[0])
            f.unlink()
    except Exception:
        pass


# ------------------------------ المصادقة والصلاحيات ------------------------------

_OPEN_PATHS = ("/login", "/api/login", "/signup", "/api/signup", "/static/", "/favicon")
COMPANY_COOKIE = "azoom_company"

# الصفحات الخمس الإدارية — القراءة والكتابة على الأدمن (owner/admin) فقط
_ADMIN_API_PREFIXES = ("/api/prices", "/api/library", "/api/repo", "/api/market", "/api/analytics",
                       "/api/repository", "/api/style-profile", "/api/paragraph-bank", "/api/paragraphs")
# مسارات يجوز فيها غير-GET لدور المشاهد (شؤون حسابه فقط)
_VIEWER_WRITE_OK = ("/api/logout", "/api/password", "/api/session/company",
                    "/api/notifications")
# مهندس الموقع: وحدة تنفيذ المشاريع وشؤون حسابه فقط — لا اطلاع على العروض والأسعار
_ENGINEER_ALLOWED = ("/api/me", "/api/status", "/api/execution", "/api/notifications",
                     "/api/logout", "/api/password", "/api/session/company")
# مسارات لا تُحجب حتى عن شركة موقوفة: الخروج، وتبديل الشركة، وهوية الحساب —
# وإلا حُبس المستخدم داخل شركة موقوفة بلا مخرج
_LIFECYCLE_EXEMPT = ("/api/logout", "/api/me", "/api/session/company")


def _under(path: str, prefixes: tuple) -> bool:
    """مطابقة على حدود المقطع: /api/me يطابق /api/me و/api/me/companies لا /api/members
    (كانت startswith الخام تفتح /api/members لمهندس الموقع وتحجب مسارات غير مقصودة)."""
    return any(path == p or path.startswith(p + "/") for p in prefixes)


# ملاحظة ترتيب: Starlette يجعل آخر @app.middleware مُسجَّل هو الأخارجي (ينفَّذ أولاً
# على الطلب، وأخيراً على الرد) — لذا security_headers يُسجَّل بعد auth_guard هنا،
# ليُغلِّف حتى الردود المبكرة (401/403) التي يعيدها auth_guard دون استدعاء call_next.
# تسجيلهما بالترتيب المعاكس كان يُخرج ردود auth_guard المبكرة بلا ترويسات أمان.
@app.middleware("http")
async def auth_guard(request: Request, call_next):
    path = request.url.path
    if any(path == p or path.startswith(p) for p in _OPEN_PATHS):
        return await call_next(request)
    username = verify_session_token(request.cookies.get(SESSION_COOKIE))
    if not username:
        if path.startswith("/api/"):
            return JSONResponse({"detail": "غير مصرح — سجّل الدخول أولاً"}, status_code=401)
        return RedirectResponse("/login")

    # حل الشركة الحالية: كوكي الشركة إن كانت متاحة له، وإلا أول عضوياته.
    # مدير المنصة يرى كل الشركات (للدعم) — بدونه كانت كوكي شركة غير عضو فيها تُهمل صامتة.
    from .auth import get_user
    user = get_user(username)
    if not user:
        return JSONResponse({"detail": "الحساب غير موجود"}, status_code=401)
    is_platform_admin = bool(user.get("is_platform_admin"))
    companies = db.user_companies(user["id"], include_all=is_platform_admin)
    if not companies:
        return JSONResponse({"detail": "لا عضوية لك في أي شركة — راجع مدير المنصة"}, status_code=403)
    wanted = request.cookies.get(COMPANY_COOKIE, "")
    current = next((c for c in companies if str(c["id"]) == wanted), companies[0])

    request.state.username = username
    request.state.user_id = user["id"]
    request.state.role = current["role"]
    request.state.company_id = current["id"]
    request.state.company_name = current["name"]
    request.state.is_platform_admin = is_platform_admin

    # فرض الأدوار في الخادم — إخفاء الأزرار في الواجهة ليس حماية
    role = current["role"]
    is_admin = role in tenancy.ADMIN_ROLES
    if _under(path, _ADMIN_API_PREFIXES) and not is_admin:
        return JSONResponse({"detail": "هذه الصفحة للأدمن فقط"}, status_code=403)
    if role == "viewer" and request.method not in ("GET", "HEAD") \
            and not _under(path, _VIEWER_WRITE_OK):
        return JSONResponse({"detail": "دورك (مُشاهد) للقراءة والتصدير فقط"}, status_code=403)
    if role == "engineer" and path.startswith("/api/") and not _under(path, _ENGINEER_ALLOWED):
        return JSONResponse({"detail": "دورك (مهندس موقع) مقصور على وحدة تنفيذ المشاريع"},
                            status_code=403)

    # دورة حياة الاشتراك: منتهي التجربة قراءة وتصدير فقط، والموقوف محجوب.
    # مدير المنصة معفى — هو من يعيد التفعيل ويدعم الشركات الموقوفة.
    company_row = db.get_company(current["id"]) or {}
    sub_status = db.effective_subscription_status(company_row)
    request.state.sub_status = sub_status
    if not is_platform_admin:
        if sub_status == "suspended" and not _under(path, _LIFECYCLE_EXEMPT):
            return JSONResponse({"detail": "الاشتراك موقوف — تواصلوا معنا لإعادة التفعيل. بياناتكم محفوظة."},
                                status_code=402)
        if sub_status == "read_only" and request.method not in ("GET", "HEAD") \
                and not _under(path, _VIEWER_WRITE_OK):
            return JSONResponse({"detail": "انتهت فترة التجربة — القراءة والتصدير متاحان، ورقّوا الاشتراك للمتابعة."},
                                status_code=402)

    # بوابات الميزات: 402 لا 403 — الواجهة تعرض دعوة الترقية
    limits = tenancy.PLAN_LIMITS.get(company_row.get("plan", "trial"), tenancy.PLAN_LIMITS["trial"])
    if _under(path, ("/api/etimad", "/api/forsah")) and not limits.get("integrations"):
        return JSONResponse({"detail": "ربط اعتماد وفرصة متاح في الخطة الاحترافية فأعلى — رقّوا الاشتراك."},
                            status_code=402)
    if _under(path, ("/api/style-profile", "/api/paragraph-bank", "/api/paragraphs",
                     "/api/repository/technical")) and not limits.get("style_engine"):
        return JSONResponse({"detail": "بصمة الكتابة وبنك الفقرات متاحان في الخطة الاحترافية فأعلى — رقّوا الاشتراك."},
                            status_code=402)

    tokens = tenancy.set_context(current["id"], role, user["id"], is_platform_admin)
    try:
        return await call_next(request)
    finally:
        tenancy.reset_context(tokens)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if is_https(request):
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response


@app.get("/login", response_class=HTMLResponse)
def login_page():
    return LOGIN_PAGE


def _text(value, limit: int = 300) -> str:
    """حقل نصي من JSON: غير النص يُهمل بدل أن يرمي خطأ 500."""
    return value.strip()[:limit] if isinstance(value, str) else ""


@app.post("/api/login")
def api_login(request: Request, body: dict):
    username = _text(body.get("username"), 100)
    password = body.get("password") if isinstance(body.get("password"), str) else ""
    ip = security.client_ip(request)
    # تحديد المحاولات الفاشلة: لكل مستخدم ولكل عنوان — يوقف التخمين دون قفل الجميع
    enforce_rate(security.LOGIN_USER_LIMITER, username.lower(), "محاولات دخول كثيرة لهذا الحساب")
    enforce_rate(security.LOGIN_IP_LIMITER, ip, "محاولات دخول كثيرة من هذا الجهاز")
    user = authenticate(username, password)
    if not user:
        security.LOGIN_USER_LIMITER.hit(username.lower())
        security.LOGIN_IP_LIMITER.hit(ip)
        raise HTTPException(401, "بيانات الدخول غير صحيحة")
    security.LOGIN_USER_LIMITER.reset(username.lower())
    companies = db.user_companies(user["id"], include_all=bool(user.get("is_platform_admin")))
    response = JSONResponse({"ok": True, "user": user, "companies": companies})
    response.set_cookie(SESSION_COOKIE, create_session_token(user["username"]),
                        httponly=True, samesite="lax", max_age=12 * 3600,
                        secure=is_https(request))
    return response


@app.post("/api/logout")
def api_logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE)
    response.delete_cookie(COMPANY_COOKIE)
    return response


@app.get("/api/me")
def api_me(request: Request):
    company = db.get_company(request.state.company_id) or {}
    return {
        "username": request.state.username,
        "user_id": request.state.user_id,
        "role": request.state.role,
        "role_ar": tenancy.ROLE_AR.get(request.state.role, request.state.role),
        "is_admin": request.state.role in tenancy.ADMIN_ROLES,
        "is_platform_admin": request.state.is_platform_admin,
        "company_id": request.state.company_id,
        "company_name": request.state.company_name,
        "company_short": company.get("short_name", ""),
        "plan": company.get("plan", "trial"),
        "plan_ar": tenancy.PLAN_AR.get(company.get("plan", ""), company.get("plan", "")),
        "logo_url": company.get("logo_url") or "",
        "brand_color": _brand_color(request.state.company_id),
    }


@app.post("/api/password")
def api_password(request: Request, body: dict):
    ok = change_password(request.state.username, body.get("old", ""), body.get("new", ""))
    if not ok:
        raise HTTPException(400, "كلمة المرور الحالية غير صحيحة أو الجديدة أقصر من 8 أحرف")
    return {"ok": True}


# ------------------------------ الشركات والأعضاء (SaaS) ------------------------------

def _require_admin(request: Request):
    if request.state.role not in tenancy.ADMIN_ROLES and not request.state.is_platform_admin:
        raise HTTPException(403, "هذه العملية للأدمن فقط")


def _require_platform_admin(request: Request):
    if not request.state.is_platform_admin:
        raise HTTPException(403, "هذه العملية لمدير المنصة فقط")


def _enforce_limit(request: Request, kind: str):
    """حدود الخطة — تُفحص قبل الفعل لا في الواجهة."""
    company = db.get_company(request.state.company_id) or {}
    limits = tenancy.PLAN_LIMITS.get(company.get("plan", "trial"), tenancy.PLAN_LIMITS["trial"])
    limit = limits.get(kind)
    if limit is None:
        return
    usage = db.company_usage(request.state.company_id)
    used = {"users": usage["users"], "proposals_month": usage["proposals_month"],
            "price_items": usage["price_items"]}.get(kind, 0)
    if used >= limit:
        raise HTTPException(402, f"بلغتم حد خطة «{tenancy.PLAN_AR.get(company.get('plan'), '')}» "
                                 f"({limit}) — رقّوا الاشتراك للمتابعة")


@app.get("/api/me/companies")
def my_companies(request: Request):
    return db.user_companies(request.state.user_id, include_all=request.state.is_platform_admin)


@app.post("/api/session/company/{company_id}")
def switch_company(request: Request, company_id: int):
    m = db.get_membership(request.state.user_id, company_id)
    if not m and not request.state.is_platform_admin:
        raise HTTPException(403, "لا تملك عضوية في هذه الشركة")
    if not db.get_company(company_id):
        raise HTTPException(404, "الشركة غير موجودة")
    role = m["role"] if m else "admin"
    response = JSONResponse({"ok": True, "role": role})
    response.set_cookie(COMPANY_COOKIE, str(company_id), httponly=True,
                        samesite="lax", max_age=90 * 24 * 3600, secure=is_https(request))
    return response


@app.get("/api/companies")
def companies_list(request: Request):
    _require_platform_admin(request)
    out = []
    for c in db.list_companies():
        out.append({**c, "usage": db.company_usage(c["id"]),
                   "limits": tenancy.PLAN_LIMITS.get(c["plan"], {}),
                   "monthly_price": db.company_monthly_price(c),
                   "effective_status": db.effective_subscription_status(c)})
    return out


@app.get("/api/plans")
def plans_list(request: Request):
    """بيانات الخطط (الأسعار والحدود) لعرضها في مقارنة الخطط ونموذج تسجيل الشركة."""
    return [
        {"id": p, "name_ar": tenancy.PLAN_AR.get(p, p), "price": tenancy.PLAN_PRICE.get(p),
         **tenancy.PLAN_LIMITS.get(p, {})}
        for p in ("trial", "basic", "pro", "enterprise")
    ]


@app.post("/api/companies")
def companies_create(request: Request, body: dict):
    """إنشاء شركة جديدة مع مالك حسابها — لمدير المنصة فقط."""
    _require_platform_admin(request)
    name = _text(body.get("name"), 200)
    if not name:
        raise HTTPException(400, "اسم الشركة مطلوب")
    plan = _text(body.get("plan"), 20) or "trial"
    if plan not in tenancy.PLAN_LIMITS:
        raise HTTPException(400, f"خطة غير معروفة — المتاح: {', '.join(tenancy.PLAN_LIMITS)}")
    if db.find_company_by_name(name):
        raise HTTPException(409, "توجد شركة بهذا الاسم مسبقاً")
    from .notify_channels import normalize_phone
    try:
        phone = normalize_phone(_text(body.get("contact_phone"), 40))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    company = db.create_company(name, _text(body.get("short_name"), 60), plan,
                                _text(body.get("sector"), 100), _text(body.get("cr_no"), 40),
                                _text(body.get("vat_no"), 40),
                                _text(body.get("currency"), 8) or "SAR", phone)
    owner_username = _text(body.get("owner_username"), 100)
    if owner_username:
        from .auth import create_user, get_user
        owner = get_user(owner_username)
        if not owner:
            password = body.get("owner_password") or ""
            try:
                owner = create_user(owner_username, password, body.get("owner_display_name", ""))
            except ValueError as exc:
                raise HTTPException(400, str(exc))
        db.set_membership(owner["id"], company["id"], "owner", request.state.user_id)
    db.log_audit("companies", company["id"], "create", name)
    return company


@app.put("/api/companies/{company_id}")
def companies_update(request: Request, company_id: int, body: dict):
    """ترقية/تخفيض اشتراك شركة وتسعيرها المتفاوض عليه وحالتها — لمدير المنصة.

    plan: الخطة (لا عودة إلى «تجريبي»)، custom_price: سعر شهري متفاوض عليه (null يعيد
    سعر الخطة القياسي)، status: active | read_only | suspended."""
    _require_platform_admin(request)
    try:
        company = db.update_company_plan(
            company_id,
            plan=body.get("plan"),
            custom_price=body.get("custom_price"),
            set_custom_price="custom_price" in body,
            status=body.get("status"),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.log_audit("companies", company_id, "plan_update",
                 f"plan={company['plan']} custom_price={company.get('custom_price')} "
                 f"status={company.get('subscription_status')}")
    return {**company, "monthly_price": db.company_monthly_price(company),
            "effective_status": db.effective_subscription_status(company)}


@app.get("/api/members")
def members_list(request: Request):
    _require_admin(request)
    return db.company_members(request.state.company_id)


@app.post("/api/members")
def members_invite(request: Request, body: dict):
    """دعوة مستخدم للشركة الحالية بدور محدد — أدمن فما فوق، والمالك فقط يمنح owner."""
    _require_admin(request)
    role = body.get("role", "viewer")
    if role not in tenancy.ROLES:
        raise HTTPException(400, f"الدور غير معروف — المتاح: {', '.join(tenancy.ROLES)}")
    if role == "owner" and request.state.role != "owner" and not request.state.is_platform_admin:
        raise HTTPException(403, "منح دور مالك الحساب للمالك فقط")
    _enforce_limit(request, "users")
    username = _text(body.get("username"), 100)
    if not username:
        raise HTTPException(400, "اسم المستخدم مطلوب")
    from .notify_channels import normalize_email, normalize_phone
    try:   # يُتحقق من جهات الاتصال قبل إنشاء أي حساب — فلا يبقى مستخدم يتيم عند الرفض
        email = normalize_email(_text(body.get("email"), 200))
        phone = normalize_phone(_text(body.get("phone"), 40))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    from .auth import create_user, get_user
    user = get_user(username)
    if not user:
        try:
            user = create_user(username, body.get("password") or "",
                               body.get("display_name", ""))
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    db.set_membership(user["id"], request.state.company_id, role, request.state.user_id)
    if email or phone:
        db.set_user_contact(user["id"], email, phone)
    db.log_audit("memberships", user["id"], "invite", f"{username} → {role}")
    return {"ok": True, "user_id": user["id"], "role": role}


def _owner_count(company_id: int) -> int:
    return sum(1 for m in db.company_members(company_id) if m["role"] == "owner")


@app.put("/api/members/{uid}")
def members_role(request: Request, uid: int, body: dict):
    """تغيير دور عضو — المالك أو مدير المنصة."""
    if request.state.role != "owner" and not request.state.is_platform_admin:
        raise HTTPException(403, "تغيير الأدوار لمالك الحساب فقط")
    role = body.get("role", "")
    if role not in tenancy.ROLES:
        raise HTTPException(400, "الدور غير معروف")
    target = db.get_membership(uid, request.state.company_id)
    if not target:
        raise HTTPException(404, "العضو غير موجود في هذه الشركة")
    if target["role"] == "owner" and role != "owner" and _owner_count(request.state.company_id) <= 1:
        raise HTTPException(400, "لا يمكن تخفيض آخر مالك للحساب — عيّن مالكاً آخر أولاً")
    db.set_membership(uid, request.state.company_id, role)
    db.log_audit("memberships", uid, "role_change", role)
    return {"ok": True}


@app.delete("/api/members/{uid}")
def members_remove(request: Request, uid: int):
    if request.state.role != "owner" and not request.state.is_platform_admin:
        raise HTTPException(403, "إزالة الأعضاء لمالك الحساب فقط")
    if uid == request.state.user_id:
        raise HTTPException(400, "لا يمكنك إزالة نفسك")
    target = db.get_membership(uid, request.state.company_id)
    if target and target["role"] == "owner" and _owner_count(request.state.company_id) <= 1:
        raise HTTPException(400, "لا يمكن إزالة آخر مالك للحساب")
    db.remove_membership(uid, request.state.company_id)
    db.log_audit("memberships", uid, "remove")
    return {"ok": True}


# شعار كل شركة — الصيغ النقطية فقط (SVG مرفوض: ثغرة XSS إن عُرض بلا تعقيم)
_MAX_LOGO_BYTES = 2 * 1024 * 1024
_MAX_LOGO_PIXELS = 25_000_000
_BRAND_COLORS = ["#175934", "#2E7D8C", "#7A5A2E", "#5A3E86"]


def _normalize_logo(content: bytes) -> tuple[bytes, str]:
    """يتحقق أن الملف صورة حقيقية (لا يُصدَّق content_type القادم من العميل)، ويعيد
    ترميزه PNG نظيفاً مصغّراً — فيُزال أي محتوى مخفي، ويُحلّ WebP الذي لا يدعمه Word."""
    try:
        from PIL import Image
    except ImportError:
        raise HTTPException(500, "مكتبة معالجة الصور (Pillow) غير مثبتة على الخادم")
    try:
        img = Image.open(io.BytesIO(content))
        if img.format not in ("PNG", "JPEG", "WEBP"):
            raise ValueError(img.format)
        if img.width * img.height > _MAX_LOGO_PIXELS:
            raise ValueError("huge")
        img.load()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(415, "الملف ليس صورة صالحة — الصيغ المقبولة: PNG أو JPG أو WebP (حتى 2 ميجابايت)")
    img.thumbnail((1000, 1000))
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "transparency" in img.info or img.mode in ("LA", "PA", "P") else "RGB")
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue(), ".png"


def _brand_color(company_id: int) -> str:
    custom = (db.get_settings(company_id).get("brand_color") or "").strip()
    if custom.startswith("#") and len(custom) == 7:
        return custom
    if company_id == 1:   # عزوم: أخضر هويتها الرسمي لا لوناً من لوحة المستأجرين (كانت وثائقها تخرج تركوازية)
        return "#" + BRAND["primary"]
    return _BRAND_COLORS[company_id % len(_BRAND_COLORS)]


def _company_logo_file(company_id: int):
    """ملف شعار الشركة على القرص: المرفوع أولاً، ثم شعار عزوم الثابت للشركة 1."""
    pth = _logo_path(company_id)
    if pth:
        return pth
    company = db.get_company(company_id) or {}
    if (company.get("logo_url") or "").startswith("/static/"):
        static_file = STATIC_DIR / company["logo_url"].removeprefix("/static/")
        if static_file.exists():
            return static_file
    return None


def _require_company_logo(request: Request):
    """لا يُبنى عرض بلا هوية الشركة — الشعار شرط قبل التوليد."""
    if _company_logo_file(request.state.company_id) is None:
        raise HTTPException(400, "ارفع شعار الشركة أولاً من معالج التهيئة — لا يُبنى عرض بلا هوية الشركة.")


def _logo_path(company_id: int):
    branding = DATA_DIR / "branding"
    branding.mkdir(exist_ok=True)
    for ext in (".png", ".jpg", ".webp"):
        pth = branding / f"logo_{company_id}{ext}"
        if pth.exists():
            return pth
    return None


@app.post("/api/companies/{company_id}/logo")
def upload_company_logo(request: Request, company_id: int, logo: UploadFile = File(...)):
    m = db.get_membership(request.state.user_id, company_id)
    allowed = request.state.is_platform_admin or (m and m["role"] in tenancy.ADMIN_ROLES)
    if not allowed:
        raise HTTPException(403, "رفع الشعار لأدمن الشركة أو مدير المنصة")
    if not db.get_company(company_id):
        raise HTTPException(404, "الشركة غير موجودة")
    content, ext = _normalize_logo(read_upload(logo, _MAX_LOGO_BYTES))
    branding = DATA_DIR / "branding"
    branding.mkdir(exist_ok=True)
    for old_ext in (".png", ".jpg", ".webp"):
        (branding / f"logo_{company_id}{old_ext}").unlink(missing_ok=True)
    (branding / f"logo_{company_id}{ext}").write_bytes(content)
    with db.get_db() as conn:
        conn.execute("UPDATE companies SET logo_url = ? WHERE id = ?",
                     (f"/api/companies/{company_id}/logo", company_id))
    db.log_audit("companies", company_id, "update", "logo uploaded")
    return {"ok": True, "logo_url": f"/api/companies/{company_id}/logo"}


@app.get("/api/companies/{company_id}/logo")
def get_company_logo(request: Request, company_id: int):
    # شعار الشركة لأعضائها ولمدير المنصة فقط — لا يُكشف هوية عملاء لشركات أخرى
    if not request.state.is_platform_admin and not db.get_membership(request.state.user_id, company_id):
        raise HTTPException(403, "لا تملك عضوية في هذه الشركة")
    path = _logo_path(company_id)
    if not path:
        raise HTTPException(404, "لا شعار مرفوعاً لهذه الشركة")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=300"})


@app.get("/api/usage")
def usage(request: Request):
    company = db.get_company(request.state.company_id) or {}
    plan = company.get("plan", "trial")
    return {"usage": db.company_usage(request.state.company_id),
            "plan": plan, "plan_ar": tenancy.PLAN_AR.get(plan, plan),
            "limits": tenancy.PLAN_LIMITS.get(plan, {})}


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/api/status")
def status():
    from .etimad import list_tenders
    from .forsah import list_projects
    stats = db.market_stats()
    return {
        "ok": True,
        "ai_enabled": ai_available(),
        "engine": "claude" if ai_available() else "template",
        "proposals": len(db.list_proposals()),
        "price_items": len(db.list_price_items()),
        "library": len(db.list_library()),
        "repo_files": stats["repo_files"],
        "etimad": len(list_tenders()),
        "forsah": len(list_projects()),
        "docs": len(db.list_company_docs()),
    }


# ------------------------------ الإعدادات ------------------------------

# الإعدادات المسموح قراءتها/كتابتها عبر الواجهة (قائمة بيضاء). كل ما عداها — مثل
# auth_secret ومفاتيح محرك الذكاء المخزنة في الشركة 1 — داخلي لا يُعرض ولا يُعدَّل.
_NOTIFY_SETTINGS = {
    "notify_email_enabled", "notify_whatsapp_enabled",
    "smtp_host", "smtp_port", "smtp_user", "smtp_pass", "smtp_from", "smtp_security",
    "whatsapp_token", "whatsapp_phone_id", "whatsapp_template", "whatsapp_template_lang",
    "whatsapp_api_version",
}
_EDITABLE_SETTINGS = set(DEFAULT_SETTINGS) | _NOTIFY_SETTINGS | {"brand_color"}
_SECRET_SETTINGS = db._SECRET_KEYS
# لا يراها إلا الأدمن: أسرار وإعدادات قنوات وحسابات منصات خارجية
_ADMIN_ONLY_SETTINGS = (_NOTIFY_SETTINGS | _SECRET_SETTINGS
                        | {"etimad_national_id", "forsah_email", "notify_last_error"})
_READONLY_SETTINGS = {"notify_last_error", "onboarding_done"}   # تظهر للأدمن ولا تُعدَّل من هنا
_PCT_SETTINGS = ("vat_rate", "overhead_pct", "risk_pct", "profit_pct", "bid_bond_pct")


def _public_settings(is_admin: bool) -> dict:
    """الإعدادات كما تُعرض: الأسرار لا تخرج أبداً (تُستبدل بعلم `<key>_set`)."""
    raw = db.get_settings()
    visible = _EDITABLE_SETTINGS | _READONLY_SETTINGS
    out = {}
    for key, value in raw.items():
        if key not in visible:
            continue
        if key in _SECRET_SETTINGS:
            if is_admin:
                out[f"{key}_set"] = "1" if value else "0"
            continue
        if key in _ADMIN_ONLY_SETTINGS and not is_admin:
            continue
        out[key] = value
    return out


def _validate_setting(key: str, value) -> str:
    """تحقق وتطبيع قيمة إعداد — يرفع HTTPException 400 لقيمة غير صالحة."""
    if isinstance(value, bool):
        value = "1" if value else "0"
    if value is None:
        value = ""
    if not isinstance(value, (str, int, float)):
        raise HTTPException(400, f"قيمة غير صالحة للإعداد {key}")
    value = str(value).strip()
    if len(value) > 4000:
        raise HTTPException(400, f"القيمة أطول من المسموح للإعداد {key}")

    def bad(msg):
        raise HTTPException(400, f"{key}: {msg}")

    if key in _PCT_SETTINGS:
        try:
            n = float(value)
        except ValueError:
            bad("يجب أن يكون رقماً")
        if not 0 <= n <= 100:
            bad("النسبة بين 0 و100")
    elif key == "validity_days":
        if not value.isdigit() or not 1 <= int(value) <= 3650:
            bad("عدد أيام صحيح بين 1 و3650")
    elif key == "smtp_port":
        if value and (not value.isdigit() or not 1 <= int(value) <= 65535):
            bad("منفذ بين 1 و65535")
    elif key in ("notify_email_enabled", "notify_whatsapp_enabled"):
        if value not in ("0", "1", ""):
            bad("القيمة 0 أو 1")
        value = value or "0"
    elif key == "smtp_security":
        if value not in ("", "starttls", "ssl", "none"):
            bad("القيم المتاحة: starttls أو ssl أو none")
    elif key == "brand_color":
        if value and not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
            bad("لون بصيغة #RRGGBB")
    elif key == "ref_prefix":
        if not re.fullmatch(r"[A-Za-z0-9]{1,8}", value):
            bad("بادئة رقم العرض: حتى 8 أحرف/أرقام إنجليزية")
        value = value.upper()
    elif key == "whatsapp_phone_id":
        if value and not value.isdigit():
            bad("معرّف رقم واتساب أرقام فقط")
    elif key == "whatsapp_api_version":
        if value and not re.fullmatch(r"v\d{1,2}\.\d", value):
            bad("صيغة الإصدار مثل v21.0")
    elif key == "company_email":
        from .notify_channels import normalize_email
        try:
            value = normalize_email(value)
        except ValueError as exc:
            bad(str(exc))
    return value


@app.get("/api/settings")
def get_settings(request: Request):
    return _public_settings(request.state.role in tenancy.ADMIN_ROLES or request.state.is_platform_admin)


@app.put("/api/settings")
def put_settings(request: Request, values: dict):
    """تعديل إعدادات الشركة — أدمن فما فوق فقط، بقائمة بيضاء وتحقق من القيم.

    الأسرار: قيمة فارغة أو مفقودة = إبقاء المحفوظ (الواجهة لا تملك القيمة أصلاً)؛
    ولمسحها صراحةً: `_clear: ["smtp_pass"]`."""
    _require_admin(request)
    clear = values.get("_clear") or []
    clean = {}
    for key, value in values.items():
        if key == "_clear" or key.endswith("_set"):
            continue
        if key not in _EDITABLE_SETTINGS:
            raise HTTPException(400, f"إعداد غير معروف أو غير قابل للتعديل: {key}")
        if key in _SECRET_SETTINGS:
            if value in (None, ""):
                continue
            if not isinstance(value, str) or len(value) > 4000:
                raise HTTPException(400, f"قيمة غير صالحة للإعداد {key}")
            clean[key] = value.strip()
            continue
        clean[key] = _validate_setting(key, value)
    for key in clear:
        if key in _SECRET_SETTINGS:
            clean[key] = ""
    try:
        db.update_settings(clean)
    except RuntimeError as exc:
        raise HTTPException(500, str(exc))
    db.log_audit("settings", request.state.company_id, "update",
                 "، ".join(sorted(k for k in clean if k not in _SECRET_SETTINGS)
                           + [f"{k}(سر)" for k in clean if k in _SECRET_SETTINGS])[:400])
    return _public_settings(True)


# ---------------------------- قاعدة الأسعار ----------------------------

@app.get("/api/prices")
def get_prices(search: str = "", category: str = ""):
    return db.list_price_items(search, category)


@app.post("/api/prices")
def post_price(request: Request, item: dict):
    if not item.get("id"):
        _enforce_limit(request, "price_items")
    required = {"code", "category", "name", "unit", "unit_price"}
    if not required.issubset(item):
        raise HTTPException(400, f"حقول مطلوبة: {', '.join(required)}")
    return db.upsert_price_item(item)


@app.delete("/api/prices/{item_id}")
def remove_price(item_id: int):
    db.delete_price_item(item_id)
    return {"ok": True}


@app.get("/api/prices/{item_id}/history")
def price_history(item_id: int):
    return db.get_price_history(item_id)


@app.get("/api/prices/export/csv")
def export_prices_csv():
    items = db.list_price_items()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["code", "category", "name", "unit", "unit_price", "notes"])
    for i in items:
        writer.writerow([i["code"], i["category"], i["name"], i["unit"], i["unit_price"], i["notes"]])
    data = "﻿" + buf.getvalue()  # BOM لدعم العربية في Excel
    return StreamingResponse(
        io.BytesIO(data.encode("utf-8")),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=azoom-prices.csv"},
    )


@app.post("/api/prices/import/csv")
def import_prices_csv(request: Request, file: UploadFile = File(...)):
    """استيراد أسعار من CSV: سقف حجم، وحد خطة الاشتراك يُحترم (كان يتجاوزه)،
    وسطر معطوب يُتخطى ويُبلَّغ عنه بدل أن يُسقط الاستيراد كله بخطأ 500."""
    content = read_upload(file).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(content))
    company = db.get_company(request.state.company_id) or {}
    limit = tenancy.PLAN_LIMITS.get(company.get("plan", "trial"),
                                    tenancy.PLAN_LIMITS["trial"]).get("price_items")
    existing = {i["code"] for i in db.list_price_items()}
    count, errors, over_limit = 0, [], 0
    for line_no, row in enumerate(reader, start=2):
        code, name = (row.get("code") or "").strip(), (row.get("name") or "").strip()
        if not code or not name:
            continue
        try:
            price = float(str(row.get("unit_price") or 0).replace(",", "").strip() or 0)
            if price < 0:
                raise ValueError
        except ValueError:
            errors.append({"line": line_no, "code": code, "error": "سعر غير صالح"})
            continue
        if limit is not None and code not in existing and len(existing) >= limit:
            over_limit += 1
            continue
        db.upsert_price_item({
            "code": code,
            "category": (row.get("category") or "غير مصنف").strip(),
            "name": name,
            "unit": (row.get("unit") or "وحدة").strip(),
            "unit_price": price,
            "notes": (row.get("notes") or "").strip(),
        })
        existing.add(code)
        count += 1
    return {"imported": count, "errors": errors[:20], "skipped_over_plan_limit": over_limit}


# --------------------------- المكتبة الفنية ---------------------------

@app.get("/api/library")
def get_library(category: str = ""):
    return db.list_library(category)


@app.post("/api/library")
def post_library(entry: dict):
    if not entry.get("title") or not entry.get("body"):
        raise HTTPException(400, "العنوان والنص مطلوبان")
    entry.setdefault("category", "عام")
    return db.upsert_library(entry)


@app.delete("/api/library/{entry_id}")
def remove_library(entry_id: int):
    db.delete_library(entry_id)
    return {"ok": True}


# ------------------------- خزنة وثائق الشركة -------------------------

@app.get("/api/docs")
def get_docs():
    return db.list_company_docs()


@app.post("/api/docs")
def post_doc(doc: dict):
    if not doc.get("name"):
        raise HTTPException(400, "اسم الوثيقة مطلوب")
    return db.upsert_company_doc(doc)


@app.delete("/api/docs/{doc_id}")
def remove_doc(doc_id: int):
    db.delete_company_doc(doc_id)
    return {"ok": True}


# ----------------------------- التحليلات -----------------------------

@app.get("/api/analytics")
def get_analytics():
    return compute_analytics()


# ------------------------ المستودع المعرفي ------------------------

@app.post("/api/repo/upload")
def repo_upload(
    source_type: str = Form("عرض الشركة السابق"),
    company: str = Form(""),
    notes: str = Form(""),
    as_reference: str = Form(""),
    sector: str = Form(""),
    files: list[UploadFile] = File(...),
):
    make_ref = as_reference in ("1", "true", "on", "yes")
    results = []
    for f in files:
        content = read_upload(f)
        results.append(ingest_file(f.filename or "file", content, source_type, company,
                                   notes, as_reference=make_ref, sector=sector))
    return results


@app.post("/api/repo/{fid}/make-reference")
def repo_make_reference(fid: int):
    """تحويل ملف موجود في المستودع إلى عرض مرجعي في ذاكرة التشابه."""
    from .repository import build_reference_from_text, parse_text_boq
    f = db.get_repo_file(fid)
    if not f:
        raise HTTPException(404, "الملف غير موجود")
    text = f.get("extracted_text") or ""
    items = parse_text_boq(text)
    ref = build_reference_from_text(f["filename"], f.get("company", ""), text, items,
                                    sector=f.get("sector", ""))
    if ref is None:
        raise HTTPException(400, "لا يوجد محتوى نصي كافٍ في هذا الملف لبناء عرض مرجعي")
    if ref.get("duplicate"):
        raise HTTPException(409, f"يوجد عرض مرجعي بنفس العنوان مسبقاً: {ref['title']}")
    return ref


@app.get("/api/repo")
def repo_list():
    return {"files": db.list_repo_files(), "stats": db.market_stats()}


@app.delete("/api/repo/{fid}")
def repo_delete(fid: int):
    db.delete_repo_file(fid)
    return {"ok": True}


@app.get("/api/market/search")
def market_search(q: str, sector: str = ""):
    """أسعار السوق من المستودع + سعر عزوم المعتمد للمقارنة — مع تصفية بالقطاع."""
    market = db.search_market_prices(q, sector=sector)
    azoom = db.list_price_items(search=q)
    prices = [m["unit_price"] for m in market]
    bench = {
        "count": len(prices),
        "min": min(prices) if prices else None,
        "avg": round(sum(prices) / len(prices), 2) if prices else None,
        "max": max(prices) if prices else None,
    }
    return {"market": market, "azoom": azoom, "benchmark": bench}


# ------------------------ التسجيل الذاتي والفوترة ------------------------

@app.post("/api/signup")
def signup(request: Request, body: dict):
    """تسجيل شركة جديدة ذاتياً: خطة تجريبية 14 يوماً مع مالك حسابها.

    نقطة عامة بلا مصادقة تنشئ بيانات — فتُقيَّد لكل عنوان وعالمياً (سقف بالساعة)
    لمنع إغراق قاعدة البيانات بشركات وهمية وتضخيم أعداد التجارب."""
    ip = security.client_ip(request)
    enforce_rate(security.SIGNUP_IP_LIMITER, ip, "تسجيلات كثيرة من هذا الجهاز")
    enforce_rate(security.SIGNUP_GLOBAL_LIMITER, "*", "التسجيل مزدحم حالياً")
    security.SIGNUP_IP_LIMITER.hit(ip)
    security.SIGNUP_GLOBAL_LIMITER.hit("*")
    name = _text(body.get("name"), 200)
    cr_no = _text(body.get("cr_no"), 40)
    owner_username = _text(body.get("owner_username"), 100)
    password = body.get("owner_password") if isinstance(body.get("owner_password"), str) else ""
    if not name or not cr_no or not owner_username:
        raise HTTPException(400, "اسم الشركة والسجل التجاري واسم مستخدم المالك مطلوبة")
    if db.find_company_by_cr(cr_no):
        raise HTTPException(409, "شركة بهذا السجل التجاري مسجّلة مسبقاً — سجّلوا الدخول أو تواصلوا معنا")
    if db.find_company_by_name(name):
        raise HTTPException(409, "توجد شركة بهذا الاسم مسبقاً")
    from .auth import create_user, get_user
    if get_user(owner_username):
        raise HTTPException(409, "اسم المستخدم محجوز — اختر اسماً آخر")
    try:
        owner = create_user(owner_username, password, _text(body.get("owner_display_name"), 100))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    company = db.create_company(name, _text(body.get("short_name"), 60), "trial",
                                _text(body.get("sector"), 100), cr_no, _text(body.get("vat_no"), 40))
    db.set_membership(owner["id"], company["id"], "owner")
    db.log_audit("companies", company["id"], "signup", name)
    return {"ok": True, "company_id": company["id"],
            "trial_ends_at": company.get("trial_ends_at", ""),
            "message": "أُنشئ حسابكم التجريبي (14 يوماً) — سجّلوا الدخول الآن"}


@app.get("/signup", response_class=HTMLResponse)
def signup_page():
    from .auth import SIGNUP_PAGE
    return SIGNUP_PAGE


@app.get("/api/invoices")
def invoices_mine(request: Request):
    _require_admin(request)
    return db.list_invoices(request.state.company_id)


@app.post("/api/platform/invoices/issue")
def invoices_issue(request: Request):
    _require_platform_admin(request)
    return db.issue_monthly_invoices()


@app.get("/api/platform/model")
def platform_model_get(request: Request):
    """حالة محرك الذكاء: الموديل الفعال ومصدره وسجل التحديثات التلقائية."""
    _require_platform_admin(request)
    from .model_updater import model_status
    return model_status()


@app.post("/api/platform/model/refresh")
def platform_model_refresh(request: Request):
    """فحص فوري لمنصة Claude واعتماد الأحدث إن اجتاز التجربة."""
    _require_platform_admin(request)
    from .model_updater import refresh_active_model
    return refresh_active_model(force=True)


@app.put("/api/platform/model")
def platform_model_put(request: Request, body: dict):
    """ضبط محرك الذكاء: تشغيل/إيقاف التحديث التلقائي، الفئة، أو تثبيت موديل يدوياً."""
    _require_platform_admin(request)
    from .model_updater import TIERS, model_status
    values = {}
    if "auto_update" in body:
        values["auto_model_update"] = "1" if body["auto_update"] else "0"
    if "tier" in body:
        if body["tier"] not in TIERS:
            raise HTTPException(400, f"الفئة غير معروفة — المتاح: {', '.join(TIERS)}")
        values["model_tier"] = body["tier"]
    if "pinned" in body:
        from .model_updater import check_pin
        pinned = _text(body.get("pinned"), 100)
        problem = check_pin(pinned)
        if problem:
            raise HTTPException(400, problem)
        values["model_pinned"] = pinned
    if values:
        db.update_settings(values, company_id=1)
        db.log_audit("claude_model", "", "config", str(values))
    return model_status()


@app.get("/api/platform/metrics")
def platform_metrics(request: Request):
    _require_platform_admin(request)
    companies = db.list_companies()
    paid = [c for c in companies
            if c["plan"] != "trial" and c["subscription_status"] == "active"]
    mrr = sum(db.company_monthly_price(c) or 0 for c in paid)   # يشمل الأسعار المتفاوض عليها
    trials = [c for c in companies if c["plan"] == "trial"]
    return {
        "mrr": mrr,
        "mrr_delta": db.mrr_delta(),
        "paid_count": len(paid),
        "trial_count": len(trials),
        "companies_total": len(companies),
        "invoices": db.list_invoices()[:30],
        "active_users_30d": db.platform_active_users(30),
        "trials_ending": db.trials_ending_soon(30),
    }


# ------------------------ المستودع الفني ومحرك الأسلوب ------------------------

@app.get("/api/repository/technical")
def tech_docs_list():
    from .style_engine import get_style_profile, list_tech_documents
    return {"documents": list_tech_documents(), "profile": get_style_profile()}


@app.get("/api/style-profile")
def style_profile_get():
    from .style_engine import get_style_profile
    return get_style_profile()


@app.post("/api/style-profile/rebuild")
def style_profile_rebuild():
    from .style_engine import extract_style_profile
    return extract_style_profile()


@app.get("/api/paragraph-bank")
def paragraph_bank(section: str = ""):
    from .style_engine import list_paragraph_bank
    return list_paragraph_bank(section)


@app.put("/api/paragraphs/{pid}")
def paragraph_approve(pid: int, body: dict):
    from .style_engine import set_paragraph_approved
    set_paragraph_approved(pid, bool(body.get("approved")))
    return {"ok": True}


# ------------------------ منافسات اعتماد ------------------------

@app.post("/api/etimad/fetch")
def etimad_fetch(pages: int = 3):
    return fetch_tenders(pages=max(1, min(pages, 10)))


@app.get("/api/etimad")
def etimad_list(status: str = "", q: str = "", min_relevance: int = 0):
    return {"tenders": list_tenders(status, q, min_relevance), "session": has_session()}


@app.put("/api/etimad/{tid}")
def etimad_status(tid: int, body: dict):
    update_tender_status(tid, body.get("status", "جديدة"))
    return {"ok": True}


# ------------------------ مشاريع منصة فرصة ------------------------

@app.post("/api/forsah/fetch")
def forsah_fetch():
    from .forsah import fetch_projects
    return fetch_projects()


@app.get("/api/forsah")
def forsah_list(category: str = "", status: str = "", q: str = ""):
    from .forsah import CATEGORIES, list_projects
    return {"projects": list_projects(category, status, q), "categories": CATEGORIES}


@app.put("/api/forsah/{pid}")
def forsah_status(pid: int, body: dict):
    from .forsah import update_project_status
    update_project_status(pid, body.get("status", "جديد"))
    return {"ok": True}


# ------------------------ تحليل فرصة الفوز ------------------------

@app.post("/api/opportunity")
def opportunity(
    title: str = Form(...),
    client: str = Form(""),
    files: list[UploadFile] = File(default=[]),
):
    texts = []
    for f in files:
        content = read_upload(f)
        texts.append(extract_text(f.filename or "file", content))
    return analyze_opportunity(title, client, "\n\n".join(texts))


# ------------------------- توليد العروض وإدارتها -------------------------

_ENTITY_TYPES = ("government", "private", "pif", "airports")


def _check_entity(entity_type: str) -> str:
    if entity_type not in _ENTITY_TYPES:
        raise HTTPException(400, f"نوع الجهة غير معروف — المتاح: {', '.join(_ENTITY_TYPES)}")
    return entity_type


def _throttle_generation(request: Request):
    """سقف بناء العروض لكل شركة بالساعة — كل بناء قد يكلّف استدعاء ذكاء اصطناعي."""
    key = str(request.state.company_id)
    enforce_rate(security.GENERATE_LIMITER, key, "طلبات بناء عروض كثيرة")
    security.GENERATE_LIMITER.hit(key)


# معالجات `def` (لا `async def`): بناء العرض يحجب دقائق (ذكاء اصطناعي + قراءة ملفات).
# كانت async فتُجمّد حلقة الأحداث كلها — تتوقف كل الطلبات الأخرى (7 ثوانٍ في القياس).
# `def` تُنفَّذ في مجمّع الخيوط فيبقى الخادم متجاوباً.
@app.post("/api/proposals/generate")
def generate_proposal(
    request: Request,
    title: str = Form(...),
    client: str = Form(...),
    entity_type: str = Form("government"),
    files: list[UploadFile] = File(default=[]),
):
    _check_entity(entity_type)
    _enforce_limit(request, "proposals_month")
    _require_company_logo(request)
    _throttle_generation(request)
    files_text = _read_uploads_text(files)
    data, matches = _build_proposal_data(title, client, entity_type, files_text)
    proposal = db.create_proposal(title, client, entity_type, data)
    return proposal


def _read_uploads_text(files: list[UploadFile]) -> str:
    texts = []
    for f in files or []:
        content = read_upload(f)
        extracted = extract_text(f.filename or "file", content)
        texts.append(f"===== الملف: {f.filename} =====\n{extracted}")
    return "\n\n".join(texts)


def _build_proposal_data(title: str, client: str, entity_type: str, files_text: str):
    """خط إنتاج العرض الموحد — يستدعيه التوليد المباشر وتحليل/توليد الوكيلين،
    فما يعرضه الوكيلان في التحليل هو حرفياً ما يُبنى عند الاعتماد."""
    # إثراء السياق من المستودع المعرفي (عروض قديمة/منافسة مخزنة)
    repo_texts = find_relevant_repo_texts(f"{title}\n{files_text[:4000]}")
    if repo_texts:
        repo_block = "\n\n".join(
            f"===== من المستودع المعرفي: {r['filename']} ({r['source_type']}"
            + (f" — {r['company']}" if r['company'] else "") + ") =====\n"
            + r["extracted_text"][:4000]
            for r in repo_texts
        )
        files_text = f"{files_text}\n\n{repo_block}" if files_text else repo_block

    # البحث عن العروض السابقة الأشبه بنطاق المشروع — أساس بناء العرض الجديد
    # (عروض نفس القطاع المحدد تُقدَّم أولاً: حكومي/خاص/صندوق الاستثمارات/مطارات)
    matches = find_similar(f"{title}\n{files_text[:8000]}", top_n=3, sector=entity_type)
    similar_refs = get_reference_content([m["id"] for m in matches]) if matches else []
    # ترتيب المحتوى بنفس ترتيب درجات التطابق
    order = {m["id"]: i for i, m in enumerate(matches)}
    similar_refs.sort(key=lambda p: order.get(p["id"], 99))

    if ai_available():
        try:
            data = generate_proposal_ai(title, client, entity_type, files_text, similar_refs)
        except Exception as exc:
            # فشل الاتصال أو التوليد — ننتقل لمحرك القوالب مع إبلاغ المستخدم
            data = build_template_proposal(title, client, entity_type, files_text, similar_refs)
            data["engine_note"] = f"تعذر التوليد بالذكاء الاصطناعي ({exc}) — استُخدم محرك القوالب."
    else:
        data = build_template_proposal(title, client, entity_type, files_text, similar_refs)

    data["similar_refs"] = [
        {"id": m["id"], "ref_no": m["ref_no"], "title": m["title"], "score": m["score"]}
        for m in matches
    ]
    return data, matches


@app.get("/api/proposals/similar")
def similar_proposals(q: str, sector: str = ""):
    """البحث عن العروض السابقة المشابهة لنص مشروع (يُستخدم مباشرة في شاشة عرض جديد)."""
    return find_similar(q, top_n=5, sector=sector)


@app.get("/api/proposals")
def get_proposals():
    return db.list_proposals()


@app.get("/api/proposals/{pid}")
def get_proposal(pid: int):
    proposal = db.get_proposal(pid)
    if not proposal:
        raise HTTPException(404, "العرض غير موجود")
    return proposal


@app.put("/api/proposals/{pid}")
def put_proposal(pid: int, fields: dict):
    # عند تعديل جدول الكميات نعيد الحسابات المالية
    if "data" in fields and "boq" in fields["data"]:
        fields["data"]["boq"] = match_price_catalog(fields["data"]["boq"])
        fields["data"]["financial"] = compute_financials(fields["data"]["boq"])
    proposal = db.update_proposal(pid, fields)
    if not proposal:
        raise HTTPException(404, "العرض غير موجود")
    return proposal


@app.delete("/api/proposals/{pid}")
def remove_proposal(pid: int):
    db.delete_proposal(pid)
    return {"ok": True}


@app.get("/api/proposals/{pid}/quality")
def proposal_quality(pid: int):
    """وكيل الجودة والمراجعة: درجة الجاهزية وملاحظات الأصالة والنظافة والاتساق."""
    from .quality_agent import review_proposal
    proposal = db.get_proposal(pid)
    if not proposal:
        raise HTTPException(404, "العرض غير موجود")
    return review_proposal(proposal["data"])


@app.post("/api/proposals/{pid}/quality/fix")
def proposal_quality_fix(pid: int):
    """الإصلاح التلقائي الآمن: إزالة العبارات القالبية ثم إعادة التقييم."""
    from .quality_agent import polish_proposal, review_proposal
    proposal = db.get_proposal(pid)
    if not proposal:
        raise HTTPException(404, "العرض غير موجود")
    data = proposal["data"]
    fixes = polish_proposal(data)
    db.update_proposal(pid, {"data": data})
    db.log_audit("quality_agent", pid, "polish", "، ".join(fixes["removed_phrases"])[:400])
    return {"fixes": fixes, "report": review_proposal(data)}


def _render_export(build, suffix: str) -> bytes:
    """يبني ملف التصدير في ملف مؤقت فريد ويعيد بايتاته ثم يحذفه.

    كان الملف يُكتب باسم رقم العرض فقط فيتصادم مع طلب آخر متزامن (ملف تالف)،
    أو مع شركة أخرى لها رقم عرض مطابق (تسرّب عرض شركة إلى أخرى)."""
    fd, tmp = tempfile.mkstemp(suffix=suffix, dir=EXPORTS_DIR)
    os.close(fd)
    try:
        build(tmp)
        return Path(tmp).read_bytes()
    finally:
        Path(tmp).unlink(missing_ok=True)


def _download(content: bytes, media_type: str, filename: str) -> Response:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", filename)
    return Response(content, media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="{safe}"',
                             "Cache-Control": "no-store"})


@app.get("/api/proposals/{pid}/export/docx")
def export_docx(pid: int):
    proposal = db.get_proposal(pid)
    if not proposal:
        raise HTTPException(404, "العرض غير موجود")
    settings = _branded_settings()
    content = _render_export(lambda path: export_proposal_docx(proposal, settings, path), ".docx")
    return _download(content,
                     "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                     f"{proposal['ref_no']}.docx")


@app.get("/api/proposals/{pid}/export/xlsx")
def export_xlsx(pid: int):
    proposal = db.get_proposal(pid)
    if not proposal:
        raise HTTPException(404, "العرض غير موجود")
    settings = _branded_settings()
    content = _render_export(lambda path: export_boq_xlsx(proposal, path, settings=settings), ".xlsx")
    return _download(content,
                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     f"{proposal['ref_no']}-BOQ.xlsx")


# ------------------------------ وحدة تنفيذ المشاريع ------------------------------
# مهندس الموقع يسجّل الإنتاجية اليومية ويختار مَن نفّذ (عمالة الشركة/مقاول باطن).
# التقرير يُقفل فور الاعتماد: تعديل غير المالك = طلب تعديل بإشعار يقبله المالك أو يرفضه.

def _display_name(request: Request) -> str:
    return request.state.username


def _company_owners(request: Request) -> list[dict]:
    return [{"user_id": m["id"]} for m in db.company_members(request.state.company_id)
            if m["role"] == "owner"]


@app.get("/api/execution/subcontractors")
def subs_list(active: int = 0):
    return execution.list_subcontractors(active_only=bool(active))


@app.post("/api/execution/subcontractors")
def subs_upsert(request: Request, body: dict):
    _require_admin(request)
    if not (body.get("name") or "").strip():
        raise HTTPException(400, "اسم مقاول الباطن مطلوب")
    try:
        return execution.upsert_subcontractor(body)
    except Exception:
        raise HTTPException(409, "مقاول باطن بهذا الاسم مسجّل مسبقاً")


@app.delete("/api/execution/subcontractors/{sid}")
def subs_delete(request: Request, sid: int):
    _require_admin(request)
    execution.delete_subcontractor(sid)
    return {"ok": True}


@app.get("/api/execution/executors")
def executors_dropdown():
    """خيارات القائمة المنسدلة «مَن نفّذ العمل» في تقرير الإنتاجية."""
    return execution.executor_options()


@app.get("/api/execution/projects")
def exec_projects_list():
    return execution.list_projects()


@app.post("/api/execution/projects")
def exec_projects_upsert(request: Request, body: dict):
    if request.state.role == "engineer":
        raise HTTPException(403, "إنشاء المشاريع للمحرر فما فوق — المهندس يسجّل التقارير")
    if not (body.get("name") or "").strip():
        raise HTTPException(400, "اسم المشروع مطلوب")
    return execution.upsert_project(body)


@app.get("/api/execution/projects/{pid}/boq")
def exec_project_boq(pid: int):
    return execution.project_boq_items(pid)


@app.get("/api/execution/reports")
def exec_reports_list(project_id: int = 0):
    return execution.list_reports(project_id or None)


@app.post("/api/execution/reports")
def exec_reports_create(request: Request, body: dict):
    try:
        return execution.create_report(body, _display_name(request))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/execution/reports/{rid}")
def exec_report_get(rid: int):
    report = execution.get_report(rid)
    if not report:
        raise HTTPException(404, "التقرير غير موجود")
    return report


@app.put("/api/execution/reports/{rid}")
def exec_report_update(request: Request, rid: int, body: dict):
    """التقرير مقفل بعد الاعتماد: المالك يعدّل مباشرة، وغيره يقدّم طلب تعديل."""
    is_owner = request.state.role == "owner" or request.state.is_platform_admin
    try:
        if is_owner:
            return execution.owner_update_report(rid, body)
        return execution.request_report_edit(rid, body, _display_name(request),
                                             _company_owners(request))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.delete("/api/execution/reports/{rid}")
def exec_report_delete(request: Request, rid: int):
    if request.state.role != "owner" and not request.state.is_platform_admin:
        raise HTTPException(403, "حذف التقارير لمالك الحساب فقط")
    execution.delete_report(rid)
    return {"ok": True}


@app.get("/api/execution/edit-requests")
def exec_edit_requests(request: Request):
    """المالك يرى كل الطلبات، وغيره يرى طلباته فقط."""
    if request.state.role == "owner" or request.state.is_platform_admin:
        return execution.list_edit_requests()
    return execution.list_edit_requests(mine_only_user=request.state.user_id)


@app.post("/api/execution/edit-requests/{req_id}/decision")
def exec_edit_decide(request: Request, req_id: int, body: dict):
    if request.state.role != "owner" and not request.state.is_platform_admin:
        raise HTTPException(403, "قبول أو رفض التعديلات لمالك الحساب فقط")
    action = body.get("action", "")
    if action not in ("approve", "reject"):
        raise HTTPException(400, "القرار: approve أو reject")
    try:
        return execution.decide_edit_request(req_id, action, body.get("note", ""),
                                             _display_name(request))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


# أسعار اتفاقيات الباطن والربحية — للمالك والأدمن حصراً: لا يصل مهندس الموقع
# ولا المحرر ولا المشاهد أي سعر من هنا (403 من الخادم، لا إخفاء واجهة فقط)
@app.get("/api/execution/agreements")
def agreements_list(request: Request, project_id: int):
    _require_admin(request)
    return execution.list_agreements(project_id)


@app.post("/api/execution/agreements")
def agreements_upsert(request: Request, body: dict):
    _require_admin(request)
    if not (body.get("item") or "").strip() or body.get("unit_rate") in (None, ""):
        raise HTTPException(400, "البند وسعر الاتفاق مطلوبان")
    if not body.get("id") and not body.get("project_id"):
        raise HTTPException(400, "المشروع مطلوب")
    return execution.upsert_agreement(body)


@app.delete("/api/execution/agreements/{aid}")
def agreements_delete(request: Request, aid: int):
    _require_admin(request)
    execution.delete_agreement(aid)
    return {"ok": True}


@app.get("/api/execution/profitability")
def exec_profitability(request: Request, project_id: int):
    """الربحية الفعلية مقابل التقديرية — شاشة المالك والأدمن فقط."""
    _require_admin(request)
    try:
        return execution.project_profitability(project_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@app.post("/api/members/{uid}/contact")
def members_contact(request: Request, uid: int, body: dict):
    """بريد وجوال العضو لقنوات الإشعارات الخارجية — أدمن فما فوق."""
    _require_admin(request)
    if not db.get_membership(uid, request.state.company_id):
        raise HTTPException(404, "العضو غير موجود في هذه الشركة")
    from .notify_channels import normalize_email, normalize_phone
    try:
        email = normalize_email(_text(body.get("email"), 200))
        phone = normalize_phone(_text(body.get("phone"), 40))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.set_user_contact(uid, email, phone)
    return {"ok": True, "email": email, "phone": phone}


@app.post("/api/notify/test")
def notify_test(request: Request):
    """اختبار قنوات البريد/واتساب بإرسال رسالة تجريبية للمستخدم الحالي."""
    _require_admin(request)
    from .notify_channels import test_channels
    return test_channels(request.state.company_id, request.state.user_id)


@app.get("/api/execution/productivity")
def exec_productivity(project_id: int = 0):
    """كم اشتغل كل منفّذ — عمالة الشركة وكل مقاول باطن (تفصيل الكميات بالوحدة)."""
    return execution.productivity_summary(project_id or None)


@app.get("/api/notifications")
def notifications_list(request: Request):
    return execution.my_notifications(request.state.user_id)


@app.post("/api/notifications/read")
def notifications_read(request: Request, body: dict = None):
    execution.mark_notifications_read(request.state.user_id,
                                      (body or {}).get("id"))
    return {"ok": True}


def _branded_settings() -> dict:
    """إعدادات الشركة + شعارها ولونها — لتخرج ملفات Word/Excel بهوية كل مستأجر."""
    settings = db.get_settings()
    company_id = tenancy.cid()
    logo = _company_logo_file(company_id)
    settings["_company_id"] = company_id
    settings["_logo_path"] = str(logo) if logo else ""
    settings["_brand_color"] = _brand_color(company_id).lstrip("#")
    return settings


# ------------------------------ معالج تهيئة المستأجر ------------------------------

@app.get("/api/onboarding")
def onboarding_get(request: Request):
    company = db.get_company(request.state.company_id) or {}
    return agents.onboarding_status(company,
                                    _company_logo_file(request.state.company_id) is not None)


@app.post("/api/onboarding/complete")
def onboarding_complete(request: Request):
    _require_admin(request)
    if _company_logo_file(request.state.company_id) is None:
        raise HTTPException(400, "الشعار إلزامي — ارفعه قبل إنهاء التهيئة.")
    db.update_settings({"onboarding_done": "1"})
    db.log_audit("onboarding", request.state.company_id, "complete")
    return {"ok": True}


@app.post("/api/onboarding/technical-upload")
def onboarding_technical_upload(request: Request, files: list[UploadFile] = File(...),
                                      client: str = Form("")):
    """رفع عروض الشركة الفنية السابقة لبنك الأسلوب — خطوة المعالج الثانية.

    متاح لكل الخطط (تغذية البنك جزء من التهيئة الأساسية)؛ صفحات تحليل البصمة
    المتقدمة تبقى خلف بوابة الخطة الاحترافية كما هي."""
    _require_admin(request)
    from .style_engine import extract_style_profile, ingest_technical_document
    results = []
    for f in files:
        content = read_upload(f)
        text = extract_text(f.filename or "file", content)
        if len((text or "").strip()) < 200:
            results.append({"filename": f.filename, "ok": False,
                            "error": "لا يوجد نص كافٍ — الملفات المصورة تحتاج OCR"})
            continue
        r = ingest_technical_document(f.filename or "file", text,
                                      doc_kind="azoom_submitted", client=client,
                                      is_style_source=True)
        results.append({"filename": f.filename, "ok": True, **{k: r[k] for k in ("sections", "paragraphs") if k in r}} if isinstance(r, dict) else {"filename": f.filename, "ok": True})
    try:
        extract_style_profile()
    except Exception:
        pass
    return {"results": results}


# ------------------------------ الوكيلان: تحليل ثم توليد ------------------------------

@app.post("/api/agents/analyze")
def agents_analyze(
    request: Request,
    title: str = Form(...),
    client: str = Form(...),
    entity_type: str = Form("government"),
    files: list[UploadFile] = File(default=[]),
):
    """تشغيل جاف لخط الإنتاج الحقيقي: الوكيل الفني ووكيل التسعير يعرضان
    خطتهما وتوصياتهما قبل الاعتماد — دون حفظ عرض.

    يُفحص حد الخطة قبل أي استدعاء ذكاء اصطناعي (لا تُنفَق تكلفة على تحليل سيُرفض
    اعتماده)، ويُحفظ العرض المبني نفسه في الجلسة فلا يُبنى مرة ثانية عند الاعتماد."""
    _check_entity(entity_type)
    _enforce_limit(request, "proposals_month")
    _throttle_generation(request)
    files_text = _read_uploads_text(files)
    data, matches = _build_proposal_data(title, client, entity_type, files_text)
    company = db.get_company(request.state.company_id) or {}
    onboarding = agents.onboarding_status(company,
                                          _company_logo_file(request.state.company_id) is not None)
    analysis = agents.build_analysis(title, client, entity_type, files_text,
                                     data, matches, onboarding)
    sid = agents.save_session(title, client, entity_type, files_text, analysis, data=data)
    analysis["session_id"] = sid
    return analysis


@app.post("/api/agents/generate")
def agents_generate(request: Request, body: dict):
    """اعتماد التحليل: يبني العرضين من جلسة التحليل نفسها (بلا إعادة رفع ملفات)."""
    try:
        sid = int(body.get("session_id") or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "معرّف الجلسة غير صالح")
    session = agents.get_session(sid)
    if not session:
        raise HTTPException(404, "جلسة التحليل غير موجودة أو انتهت — أعد التحليل")
    if session.get("proposal_id"):          # اعتماد مكرر (نقرة مزدوجة) → العرض نفسه لا نسخة ثانية
        existing = db.get_proposal(session["proposal_id"])
        if existing:
            return existing
    _enforce_limit(request, "proposals_month")
    _require_company_logo(request)
    data = session.get("data")
    if not data:                            # جلسة قديمة بلا عرض محفوظ
        _throttle_generation(request)
        data, _ = _build_proposal_data(session["title"], session["client"],
                                       session["entity_type"], session["files_text"])
    proposal = db.create_proposal(session["title"], session["client"],
                                  session["entity_type"], data)
    agents.mark_session_used(sid, proposal["id"])
    db.log_audit("agents", proposal["id"], "generate", session["title"])
    return proposal


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
