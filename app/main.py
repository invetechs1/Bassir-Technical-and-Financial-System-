"""نظام عزوم للعروض الفنية والمالية — خادم التطبيق."""
import csv
import io
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import database as db
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


# ------------------------------ المصادقة ------------------------------

_OPEN_PATHS = ("/login", "/api/login", "/static/", "/favicon")


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
    request.state.username = username
    return await call_next(request)


@app.get("/login", response_class=HTMLResponse)
def login_page():
    return LOGIN_PAGE


@app.post("/api/login")
def api_login(body: dict):
    user = authenticate(body.get("username", ""), body.get("password", ""))
    if not user:
        raise HTTPException(401, "بيانات الدخول غير صحيحة")
    response = JSONResponse({"ok": True, "user": user})
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
    return {"username": request.state.username}


@app.post("/api/password")
def api_password(request: Request, body: dict):
    ok = change_password(request.state.username, body.get("old", ""), body.get("new", ""))
    if not ok:
        raise HTTPException(400, "كلمة المرور الحالية غير صحيحة أو الجديدة أقصر من 8 أحرف")
    return {"ok": True}


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
def post_price(item: dict):
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
    title: str = Form(...),
    client: str = Form(...),
    entity_type: str = Form("government"),
    files: list[UploadFile] = File(default=[]),
):
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
