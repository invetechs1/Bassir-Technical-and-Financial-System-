"""نظام عزوم للعروض الفنية والمالية — خادم التطبيق."""
import csv
import io
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import database as db
from . import tenancy
from .auth import (LOGIN_PAGE, SESSION_COOKIE, authenticate, change_password,
                   create_session_token, init_auth, verify_session_token)
from .ai_engine import ai_available, generate_proposal_ai
from .analytics import compute_analytics
from .config import EXPORTS_DIR
from .export_docx import export_proposal_docx
from .export_xlsx import export_boq_xlsx
from .file_extract import extract_text
from .proposal_builder import build_template_proposal, compute_financials, match_price_catalog
from .etimad import fetch_tenders, has_session, list_tenders, update_tender_status
from .opportunity import analyze_opportunity
from .repository import find_relevant_repo_texts, ingest_file
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


# ------------------------------ المصادقة والصلاحيات ------------------------------

_OPEN_PATHS = ("/login", "/api/login", "/signup", "/api/signup", "/static/", "/favicon")
COMPANY_COOKIE = "azoom_company"

# الصفحات الخمس الإدارية — القراءة والكتابة على الأدمن (owner/admin) فقط
_ADMIN_API_PREFIXES = ("/api/prices", "/api/library", "/api/repo", "/api/market", "/api/analytics", "/api/repository", "/api/style-profile", "/api/paragraph")
# مسارات يجوز فيها غير-GET لدور المشاهد (شؤون حسابه فقط)
_VIEWER_WRITE_OK = ("/api/logout", "/api/password", "/api/session/company")


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

    # حل الشركة الحالية: كوكي الشركة إن كانت عضويته قائمة، وإلا أول عضوياته
    from .auth import get_user
    user = get_user(username)
    if not user:
        return JSONResponse({"detail": "الحساب غير موجود"}, status_code=401)
    companies = db.user_companies(user["id"])
    if not companies:
        return JSONResponse({"detail": "لا عضوية لك في أي شركة — راجع مدير المنصة"}, status_code=403)
    wanted = request.cookies.get(COMPANY_COOKIE, "")
    current = next((c for c in companies if str(c["id"]) == wanted), companies[0])

    request.state.username = username
    request.state.user_id = user["id"]
    request.state.role = current["role"]
    request.state.company_id = current["id"]
    request.state.company_name = current["name"]
    request.state.is_platform_admin = bool(user.get("is_platform_admin"))

    # فرض الأدوار في الخادم — إخفاء الأزرار في الواجهة ليس حماية
    role = current["role"]
    is_admin = role in tenancy.ADMIN_ROLES
    if path.startswith(_ADMIN_API_PREFIXES) and not is_admin:
        return JSONResponse({"detail": "هذه الصفحة للأدمن فقط"}, status_code=403)
    if role == "viewer" and request.method not in ("GET", "HEAD") \
            and not path.startswith(_VIEWER_WRITE_OK):
        return JSONResponse({"detail": "دورك (مُشاهد) للقراءة والتصدير فقط"}, status_code=403)

    # دورة حياة الاشتراك: منتهي التجربة قراءة وتصدير فقط، والموقوف محجوب
    company_row = db.get_company(current["id"]) or {}
    sub_status = db.effective_subscription_status(company_row)
    request.state.sub_status = sub_status
    if sub_status == "suspended" and path != "/api/logout" and path != "/api/me":
        return JSONResponse({"detail": "الاشتراك موقوف — تواصلوا معنا لإعادة التفعيل. بياناتكم محفوظة."},
                            status_code=402)
    if sub_status == "read_only" and request.method not in ("GET", "HEAD") \
            and not path.startswith(_VIEWER_WRITE_OK):
        return JSONResponse({"detail": "انتهت فترة التجربة — القراءة والتصدير متاحان، ورقّوا الاشتراك للمتابعة."},
                            status_code=402)

    # بوابات الميزات: 402 لا 403 — الواجهة تعرض دعوة الترقية
    limits = tenancy.PLAN_LIMITS.get(company_row.get("plan", "trial"), tenancy.PLAN_LIMITS["trial"])
    if path.startswith(("/api/etimad", "/api/forsah")) and not limits.get("integrations"):
        return JSONResponse({"detail": "ربط اعتماد وفرصة متاح في الخطة الاحترافية فأعلى — رقّوا الاشتراك."},
                            status_code=402)
    if path.startswith(("/api/style-profile", "/api/paragraph", "/api/repository/technical")) \
            and not limits.get("style_engine"):
        return JSONResponse({"detail": "بصمة الكتابة وبنك الفقرات متاحان في الخطة الاحترافية فأعلى — رقّوا الاشتراك."},
                            status_code=402)

    tokens = tenancy.set_context(current["id"], role, user["id"],
                                 bool(user.get("is_platform_admin")))
    try:
        return await call_next(request)
    finally:
        tenancy.reset_context(tokens)


@app.get("/login", response_class=HTMLResponse)
def login_page():
    return LOGIN_PAGE


@app.post("/api/login")
def api_login(body: dict):
    user = authenticate(body.get("username", ""), body.get("password", ""))
    if not user:
        raise HTTPException(401, "بيانات الدخول غير صحيحة")
    companies = db.user_companies(user["id"])
    response = JSONResponse({"ok": True, "user": user, "companies": companies})
    response.set_cookie(SESSION_COOKIE, create_session_token(user["username"]),
                        httponly=True, samesite="lax", max_age=12 * 3600)
    return response


@app.post("/api/logout")
def api_logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE)
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
    return db.user_companies(request.state.user_id)


@app.post("/api/session/company/{company_id}")
def switch_company(request: Request, company_id: int):
    m = db.get_membership(request.state.user_id, company_id)
    if not m and not request.state.is_platform_admin:
        raise HTTPException(403, "لا تملك عضوية في هذه الشركة")
    role = m["role"] if m else "admin"
    response = JSONResponse({"ok": True, "role": role})
    response.set_cookie(COMPANY_COOKIE, str(company_id), httponly=True,
                        samesite="lax", max_age=90 * 24 * 3600)
    return response


@app.get("/api/companies")
def companies_list(request: Request):
    _require_platform_admin(request)
    out = []
    for c in db.list_companies():
        out.append({**c, "usage": db.company_usage(c["id"]),
                   "limits": tenancy.PLAN_LIMITS.get(c["plan"], {}),
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
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "اسم الشركة مطلوب")
    if db.find_company_by_name(name):
        raise HTTPException(409, "توجد شركة بهذا الاسم مسبقاً")
    company = db.create_company(name, body.get("short_name", ""),
                                body.get("plan", "trial"), body.get("sector", ""),
                                body.get("cr_no", ""), body.get("vat_no", ""),
                                body.get("currency", "SAR"), body.get("contact_phone", ""))
    owner_username = (body.get("owner_username") or "").strip()
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
    username = (body.get("username") or "").strip()
    if not username:
        raise HTTPException(400, "اسم المستخدم مطلوب")
    from .auth import create_user, get_user
    user = get_user(username)
    if not user:
        try:
            user = create_user(username, body.get("password") or "",
                               body.get("display_name", ""))
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    db.set_membership(user["id"], request.state.company_id, role, request.state.user_id)
    db.log_audit("memberships", user["id"], "invite", f"{username} → {role}")
    return {"ok": True, "user_id": user["id"], "role": role}


@app.put("/api/members/{uid}")
def members_role(request: Request, uid: int, body: dict):
    """تغيير دور عضو — المالك أو مدير المنصة."""
    if request.state.role != "owner" and not request.state.is_platform_admin:
        raise HTTPException(403, "تغيير الأدوار لمالك الحساب فقط")
    role = body.get("role", "")
    if role not in tenancy.ROLES:
        raise HTTPException(400, "الدور غير معروف")
    if not db.get_membership(uid, request.state.company_id):
        raise HTTPException(404, "العضو غير موجود في هذه الشركة")
    db.set_membership(uid, request.state.company_id, role)
    db.log_audit("memberships", uid, "role_change", role)
    return {"ok": True}


@app.delete("/api/members/{uid}")
def members_remove(request: Request, uid: int):
    if request.state.role != "owner" and not request.state.is_platform_admin:
        raise HTTPException(403, "إزالة الأعضاء لمالك الحساب فقط")
    if uid == request.state.user_id:
        raise HTTPException(400, "لا يمكنك إزالة نفسك")
    db.remove_membership(uid, request.state.company_id)
    db.log_audit("memberships", uid, "remove")
    return {"ok": True}


# شعار كل شركة — الصيغ النقطية فقط (SVG مرفوض: ثغرة XSS إن عُرض بلا تعقيم)
_LOGO_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
_MAX_LOGO_BYTES = 2 * 1024 * 1024
_BRAND_COLORS = ["#175934", "#2E7D8C", "#7A5A2E", "#5A3E86"]


def _brand_color(company_id: int) -> str:
    return _BRAND_COLORS[company_id % len(_BRAND_COLORS)]


def _logo_path(company_id: int):
    from .config import DATA_DIR
    branding = DATA_DIR / "branding"
    branding.mkdir(exist_ok=True)
    for ext in (".png", ".jpg", ".webp"):
        pth = branding / f"logo_{company_id}{ext}"
        if pth.exists():
            return pth
    return None


@app.post("/api/companies/{company_id}/logo")
async def upload_company_logo(request: Request, company_id: int,
                              logo: UploadFile = File(...)):
    m = db.get_membership(request.state.user_id, company_id)
    allowed = request.state.is_platform_admin or (m and m["role"] in tenancy.ADMIN_ROLES)
    if not allowed:
        raise HTTPException(403, "رفع الشعار لأدمن الشركة أو مدير المنصة")
    if logo.content_type not in _LOGO_TYPES:
        raise HTTPException(415, "الصيغ المقبولة: PNG أو JPG أو WebP (حتى 2 ميجابايت)")
    content = await logo.read()
    if len(content) > _MAX_LOGO_BYTES:
        raise HTTPException(413, "حجم الملف يتجاوز 2 ميجابايت")
    from .config import DATA_DIR
    branding = DATA_DIR / "branding"
    branding.mkdir(exist_ok=True)
    old = _logo_path(company_id)
    if old:
        old.unlink()
    path = branding / f"logo_{company_id}{_LOGO_TYPES[logo.content_type]}"
    path.write_bytes(content)
    with db.get_db() as conn:
        conn.execute("UPDATE companies SET logo_url = ? WHERE id = ?",
                     (f"/api/companies/{company_id}/logo", company_id))
    db.log_audit("companies", company_id, "update", "logo uploaded")
    return {"ok": True, "logo_url": f"/api/companies/{company_id}/logo"}


@app.get("/api/companies/{company_id}/logo")
def get_company_logo(request: Request, company_id: int):
    # أي عضو مسجل دخوله يرى شعارات الشركات (تظهر في مبدل الشركات)
    path = _logo_path(company_id)
    if not path:
        raise HTTPException(404, "لا شعار مرفوعاً لهذه الشركة")
    return FileResponse(path)


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

# مفاتيح داخلية لا يجب أن تُعرض أو تُعدَّل عبر API الإعدادات العام
_INTERNAL_SETTINGS_KEYS = {"auth_secret"}


def _public_settings() -> dict:
    return {k: v for k, v in db.get_settings().items() if k not in _INTERNAL_SETTINGS_KEYS}


@app.get("/api/settings")
def get_settings():
    return _public_settings()


@app.put("/api/settings")
def put_settings(values: dict):
    values = {k: v for k, v in values.items() if k not in _INTERNAL_SETTINGS_KEYS}
    db.update_settings(values)
    return _public_settings()


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
async def import_prices_csv(file: UploadFile = File(...)):
    content = (await file.read()).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(content))
    count = 0
    for row in reader:
        if not row.get("code") or not row.get("name"):
            continue
        db.upsert_price_item({
            "code": row["code"].strip(),
            "category": (row.get("category") or "غير مصنف").strip(),
            "name": row["name"].strip(),
            "unit": (row.get("unit") or "وحدة").strip(),
            "unit_price": float(row.get("unit_price") or 0),
            "notes": (row.get("notes") or "").strip(),
        })
        count += 1
    return {"imported": count}


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
async def repo_upload(
    source_type: str = Form("عرض عزوم سابق"),
    company: str = Form(""),
    notes: str = Form(""),
    as_reference: str = Form(""),
    sector: str = Form(""),
    files: list[UploadFile] = File(...),
):
    make_ref = as_reference in ("1", "true", "on", "yes")
    results = []
    for f in files:
        content = await f.read()
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
def signup(body: dict):
    """تسجيل شركة جديدة ذاتياً: خطة تجريبية 14 يوماً مع مالك حسابها."""
    name = (body.get("name") or "").strip()
    cr_no = (body.get("cr_no") or "").strip()
    owner_username = (body.get("owner_username") or "").strip()
    password = body.get("owner_password") or ""
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
        owner = create_user(owner_username, password, body.get("owner_display_name", ""))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    company = db.create_company(name, body.get("short_name", ""), "trial",
                                body.get("sector", ""), cr_no, body.get("vat_no", ""))
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


@app.get("/api/platform/metrics")
def platform_metrics(request: Request):
    _require_platform_admin(request)
    companies = db.list_companies()
    paid = [c for c in companies
            if c["plan"] != "trial" and c["subscription_status"] == "active"]
    mrr = sum(tenancy.PLAN_PRICE.get(c["plan"]) or 0 for c in paid)
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
async def opportunity(
    title: str = Form(...),
    client: str = Form(""),
    files: list[UploadFile] = File(default=[]),
):
    texts = []
    for f in files:
        content = await f.read()
        texts.append(extract_text(f.filename or "file", content))
    return analyze_opportunity(title, client, "\n\n".join(texts))


# ------------------------- توليد العروض وإدارتها -------------------------

@app.post("/api/proposals/generate")
async def generate_proposal(
    request: Request,
    title: str = Form(...),
    client: str = Form(...),
    entity_type: str = Form("government"),
    files: list[UploadFile] = File(default=[]),
):
    _enforce_limit(request, "proposals_month")
    texts = []
    for f in files:
        content = await f.read()
        extracted = extract_text(f.filename or "file", content)
        texts.append(f"===== الملف: {f.filename} =====\n{extracted}")
    files_text = "\n\n".join(texts)

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
    proposal = db.create_proposal(title, client, entity_type, data)
    return proposal


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


@app.get("/api/proposals/{pid}/export/docx")
def export_docx(pid: int):
    proposal = db.get_proposal(pid)
    if not proposal:
        raise HTTPException(404, "العرض غير موجود")
    path = EXPORTS_DIR / f"{proposal['ref_no']}.docx"
    export_proposal_docx(proposal, db.get_settings(), str(path))
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"{proposal['ref_no']}.docx",
    )


@app.get("/api/proposals/{pid}/export/xlsx")
def export_xlsx(pid: int):
    proposal = db.get_proposal(pid)
    if not proposal:
        raise HTTPException(404, "العرض غير موجود")
    path = EXPORTS_DIR / f"{proposal['ref_no']}-BOQ.xlsx"
    export_boq_xlsx(proposal, str(path))
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=f"{proposal['ref_no']}-BOQ.xlsx",
    )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
