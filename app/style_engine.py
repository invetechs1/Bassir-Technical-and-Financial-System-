"""المستودع الفني ومحرك أسلوب الشركة.

الفكرة الجوهرية: العرض الفني يُبنى من فقرات الشركة الفعلية المعتمدة
(استرجاع وتكييف)، لا من توليد حر — فيخرج النص بلغة عزوم ومصطلحاتها،
ويقلّ إحساس العميل بأن النص آلي.

ثلاث طبقات:
1) المستودع الفني: tech_documents → tech_sections → tech_paragraphs
2) بصمة الكتابة style_profiles: طول الجملة، الضمير، المصطلحات، ترتيب الأقسام
3) البناء: لكل قسم قياسي، أقرب فقرات معتمدة من مشروع مشابه؛ وإلا قوالب
   النظام بعد تنقيتها من عبارات القائمة السوداء.
"""
import json
import re
from collections import Counter

from .database import get_db, _ensure_column, now_iso
from .tenancy import cid

# الأقسام القياسية وكلمات التعرف عليها في عناوين العروض الفعلية
CANONICAL_SECTIONS = {
    "company_intro": ("نبذة", "مقدمة", "التعريف بالشركة", "من نحن", "خلفية"),
    "scope": ("نطاق العمل", "نطاق المشروع", "الأعمال المطلوبة", "وصف الأعمال"),
    "methodology": ("منهجية", "المنهجية", "أسلوب التنفيذ", "طريقة التنفيذ", "آلية التنفيذ"),
    "quality": ("الجودة", "ضبط الجودة", "ضمان الجودة", "خطة الجودة"),
    "hse": ("السلامة", "الصحة والسلامة", "الأمن والسلامة", "البيئة والسلامة"),
    "staffing": ("فريق العمل", "الكوادر", "الجهاز الفني", "الموارد البشرية", "التنظيم الإداري"),
    "maintenance": ("الصيانة", "الضمان", "ما بعد التسليم", "التشغيل والصيانة"),
    "schedule": ("الجدول الزمني", "البرنامج الزمني", "مدة التنفيذ", "الخطة الزمنية"),
}

# فئات المشاريع — يُصنَّف كل مشروع وكل عرض فني مرفوع تلقائياً بإحداها،
# فتُبنى العروض الجديدة من فقرات وأسعار الفئة نفسها
PROJECT_KINDS = {
    "صيانة وتشغيل": ("صيانة", "تشغيل", "وقائية", "تصحيحية", "أعطال", "اعطال",
                     "عقد سنوي", "مرافق", "قطع الغيار", "منظومات"),
    "نظافة": ("نظافة", "تنظيف", "محارم", "مبيدات", "مكافحة الحشرات"),
    "توريد": ("توريد مواد", "توريد معدات", "توريد عمالة", "توريد أجهزة", "توريد اثاث", "توريد أثاث"),
    "تصميم وإشراف": ("تصميم", "إشراف", "اشراف", "استشاري", "مخططات", "دراسات هندسية"),
    "إنشاءات وتشطيبات": ("إنشاء", "انشاء", "بناء", "تشطيب", "ترميم", "خرسانة", "عزل",
                          "مبنى", "مباني", "لياسة", "دهانات", "أرضيات", "اسقف", "أسقف",
                          "حفر", "ردم", "هيكل", "بلاط", "سور", "مظلات"),
}
DEFAULT_PROJECT_KIND = "إنشاءات وتشطيبات"


def detect_project_kind(text: str) -> tuple[str, dict]:
    """قراءة نص المشروع وتحديد فئته بترجيح الكلمات — يعيد (الفئة، الدرجات).

    الصيانة والتشغيل تُرجَّح أولاً لأن كلماتها أدق دلالة: مشروع «صيانة مبنى»
    فئته صيانة وتشغيل وإن ذُكر المبنى."""
    text = (text or "")[:60_000]
    scores = {}
    for kind, keywords in PROJECT_KINDS.items():
        scores[kind] = sum(text.count(k) for k in keywords)
    # ترجيح الفئات الأدق دلالةً على فئة الإنشاءات العامة
    weighted = dict(scores)
    weighted["صيانة وتشغيل"] *= 3
    weighted["نظافة"] *= 3
    weighted["توريد"] *= 2
    weighted["تصميم وإشراف"] *= 2
    best = max(weighted, key=lambda k: weighted[k])
    if weighted[best] == 0:
        best = DEFAULT_PROJECT_KIND
    return best, scores


# ما يفضح النص المولَّد — تُحذف الجمل الحاوية عليها من أي مخرَج
DEFAULT_BANNED = [
    "حلول مبتكرة", "أعلى معايير الجودة", "شريك النجاح", "نفخر بأن", "تجدر الإشارة",
    "في الختام", "يسعدنا أن", "رؤية طموحة", "بما يتماشى مع", "نسعى جاهدين",
    "في عالم اليوم", "لا يخفى على أحد", "من الجدير بالذكر",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS tech_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL DEFAULT 1,
    repo_file_id INTEGER,
    filename TEXT NOT NULL,
    doc_kind TEXT NOT NULL DEFAULT 'azoom_submitted',
    project_kind TEXT DEFAULT '',
    client TEXT DEFAULT '',
    year INTEGER,
    is_style_source INTEGER NOT NULL DEFAULT 0,
    sections_count INTEGER DEFAULT 0,
    paragraphs_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_techdocs_company ON tech_documents(company_id, project_kind);

CREATE TABLE IF NOT EXISTS tech_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES tech_documents(id) ON DELETE CASCADE,
    company_id INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL,
    canonical TEXT DEFAULT '',
    ordinal INTEGER DEFAULT 0,
    word_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tech_paragraphs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    section_id INTEGER NOT NULL REFERENCES tech_sections(id) ON DELETE CASCADE,
    company_id INTEGER NOT NULL DEFAULT 1,
    body TEXT NOT NULL,
    ordinal INTEGER DEFAULT 0,
    use_count INTEGER NOT NULL DEFAULT 0,
    approved INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_paras_company_sec ON tech_paragraphs(company_id, section_id);

CREATE TABLE IF NOT EXISTS style_profiles (
    company_id INTEGER PRIMARY KEY,
    avg_sentence_len INTEGER DEFAULT 18,
    heading_style TEXT DEFAULT 'nominal_unnumbered',
    voice TEXT DEFAULT 'third_person_company',
    section_order TEXT DEFAULT '[]',
    avg_section_words INTEGER DEFAULT 120,
    avg_paras_per_sec INTEGER DEFAULT 2,
    number_style TEXT DEFAULT 'numeric',
    glossary_json TEXT DEFAULT '[]',
    banned_json TEXT DEFAULT '[]',
    sample_count INTEGER DEFAULT 0,
    updated_at TEXT DEFAULT ''
);
"""

MIN_STYLE_DOCS = 6  # الحد الأدنى لاعتماد البصمة — دونه افتراضات + تنبيه


def init_style_tables():
    with get_db() as db:
        db.executescript(SCHEMA)
        _ensure_column(db, "repo_files", "repo_kind", "TEXT NOT NULL DEFAULT 'financial'")


# ------------------------- التقسيم والاستخلاص -------------------------

_HEADING_MAX_WORDS = 8


def _canonical_for(title: str) -> str:
    title = (title or "").replace("ـ", "")  # عناوين العروض الفعلية تُزخرف بالكشيدة
    for canonical, keywords in CANONICAL_SECTIONS.items():
        if any(k in title for k in keywords):
            return canonical
    return ""


def split_into_sections(text: str) -> list[dict]:
    """تقسيم نص عرض فني إلى أقسام: سطر قصير بلا ترقيم نقطي = عنوان مرشح."""
    sections, current = [], None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        clean = re.sub(r"^[\d\.\-–•)\s:]+|[\s:]+$", "", line).replace("ـ", "")
        words = clean.split()
        is_heading = (0 < len(words) <= _HEADING_MAX_WORDS
                      and not re.search(r"[.،؛]$", line)
                      and (_canonical_for(clean) or len(clean) <= 45))
        if is_heading and _canonical_for(clean):
            current = {"title": clean, "canonical": _canonical_for(clean), "paragraphs": []}
            sections.append(current)
        elif current is not None and len(line) > 40:
            current["paragraphs"].append(line)
    return [s for s in sections if s["paragraphs"]]


def ingest_technical_document(filename: str, text: str, doc_kind: str = "azoom_submitted",
                              project_kind: str = "", client: str = "",
                              is_style_source: bool = True,
                              repo_file_id: int | None = None) -> dict:
    """تخزين عرض فني في المستودع الفني: أقسام + فقرات.

    فقرات عروض الشركة نفسها تدخل بنك الفقرات معتمدةً؛ فقرات المنافسين
    تُخزَّن للاطلاع دون اعتماد (لا تدخل في بناء العروض)."""
    init_style_tables()
    if not project_kind or project_kind in ("government", "private", "pif", "airports"):
        # القيم القطاعية القديمة أو الفراغ → صنّف من محتوى العرض نفسه
        detected, _ = detect_project_kind(text)
        project_kind = detected
    sections = split_into_sections(text)
    approved_default = 1 if doc_kind.startswith("azoom") else 0
    para_total = 0
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO tech_documents (company_id, repo_file_id, filename, doc_kind, "
            " project_kind, client, is_style_source, sections_count, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cid(), repo_file_id, filename, doc_kind, project_kind, client,
             1 if (is_style_source and approved_default) else 0, len(sections), now_iso()),
        )
        doc_id = cur.lastrowid
        for i, sec in enumerate(sections):
            wc = sum(len(p.split()) for p in sec["paragraphs"])
            scur = db.execute(
                "INSERT INTO tech_sections (document_id, company_id, title, canonical, ordinal, word_count) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (doc_id, cid(), sec["title"], sec["canonical"], i, wc),
            )
            for j, para in enumerate(sec["paragraphs"]):
                db.execute(
                    "INSERT INTO tech_paragraphs (section_id, company_id, body, ordinal, approved) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (scur.lastrowid, cid(), para[:4000], j, approved_default),
                )
                para_total += 1
        db.execute("UPDATE tech_documents SET paragraphs_count = ? WHERE id = ?",
                   (para_total, doc_id))
    return {"id": doc_id, "sections": len(sections), "paragraphs": para_total}


def migrate_repo_to_tech():
    """ملفات المستودع القديمة الموسومة «فني» تدخل المستودع الفني مرة واحدة."""
    init_style_tables()
    # ترقية فئات المستندات القديمة (كانت قيماً قطاعية) إلى فئات المشاريع
    with get_db() as db:
        stale = db.execute(
            "SELECT id FROM tech_documents WHERE project_kind IN "
            "('', 'government', 'private', 'pif', 'airports')").fetchall()
        for row in stale:
            paras = db.execute(
                "SELECT p.body FROM tech_paragraphs p JOIN tech_sections s ON s.id = p.section_id "
                "WHERE s.document_id = ? LIMIT 40", (row["id"],)).fetchall()
            kind, _ = detect_project_kind(" ".join(p["body"] for p in paras))
            db.execute("UPDATE tech_documents SET project_kind = ? WHERE id = ?",
                       (kind, row["id"]))
    with get_db() as db:
        rows = db.execute(
            "SELECT r.* FROM repo_files r "
            "LEFT JOIN tech_documents t ON t.repo_file_id = r.id "
            "WHERE t.id IS NULL AND (r.source_type LIKE '%فني%')"
        ).fetchall()
    migrated = 0
    for r in rows:
        kind = "competitor" if "منافس" in (r["source_type"] or "") else "azoom_submitted"
        from .tenancy import _company_id
        token = _company_id.set(r["company_id"])
        try:
            res = ingest_technical_document(
                r["filename"], r["extracted_text"] or "", doc_kind=kind,
                project_kind=r["sector"] or "", client=r["company"] or "",
                repo_file_id=r["id"])
            if res["paragraphs"]:
                migrated += 1
        finally:
            _company_id.reset(token)
    return migrated


# ------------------------- بصمة الكتابة -------------------------

_SENT_SPLIT = re.compile(r"[.؟!؛\n]+")
_STOP = {"على", "إلى", "الى", "من", "في", "عن", "مع", "التي", "الذي", "ذلك", "هذه",
         "هذا", "كما", "وقد", "حيث", "وذلك", "خلال", "بعد", "قبل", "عند", "حسب",
         "وفق", "وفقاً", "بموجب", "جميع", "كافة", "أي", "كل", "ثم", "أو", "لا"}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(text or "") if len(s.strip()) > 8]


def _median(values: list) -> int:
    if not values:
        return 0
    vals = sorted(values)
    return int(vals[len(vals) // 2])


def _company_paragraphs(style_source_only: bool = True) -> list[dict]:
    q = ("SELECT p.body, s.canonical, s.ordinal, d.id AS doc_id FROM tech_paragraphs p "
         "JOIN tech_sections s ON s.id = p.section_id "
         "JOIN tech_documents d ON d.id = s.document_id "
         "WHERE p.company_id = ?")
    if style_source_only:
        q += " AND d.is_style_source = 1"
    with get_db() as db:
        rows = db.execute(q, (cid(),)).fetchall()
    return [dict(r) for r in rows]


def extract_style_profile() -> dict:
    """حساب بصمة الكتابة من كل مستندات الشركة المعتمدة مصدراً للأسلوب."""
    init_style_tables()
    paras = _company_paragraphs()
    with get_db() as db:
        doc_count = db.execute(
            "SELECT COUNT(*) AS n FROM tech_documents WHERE company_id = ? AND is_style_source = 1",
            (cid(),)).fetchone()["n"]

    sentences = [s for p in paras for s in _sentences(p["body"])]
    all_text = " ".join(p["body"] for p in paras)

    # الضمير: اسم الشركة («تقوم الشركة») مقابل جمع المتكلم («نقوم»)
    first_person = len(re.findall(r"\bن\w{2,}\b", " ".join(s[:20] for s in sentences)))
    company_voice = all_text.count("الشركة") + all_text.count("شركة")
    voice = "first_person_plural" if first_person > company_voice * 2 else "third_person_company"

    # المصطلحات المتكررة المميزة
    tokens = [t for t in re.findall(r"[ء-ي]{4,}", all_text)
              if t not in _STOP and not t.startswith("ال") or len(t) > 6]
    glossary = [w for w, c in Counter(tokens).most_common(60) if c >= 3][:40]

    # ترتيب الأقسام الأكثر شيوعاً
    order_votes: dict = {}
    for p in paras:
        if p["canonical"]:
            order_votes.setdefault(p["canonical"], []).append(p["ordinal"])
    section_order = sorted(order_votes, key=lambda c: _median(order_votes[c]))
    if not section_order:
        section_order = list(CANONICAL_SECTIONS)

    sec_words: dict = {}
    for p in paras:
        key = (p["doc_id"], p["canonical"])
        sec_words[key] = sec_words.get(key, 0) + len(p["body"].split())

    profile = {
        "company_id": cid(),
        "avg_sentence_len": _median([len(s.split()) for s in sentences]) or 18,
        "heading_style": "nominal_unnumbered",
        "voice": voice,
        "section_order": json.dumps(section_order, ensure_ascii=False),
        "avg_section_words": _median(list(sec_words.values())) or 120,
        "avg_paras_per_sec": 2,
        "number_style": "numeric",
        "glossary_json": json.dumps(glossary, ensure_ascii=False),
        "banned_json": json.dumps(DEFAULT_BANNED, ensure_ascii=False),
        "sample_count": len(paras),
        "updated_at": now_iso(),
    }
    with get_db() as db:
        db.execute("INSERT OR REPLACE INTO style_profiles "
                   f"({', '.join(profile)}) VALUES ({', '.join('?' * len(profile))})",
                   list(profile.values()))
    profile["docs"] = doc_count
    profile["reliable"] = doc_count >= MIN_STYLE_DOCS
    return profile


def get_style_profile() -> dict:
    init_style_tables()
    with get_db() as db:
        row = db.execute("SELECT * FROM style_profiles WHERE company_id = ?", (cid(),)).fetchone()
        doc_count = db.execute(
            "SELECT COUNT(*) AS n FROM tech_documents WHERE company_id = ? AND is_style_source = 1",
            (cid(),)).fetchone()["n"]
    if not row:
        return {"company_id": cid(), "sample_count": 0, "docs": doc_count, "reliable": False,
                "avg_sentence_len": 18, "voice": "third_person_company",
                "section_order": "[]", "glossary_json": "[]",
                "banned_json": json.dumps(DEFAULT_BANNED, ensure_ascii=False)}
    d = dict(row)
    d["docs"] = doc_count
    d["reliable"] = doc_count >= MIN_STYLE_DOCS
    return d


# ------------------------- التنقية من عبارات القوالب -------------------------

def scrub_banned(text: str, banned: list[str] | None = None) -> tuple[str, list[str]]:
    """حذف الجمل الحاوية على عبارات القائمة السوداء — تعديل جراحي لا إعادة كتابة."""
    banned = banned or DEFAULT_BANNED
    hits = [b for b in banned if b in text]
    if not hits:
        return text, []
    kept = []
    for sentence in re.split(r"(?<=[.؟!؛])\s+", text):
        if not any(b in sentence for b in banned):
            kept.append(sentence)
    return " ".join(kept).strip(), hits


# ------------------------- بناء الأقسام من بنك الفقرات -------------------------

def _tokens_of(text: str) -> set:
    from .similarity import _tokens
    return _tokens(text)


def build_from_bank(brief_text: str, project_kind: str = "") -> dict:
    """لكل قسم قياسي: أقرب فقرات معتمدة من مشروع مشابه.

    يعيد {canonical: {body, source, ref, score}} — الأقسام بلا مرشح مناسب
    لا تظهر هنا ويكمّلها محرك القوالب."""
    init_style_tables()
    brief_tokens = _tokens_of(f"{brief_text} {project_kind}")
    with get_db() as db:
        rows = db.execute(
            "SELECT p.id, p.body, p.use_count, s.canonical, d.project_kind, d.doc_kind, "
            "       d.filename, d.client "
            "FROM tech_paragraphs p "
            "JOIN tech_sections s ON s.id = p.section_id "
            "JOIN tech_documents d ON d.id = s.document_id "
            "WHERE p.company_id = ? AND p.approved = 1 AND s.canonical != ''",
            (cid(),)).fetchall()

    by_canonical: dict = {}
    for r in rows:
        overlap = len(brief_tokens & _tokens_of(r["body"])) if brief_tokens else 0
        score = overlap
        if project_kind and r["project_kind"] == project_kind:
            score += 6            # نفس نوع المشروع أولاً
        if r["doc_kind"] == "azoom_won":
            score += 3            # ثم العروض الفائزة
        by_canonical.setdefault(r["canonical"], []).append((score, dict(r)))

    out = {}
    used_ids = []
    for canonical, candidates in by_canonical.items():
        candidates.sort(key=lambda t: -t[0])
        if not candidates or candidates[0][0] < 2:
            continue  # لا فقرة مناسبة — يكمّل محرك القوالب هذا القسم
        top = [c for s, c in candidates[:3] if s >= 2]
        body = "\n".join(dict.fromkeys(p["body"] for p in top))
        body, _ = scrub_banned(body)
        out[canonical] = {
            "body": body,
            "source": "bank",
            "ref": top[0]["filename"][:60],
            "score": candidates[0][0],
        }
        used_ids += [p["id"] for p in top]
    if used_ids:
        with get_db() as db:
            db.executemany("UPDATE tech_paragraphs SET use_count = use_count + 1 WHERE id = ?",
                           [(i,) for i in used_ids])
    return out


def style_report(sections: list[dict], profile: dict) -> dict:
    """درجة مطابقة الأسلوب للعرض المبني — bank_ratio أعلى وزن."""
    total = len(sections) or 1
    bank = sum(1 for s in sections if s.get("source") == "bank")
    text = " ".join(s.get("body", "") for s in sections)
    banned = json.loads(profile.get("banned_json") or "[]") or DEFAULT_BANNED
    banned_hits = [b for b in banned if b in text]
    sent_lens = [len(s.split()) for s in _sentences(text)]
    target = profile.get("avg_sentence_len") or 18
    med = _median(sent_lens) or target
    closeness = max(0.0, 1 - abs(med - target) / max(target, 1))
    checks = {
        "bank_ratio": bank / total,
        "banned": 0.0 if banned_hits else 1.0,
        "sentence_len": closeness,
    }
    score = round(100 * (checks["bank_ratio"] * 0.55 + checks["banned"] * 0.2
                         + checks["sentence_len"] * 0.25))
    return {"score": score, "bank_sections": bank, "total_sections": total,
            "bank_ratio": round(checks["bank_ratio"], 2), "banned_hits": banned_hits}


# ------------------------- بنك الفقرات (للواجهة) -------------------------

def list_tech_documents() -> list[dict]:
    init_style_tables()
    with get_db() as db:
        rows = db.execute(
            "SELECT id, filename, doc_kind, project_kind, client, is_style_source, "
            "sections_count, paragraphs_count, created_at "
            "FROM tech_documents WHERE company_id = ? ORDER BY id DESC", (cid(),)).fetchall()
    return [dict(r) for r in rows]


def list_paragraph_bank(canonical: str = "") -> list[dict]:
    init_style_tables()
    q = ("SELECT p.id, p.body, p.use_count, p.approved, s.canonical, s.title, d.filename "
         "FROM tech_paragraphs p JOIN tech_sections s ON s.id = p.section_id "
         "JOIN tech_documents d ON d.id = s.document_id WHERE p.company_id = ?")
    params: list = [cid()]
    if canonical:
        q += " AND s.canonical = ?"
        params.append(canonical)
    q += " ORDER BY p.use_count DESC, p.id DESC LIMIT 200"
    with get_db() as db:
        rows = db.execute(q, params).fetchall()
    return [dict(r) for r in rows]


def set_paragraph_approved(pid: int, approved: bool):
    with get_db() as db:
        db.execute("UPDATE tech_paragraphs SET approved = ? WHERE id = ? AND company_id = ?",
                   (1 if approved else 0, pid, cid()))
