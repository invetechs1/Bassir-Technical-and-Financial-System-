"""طبقة قاعدة البيانات — SQLite مع عزل تعدد الشركات.

كل جدول بيانات يحمل company_id، وكل دالة وصول هنا تعزل تلقائياً على الشركة
الحالية من سياق الطلب (app/tenancy.py). لا يمر أي SQL خام من طبقة الويب —
هذه الدوال هي المسار الوحيد للقراءة والكتابة، فلا يُنسى شرط العزل.

قواعد البيانات القديمة (شركة واحدة) تُرحَّل تلقائياً عند الإقلاع: بيانات
عزوم القائمة تصير الشركة رقم 1 ولا يُفقد شيء.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import DB_PATH, DEFAULT_SETTINGS
from .tenancy import cid, user_id

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    short_name TEXT DEFAULT '',
    logo_url TEXT DEFAULT '',
    cr_no TEXT DEFAULT '',
    vat_no TEXT DEFAULT '',
    currency TEXT NOT NULL DEFAULT 'SAR',
    sector TEXT DEFAULT '',
    plan TEXT NOT NULL DEFAULT 'trial',
    subscription_status TEXT NOT NULL DEFAULT 'active',
    trial_ends_at TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memberships (
    user_id INTEGER NOT NULL,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    role TEXT NOT NULL DEFAULT 'viewer',
    invited_by INTEGER,
    joined_at TEXT NOT NULL,
    PRIMARY KEY (user_id, company_id)
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    plan TEXT NOT NULL,
    seats INTEGER NOT NULL DEFAULT 1,
    price REAL,
    period_start TEXT, period_end TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    invoice_ref TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    actor_id INTEGER,
    entity TEXT NOT NULL,
    entity_id TEXT DEFAULT '',
    action TEXT NOT NULL,
    detail TEXT DEFAULT '',
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_company_at ON audit_events(company_id, at DESC);

CREATE TABLE IF NOT EXISTS settings (
    company_id INTEGER NOT NULL DEFAULT 1,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (company_id, key)
);

CREATE TABLE IF NOT EXISTS price_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL DEFAULT 1,
    code TEXT NOT NULL,
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    unit TEXT NOT NULL,
    unit_price REAL NOT NULL,
    notes TEXT DEFAULT '',
    updated_at TEXT NOT NULL,
    UNIQUE (company_id, code)
);

CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES price_items(id) ON DELETE CASCADE,
    old_price REAL NOT NULL,
    new_price REAL NOT NULL,
    changed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL DEFAULT 1,
    ref_no TEXT NOT NULL,
    title TEXT NOT NULL,
    client TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT 'government',
    status TEXT NOT NULL DEFAULT 'draft',
    data TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (company_id, ref_no)
);

CREATE TABLE IF NOT EXISTS content_library (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL DEFAULT 1,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    tags TEXT DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS repo_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL DEFAULT 1,
    filename TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'عرض عزوم سابق',
    company TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    sector TEXT DEFAULT '',
    extracted_text TEXT DEFAULT '',
    items_count INTEGER DEFAULT 0,
    uploaded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS market_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL DEFAULT 1,
    repo_file_id INTEGER REFERENCES repo_files(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    unit TEXT DEFAULT '',
    unit_price REAL NOT NULL,
    qty REAL,
    source_company TEXT DEFAULT '',
    source_type TEXT DEFAULT '',
    sector TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS company_docs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL DEFAULT 1,
    name TEXT NOT NULL,
    number TEXT DEFAULT '',
    issuer TEXT DEFAULT '',
    issue_date TEXT DEFAULT '',
    expiry_date TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    updated_at TEXT NOT NULL
);
"""

# الجداول التي تحمل company_id — تُستكمل هجرتها إن كانت من نسخة قديمة
_TENANT_TABLES = ("settings", "price_items", "proposals", "content_library",
                  "repo_files", "market_prices", "company_docs",
                  "etimad_tenders", "forsah_projects")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _cols(db, table: str) -> list[str]:
    return [r["name"] for r in db.execute(f"PRAGMA table_info({table})").fetchall()]


def _table_exists(db, table: str) -> bool:
    return bool(db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def _ensure_column(db, table: str, column: str, decl: str):
    """هجرة آمنة: إضافة عمود لجدول قائم إن لم يكن موجوداً."""
    if _table_exists(db, table) and column not in _cols(db, table):
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def _rebuild_settings(db):
    """settings القديم (key مفتاح وحيد) → مفتاح مركب (company_id, key)."""
    if "company_id" in _cols(db, "settings"):
        return
    db.executescript("""
        CREATE TABLE settings_new (
            company_id INTEGER NOT NULL DEFAULT 1,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            PRIMARY KEY (company_id, key)
        );
        INSERT INTO settings_new (company_id, key, value) SELECT 1, key, value FROM settings;
        DROP TABLE settings;
        ALTER TABLE settings_new RENAME TO settings;
    """)


def _rebuild_unique_per_company(db, table: str, unique_col: str):
    """إزالة قيد UNIQUE العام (code/ref_no) واستبداله بقيد داخل الشركة."""
    ddl = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                     (table,)).fetchone()
    if not ddl or "company_id" in _cols(db, table):
        return
    old_cols = _cols(db, table)
    cols_csv = ", ".join(old_cols)
    new_ddl = ddl["sql"].replace(f"{unique_col} TEXT UNIQUE NOT NULL", f"{unique_col} TEXT NOT NULL")
    new_ddl = new_ddl.replace(f"CREATE TABLE {table}", f"CREATE TABLE {table}_new")
    new_ddl = new_ddl.rstrip().rstrip(")")
    new_ddl += f", company_id INTEGER NOT NULL DEFAULT 1, UNIQUE (company_id, {unique_col}))"
    db.execute(new_ddl)
    db.execute(f"INSERT INTO {table}_new ({cols_csv}) SELECT {cols_csv} FROM {table}")
    db.execute(f"DROP TABLE {table}")
    db.execute(f"ALTER TABLE {table}_new RENAME TO {table}")


def _migrate_multitenant(db):
    """ترحيل قاعدة قديمة (شركة واحدة) — كل شيء يصير الشركة رقم 1 (عزوم)."""
    _rebuild_settings(db)
    _rebuild_unique_per_company(db, "price_items", "code")
    _rebuild_unique_per_company(db, "proposals", "ref_no")
    for table in ("content_library", "repo_files", "market_prices", "company_docs",
                  "etimad_tenders", "forsah_projects"):
        _ensure_column(db, table, "company_id", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(db, "users", "is_platform_admin", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(db, "users", "last_login_at", "TEXT DEFAULT ''")
    # الفهارس بعد اكتمال أعمدة الترحيل
    db.execute("CREATE INDEX IF NOT EXISTS idx_prices_company ON price_items(company_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_proposals_company ON proposals(company_id, created_at DESC)")
    # شركة عزوم الأصلية
    if not db.execute("SELECT 1 FROM companies WHERE id = 1").fetchone():
        db.execute(
            "INSERT INTO companies (id, name, short_name, cr_no, vat_no, currency, sector, plan, "
            " subscription_status, created_at) "
            "VALUES (1, 'شركة عزوم المتحدة للمقاولات', 'عزوم', '1010467099', '311917527400003', "
            " 'SAR', 'المقاولات العامة', 'enterprise', 'active', ?)",
            (now_iso(),),
        )


def ensure_memberships():
    """كل مستخدم بلا عضوية يصير مالكاً في شركة عزوم (1) — يُستدعى بعد init_auth."""
    with get_db() as db:
        if not _table_exists(db, "users"):
            return
        # جدول المستخدمين يُنشأ في init_auth بعد الترحيل — نضمن أعمدته هنا
        _ensure_column(db, "users", "is_platform_admin", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(db, "users", "last_login_at", "TEXT DEFAULT ''")
        rows = db.execute(
            "SELECT u.id, u.username FROM users u "
            "LEFT JOIN memberships m ON m.user_id = u.id WHERE m.user_id IS NULL"
        ).fetchall()
        for r in rows:
            db.execute(
                "INSERT OR IGNORE INTO memberships (user_id, company_id, role, joined_at) "
                "VALUES (?, 1, 'owner', ?)", (r["id"], now_iso()),
            )
        # حساب azoom الأول هو مدير المنصة
        db.execute("UPDATE users SET is_platform_admin = 1 WHERE username = 'azoom'")


def init_db():
    with get_db() as db:
        db.executescript(SCHEMA)
        _migrate_multitenant(db)
        _ensure_column(db, "repo_files", "sector", "TEXT DEFAULT ''")
        _ensure_column(db, "market_prices", "sector", "TEXT DEFAULT ''")
        for key, value in DEFAULT_SETTINGS.items():
            db.execute(
                "INSERT OR IGNORE INTO settings (company_id, key, value) VALUES (1, ?, ?)",
                (key, value),
            )


# ------------------------- تدقيق العمليات -------------------------

def log_audit(entity: str, entity_id, action: str, detail: str = ""):
    try:
        with get_db() as db:
            db.execute(
                "INSERT INTO audit_events (company_id, actor_id, entity, entity_id, action, detail, at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cid(), user_id() or None, entity, str(entity_id or ""), action, detail[:500], now_iso()),
            )
    except Exception:
        pass  # التدقيق لا يُسقط العملية الأصلية أبداً


# ------------------------- الإعدادات (لكل شركة) -------------------------

# مفاتيح حساسة تُخزَّن مشفرة إن توفرت مكتبة التشفير
_SECRET_KEYS = {"forsah_password"}
_ENC_PREFIX = "enc:v1:"


def _fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return None
    from .config import DATA_DIR
    key_file = DATA_DIR / "secret.key"
    if not key_file.exists():
        key_file.write_bytes(Fernet.generate_key())
        try:
            key_file.chmod(0o600)
        except OSError:
            pass
    return Fernet(key_file.read_bytes())


def _enc_value(key: str, value: str) -> str:
    if key in _SECRET_KEYS and value and not value.startswith(_ENC_PREFIX):
        f = _fernet()
        if f:
            return _ENC_PREFIX + f.encrypt(value.encode()).decode()
    return value


def _dec_value(key: str, value: str) -> str:
    if key in _SECRET_KEYS and value.startswith(_ENC_PREFIX):
        f = _fernet()
        if f:
            try:
                return f.decrypt(value[len(_ENC_PREFIX):].encode()).decode()
            except Exception:
                return ""
    return value


def get_settings(company_id: int | None = None) -> dict:
    c = company_id if company_id is not None else cid()
    with get_db() as db:
        rows = db.execute("SELECT key, value FROM settings WHERE company_id = ?", (c,)).fetchall()
    return {r["key"]: _dec_value(r["key"], r["value"]) for r in rows}


def update_settings(values: dict, company_id: int | None = None):
    c = company_id if company_id is not None else cid()
    with get_db() as db:
        for key, value in values.items():
            db.execute(
                "INSERT INTO settings (company_id, key, value) VALUES (?, ?, ?) "
                "ON CONFLICT(company_id, key) DO UPDATE SET value = excluded.value",
                (c, key, _enc_value(key, str(value))),
            )


def seed_company_defaults(company_id: int, name: str):
    """إعدادات افتراضية لشركة جديدة: النسب المالية القياسية وبيانات شركة فارغة."""
    azoom_specific = {"company_cr", "company_vat_no", "company_address", "company_bank",
                      "company_iban", "company_chamber_no", "company_phone", "company_email",
                      "etimad_national_id", "forsah_email", "forsah_password"}
    values = {k: ("" if k in azoom_specific else v) for k, v in DEFAULT_SETTINGS.items()}
    values["company_name"] = name
    update_settings(values, company_id=company_id)


# ------------------------- الشركات والعضويات -------------------------

def create_company(name: str, short_name: str = "", plan: str = "trial",
                   sector: str = "", cr_no: str = "", vat_no: str = "") -> dict:
    ts = now_iso()
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO companies (name, short_name, cr_no, vat_no, sector, plan, "
            " subscription_status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'active', ?)",
            (name, short_name or name[:12], cr_no, vat_no, sector, plan, ts),
        )
        row = db.execute("SELECT * FROM companies WHERE id = ?", (cur.lastrowid,)).fetchone()
    seed_company_defaults(row["id"], name)
    return dict(row)


def get_company(company_id: int) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
    return dict(row) if row else None


def list_companies() -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT c.*, COUNT(m.user_id) AS members FROM companies c "
            "LEFT JOIN memberships m ON m.company_id = c.id GROUP BY c.id ORDER BY c.id"
        ).fetchall()
    return [dict(r) for r in rows]


def find_company_by_name(name: str) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM companies WHERE name = ?", (name,)).fetchone()
    return dict(row) if row else None


def user_companies(uid: int) -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT c.id, c.name, c.short_name, c.plan, m.role FROM memberships m "
            "JOIN companies c ON c.id = m.company_id WHERE m.user_id = ? ORDER BY m.joined_at",
            (uid,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_membership(uid: int, company_id: int) -> dict | None:
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM memberships WHERE user_id = ? AND company_id = ?",
            (uid, company_id),
        ).fetchone()
    return dict(row) if row else None


def set_membership(uid: int, company_id: int, role: str, invited_by: int | None = None):
    with get_db() as db:
        db.execute(
            "INSERT INTO memberships (user_id, company_id, role, invited_by, joined_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id, company_id) DO UPDATE SET role = excluded.role",
            (uid, company_id, role, invited_by, now_iso()),
        )


def remove_membership(uid: int, company_id: int):
    with get_db() as db:
        db.execute("DELETE FROM memberships WHERE user_id = ? AND company_id = ?",
                   (uid, company_id))


def company_members(company_id: int) -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT u.id, u.username, u.display_name, u.last_login_at, m.role, m.joined_at "
            "FROM memberships m JOIN users u ON u.id = m.user_id "
            "WHERE m.company_id = ? ORDER BY m.joined_at",
            (company_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def company_usage(company_id: int) -> dict:
    month_start = datetime.now(timezone.utc).strftime("%Y-%m-01")
    with get_db() as db:
        users = db.execute("SELECT COUNT(*) AS n FROM memberships WHERE company_id = ?",
                           (company_id,)).fetchone()["n"]
        prices = db.execute("SELECT COUNT(*) AS n FROM price_items WHERE company_id = ?",
                            (company_id,)).fetchone()["n"]
        proposals_month = db.execute(
            "SELECT COUNT(*) AS n FROM proposals WHERE company_id = ? AND created_at >= ?",
            (company_id, month_start)).fetchone()["n"]
        proposals_total = db.execute("SELECT COUNT(*) AS n FROM proposals WHERE company_id = ?",
                                     (company_id,)).fetchone()["n"]
    return {"users": users, "price_items": prices,
            "proposals_month": proposals_month, "proposals_total": proposals_total}


# ------------------------- قاعدة الأسعار -------------------------

def list_price_items(search: str = "", category: str = "") -> list[dict]:
    query = "SELECT * FROM price_items WHERE company_id = ?"
    params: list = [cid()]
    if search:
        query += " AND (name LIKE ? OR code LIKE ?)"
        params += [f"%{search}%", f"%{search}%"]
    if category:
        query += " AND category = ?"
        params.append(category)
    query += " ORDER BY category, code"
    with get_db() as db:
        rows = db.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def upsert_price_item(item: dict) -> dict:
    ts = now_iso()
    with get_db() as db:
        existing = db.execute(
            "SELECT * FROM price_items WHERE company_id = ? AND code = ?",
            (cid(), item["code"]),
        ).fetchone()
        if existing:
            if float(existing["unit_price"]) != float(item["unit_price"]):
                db.execute(
                    "INSERT INTO price_history (item_id, old_price, new_price, changed_at) "
                    "VALUES (?, ?, ?, ?)",
                    (existing["id"], existing["unit_price"], item["unit_price"], ts),
                )
            db.execute(
                "UPDATE price_items SET category=?, name=?, unit=?, unit_price=?, notes=?, updated_at=? "
                "WHERE company_id=? AND code=?",
                (item["category"], item["name"], item["unit"], item["unit_price"],
                 item.get("notes", ""), ts, cid(), item["code"]),
            )
            row = db.execute("SELECT * FROM price_items WHERE company_id = ? AND code = ?",
                             (cid(), item["code"])).fetchone()
        else:
            cur = db.execute(
                "INSERT INTO price_items (company_id, code, category, name, unit, unit_price, notes, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (cid(), item["code"], item["category"], item["name"], item["unit"],
                 item["unit_price"], item.get("notes", ""), ts),
            )
            row = db.execute("SELECT * FROM price_items WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def delete_price_item(item_id: int):
    with get_db() as db:
        db.execute("DELETE FROM price_items WHERE id = ? AND company_id = ?", (item_id, cid()))


def get_price_history(item_id: int) -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT h.* FROM price_history h JOIN price_items p ON p.id = h.item_id "
            "WHERE h.item_id = ? AND p.company_id = ? ORDER BY h.changed_at DESC",
            (item_id, cid()),
        ).fetchall()
    return [dict(r) for r in rows]


# ------------------------- العروض -------------------------

def next_ref_no() -> str:
    year = datetime.now().year
    prefix = f"AZM-{year}-"
    with get_db() as db:
        row = db.execute(
            "SELECT ref_no FROM proposals WHERE company_id = ? AND ref_no LIKE ? "
            "ORDER BY id DESC LIMIT 1",
            (cid(), f"{prefix}%"),
        ).fetchone()
    seq = int(row["ref_no"].rsplit("-", 1)[1]) + 1 if row else 1
    return f"{prefix}{seq:03d}"


def create_proposal(title: str, client: str, entity_type: str, data: dict) -> dict:
    ts = now_iso()
    ref_no = next_ref_no()
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO proposals (company_id, ref_no, title, client, entity_type, status, data, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'draft', ?, ?, ?)",
            (cid(), ref_no, title, client, entity_type, json.dumps(data, ensure_ascii=False), ts, ts),
        )
        row = db.execute("SELECT * FROM proposals WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _proposal_dict(row)


def update_proposal(pid: int, fields: dict) -> dict | None:
    allowed = {"title", "client", "entity_type", "status", "data"}
    sets, params = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        sets.append(f"{k} = ?")
        params.append(json.dumps(v, ensure_ascii=False) if k == "data" else v)
    if not sets:
        return get_proposal(pid)
    sets.append("updated_at = ?")
    params += [now_iso(), pid, cid()]
    with get_db() as db:
        db.execute(f"UPDATE proposals SET {', '.join(sets)} WHERE id = ? AND company_id = ?", params)
        row = db.execute("SELECT * FROM proposals WHERE id = ? AND company_id = ?",
                         (pid, cid())).fetchone()
    return _proposal_dict(row) if row else None


def get_proposal(pid: int) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM proposals WHERE id = ? AND company_id = ?",
                         (pid, cid())).fetchone()
    return _proposal_dict(row) if row else None


def list_proposals() -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT id, ref_no, title, client, entity_type, status, created_at, updated_at "
            "FROM proposals WHERE company_id = ? ORDER BY id DESC", (cid(),)
        ).fetchall()
    return [dict(r) for r in rows]


def delete_proposal(pid: int):
    with get_db() as db:
        db.execute("DELETE FROM proposals WHERE id = ? AND company_id = ?", (pid, cid()))


def _proposal_dict(row) -> dict:
    d = dict(row)
    d["data"] = json.loads(d.get("data") or "{}")
    return d


def list_proposals_full() -> list[dict]:
    with get_db() as db:
        rows = db.execute("SELECT * FROM proposals WHERE company_id = ? ORDER BY id DESC",
                          (cid(),)).fetchall()
    return [_proposal_dict(r) for r in rows]


# ------------------------- المكتبة الفنية -------------------------

def list_library(category: str = "") -> list[dict]:
    query = "SELECT * FROM content_library WHERE company_id = ?"
    params: list = [cid()]
    if category:
        query += " AND category = ?"
        params.append(category)
    query += " ORDER BY category, title"
    with get_db() as db:
        rows = db.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def upsert_library(entry: dict) -> dict:
    ts = now_iso()
    with get_db() as db:
        if entry.get("id"):
            db.execute(
                "UPDATE content_library SET category=?, title=?, body=?, tags=?, updated_at=? "
                "WHERE id=? AND company_id=?",
                (entry["category"], entry["title"], entry["body"], entry.get("tags", ""),
                 ts, entry["id"], cid()),
            )
            row = db.execute("SELECT * FROM content_library WHERE id = ?", (entry["id"],)).fetchone()
        else:
            cur = db.execute(
                "INSERT INTO content_library (company_id, category, title, body, tags, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (cid(), entry["category"], entry["title"], entry["body"], entry.get("tags", ""), ts),
            )
            row = db.execute("SELECT * FROM content_library WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def delete_library(entry_id: int):
    with get_db() as db:
        db.execute("DELETE FROM content_library WHERE id = ? AND company_id = ?", (entry_id, cid()))


# ------------------------- خزنة وثائق الشركة -------------------------

def list_company_docs() -> list[dict]:
    """الوثائق مع حالة الصلاحية: منتهية / تنتهي قريباً (≤30 يوماً) / سارية / غير مُدخلة."""
    from datetime import date, timedelta
    with get_db() as db:
        rows = db.execute("SELECT * FROM company_docs WHERE company_id = ? ORDER BY expiry_date, name",
                          (cid(),)).fetchall()
    today = date.today()
    soon = today + timedelta(days=30)
    docs = []
    for r in rows:
        d = dict(r)
        exp = d.get("expiry_date") or ""
        if not exp:
            d["status"] = "missing"
        else:
            try:
                exp_date = date.fromisoformat(exp)
                if exp_date < today:
                    d["status"] = "expired"
                elif exp_date <= soon:
                    d["status"] = "expiring"
                else:
                    d["status"] = "valid"
                d["days_left"] = (exp_date - today).days
            except ValueError:
                d["status"] = "missing"
        docs.append(d)
    return docs


def upsert_company_doc(doc: dict) -> dict:
    ts = now_iso()
    with get_db() as db:
        if doc.get("id"):
            db.execute(
                "UPDATE company_docs SET name=?, number=?, issuer=?, issue_date=?, expiry_date=?, notes=?, updated_at=? "
                "WHERE id=? AND company_id=?",
                (doc["name"], doc.get("number", ""), doc.get("issuer", ""), doc.get("issue_date", ""),
                 doc.get("expiry_date", ""), doc.get("notes", ""), ts, doc["id"], cid()),
            )
            row = db.execute("SELECT * FROM company_docs WHERE id = ?", (doc["id"],)).fetchone()
        else:
            cur = db.execute(
                "INSERT INTO company_docs (company_id, name, number, issuer, issue_date, expiry_date, notes, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (cid(), doc["name"], doc.get("number", ""), doc.get("issuer", ""), doc.get("issue_date", ""),
                 doc.get("expiry_date", ""), doc.get("notes", ""), ts),
            )
            row = db.execute("SELECT * FROM company_docs WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def delete_company_doc(doc_id: int):
    with get_db() as db:
        db.execute("DELETE FROM company_docs WHERE id = ? AND company_id = ?", (doc_id, cid()))


# ------------------------- المستودع المعرفي -------------------------

def create_repo_file(meta: dict, extracted_text: str, items: list[dict]) -> dict:
    ts = now_iso()
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO repo_files (company_id, filename, source_type, company, notes, sector, extracted_text, items_count, uploaded_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cid(), meta["filename"], meta.get("source_type", "عرض عزوم سابق"), meta.get("company", ""),
             meta.get("notes", ""), meta.get("sector", ""), extracted_text[:200_000], len(items), ts),
        )
        fid = cur.lastrowid
        for it in items:
            db.execute(
                "INSERT INTO market_prices (company_id, repo_file_id, name, unit, unit_price, qty, source_company, source_type, sector, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (cid(), fid, it["name"], it.get("unit", ""), it["unit_price"], it.get("qty"),
                 meta.get("company", ""), meta.get("source_type", ""), meta.get("sector", ""), ts),
            )
        row = db.execute("SELECT id, filename, source_type, company, notes, sector, items_count, uploaded_at "
                         "FROM repo_files WHERE id = ?", (fid,)).fetchone()
    return dict(row)


def list_repo_files() -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT id, filename, source_type, company, notes, sector, items_count, uploaded_at "
            "FROM repo_files WHERE company_id = ? ORDER BY id DESC", (cid(),)
        ).fetchall()
    return [dict(r) for r in rows]


def get_repo_texts(limit_chars: int = 4000) -> list[dict]:
    with get_db() as db:
        rows = db.execute("SELECT id, filename, source_type, company, extracted_text "
                          "FROM repo_files WHERE company_id = ?", (cid(),)).fetchall()
    return [{**dict(r), "extracted_text": (r["extracted_text"] or "")[:limit_chars]} for r in rows]


def get_repo_file(fid: int) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM repo_files WHERE id = ? AND company_id = ?",
                         (fid, cid())).fetchone()
    return dict(row) if row else None


def delete_repo_file(fid: int):
    with get_db() as db:
        db.execute("DELETE FROM repo_files WHERE id = ? AND company_id = ?", (fid, cid()))


def search_market_prices(query: str, sector: str = "", limit: int = 60) -> list[dict]:
    sql = ("SELECT m.*, f.filename FROM market_prices m "
           "LEFT JOIN repo_files f ON f.id = m.repo_file_id "
           "WHERE m.company_id = ? AND m.name LIKE ?")
    params: list = [cid(), f"%{query}%"]
    if sector:
        sql += " AND m.sector = ?"
        params.append(sector)
    sql += " ORDER BY m.unit_price LIMIT ?"
    params.append(limit)
    with get_db() as db:
        rows = db.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def market_stats() -> dict:
    with get_db() as db:
        row = db.execute("SELECT COUNT(*) AS n FROM market_prices WHERE company_id = ?",
                         (cid(),)).fetchone()
        files = db.execute("SELECT COUNT(*) AS n FROM repo_files WHERE company_id = ?",
                           (cid(),)).fetchone()
    return {"market_items": row["n"], "repo_files": files["n"]}
