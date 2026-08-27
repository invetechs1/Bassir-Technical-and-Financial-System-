# تعدد الشركات (SaaS) — الباك اند

الهدف: تشغيل النظام لأكثر من شركة على نفس النشر، بعزل كامل للبيانات، **دون تغيير أي وظيفة قائمة**. كل شركة مستأجر (tenant) له أسعاره وعروضه ومكتبته الفنية ومستودعه ووثائقه ومستخدموه وإعداداته.

---

## ١. مخطط قاعدة البيانات

### جداول جديدة

```sql
CREATE TABLE companies (
  id                  INTEGER PRIMARY KEY,
  name                TEXT NOT NULL,
  short_name          TEXT,
  logo_url            TEXT,
  cr_no               TEXT,
  vat_no              TEXT,
  currency            TEXT NOT NULL DEFAULT 'SAR',
  sector              TEXT,
  plan                TEXT NOT NULL DEFAULT 'trial',   -- trial | basic | pro | enterprise
  subscription_status TEXT NOT NULL DEFAULT 'active',  -- active | past_due | suspended
  trial_ends_at       TEXT,
  created_at          TEXT NOT NULL
);

CREATE TABLE memberships (
  user_id    INTEGER NOT NULL REFERENCES users(id),
  company_id INTEGER NOT NULL REFERENCES companies(id),
  role       TEXT NOT NULL,          -- owner | admin | editor | viewer
  invited_by INTEGER REFERENCES users(id),
  joined_at  TEXT NOT NULL,
  PRIMARY KEY (user_id, company_id)
);

CREATE TABLE subscriptions (
  id           INTEGER PRIMARY KEY,
  company_id   INTEGER NOT NULL REFERENCES companies(id),
  plan         TEXT NOT NULL,
  seats        INTEGER NOT NULL,
  price        REAL,
  period_start TEXT, period_end TEXT,
  status       TEXT NOT NULL,
  invoice_ref  TEXT
);

CREATE TABLE audit_events (
  id          INTEGER PRIMARY KEY,
  company_id  INTEGER NOT NULL REFERENCES companies(id),
  actor_id    INTEGER REFERENCES users(id),
  entity      TEXT NOT NULL,       -- prices | proposals | library_texts | …
  entity_id   TEXT,
  action      TEXT NOT NULL,       -- create | update | delete | publish
  before_json TEXT, after_json TEXT,
  at          TEXT NOT NULL
);
CREATE INDEX idx_audit_company_at ON audit_events(company_id, at DESC);
```

### جداول معدَّلة

`users` — المستخدم عام على مستوى المنصة، وارتباطه بالشركات من `memberships`:

```sql
ALTER TABLE users ADD COLUMN is_platform_admin INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN last_login_at TEXT;
```

كل جدول بيانات يأخذ `company_id` مع فهرس مركّب:

```sql
ALTER TABLE prices               ADD COLUMN company_id INTEGER NOT NULL DEFAULT 1;
ALTER TABLE proposals            ADD COLUMN company_id INTEGER NOT NULL DEFAULT 1;
ALTER TABLE library_texts        ADD COLUMN company_id INTEGER NOT NULL DEFAULT 1;
ALTER TABLE company_docs         ADD COLUMN company_id INTEGER NOT NULL DEFAULT 1;
ALTER TABLE repository_files     ADD COLUMN company_id INTEGER NOT NULL DEFAULT 1;
ALTER TABLE reference_proposals  ADD COLUMN company_id INTEGER NOT NULL DEFAULT 1;
ALTER TABLE etimad_tenders       ADD COLUMN company_id INTEGER NOT NULL DEFAULT 1;
ALTER TABLE forsah_projects      ADD COLUMN company_id INTEGER NOT NULL DEFAULT 1;

CREATE INDEX idx_prices_company    ON prices(company_id);
CREATE INDEX idx_proposals_company ON proposals(company_id, created_at DESC);
-- … لكل جدول
```

**كود بند السعر صار فريداً داخل الشركة لا على مستوى النظام:**

```sql
DROP INDEX IF EXISTS idx_prices_code;              -- كان UNIQUE(code)
CREATE UNIQUE INDEX idx_prices_company_code ON prices(company_id, code);
```

**`settings` يصبح مفتاحاً مركّباً** — نموذج التسعير وبيانات الشركة لكل شركة على حدة:

```sql
CREATE TABLE settings_new (
  company_id INTEGER NOT NULL REFERENCES companies(id),
  key        TEXT NOT NULL,
  value      TEXT,
  PRIMARY KEY (company_id, key)
);
INSERT INTO settings_new SELECT 1, key, value FROM settings;
DROP TABLE settings;
ALTER TABLE settings_new RENAME TO settings;
```

### الترحيل

بيانات عزوم الحالية تصير الشركة رقم 1، فلا شيء يُفقد:

```sql
INSERT INTO companies (id, name, short_name, currency, sector, plan, subscription_status, created_at)
VALUES (1, 'شركة عزوم المتحدة', 'عزوم', 'SAR', 'المقاولات العامة', 'enterprise', 'active', datetime('now'));

INSERT INTO memberships (user_id, company_id, role, joined_at)
SELECT id, 1, 'owner', datetime('now') FROM users;
```

`DEFAULT 1` في كل `ALTER TABLE` أعلاه يجعل الصفوف القائمة تنتسب لعزوم تلقائياً.

---

## ٢. طبقة العزل — أهم جزء

**لا تكتب `WHERE company_id = ?` يدوياً في كل استعلام.** أول استعلام يُنسى فيه الشرط يسرّب بيانات شركة لأخرى. مرّر كل شيء عبر نقطة واحدة في `app/database.py`.

### الشركة الحالية في سياق الطلب

```python
# app/tenancy.py  (جديد)
from flask import g, session, abort
from app.database import query_one

def load_current_company():
    """يُستدعى في before_request — يحدد الشركة ويتحقق من العضوية."""
    uid = session.get('user_id')
    if not uid:
        g.company_id, g.role = None, None
        return
    cid = session.get('company_id')
    if cid is None:
        row = query_one(
            "SELECT company_id, role FROM memberships WHERE user_id = ? ORDER BY joined_at LIMIT 1",
            (uid,), tenant_scoped=False)
        if not row:
            abort(403)
        cid, session['company_id'] = row['company_id'], row['company_id']
    m = query_one(
        "SELECT role FROM memberships WHERE user_id = ? AND company_id = ?",
        (uid, cid), tenant_scoped=False)
    if not m:
        session.pop('company_id', None)
        abort(403)
    g.company_id, g.role = cid, m['role']
```

في `app/main.py`:

```python
from app.tenancy import load_current_company

@app.before_request
def _tenancy():
    load_current_company()
```

**الشركة تُقرأ من الجلسة فقط.** لا تقبلها أبداً من الواجهة (query string أو body) — وإلا صار تبديل الشركة بتعديل الطلب.

### حقن الشرط تلقائياً

في `app/database.py` غلّف دوال الاستعلام:

```python
import re
from flask import g

TENANT_TABLES = {
    'prices', 'proposals', 'library_texts', 'company_docs',
    'repository_files', 'reference_proposals', 'etimad_tenders',
    'forsah_projects', 'settings', 'audit_events', 'subscriptions',
}

def _scope(sql, params):
    """يضيف company_id للاستعلام إن كان يمس جدولاً مستأجَراً."""
    tables = set(re.findall(r'\b(?:FROM|JOIN|INTO|UPDATE)\s+([a-z_]+)', sql, re.I))
    if not (tables & TENANT_TABLES):
        return sql, params
    cid = getattr(g, 'company_id', None)
    if cid is None:
        raise RuntimeError('استعلام على جدول مستأجَر بلا شركة في السياق')
    if re.match(r'\s*SELECT|\s*DELETE|\s*UPDATE', sql, re.I):
        sql = re.sub(r'\bWHERE\b', f'WHERE company_id = {int(cid)} AND', sql, count=1, flags=re.I) \
              if re.search(r'\bWHERE\b', sql, re.I) else _append_where(sql, cid)
    return sql, params

def query_all(sql, params=(), tenant_scoped=True):
    if tenant_scoped:
        sql, params = _scope(sql, params)
    ...
```

`_scope` بالتعبير النمطي حلٌّ عملي لقاعدة SQL مكتوبة يدوياً، لكنه هشّ مع الاستعلامات المركّبة. البديل الأمتن — وهو المفضّل إن توفر وقت — تغليف كل جدول في دالة وصول (`prices_all()`, `price_upsert()`, `proposals_page()`) تبني `WHERE` بنفسها، فلا يمر أي SQL خام من طبقة الويب. أياً كان الاختيار: **مسار واحد فقط للقراءة والكتابة.**

للإدراج، ضع `company_id` في القاموس قبل البناء:

```python
def insert(table, data):
    if table in TENANT_TABLES:
        data = {**data, 'company_id': g.company_id}
    ...
```

### الملفات

`app/repository.py` و `app/file_extract.py` يخزنان الرفعات. افصل المسار لكل شركة:

```python
UPLOAD_ROOT / str(g.company_id) / <filename>
```

وعند التنزيل تحقق من الملكية في قاعدة البيانات لا من المسار وحده — `../` في اسم الملف يتجاوز أي عزل مبني على المسار.

### محرك التشابه والذكاء الاصطناعي

`app/similarity.py` و `app/ai_engine.py` و `app/proposal_builder.py` تقرأ العروض المرجعية. بعد التعديل تقرأ عروض الشركة الحالية فقط. أضف علماً اختيارياً `is_shared` على `reference_proposals` لمكتبة قياسية عامة تُقرأ للجميع:

```sql
ALTER TABLE reference_proposals ADD COLUMN is_shared INTEGER NOT NULL DEFAULT 0;
```

والاستعلام: `WHERE (company_id = :cid OR is_shared = 1)`.

### بيانات دخول المنصات

`app/forsah.py` يحفظ بريد وكلمة مرور فرصة، و `app/config.py` يحفظ رقم هوية نفاذ. كلاهما صار لكل شركة، ويُخزَّن **مشفَّراً** (`cryptography.fernet`) بمفتاح من متغير بيئة، لا نصاً صريحاً.

### التصدير

`app/export_docx.py` و `app/export_xlsx.py` يستخدمان اسم الشركة وشعارها وسجلها التجاري من `settings`. بعد التعديل تُقرأ من إعدادات الشركة الحالية، فيخرج كل عرض بهوية صاحبه.

---

## ٣. نقاط النهاية

| الطريقة | المسار | الوصف |
| --- | --- | --- |
| `POST` | `/api/companies` | إنشاء شركة + مالك حسابها. لمدير المنصة فقط. |
| `GET` | `/api/me/companies` | الشركات التي للمستخدم عضوية فيها — تغذي قائمة التبديل. |
| `POST` | `/api/session/company/<id>` | تبديل الشركة الحالية بعد التحقق من العضوية. |
| `GET` | `/api/companies/<id>/members` | مستخدمو الشركة وأدوارهم. |
| `POST` | `/api/memberships` | دعوة مستخدم بدور محدد. |
| `PATCH` | `/api/memberships/<uid>/<cid>` | تغيير دور. |
| `POST` | `/api/companies/<id>/import` | استيراد قاعدة أسعار الشركة وعروضها السابقة إلى مستودعها. |
| `GET` | `/api/companies/<id>/usage` | استهلاك الخطة: مستخدمون، عروض الشهر، بنود الأسعار. |
| `PATCH` | `/api/subscriptions/<id>` | ترقية أو تجميد الاشتراك. |

مثال التبديل:

```python
@app.post('/api/session/company/<int:cid>')
@login_required
def switch_company(cid):
    m = query_one("SELECT role FROM memberships WHERE user_id = ? AND company_id = ?",
                  (session['user_id'], cid), tenant_scoped=False)
    if not m:
        return {'error': 'لا تملك صلاحية على هذه الشركة'}, 403
    session['company_id'] = cid
    return {'ok': True, 'role': m['role']}
```

---

## ٤. حدود الخطة

تُفحص في طبقة الخدمة قبل الفعل، لا في الواجهة:

| الخطة | مستخدمون | عروض شهرياً | بنود أسعار | ربط اعتماد وفرصة |
| --- | --- | --- | --- | --- |
| تجريبي | 2 | 5 | 100 | لا |
| أساسي | 3 | 20 | 500 | لا |
| احترافي | 10 | غير محدود | غير محدود | نعم |
| مؤسسي | غير محدود | غير محدود | غير محدود | نعم |

```python
def enforce_limit(kind):
    limits = PLAN_LIMITS[current_company()['plan']]
    if limits[kind] is not None and current_usage(kind) >= limits[kind]:
        abort(402, 'تم بلوغ حد الخطة — رقِّ الاشتراك للمتابعة')
```

استدعِها قبل `generate_proposal()` وقبل `POST /api/memberships` وقبل حفظ بند سعر جديد.

---

## ٥. اختبارات لا تُهمَل

1. مستخدم في الشركة A لا يرى أي صف من الشركة B عبر كل نقطة نهاية (اكتبها كاختبار يمر على كل مسار).
2. تبديل `company_id` في الجلسة يدوياً إلى شركة بلا عضوية ← 403.
3. كود بند سعر مكرر عبر شركتين ← مسموح؛ مكرر داخل الشركة ← مرفوض.
4. تنزيل ملف مستودع بمعرّف من شركة أخرى ← 403.
5. تصدير Word يحمل شعار الشركة الحالية وسجلها التجاري.
6. بعد الترحيل: كل بيانات عزوم القائمة موجودة تحت `company_id = 1` وعددها مطابق لما قبل الترحيل.
