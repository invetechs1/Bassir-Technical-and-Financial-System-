"""وحدة تنفيذ المشاريع — الإنتاجية اليومية ومقاولو الباطن.

مهندس الموقع يسجّل الإنتاجية اليومية ويحدد مَن نفّذ كل بند: عمالة الشركة أو
أحد مقاولي الباطن المسجّلين (قائمة منسدلة). التقرير يُقفل فور اعتماده —
أي تعديل لاحق من غير مالك الحساب يتحول إلى «طلب تعديل» يصل للمالك بإشعار،
فيقبله فيُطبَّق أو يرفضه، ويصل القرار للمهندس بإشعار. المالك وحده يعدّل
مباشرة. كل الجداول معزولة بالشركة (company_id) كبقية النظام.
"""
import json

from .database import get_db, log_audit, now_iso
from .tenancy import cid, user_id

EXEC_SCHEMA = """
CREATE TABLE IF NOT EXISTS subcontractors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL DEFAULT 1,
    name TEXT NOT NULL,
    cr_no TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    trade TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE (company_id, name)
);

CREATE TABLE IF NOT EXISTS exec_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL DEFAULT 1,
    name TEXT NOT NULL,
    client TEXT DEFAULT '',
    proposal_id INTEGER,
    status TEXT NOT NULL DEFAULT 'نشط',
    start_date TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL DEFAULT 1,
    project_id INTEGER NOT NULL REFERENCES exec_projects(id) ON DELETE CASCADE,
    report_date TEXT NOT NULL,
    engineer_id INTEGER NOT NULL,
    engineer_name TEXT DEFAULT '',
    lines TEXT NOT NULL DEFAULT '[]',
    notes TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'submitted',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reports_company ON daily_reports(company_id, report_date DESC);

CREATE TABLE IF NOT EXISTS report_edit_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL DEFAULT 1,
    report_id INTEGER NOT NULL REFERENCES daily_reports(id) ON DELETE CASCADE,
    requested_by INTEGER NOT NULL,
    requested_by_name TEXT DEFAULT '',
    payload TEXT NOT NULL,
    reason TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    decided_by INTEGER,
    decision_note TEXT DEFAULT '',
    decided_at TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL DEFAULT 1,
    user_id INTEGER NOT NULL,
    kind TEXT NOT NULL DEFAULT 'info',
    title TEXT NOT NULL,
    body TEXT DEFAULT '',
    ref TEXT DEFAULT '',
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications(company_id, user_id, is_read);
"""

# منفّذ العمل داخل سطر الإنتاجية: عمالة الشركة أو مقاول باطن
EXECUTOR_COMPANY = "company"
EXECUTOR_SUB = "subcontractor"
COMPANY_LABOR_LABEL = "عمالة الشركة"


def init_execution_tables():
    with get_db() as db:
        db.executescript(EXEC_SCHEMA)


# ------------------------- مقاولو الباطن -------------------------

def list_subcontractors(active_only: bool = False) -> list[dict]:
    q = "SELECT * FROM subcontractors WHERE company_id = ?"
    if active_only:
        q += " AND active = 1"
    with get_db() as db:
        rows = db.execute(q + " ORDER BY name", (cid(),)).fetchall()
    return [dict(r) for r in rows]


def upsert_subcontractor(item: dict) -> dict:
    with get_db() as db:
        if item.get("id"):
            db.execute(
                "UPDATE subcontractors SET name=?, cr_no=?, phone=?, trade=?, notes=?, active=? "
                "WHERE id=? AND company_id=?",
                (item["name"].strip(), item.get("cr_no", ""), item.get("phone", ""),
                 item.get("trade", ""), item.get("notes", ""),
                 1 if item.get("active", 1) else 0, item["id"], cid()),
            )
            sid = item["id"]
            log_audit("subcontractors", sid, "update", item["name"])
        else:
            cur = db.execute(
                "INSERT INTO subcontractors (company_id, name, cr_no, phone, trade, notes, active, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                (cid(), item["name"].strip(), item.get("cr_no", ""), item.get("phone", ""),
                 item.get("trade", ""), item.get("notes", ""), now_iso()),
            )
            sid = cur.lastrowid
            log_audit("subcontractors", sid, "create", item["name"])
    return {"ok": True, "id": sid}


def delete_subcontractor(sid: int):
    with get_db() as db:
        db.execute("DELETE FROM subcontractors WHERE id=? AND company_id=?", (sid, cid()))
    log_audit("subcontractors", sid, "delete")


def executor_options() -> list[dict]:
    """خيارات القائمة المنسدلة «مَن نفّذ العمل» — عمالة الشركة ثم مقاولو الباطن النشطون."""
    opts = [{"type": EXECUTOR_COMPANY, "id": 0, "label": COMPANY_LABOR_LABEL}]
    for s in list_subcontractors(active_only=True):
        opts.append({"type": EXECUTOR_SUB, "id": s["id"], "label": f"مقاول باطن — {s['name']}"})
    return opts


# ------------------------- مشاريع التنفيذ -------------------------

def list_projects() -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT p.*, (SELECT COUNT(*) FROM daily_reports r "
            "  WHERE r.project_id = p.id AND r.company_id = p.company_id) AS reports_count "
            "FROM exec_projects p WHERE p.company_id = ? ORDER BY p.created_at DESC",
            (cid(),)).fetchall()
    return [dict(r) for r in rows]


def upsert_project(item: dict) -> dict:
    with get_db() as db:
        if item.get("id"):
            db.execute(
                "UPDATE exec_projects SET name=?, client=?, proposal_id=?, status=?, start_date=?, notes=? "
                "WHERE id=? AND company_id=?",
                (item["name"].strip(), item.get("client", ""), item.get("proposal_id") or None,
                 item.get("status", "نشط"), item.get("start_date", ""), item.get("notes", ""),
                 item["id"], cid()),
            )
            pid = item["id"]
        else:
            cur = db.execute(
                "INSERT INTO exec_projects (company_id, name, client, proposal_id, status, start_date, notes, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (cid(), item["name"].strip(), item.get("client", ""), item.get("proposal_id") or None,
                 item.get("status", "نشط"), item.get("start_date", ""), item.get("notes", ""), now_iso()),
            )
            pid = cur.lastrowid
    log_audit("exec_projects", pid, "upsert", item["name"])
    return {"ok": True, "id": pid}


def get_project(pid: int) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM exec_projects WHERE id=? AND company_id=?",
                         (pid, cid())).fetchone()
    return dict(row) if row else None


def project_boq_items(pid: int) -> list[dict]:
    """بنود جدول كميات العرض المرتبط (إن وُجد) — لاقتراحها عند تسجيل الإنتاجية."""
    project = get_project(pid)
    if not project or not project.get("proposal_id"):
        return []
    with get_db() as db:
        row = db.execute("SELECT data FROM proposals WHERE id=? AND company_id=?",
                         (project["proposal_id"], cid())).fetchone()
    if not row:
        return []
    try:
        boq = json.loads(row["data"]).get("boq", [])
    except (json.JSONDecodeError, AttributeError):
        return []
    items = []
    for line in boq:
        children = line.get("children") or []
        if children:
            for c in children:
                items.append({"name": f"{line.get('name', '')} — {c.get('name', '')}",
                              "unit": c.get("unit") or line.get("unit", ""),
                              "qty": c.get("qty", line.get("qty"))})
        else:
            items.append({"name": line.get("name", ""), "unit": line.get("unit", ""),
                          "qty": line.get("qty")})
    return items


# ------------------------- التقارير اليومية -------------------------

def _clean_lines(lines: list[dict], subs_by_id: dict[int, str]) -> list[dict]:
    """تثبيت أسطر التقرير: كمية رقمية، ومنفّذ محسوم (عمالة الشركة أو مقاول باطن قائم)."""
    cleaned = []
    for l in lines or []:
        name = (l.get("item") or l.get("name") or "").strip()
        if not name:
            continue
        ex_type = l.get("executor_type") or EXECUTOR_COMPANY
        sub_id = int(l.get("subcontractor_id") or 0)
        if ex_type == EXECUTOR_SUB and sub_id in subs_by_id:
            ex_name = subs_by_id[sub_id]
        else:
            ex_type, sub_id, ex_name = EXECUTOR_COMPANY, 0, COMPANY_LABOR_LABEL
        cleaned.append({
            "item": name,
            "unit": (l.get("unit") or "").strip(),
            "qty": float(l.get("qty") or 0),
            "executor_type": ex_type,
            "subcontractor_id": sub_id,
            "executor_name": ex_name,
            "notes": (l.get("notes") or "").strip(),
        })
    return cleaned


def _subs_map() -> dict[int, str]:
    return {s["id"]: s["name"] for s in list_subcontractors()}


def create_report(body: dict, engineer_name: str) -> dict:
    project = get_project(int(body.get("project_id") or 0))
    if not project:
        raise ValueError("المشروع غير موجود")
    lines = _clean_lines(body.get("lines") or [], _subs_map())
    if not lines:
        raise ValueError("أضف سطر إنتاجية واحداً على الأقل (البند والكمية ومَن نفّذ)")
    now = now_iso()
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO daily_reports (company_id, project_id, report_date, engineer_id, "
            " engineer_name, lines, notes, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'submitted', ?, ?)",
            (cid(), project["id"], body.get("report_date") or now[:10], user_id(),
             engineer_name, json.dumps(lines, ensure_ascii=False), body.get("notes", ""), now, now),
        )
        rid = cur.lastrowid
    log_audit("daily_reports", rid, "create", f"{project['name']} — {len(lines)} سطر")
    return {"ok": True, "id": rid}


def list_reports(project_id: int | None = None) -> list[dict]:
    q = ("SELECT r.*, p.name AS project_name FROM daily_reports r "
         "JOIN exec_projects p ON p.id = r.project_id "
         "WHERE r.company_id = ?")
    args: list = [cid()]
    if project_id:
        q += " AND r.project_id = ?"
        args.append(project_id)
    q += " ORDER BY r.report_date DESC, r.id DESC"
    with get_db() as db:
        rows = db.execute(q, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["lines"] = json.loads(d["lines"] or "[]")
        d["pending_edit"] = _pending_request_id(d["id"])
        out.append(d)
    return out


def get_report(rid: int) -> dict | None:
    with get_db() as db:
        row = db.execute(
            "SELECT r.*, p.name AS project_name FROM daily_reports r "
            "JOIN exec_projects p ON p.id = r.project_id "
            "WHERE r.id = ? AND r.company_id = ?", (rid, cid())).fetchone()
    if not row:
        return None
    d = dict(row)
    d["lines"] = json.loads(d["lines"] or "[]")
    d["pending_edit"] = _pending_request_id(rid)
    return d


def _pending_request_id(rid: int) -> int | None:
    with get_db() as db:
        row = db.execute(
            "SELECT id FROM report_edit_requests WHERE report_id=? AND company_id=? "
            "AND status='pending'", (rid, cid())).fetchone()
    return row["id"] if row else None


def _apply_report_changes(rid: int, payload: dict):
    lines = _clean_lines(payload.get("lines") or [], _subs_map())
    with get_db() as db:
        db.execute(
            "UPDATE daily_reports SET report_date = COALESCE(?, report_date), "
            " lines = ?, notes = COALESCE(?, notes), updated_at = ? "
            "WHERE id = ? AND company_id = ?",
            (payload.get("report_date"), json.dumps(lines, ensure_ascii=False),
             payload.get("notes"), now_iso(), rid, cid()),
        )


def owner_update_report(rid: int, payload: dict) -> dict:
    """المالك يعدّل مباشرة — بلا طلبات."""
    if not get_report(rid):
        raise ValueError("التقرير غير موجود")
    _apply_report_changes(rid, payload)
    log_audit("daily_reports", rid, "owner_update")
    return {"ok": True, "applied": True}


def request_report_edit(rid: int, payload: dict, requester_name: str, owners: list[dict]) -> dict:
    """غير المالك: التقرير مقفل — يُسجَّل طلب تعديل ويُشعَر الملّاك."""
    report = get_report(rid)
    if not report:
        raise ValueError("التقرير غير موجود")
    if report["pending_edit"]:
        raise ValueError("يوجد طلب تعديل معلّق على هذا التقرير — بانتظار قرار مالك الحساب")
    now = now_iso()
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO report_edit_requests (company_id, report_id, requested_by, "
            " requested_by_name, payload, reason, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
            (cid(), rid, user_id(), requester_name,
             json.dumps(payload, ensure_ascii=False), payload.get("reason", ""), now),
        )
        req_id = cur.lastrowid
    for o in owners:
        notify(o["user_id"],
               "طلب تعديل تقرير إنتاجية",
               f"{requester_name} يطلب تعديل تقرير {report['report_date']} "
               f"لمشروع «{report['project_name']}» — راجعه للقبول أو الرفض.",
               kind="edit_request", ref=f"edit_request:{req_id}")
    log_audit("report_edit_requests", req_id, "create", f"تقرير {rid}")
    return {"ok": True, "pending": True, "request_id": req_id}


def list_edit_requests(mine_only_user: int | None = None) -> list[dict]:
    q = ("SELECT e.*, r.report_date, r.project_id, p.name AS project_name "
         "FROM report_edit_requests e "
         "JOIN daily_reports r ON r.id = e.report_id "
         "JOIN exec_projects p ON p.id = r.project_id "
         "WHERE e.company_id = ?")
    args: list = [cid()]
    if mine_only_user is not None:
        q += " AND e.requested_by = ?"
        args.append(mine_only_user)
    q += " ORDER BY CASE e.status WHEN 'pending' THEN 0 ELSE 1 END, e.created_at DESC LIMIT 100"
    with get_db() as db:
        rows = db.execute(q, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["payload"] = json.loads(d["payload"] or "{}")
        out.append(d)
    return out


def decide_edit_request(req_id: int, action: str, note: str, decider_name: str) -> dict:
    """قرار المالك: approve يطبّق التعديل على التقرير، reject يبقيه كما هو — وإشعار للطالب."""
    with get_db() as db:
        row = db.execute("SELECT * FROM report_edit_requests WHERE id=? AND company_id=?",
                         (req_id, cid())).fetchone()
    if not row:
        raise ValueError("طلب التعديل غير موجود")
    if row["status"] != "pending":
        raise ValueError("هذا الطلب محسوم مسبقاً")
    approved = action == "approve"
    if approved:
        _apply_report_changes(row["report_id"], json.loads(row["payload"]))
    with get_db() as db:
        db.execute(
            "UPDATE report_edit_requests SET status=?, decided_by=?, decision_note=?, decided_at=? "
            "WHERE id=? AND company_id=?",
            ("approved" if approved else "rejected", user_id(), note, now_iso(), req_id, cid()),
        )
    report = get_report(row["report_id"]) or {}
    verdict = "قُبل" if approved else "رُفض"
    notify(row["requested_by"],
           f"{verdict} طلب تعديل التقرير",
           f"{verdict} طلبك تعديل تقرير {report.get('report_date', '')} "
           f"لمشروع «{report.get('project_name', '')}»"
           + (f" — ملاحظة {decider_name}: {note}" if note else "."),
           kind="edit_decision", ref=f"report:{row['report_id']}")
    log_audit("report_edit_requests", req_id, action, note)
    return {"ok": True, "applied": approved}


def delete_report(rid: int):
    with get_db() as db:
        db.execute("DELETE FROM daily_reports WHERE id=? AND company_id=?", (rid, cid()))
    log_audit("daily_reports", rid, "delete")


# ------------------------- الإشعارات -------------------------

def notify(to_user: int, title: str, body: str = "", kind: str = "info", ref: str = ""):
    with get_db() as db:
        db.execute(
            "INSERT INTO notifications (company_id, user_id, kind, title, body, ref, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (cid(), to_user, kind, title, body, ref, now_iso()),
        )


def my_notifications(uid: int, limit: int = 30) -> dict:
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM notifications WHERE company_id=? AND user_id=? "
            "ORDER BY id DESC LIMIT ?", (cid(), uid, limit)).fetchall()
        unread = db.execute(
            "SELECT COUNT(*) AS n FROM notifications WHERE company_id=? AND user_id=? AND is_read=0",
            (cid(), uid)).fetchone()["n"]
    return {"items": [dict(r) for r in rows], "unread": unread}


def mark_notifications_read(uid: int, notif_id: int | None = None):
    with get_db() as db:
        if notif_id:
            db.execute("UPDATE notifications SET is_read=1 WHERE id=? AND company_id=? AND user_id=?",
                       (notif_id, cid(), uid))
        else:
            db.execute("UPDATE notifications SET is_read=1 WHERE company_id=? AND user_id=?",
                       (cid(), uid))


# ------------------------- تحليل الإنتاجية حسب المنفّذ -------------------------

def productivity_summary(project_id: int | None = None) -> list[dict]:
    """كم اشتغل كل منفّذ (عمالة الشركة/كل مقاول باطن)؟

    لكل منفّذ: عدد التقارير التي ظهر فيها وعدد الأسطر، وتفصيل الكميات
    مجموعةً بالوحدة (م2، م.ط، عدد...) لأن جمع وحدات مختلفة معاً لا يصح."""
    totals: dict[str, dict] = {}
    for r in list_reports(project_id):
        for l in r["lines"]:
            key = l.get("executor_name") or COMPANY_LABOR_LABEL
            agg = totals.setdefault(key, {"executor": key,
                                          "executor_type": l.get("executor_type", EXECUTOR_COMPANY),
                                          "lines": 0, "reports": set(), "by_unit": {}})
            agg["lines"] += 1
            agg["reports"].add(r["id"])
            unit = (l.get("unit") or "—").strip() or "—"
            agg["by_unit"][unit] = round(agg["by_unit"].get(unit, 0.0) + float(l.get("qty") or 0), 2)
    out = []
    for agg in totals.values():
        agg["reports"] = len(agg["reports"])
        agg["by_unit"] = [{"unit": u, "qty": q} for u, q in
                          sorted(agg["by_unit"].items(), key=lambda kv: -kv[1])]
        out.append(agg)
    return sorted(out, key=lambda a: (-a["lines"], a["executor"]))
