"""فحص شامل لنظام بصير/عزوم — يختبر كل نقطة نهاية وكل وظيفة وكل إصلاح أمني.

التشغيل (محلياً أو على الخادم بعد أي نشر):
    python scripts/system_check.py
يعمل افتراضياً على **قاعدة بيانات مؤقتة معزولة** (AZOOM_DATA_DIR) تُحذف عند
الانتهاء — لا يلمس بيانات الإنتاج ولا يترك مستخدمين أو شركات اختبار فيها، ولا
يستبدل أسرار الإشعارات الحقيقية. للتشغيل على القاعدة الحالية عمداً:
    python scripts/system_check.py --current-db
(يتطلب عندها أن تكون كلمة مرور azoom هي Azoom@2026.)
"""
import atexit
import io
import os
import shutil
import sys
import tempfile
from pathlib import Path

if "--current-db" not in sys.argv:
    _SCRATCH = tempfile.mkdtemp(prefix="azoom-check-")
    os.environ["AZOOM_DATA_DIR"] = _SCRATCH
    atexit.register(lambda: shutil.rmtree(_SCRATCH, ignore_errors=True))
# كلمة مرور المدير في القاعدة المؤقتة (لا كلمة افتراضية ثابتة في الكود)
os.environ.setdefault("AZOOM_ADMIN_PASSWORD", "Azoom@2026")
# لا خيوط خلفية (تحديث الموديل/الفوترة) أثناء الفحص، وسقوف التحديد مرتفعة
# (الفحص يسجّل ويسجّل شركات عشرات المرات) — تُختبر المحدِّدات مباشرة لاحقاً
os.environ["AZOOM_DISABLE_BACKGROUND"] = "1"
os.environ.setdefault("SIGNUP_MAX_PER_IP_HOUR", "1000")
os.environ.setdefault("SIGNUP_MAX_PER_HOUR", "1000")
os.environ.setdefault("GENERATE_MAX_PER_HOUR", "1000")
os.environ.setdefault("LOGIN_MAX_FAILS_USER", "1000")
os.environ.setdefault("LOGIN_MAX_FAILS_IP", "1000")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

RESULTS = []
def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    mark = "✅" if cond else "❌"
    print(f"{mark} {name}" + (f"  — {detail}" if detail and not cond else ""))

# ---------- 1. تشغيل أول مرة: التهيئة والبذور ----------
from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db
from app.auth import init_auth
from app.seed import seed_if_empty

init_db(); init_auth(); seed_if_empty()
# تهيئة جداول الوحدات كلها — فاحص النظام يعمل على قاعدة جديدة تماماً أيضاً
from app.style_engine import init_style_tables, migrate_repo_to_tech
from app.execution import init_execution_tables
from app.agents import init_agent_tables
init_style_tables(); migrate_repo_to_tech(); init_execution_tables(); init_agent_tables()
c = TestClient(app)

# ---------- 2. المصادقة ----------
r = c.get("/api/status")
check("حماية API قبل الدخول (401)", r.status_code == 401)
r = c.get("/", follow_redirects=False)
check("تحويل الصفحة الرئيسية لتسجيل الدخول", r.status_code in (302, 307) and "/login" in r.headers.get("location", ""))
r = c.get("/login")
check("صفحة الدخول تعمل وبالهوية الخضراء", r.status_code == 200 and "AZOOM United Co." in r.text and "#175934" in r.text)
r = c.post("/api/login", json={"username": "azoom", "password": "wrong"})
check("رفض كلمة مرور خاطئة", r.status_code == 401)
r = c.post("/api/login", json={"username": "azoom", "password": "Azoom@2026"})
check("تسجيل الدخول", r.status_code == 200 and r.json()["user"]["username"] == "azoom")
r = c.get("/api/me")
check("/api/me", r.status_code == 200 and r.json()["username"] == "azoom")
r = c.post("/api/password", json={"old": "Azoom@2026", "new": "Test@12345"})
check("تغيير كلمة المرور", r.status_code == 200)
r = c.post("/api/login", json={"username": "azoom", "password": "Test@12345"})
check("الدخول بالكلمة الجديدة", r.status_code == 200)
r = c.post("/api/password", json={"old": "Test@12345", "new": "Azoom@2026"})
check("إرجاع كلمة المرور الأصلية", r.status_code == 200)
r = c.post("/api/password", json={"old": "Azoom@2026", "new": "short"})
check("رفض كلمة مرور قصيرة", r.status_code != 200)

# ---------- 3. الحالة والبذور ----------
r = c.get("/api/status"); st = r.json()
check("/api/status", r.status_code == 200 and st.get("ok"))
check(f"بذور الأسعار ({st.get('price_items')} بنداً)", st.get("price_items", 0) >= 600, str(st))
r = c.get("/api/proposals"); props = r.json()
refs = [p for p in props if p.get("is_reference") or "مرجعي" in str(p)]
check(f"العروض المرجعية المبذورة ({len(props)} عرضاً بالأرشيف)", len(props) >= 7)
r = c.get("/")
check("الواجهة الرئيسية بالهوية الجديدة (الشعار الرسمي + المجموعات)",
      "AZOOM" in r.text and "azoom-mark.png" in r.text and "nav-group" in r.text)
r = c.get("/static/app.js")
check("ملف app.js يُقدَّم", r.status_code == 200 and "makeReference" in r.text)
r = c.get("/static/styles.css")
check("ملف styles.css أخضر", r.status_code == 200 and "#175934" in r.text)

# ---------- 4. الإعدادات ----------
r = c.get("/api/settings"); s0 = r.json()
check("قراءة الإعدادات (بيانات عزوم الرسمية)",
      s0.get("company_cr") == "1010467099" and s0.get("company_vat_no") == "311917527400003"
      and s0.get("company_iban", "").startswith("SA49"))
r = c.put("/api/settings", json={"profit_pct": "18"})
r2 = c.get("/api/settings")
check("تعديل الإعدادات", r.status_code == 200 and r2.json()["profit_pct"] == "18")
c.put("/api/settings", json={"profit_pct": "15"})

# ---------- 5. قاعدة الأسعار ----------
r = c.get("/api/prices")
all_prices = r.json()
check(f"قائمة الأسعار ({len(all_prices)})", len(all_prices) >= 600)
r = c.get("/api/prices", params={"search": "دهان"})
check("البحث في الأسعار", r.status_code == 200 and len(r.json()) > 0)
r = c.post("/api/prices", json={"code": "TST-001", "category": "اختبار", "name": "بند اختبار الفحص", "unit": "م2", "unit_price": 100})
check("إضافة بند سعر", r.status_code == 200)
tid = r.json()["id"]
r = c.post("/api/prices", json={"id": tid, "code": "TST-001", "category": "اختبار", "name": "بند اختبار الفحص", "unit": "م2", "unit_price": 120})
r = c.get(f"/api/prices/{tid}/history")
check("تاريخ تغير السعر يُسجل", r.status_code == 200 and len(r.json()) >= 1)
r = c.get("/api/prices/export/csv")
check("تصدير CSV", r.status_code == 200 and "TST-001" in r.text)
csv_data = "code,category,name,unit,unit_price\nTST-002,اختبار,بند مستورد من CSV,عدد,55\n"
r = c.post("/api/prices/import/csv", files={"file": ("prices.csv", csv_data.encode("utf-8-sig"), "text/csv")})
check("استيراد CSV", r.status_code == 200)
r = c.get("/api/prices", params={"search": "TST-002"})
imported = r.json()
check("البند المستورد موجود", len(imported) == 1 and imported[0]["unit_price"] == 55)
r = c.delete(f"/api/prices/{tid}")
check("حذف بند سعر", r.status_code == 200)

# ---------- 6. المكتبة الفنية ----------
r = c.get("/api/library")
check(f"المكتبة الفنية ({len(r.json())} محتوى)", len(r.json()) >= 5)
track = [e for e in r.json() if "جازان" in e.get("body", "")]
check("سجل الخبرات الحقيقي (جازان 89 مليون...)", len(track) >= 1)
r = c.post("/api/library", json={"category": "اختبار", "title": "محتوى اختبار", "body": "نص", "tags": ""})
lid = r.json()["id"]
r = c.delete(f"/api/library/{lid}")
check("إضافة/حذف محتوى مكتبة", r.status_code == 200)

# ---------- 7. وثائق الشركة ----------
r = c.get("/api/docs"); docs = r.json()
check(f"وثائق الشركة ({len(docs)})", len(docs) >= 9)
check("حساب حالة الصلاحية", all("status" in d for d in docs))
official = [d for d in docs if d.get("number")]
check(f"الوثائق بأرقامها الرسمية ({len(official)})", len(official) >= 4)

# ---------- 8. توليد عرض متكامل (محرك القوالب + التشابه + المستودع) ----------
from openpyxl import Workbook
wb = Workbook(); ws = wb.active
ws.append(["م", "وصف الأعمال", "الوحدة", "الكمية", "سعر الوحدة", "الإجمالي"])
ws.append([1, "توريد وتركيب عزل مائي للأسطح", "م2", 500, 40, 20000])
ws.append([2, "أعمال دهانات خارجية عازلة للحرارة", "م2", 1000, 25, 25000])
buf = io.BytesIO(); wb.save(buf)

r = c.post("/api/proposals/generate",
           data={"title": "مشروع عزل وترميم مبانٍ حكومية بمنطقة حائل", "client": "أمانة منطقة حائل", "entity_type": "government"},
           files=[("files", ("boq.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))])
check("توليد عرض جديد", r.status_code == 200, r.text[:200])
prop = r.json(); pid = prop["id"]; data = prop["data"]
check("أقسام فنية (11 قسماً)", len(data.get("technical_sections", [])) >= 10)
check("جدول كميات غير فارغ", len(data.get("boq", [])) > 0)
check("خطة تنفيذية بمراحل", len(data.get("plan", [])) >= 3)
check("مصفوفة الالتزام", len(data.get("compliance_matrix", [])) >= 3)
check("التشابه وجد عروضاً مرجعية (عزل حائل/المطارات)", len(data.get("similar_refs", [])) >= 1,
      str(data.get("similar_refs")))

fin = data.get("financial", {})
direct = round(sum(l["total"] for l in data["boq"]), 2)
ok_math = (abs(fin["direct_cost"] - direct) < 1
           and abs(fin["overhead"] - direct * 0.12) < 1
           and abs(fin["risk"] - direct * 0.03) < 1
           and abs(fin["subtotal"] - (direct + fin["overhead"] + fin["risk"] + fin["profit"])) < 1
           and abs(fin["vat"] - fin["subtotal"] * 0.15) < 1
           and abs(fin["grand_total"] - (fin["subtotal"] + fin["vat"])) < 1)
check("صحة الحسابات المالية (إداري 12% + مخاطر 3% + ربح + ضريبة 15%)", ok_math, str(fin))

r = c.get("/api/proposals/similar", params={"q": "مشروع عزل أسطح ومعالجة تسربات لمطارات"})
check("نقطة نهاية التشابه", r.status_code == 200 and len(r.json()) >= 1)

r = c.get(f"/api/proposals/{pid}")
check("قراءة عرض واحد", r.status_code == 200)
r = c.put(f"/api/proposals/{pid}", json={"status": "won"})
check("تحديث حالة العرض (فائز)", r.status_code == 200)

# ---------- 9. التصدير Word + Excel ----------
_titles = [sec["title"] for sec in data.get("technical_sections", [])]
check("بنية العرض الحقيقية (خطاب التقديم أولاً + معلومات الشركة + من نحن)",
      _titles[:1] == ["خطاب التقديم"] and "معلومات الشركة" in _titles and "من نحن" in _titles,
      str(_titles[:5]))
_bodies_all = " ".join(sec["body"] for sec in data.get("technical_sections", []))
check("لا ملاحظات تحريرية في نصوص العميل", "حرّر هذا القسم" not in _bodies_all)
r = c.get(f"/api/proposals/{pid}/export/docx")
check("تصدير Word", r.status_code == 200 and len(r.content) > 10000)
from docx import Document
d = Document(io.BytesIO(r.content))
footer_ok = any("+966114880122" in p.text and "1010467099" in p.text
                for s in d.sections for p in s.footer.paragraphs)
check("تذييل Word الرسمي في كل صفحة", footer_ok)
_doc_text = "\n".join(p2.text for p2 in d.paragraphs)
for _t2 in d.tables:
    for _row in _t2.rows:
        _doc_text += "\n" + " ".join(cell.text for cell in _row.cells)
check("Word للعميل: لا هامش ربح ولا مخاطر ولا مصاريف إدارية",
      all(x not in _doc_text for x in ("هامش الربح", "احتياطي المخاطر", "المصاريف الإدارية", "التكلفة المباشرة")))
from app.proposal_builder import client_facing_pricing as _cfp
_loaded = _cfp(data["boq"], fin)
check("الأسعار المحمَّلة: مجموع البنود = الإجمالي قبل الضريبة",
      abs(round(sum(l["total"] for l in _loaded), 2) - fin["subtotal"]) < 0.01)
r = c.get(f"/api/proposals/{pid}/export/xlsx")
check("تصدير Excel", r.status_code == 200 and len(r.content) > 3000)
from openpyxl import load_workbook
wb2 = load_workbook(io.BytesIO(r.content))
check("ملف Excel سليم", len(wb2.sheetnames) >= 1)
_xl_text = " ".join(str(c2.value) for _r2 in wb2.active.iter_rows() for c2 in _r2 if c2.value)
check("Excel للعميل: لا نسب داخلية",
      all(x not in _xl_text for x in ("هامش الربح", "احتياطي المخاطر", "المصاريف الإدارية")))

# ---------- 10. المستودع المعرفي ----------
boq_txt = """عرض مالي — مشروع إنشاء حدائق وممرات مشاة
أعمال زراعة أشجار وشجيرات محلية
عدد 300 150.00 45,000.00
توريد وتركيب مظلات خشبية للجلسات
عدد 20 3,500.00 70,000.00
""".encode()
r = c.post("/api/repo/upload",
           data={"source_type": "عرض فني سابق", "company": "شركة الفحص", "notes": "فحص عميق", "as_reference": "1"},
           files=[("files", ("عرض حدائق وممرات.txt", boq_txt, "text/plain"))])
rec = r.json()[0]
check("رفع للمستودع + استخراج بندين", r.status_code == 200 and rec["items_count"] == 2, str(rec))
check("إنشاء عرض مرجعي تلقائي من الملف", bool(rec.get("reference")) or "مسبقاً" in str(rec.get("reference_note", "")), str(rec))
rfid = rec["id"]
r = c.post(f"/api/repo/{rfid}/make-reference")
check("منع تكرار المرجعي (409)", r.status_code == 409)
r = c.get("/api/repo")
check("قائمة المستودع + الإحصاءات", r.status_code == 200 and r.json()["stats"]["market_items"] >= 2)
r = c.get("/api/market/search", params={"q": "مظلات"})
mk = r.json()
check("مقارنة أسعار السوق", r.status_code == 200 and mk["benchmark"]["count"] >= 1 and mk["benchmark"]["avg"] == 3500)
r = c.delete(f"/api/repo/{rfid}")
check("حذف ملف من المستودع", r.status_code == 200)

# ملف مصور بلا نص — تشخيص واضح لا انهيار
r = c.post("/api/repo/upload", data={"source_type": "عرض شركة منافسة", "company": "", "notes": "", "as_reference": ""},
           files=[("files", ("scan.pdf", b"%PDF-1.4 fake", "application/pdf"))])
check("ملف مصور: تشخيص واضح بلا خطأ", r.status_code == 200 and r.json()[0].get("note"))

# ---------- 11. محلل الفرص ----------
risk_text = ("اشتراطات التأهيل: تصنيف مقاولين درجة ثانية في المباني، خبرة لا تقل عن 10 سنوات، "
             "ضمان نهائي 10% وغرامات تأخير 20%، نسبة محتوى محلي 40%").encode()
r = c.post("/api/opportunity", data={"title": "منافسة صيانة وتشغيل مباني بلدية", "client": "بلدية"},
           files=[("files", ("terms.txt", risk_text, "text/plain"))])
opp = r.json()
check("محلل الفرص: درجة ونتيجة", r.status_code == 200 and 0 <= opp.get("score", -1) <= 100 and opp.get("verdict"))
check("رصد مخاطر التأهيل (تصنيف/غرامات/محتوى محلي)", len(opp.get("qualification_warnings", [])) >= 2,
      str(opp.get("qualification_warnings")))
check("عوامل التقييم الخمسة", len(opp.get("factors", [])) == 5)

# ---------- 12. التحليلات ----------
r = c.get("/api/analytics"); an = r.json()
check("التحليلات: نسبة الفوز والقيم", r.status_code == 200 and "win_rate" in an.get("totals", {}) and an["totals"].get("won_value", 0) > 0)

# ---------- 13. اعتماد (الشبكة محجوبة هنا — يجب أن يفشل بلطف) ----------
r = c.post("/api/etimad/fetch", params={"pages": 1})
graceful = r.status_code in (200, 502, 503) and (r.status_code != 200 or "error" in str(r.json()) or isinstance(r.json(), dict))
check("جلب اعتماد يفشل بلطف عند حجب الشبكة", graceful, r.text[:150])
r = c.get("/api/etimad")
check("قائمة منافسات اعتماد", r.status_code == 200)

# ---------- 13ب. مشاريع منصة فرصة ----------
r = c.get("/api/forsah")
check("قائمة مشاريع فرصة + التصنيفات",
      r.status_code == 200 and len(r.json().get("categories", [])) == 5)
_saved_fs = c.get("/api/settings").json()
r = c.post("/api/forsah/fetch")
_j = r.json()
if not _saved_fs.get("forsah_email"):
    check("سحب فرصة بلا بيانات دخول: رسالة إرشادية", r.status_code == 200 and not _j.get("ok")
          and "بريد" in _j.get("error", ""), str(_j))
else:
    check("سحب فرصة: استجابة سليمة (نجاح أو تشخيص واضح)",
          r.status_code == 200 and (_j.get("ok") or _j.get("error")), str(_j)[:150])
r = c.get("/")
check("صفحة فرصة في الواجهة", "مشاريع منصة فرصة" in r.text and 'id="page-forsah"' in r.text)

# ---------- 14. حذف العرض + الخروج ----------
r = c.delete(f"/api/proposals/{pid}")
check("حذف عرض", r.status_code == 200)
r = c.post("/api/logout")
check("تسجيل الخروج", r.status_code == 200)
r = c.get("/api/status")
check("انقطاع الوصول بعد الخروج", r.status_code == 401)

# ---------- 15. تصنيف القطاعات (حكومي/خاص/صندوق الاستثمارات/مطارات) ----------
c.post("/api/login", json={"username": "azoom", "password": "Azoom@2026"})
apt_txt = """عرض مالي — أعمال صيانة مدرجات مطار
إعادة تأهيل طبقات الأسفلت لمدرج الطائرات
م2 4,000 85.00 340,000.00
دهانات علامات أرضية للمدرجات وممرات الطائرات
م.ط 6,000 12.50 75,000.00
""".encode()
r = c.post("/api/repo/upload",
           data={"source_type": "عرض عزوم سابق", "company": "", "notes": "", "as_reference": "1", "sector": "airports"},
           files=[("files", ("عرض صيانة مدرجات.txt", apt_txt, "text/plain"))])
rec_a = r.json()[0]
check("رفع بقطاع مطارات + مرجعي", r.status_code == 200 and rec_a["items_count"] == 2
      and (rec_a.get("reference") or "مسبقاً" in str(rec_a.get("reference_note", ""))), str(rec_a))
r = c.get("/api/market/search", params={"q": "مدرج", "sector": "airports"})
check("بحث السوق مصفّى بقطاع المطارات", r.json()["benchmark"]["count"] >= 1)
r = c.get("/api/market/search", params={"q": "مدرج", "sector": "private"})
check("التصفية تستبعد القطاعات الأخرى", r.json()["benchmark"]["count"] == 0)
r = c.get("/api/proposals/similar", params={"q": "مشروع أعمال عزل أسطح ومباني", "sector": "airports"})
sims = r.json()
check("التشابه يقدّم عروض نفس القطاع أولاً", len(sims) >= 1 and sims[0].get("sector_match") is True, str(sims[:2]))
r = c.get("/api/analytics")
check("التحليلات تشمل القطاعات الأربعة", set(r.json()["by_entity"]) == {"government", "private", "pif", "airports"})
r = c.get("/api/repo")
sect_file = [f for f in r.json()["files"] if f["filename"] == "عرض صيانة مدرجات.txt"]
check("القطاع محفوظ على ملف المستودع", sect_file and sect_file[0].get("sector") == "airports")

# ---------- 16. إعادة تشغيل: البذور لا تتكرر ----------
n_before = c.get("/api/status").json() if False else None
c.post("/api/login", json={"username": "azoom", "password": "Azoom@2026"})
before = c.get("/api/status").json()["price_items"]
seed_if_empty()
after = c.get("/api/status").json()["price_items"]
check("إعادة التشغيل لا تكرر البذور", before == after, f"{before} -> {after}")

# ---------- 15ب. المستودع الفني ومحرك الأسلوب ----------
c.post("/api/login", json={"username": "azoom", "password": "Azoom@2026"})
tech_text = """نبذة عن الشركة
تُعد شركة عزوم المتحدة للمقاولات من الشركات الرائدة في تنفيذ مشاريع المباني الحكومية، وقد نفذت الشركة مشاريع عزل وترميم وتشطيب تجاوزت قيمتها أربعمائة مليون ريال خلال السنوات الماضية بمعدلات إنجاز موثقة.
نطاق العمل
يشمل نطاق العمل تنفيذ أعمال العزل المائي والحراري للأسطح والمباني، وأعمال الترميم الإنشائي، ومعالجة التشققات، وفق كراسة الشروط والمواصفات الفنية المعتمدة من الجهة المالكة.
منهجية التنفيذ
تعتمد الشركة منهجية تنفيذ مرحلية تبدأ بالتعبئة واستلام الموقع، ثم تنفيذ الأعمال ببرنامج زمني معتمد من الاستشاري، مع رفع مستخلصات شهرية موثقة بنسب الإنجاز الفعلية في الموقع.
خطة ضمان الجودة
تطبق الشركة نظام إدارة جودة يشمل فحص المواد قبل التوريد، واختبارات معتمدة من مختبرات مستقلة، وسجلات تفتيش يومية يعتمدها الاستشاري قبل الانتقال لأي مرحلة لاحقة.
خطة السلامة والصحة المهنية
تلتزم الشركة بتطبيق اشتراطات السلامة في مواقع العمل، وتوفير مهمات الوقاية الشخصية لكافة العاملين، وتعيين مشرف سلامة متفرغ للموقع طوال مدة التنفيذ."""

for i in range(3):
    r = c.post("/api/repo/upload",
               data={"source_type": "عرض فني سابق", "company": "عزوم", "notes": "فحص أسلوب",
                     "as_reference": "", "sector": "government"},
               files=[("files", (f"عرض فني عزل مباني {i+1}.txt",
                                 tech_text.encode(), "text/plain"))])
    assert r.status_code == 200, r.text
tech_rec = r.json()[0]
check("رفع عرض فني → استخراج أقسام وفقرات", bool(tech_rec.get("tech", {}).get("sections", 0) >= 4),
      str(tech_rec.get("tech")))
r = c.post("/api/style-profile/rebuild")
sp = r.json()
check("استخلاص بصمة الكتابة", r.status_code == 200 and sp.get("sample_count", 0) >= 10, str(sp)[:150])
r = c.get("/api/paragraph-bank")
bank_items = r.json()
check(f"بنك الفقرات المعتمد ({len(bank_items)})", len(bank_items) >= 10)
r = c.get("/api/repository/technical")
check("قائمة المستودع الفني", r.status_code == 200 and len(r.json()["documents"]) >= 3)

r = c.post("/api/proposals/generate",
           data={"title": "مشروع عزل وترميم مبانٍ حكومية بالقصيم", "client": "أمانة القصيم",
                 "entity_type": "government"})
sty = r.json()["data"].get("style", {})
spid = r.json()["id"]
check("العرض مبني من بنك الفقرات (bank_ratio > 0)",
      sty.get("bank_ratio", 0) > 0 and sty.get("score", 0) > 0, str(sty))
_bodies = " ".join(sec["body"] for sec in r.json()["data"]["technical_sections"])
check("لا عبارات من القائمة السوداء في المخرَج",
      not any(b in _bodies for b in ("حلول مبتكرة", "شريك النجاح", "في الختام", "نسعى جاهدين")))
c.delete(f"/api/proposals/{spid}")
if bank_items:
    r = c.put(f"/api/paragraphs/{bank_items[0]['id']}", json={"approved": False})
    check("سحب اعتماد فقرة", r.status_code == 200)
    c.put(f"/api/paragraphs/{bank_items[0]['id']}", json={"approved": True})

# ---------- 15ج. تصنيف فئة المشروع (إنشاءات / صيانة وتشغيل / ...) ----------
from app.style_engine import detect_project_kind as _dpk
check("المصنف: صيانة وتشغيل", _dpk("عقد صيانة وتشغيل المرافق مع الصيانة الوقائية ومعالجة الأعطال")[0] == "صيانة وتشغيل")
check("المصنف: إنشاءات", _dpk("إنشاء وتشطيب مبنى خرسانة مسلحة مع أعمال العزل")[0] == "إنشاءات وتشطيبات")
check("المصنف: نظافة", _dpk("خدمات نظافة وتنظيف شاملة مع مكافحة الحشرات")[0] == "نظافة")

_maint_text = """نطاق العمل
يشمل نطاق العمل تشغيل وصيانة الأنظمة الكهربائية والميكانيكية، وبرامج الصيانة الوقائية الدورية، ومعالجة الأعطال والبلاغات ضمن أزمنة الاستجابة المحددة بالعقد المعتمد.
منهجية التنفيذ
نبدأ باستلام المواقع وجرد الأصول، ثم تنفيذ برنامج الصيانة الوقائية الشهري بسجلات لكل أصل، ومعالجة البلاغات بفريق مناوب، وتقارير شهرية بمؤشرات الأداء المعتمدة.""".encode()
r = c.post("/api/repo/upload",
           data={"source_type": "عرض فني سابق", "company": "عزوم", "notes": "فحص فئة",
                 "as_reference": "", "sector": "government"},
           files=[("files", ("عرض صيانة فحص الفئات.txt", _maint_text, "text/plain"))])
check("رفع عرض صيانة → تصنيف تلقائي في المستودع الفني", r.status_code == 200)
_docs = c.get("/api/repository/technical").json()["documents"]
_md = next((dd for dd in _docs if "صيانة فحص الفئات" in dd["filename"]), None)
check("فئة المستند المكتشفة = صيانة وتشغيل", _md and _md["project_kind"] == "صيانة وتشغيل", str(_md))

r = c.post("/api/proposals/generate",
           data={"title": "مشروع صيانة وتشغيل مرافق تعليمية", "client": "إدارة تعليم", "entity_type": "government"})
_dk = r.json()["data"]
check("توليد صيانة: الفئة مكتشفة والخطة تشغيلية سنوية",
      _dk.get("project_kind") == "صيانة وتشغيل" and "التشغيل والصيانة الدورية" in _dk["plan"][1]["phase"],
      str((_dk.get("project_kind"), _dk["plan"][1]["phase"])))
_bank_refs = {s3.get("source_ref", "") for s3 in _dk["technical_sections"] if s3.get("source") == "bank"}
check("بنك الفقرات اختار عروض الصيانة لا الإنشاءات",
      any("صيانة" in (ref or "") for ref in _bank_refs), str(_bank_refs))
c.delete(f"/api/proposals/{r.json()['id']}")

# ---------- 16. تعدد الشركات والأدوار ----------
c.post("/api/login", json={"username": "azoom", "password": "Azoom@2026"})
me = c.get("/api/me").json()
check("me: الدور والشركة ومدير المنصة", me.get("role") == "owner" and me.get("company_id") == 1
      and me.get("is_platform_admin") and me.get("is_admin"), str(me))
r = c.get("/api/me/companies")
check("قائمة شركات المستخدم", r.status_code == 200 and len(r.json()) >= 1)
azoom_prices_before = c.get("/api/status").json()["price_items"]

# شركة معزولة للاختبار (قابلة للتكرار: 409 عند إعادة التشغيل)
r = c.post("/api/companies", json={"name": "شركة الفحص المعزولة", "plan": "trial",
                                   "owner_username": "isocheck", "owner_password": "Iso@12345"})
check("إنشاء شركة جديدة بمالكها (أو موجودة من فحص سابق)", r.status_code in (200, 409), r.text[:120])

c2 = TestClient(app)
r = c2.post("/api/login", json={"username": "isocheck", "password": "Iso@12345"})
check("دخول مالك الشركة الثانية", r.status_code == 200)
me2 = c2.get("/api/me").json()
check("سياق الشركة الثانية (اسم وخطة ودور)",
      me2.get("company_name") == "شركة الفحص المعزولة" and me2.get("role") == "owner"
      and me2.get("company_id") != 1, str(me2))
st2 = c2.get("/api/status").json()
check("العزل: لا أسعار ولا عروض من عزوم في الشركة الثانية",
      st2["price_items"] == 0 or st2["price_items"] < 5, str(st2))
check("العزل: أرشيف عروض فارغ", len(c2.get("/api/proposals").json()) == 0)
s2 = c2.get("/api/settings").json()
check("العزل: إعدادات مستقلة (لا آيبان عزوم)",
      s2.get("company_name") == "شركة الفحص المعزولة" and not s2.get("company_iban"))
r = c2.post("/api/prices", json={"code": "LIT-LB.1", "category": "اختبار عزل",
                                 "name": "بند بكود مكرر عبر الشركات", "unit": "م2", "unit_price": 77})
check("نفس كود البند مسموح عبر شركتين", r.status_code == 200, r.text[:120])
check("وعدد أسعار الشركة الثانية = 1", len(c2.get("/api/prices").json()) == 1)
r = c2.post("/api/session/company/1")
check("تبديل لشركة بلا عضوية → 403", r.status_code == 403)
r = c2.get("/api/paragraph-bank")
check("العزل: بنك فقرات الشركة الثانية محجوب (402 للتجريبي) أو فارغ",
      r.status_code == 402 or (r.status_code == 200 and len(r.json()) == 0), r.text[:100])

# دور المشاهد في عزوم
r = c.post("/api/members", json={"username": "viewcheck", "password": "View@12345", "role": "viewer"})
check("دعوة مُشاهد لشركة عزوم", r.status_code == 200, r.text[:120])
c3 = TestClient(app)
r = c3.post("/api/login", json={"username": "viewcheck", "password": "View@12345"})
check("دخول المُشاهد", r.status_code == 200)
check("المُشاهد محجوب عن قاعدة الأسعار (403)", c3.get("/api/prices").status_code == 403)
check("المُشاهد محجوب عن التحليلات (403)", c3.get("/api/analytics").status_code == 403)
check("المُشاهد يقرأ لوحة التحكم", c3.get("/api/proposals").status_code == 200)
check("المُشاهد لا يكتب (403)",
      c3.put("/api/settings", json={"profit_pct": "99"}).status_code == 403)
check("المُشاهد لا يولد عروضاً (403)",
      c3.post("/api/proposals/generate", data={"title": "x", "client": "y"}).status_code == 403)
check("المُشاهد لا يدير الأعضاء (403)", c3.get("/api/members").status_code == 403)
check("بيانات عزوم سليمة بعد كل الفحوص",
      c.get("/api/status").json()["price_items"] == azoom_prices_before)

# ---------- 17. الاشتراكات والتسجيل الذاتي ----------
r = c.post("/api/signup", json={"name": "شركة التسجيل الذاتي للفحص", "cr_no": "9990001112",
                                "owner_username": "signupcheck", "owner_password": "Sign@12345",
                                "sector": "المقاولات"})
check("التسجيل الذاتي (شركة تجريبية 14 يوماً) أو 409 عند التكرار",
      r.status_code in (200, 409), r.text[:120])
r = c.post("/api/signup", json={"name": "شركة أخرى", "cr_no": "9990001112",
                                "owner_username": "someoneelse", "owner_password": "Else@12345"})
check("سجل تجاري مكرر → 409", r.status_code == 409)

c4 = TestClient(app)
r = c4.post("/api/login", json={"username": "signupcheck", "password": "Sign@12345"})
check("دخول مالك الشركة المسجلة ذاتياً", r.status_code == 200)
me4 = c4.get("/api/me").json()
check("خطة تجريبية للشركة الجديدة", me4.get("plan") == "trial", str(me4)[:120])

# بوابات الميزات: التجريبي بلا اعتماد/فرصة ولا محرك أسلوب → 402
check("بوابة الميزات: اعتماد 402 للخطة التجريبية", c4.get("/api/etimad").status_code == 402)
check("بوابة الميزات: بصمة الكتابة 402 للخطة التجريبية",
      c4.get("/api/style-profile").status_code == 402)
check("عزوم (مؤسسي) تصل لاعتماد طبيعياً", c.get("/api/etimad").status_code == 200)

# دورة الحياة: تجربة منتهية → قراءة وتصدير فقط (402 على الكتابة)
from app.database import get_db as _gdb
with _gdb() as _db:
    from datetime import datetime, timedelta, timezone
    _ended = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    _db.execute("UPDATE companies SET trial_ends_at = ? WHERE cr_no = '9990001112'", (_ended,))
check("تجربة منتهية: القراءة تعمل", c4.get("/api/proposals").status_code == 200)
r = c4.post("/api/proposals/generate", data={"title": "x", "client": "y"})
check("تجربة منتهية: الكتابة 402", r.status_code == 402 and "التجربة" in r.json()["detail"], r.text[:120])
with _gdb() as _db:
    _db.execute("UPDATE companies SET trial_ends_at = '2030-01-01T00:00:00+00:00' "
                "WHERE cr_no = '9990001112'")

# الفوترة: شركة مدفوعة تُفوتر مرة واحدة للفترة، والتجارب تُتخطى
with _gdb() as _db:
    _db.execute("UPDATE companies SET plan = 'basic' WHERE cr_no = '9990001112'")
r1 = c.post("/api/platform/invoices/issue").json()
r2 = c.post("/api/platform/invoices/issue").json()
check("إصدار الفواتير الشهرية يعمل وبلا تكرار للفترة",
      (r1["issued"] + r1["skipped"]) >= 1 and r2["issued"] == 0, f"{r1} ثم {r2}")
with _gdb() as _db:
    _db.execute("UPDATE companies SET plan = 'trial' WHERE cr_no = '9990001112'")
r = c.get("/api/platform/metrics")
check("مؤشرات مدير المنصة", r.status_code == 200 and "mrr" in r.json())
check("المؤشرات محجوبة عن غير مدير المنصة", c2.get("/api/platform/metrics").status_code == 403)
r = c.get("/signup")
check("صفحة التسجيل الذاتي العامة", r.status_code == 200 and "تجربة مجانية" in r.text)

# ---------- 18. تقسيم البند إلى أجزاء مستقلة (كمية ووحدة وسعر لكل جزء) ----------
r = c.post("/api/proposals/generate", data={"title": "فحص تقسيم بنود جدول الكميات",
                                            "client": "جهة الفحص", "entity_type": "government"})
check("توليد عرض لفحص تقسيم البنود", r.status_code == 200, r.text[:120])
_sp = r.json()["id"]
_sd = c.get(f"/api/proposals/{_sp}").json()["data"]
_sd["boq"][0]["children"] = [
    {"name": "توريد المواد", "unit": "طن", "qty": 5, "unit_price": 1000},
    {"name": "أعمال التركيب", "unit": "م2", "qty": 20, "unit_price": 150},
    {"name": "الاختبار والتشغيل", "unit": "مقطوعية", "qty": 1, "unit_price": 2500},
]
c.put(f"/api/proposals/{_sp}", json={"data": _sd})
_sd2 = c.get(f"/api/proposals/{_sp}").json()["data"]
_sl = _sd2["boq"][0]
check("كل جزء: الإجمالي = كميته × سعره",
      all(abs(k["total"] - k["qty"] * k["unit_price"]) < 0.01 for k in _sl["children"])
      and _sl["children"][0]["total"] == 5000 and _sl["children"][1]["total"] == 3000,
      str(_sl["children"])[:200])
check("إجمالي البند الأب = مجموع أجزائه (10500)", abs(_sl["total"] - 10500) < 0.01, str(_sl["total"]))
check("التكلفة المباشرة متسقة بعد التقسيم",
      abs(_sd2["financial"]["direct_cost"] - sum(l["total"] for l in _sd2["boq"])) < 0.05)
from app.proposal_builder import client_facing_pricing as _cfp
_cf = _cfp(_sd2["boq"], _sd2["financial"])
check("التسعير المحمَّل: مجموع الأجزاء المحمَّلة = إجمالي الأب",
      abs(_cf[0]["total"] - round(sum(k["total"] for k in _cf[0]["children"]), 2)) < 0.01)
check("التسعير المحمَّل: مجموع البنود = الإجمالي قبل الضريبة",
      abs(round(sum(l["total"] for l in _cf), 2) - _sd2["financial"]["subtotal"]) < 0.05)
r = c.get(f"/api/proposals/{_sp}/export/xlsx")
_rows = []
if r.status_code == 200:
    _wbx = load_workbook(io.BytesIO(r.content))
    for _wsx in _wbx.worksheets:
        for _row in _wsx.iter_rows(values_only=True):
            _rows.append(" | ".join(str(x) for x in _row if x is not None))
check("إكسل: صف الجزء يحمل كميته ووحدته (طن × 5)",
      any("توريد المواد" in x and "طن" in x and (" 5 " in f" {x} " or "| 5 |" in x) for x in _rows),
      str([x for x in _rows if "توريد" in x])[:200])
# توافق رجعي: جزء قديم بلا كمية/وحدة يرث كمية الأب ووحدته
_sd2["boq"][0]["children"] = [{"name": "جزء قديم", "unit_price": 100}]
c.put(f"/api/proposals/{_sp}", json={"data": _sd2})
_sl3 = c.get(f"/api/proposals/{_sp}").json()["data"]["boq"][0]
check("توافق رجعي: الجزء بلا كمية يرث كمية الأب ووحدته",
      _sl3["children"][0]["qty"] == _sl3["qty"] and _sl3["children"][0]["unit"] == _sl3["unit"])
c.delete(f"/api/proposals/{_sp}")

# ---------- 19. تنفيذ المشاريع: مقاولو الباطن وقفل تقارير الإنتاجية ----------
r = c.post("/api/execution/subcontractors", json={"name": "مؤسسة فحص الدرع", "trade": "خرسانة"})
check("تسجيل مقاول باطن (أو 409 لتكرار الاسم)", r.status_code in (200, 409), r.text[:120])
_opts = c.get("/api/execution/executors").json()
check("القائمة المنسدلة: عمالة الشركة أولاً ثم مقاولو الباطن",
      _opts and _opts[0]["label"] == "عمالة الشركة"
      and any("فحص الدرع" in o["label"] for o in _opts))
r = c.post("/api/execution/projects", json={"name": "مشروع فحص التنفيذ", "client": "جهة الفحص"})
_xp = r.json()["id"]
r = c.post("/api/members", json={"username": "engcheck", "password": "Eng@12345", "role": "engineer"})
check("دعوة مهندس موقع (دور جديد)", r.status_code == 200, r.text[:120])
c_eng = TestClient(app)
c_eng.post("/api/login", json={"username": "engcheck", "password": "Eng@12345"})
check("المهندس محجوب عن العروض والأسعار (403)",
      c_eng.get("/api/proposals").status_code == 403 and c_eng.get("/api/prices").status_code == 403)
_sub_id = next(o["id"] for o in _opts if "فحص الدرع" in o["label"])
r = c_eng.post("/api/execution/reports", json={
    "project_id": _xp, "report_date": "2026-09-01",
    "lines": [{"item": "صب خرسانة", "unit": "م3", "qty": 40,
               "executor_type": "subcontractor", "subcontractor_id": _sub_id},
              {"item": "أعمال حفر", "unit": "م3", "qty": 65, "executor_type": "company"}]})
check("المهندس يسجّل تقرير إنتاجية بمنفّذين مختلفين", r.status_code == 200, r.text[:120])
_xr = r.json()["id"]
_rep = c_eng.get(f"/api/execution/reports/{_xr}").json()
check("سطر التقرير يحمل اسم المنفّذ", _rep["lines"][0]["executor_name"] == "مؤسسة فحص الدرع"
      and _rep["lines"][1]["executor_name"] == "عمالة الشركة")
r = c_eng.put(f"/api/execution/reports/{_xr}", json={
    "project_id": _xp, "lines": [dict(_rep["lines"][0], qty=45), _rep["lines"][1]]})
check("القفل: تعديل المهندس يتحول لطلب موافقة", r.status_code == 200 and r.json().get("pending"))
_req = r.json().get("request_id")
check("الكمية لم تتغير قبل قرار المالك",
      c_eng.get(f"/api/execution/reports/{_xr}").json()["lines"][0]["qty"] == 40)
_n = c.get("/api/notifications").json()
check("إشعار للمالك بطلب التعديل", any("طلب تعديل" in i["title"] for i in _n["items"]))
r = c.post(f"/api/execution/edit-requests/{_req}/decision", json={"action": "approve"})
check("قبول المالك يطبّق التعديل",
      r.status_code == 200
      and c_eng.get(f"/api/execution/reports/{_xr}").json()["lines"][0]["qty"] == 45)
check("إشعار المهندس بالقبول",
      any("قُبل" in i["title"] for i in c_eng.get("/api/notifications").json()["items"]))
_ps = c.get(f"/api/execution/productivity?project_id={_xp}").json()
_by = {s["executor"]: s for s in _ps}
check("كم اشتغل كل منفّذ: التفصيل بالوحدة صحيح",
      {"unit": "م3", "qty": 45.0} in _by.get("مؤسسة فحص الدرع", {}).get("by_unit", [])
      and {"unit": "م3", "qty": 65.0} in _by.get("عمالة الشركة", {}).get("by_unit", []),
      str(_ps)[:200])

# ---------- 20. التكلفة والربحية الفعلية + قنوات الإشعارات الخارجية ----------
r = c.post("/api/execution/agreements", json={
    "project_id": _xp, "subcontractor_id": _sub_id, "item": "صب خرسانة",
    "unit": "م3", "unit_rate": 100})
check("تسجيل سعر اتفاق مقاول باطن", r.status_code == 200, r.text[:120])
_pr = c.get(f"/api/execution/profitability?project_id={_xp}")
check("شاشة الربحية تعمل للمالك", _pr.status_code == 200, _pr.text[:120])
_prj = _pr.json()
_row = next((x for x in _prj["rows"] if x["item"] == "صب خرسانة"), None)
check("تكلفة فعلية = المنفَّذ × سعر الاتفاق (45×100)",
      _row is not None and _row["cost"] == 4500.0 and _row["rate"] == 100,
      str(_row)[:150])
check("راية البنود بلا سعر اتفاق", _prj["totals"]["missing_rates"] >= 1)
check("المهندس محجوب عن الربحية وأسعار الاتفاقيات (403)",
      c_eng.get(f"/api/execution/profitability?project_id={_xp}").status_code == 403
      and c_eng.get(f"/api/execution/agreements?project_id={_xp}").status_code == 403)
check("تقارير المهندس بلا أي حقل سعر",
      all(k not in str(c_eng.get("/api/execution/reports").json())
          for k in ("unit_rate", "client_price", "profit")))
r = c.post("/api/members/{}/contact".format(
    next(m["id"] for m in c.get("/api/members").json() if m["username"] == "engcheck")),
    json={"email": "eng@example.com", "phone": "966500000000"})
check("حفظ بريد وجوال العضو للإشعارات", r.status_code == 200)
_rs = c.put("/api/settings", json={"smtp_pass": "Secret123", "whatsapp_token": "TOK-abc"})
with _gdb() as _db:
    _raw = {x["key"]: x["value"] for x in _db.execute(
        "SELECT key, value FROM settings WHERE company_id=1 "
        "AND key IN ('smtp_pass','whatsapp_token')")}
check("أسرار قنوات الإشعارات مشفرة في القاعدة",
      _raw.get("smtp_pass", "").startswith("enc:v1:")
      and _raw.get("whatsapp_token", "").startswith("enc:v1:"), f"{_rs.status_code} {_rs.text[:200]} {_raw}")
c.put("/api/settings", json={"notify_email_enabled": "0", "notify_whatsapp_enabled": "0"})
r = c.post("/api/notify/test", json={})
check("اختبار القنوات يتخطى بأمان وهي معطلة",
      r.status_code == 200 and r.json() == {"email": "skipped", "whatsapp": "skipped"})
check("قنوات الإشعارات محجوبة عن المهندس (403)",
      c_eng.post("/api/notify/test", json={}).status_code == 403)

# ---------- 21. الوكيلان ومعالج تهيئة المستأجر والهوية في المخرجات ----------
_ob = c.get("/api/onboarding").json()
check("جاهزية عزوم: الشعار موجود والوكيلان جاهزان",
      _ob["logo"] and _ob["tech_readiness"] >= 90 and _ob["fin_readiness"] >= 90, str(_ob)[:150])
r = c.post("/api/agents/analyze", data={"title": "مشروع صيانة وتشغيل أنظمة تكييف لفحص الوكيلين",
                                        "client": "جهة الفحص", "entity_type": "private"})
check("تحليل الوكيلين (تشغيل جاف)", r.status_code == 200, r.text[:150])
_an = r.json()
check("الوكيل الفني: فئة + تغطية بنك + توصيات",
      _an["project_kind"] == "صيانة وتشغيل" and _an["tech"]["sections_total"] >= 10
      and isinstance(_an["recommendations"], list))
check("وكيل التسعير: بنود ومصادر أسعار",
      _an["fin"]["total"] > 0 and _an["fin"]["by_source"])
r = c.post("/api/agents/generate", json={"session_id": _an["session_id"]})
check("التوليد من جلسة التحليل", r.status_code == 200, r.text[:150])
_ap = r.json()
check("ما وعد به التحليل هو ما بُني (نفس الإجمالي)",
      abs(_ap["data"]["financial"]["grand_total"] - _an["financial_preview"]["grand_total"]) < 1)
import struct as _st, zlib as _zl
def _png(rgb):
    def ch(t, d):
        x = _st.pack(">I", len(d)) + t + d
        return x + _st.pack(">I", _zl.crc32(t + d) & 0xffffffff)
    raw = b"".join(b"\x00" + bytes(rgb) * 40 for _ in range(40))
    return (b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", _st.pack(">IIBBBBB", 40, 40, 8, 2, 0, 0, 0))
            + ch(b"IDAT", _zl.compress(raw)) + ch(b"IEND", b""))
import time as _tm
_suf = str(int(_tm.time()) % 1000000)
r = c.post("/api/signup", json={"name": "شركة فحص الوكيلين " + _suf, "cr_no": "88" + _suf,
                                "owner_username": "agchk" + _suf, "owner_password": "Chk@12345"})
check("تسجيل شركة فحص الوكيلين", r.status_code == 200, r.text[:120])
c5 = TestClient(app)
c5.post("/api/login", json={"username": "agchk" + _suf, "password": "Chk@12345"})
_o5 = c5.get("/api/onboarding").json()
check("مستأجر جديد: لا شعار وجاهزية صفرية", _o5["logo"] is False and _o5["style_docs"] == 0)
r = c5.post("/api/proposals/generate", data={"title": "x", "client": "y"})
check("الشعار إلزامي: التوليد محجوب قبل رفعه (400)",
      r.status_code == 400 and "شعار" in r.json()["detail"], r.text[:120])
_me5 = c5.get("/api/me").json()
r = c5.post(f"/api/companies/{_me5['company_id']}/logo",
            files={"logo": ("logo.png", _png((90, 62, 134)), "image/png")})
check("رفع شعار المستأجر", r.status_code == 200, r.text[:120])
c5.put("/api/settings", json={"company_name": "شركة فحص الوكيلين", "brand_color": "#5A3E86"})
r = c5.post("/api/proposals/generate", data={"title": "مشروع مكاتب صغير", "client": "جهة"})
check("بعد الشعار: التوليد يعمل", r.status_code == 200, r.text[:150])
_p5 = r.json()
r = c5.get(f"/api/proposals/{_p5['id']}/export/docx")
from docx import Document as _Doc
_d5 = _Doc(io.BytesIO(r.content))
_t5 = "\n".join(p.text for p in _d5.paragraphs)
for _tb in _d5.tables:
    for _rw in _tb.rows:
        for _cl in _rw.cells:
            _t5 += "\n" + _cl.text
check("Word المستأجر: شعاره واسمه وبلا أي ذكر لعزوم",
      "شركة فحص الوكيلين" in _t5 and "عزوم" not in _t5
      and any(rel.reltype.endswith("/image") for rel in _d5.part.rels.values()))
r = c5.post("/api/onboarding/technical-upload",
            files=[("files", ("old.txt", ("العرض الفني\nنطاق العمل\n" +
                    "نلتزم في شركتنا بتنفيذ الأعمال وفق أعلى المعايير ونحرص على رضا العميل. " * 30).encode(),
                    "text/plain"))])
check("رفع عرض فني سابق يغذي بنك الأسلوب",
      r.status_code == 200 and r.json()["results"][0]["ok"]
      and c5.get("/api/onboarding").json()["style_docs"] == 1, r.text[:150])
r = c5.post("/api/onboarding/complete", json={})
check("إنهاء التهيئة بعد الشعار", r.status_code == 200 and c5.get("/api/onboarding").json()["done"])

# ---------- 22. التحديث التلقائي لموديل Claude ----------
from app.model_updater import choose_latest as _cl
_mods = [{"id": "claude-sonnet-5", "created_at": "2026-08-01"},
         {"id": "claude-sonnet-5-1", "created_at": "2026-09-10"},
         {"id": "claude-opus-5", "created_at": "2026-08-15"}]
check("اختيار الأحدث من الفئة المفضلة",
      _cl(_mods, "sonnet") == "claude-sonnet-5-1" and _cl(_mods, "opus") == "claude-opus-5")
r = c.get("/api/platform/model")
check("حالة محرك الذكاء لمدير المنصة",
      r.status_code == 200 and r.json().get("active") and "auto_update" in r.json())
_prev = r.json()
r = c.post("/api/platform/model/refresh", json={})
check("الفحص اليدوي يتصرف بأمان بلا مفتاح أو يفحص فعلاً",
      r.status_code == 200 and ("ok" in r.json()), r.text[:120])
r = c.put("/api/platform/model", json={"tier": "opus"})
check("ضبط الفئة المفضلة", r.status_code == 200 and r.json()["tier"] == "opus")
c.put("/api/platform/model", json={"tier": _prev.get("tier", "sonnet"),
                                   "auto_update": _prev.get("auto_update", True),
                                   "pinned": _prev.get("pinned", "")})
check("الفئة المجهولة مرفوضة (400)",
      c.put("/api/platform/model", json={"tier": "xyz"}).status_code == 400)
check("محرك الذكاء محجوب عن غير مدير المنصة",
      c2.get("/api/platform/model").status_code == 403)
from app.database import update_settings as _ups
from app.ai_engine import _active_model as _am
_ups({"active_claude_model": "claude-test-check"}, company_id=1)
check("محرك التوليد يستخدم الموديل المحدَّث تلقائياً", _am() == "claude-test-check")
_ups({"active_claude_model": ""}, company_id=1)

# ---------- 23. وكيل الجودة والمراجعة ----------
r = c.post("/api/proposals/generate", data={"title": "فحص وكيل الجودة والمراجعة",
                                            "client": "جهة الفحص", "entity_type": "government"})
_qp = r.json()["id"]
r = c.get(f"/api/proposals/{_qp}/quality")
check("تقرير وكيل الجودة", r.status_code == 200 and 0 <= r.json()["score"] <= 100
      and "issues" in r.json(), r.text[:120])
_q0 = r.json()["score"]
_qd = c.get(f"/api/proposals/{_qp}").json()["data"]
_qd["technical_sections"][3]["body"] += " نقدم حلول مبتكرة ومما لا شك فيه أن ذلك مهم."
_qd["technical_sections"][4]["body"] += " [placeholder هنا]"
c.put(f"/api/proposals/{_qp}", json={"data": _qd})
_q1 = c.get(f"/api/proposals/{_qp}/quality").json()
check("كشف العبارات القالبية والنصوص المؤقتة",
      {"cliche", "placeholder"} <= {i["kind"] for i in _q1["issues"]} and _q1["score"] < _q0)
r = c.post(f"/api/proposals/{_qp}/quality/fix")
check("الإصلاح التلقائي يزيل القالبية ويعيد التقييم",
      r.status_code == 200 and r.json()["fixes"]["removed_phrases"]
      and not any(i["kind"] == "cliche" for i in r.json()["report"]["issues"]))
_qbody = c.get(f"/api/proposals/{_qp}").json()["data"]["technical_sections"][3]["body"]
check("النص نظيف بعد الإصلاح", "حلول مبتكرة" not in _qbody and "مما لا شك فيه" not in _qbody)
r = c.get(f"/api/proposals/{_qp}/export/docx")
_qdoc = _Doc(io.BytesIO(r.content))
check("خصائص Word باسم الشركة لا مكتبة برمجية",
      _qdoc.core_properties.author == "شركة عزوم المتحدة للمقاولات"
      and "python-docx" not in str(_qdoc.core_properties.author)
      + str(_qdoc.core_properties.last_modified_by or ""))
r = c.get(f"/api/proposals/{_qp}/export/xlsx")
_qwb = load_workbook(io.BytesIO(r.content))
check("خصائص Excel باسم الشركة",
      _qwb.properties.creator == "شركة عزوم المتحدة للمقاولات")
from app.quality_agent import review_proposal as _rq
import copy as _cp
_qbad = _cp.deepcopy(c.get(f"/api/proposals/{_qp}").json()["data"])
_qbad["financial"]["grand_total"] += 5000
check("كشف عدم الاتساق المالي",
      any(i["kind"] == "finance" and i["level"] == "error" for i in _rq(_qbad)["issues"]))
c.delete(f"/api/proposals/{_qp}")

# ---------- 24. تحصين ما بعد المراجعة الهندسية: اختبار انحدار لكل إصلاح ----------
import inspect as _insp
import json as _json
import subprocess as _sp
import types as _ty
import zipfile as _zf
from concurrent.futures import ThreadPoolExecutor as _TPE

import app.main as _main
from app import agents as _ag
from app import database as _dbm
from app import model_updater as _mu
from app import notify_channels as _nc
from app import security as _sec
from app import tenancy as _tn
from app.config import DATA_DIR as _DATA
from app.database import get_settings as _gs
from app.database import update_settings as _ups
from app.quality_agent import review_proposal as _rq2

_ROOT = Path(__file__).resolve().parent.parent
_cid5, _cid2, _cid4 = _me5["company_id"], me2["company_id"], me4["company_id"]

# --- 24.1 الدخول والتسجيل: تحديد المعدل + كوكي آمن + ترويسات ---
check("ترويسات الأمان تظهر حتى على 401 المبكرة من auth_guard (لا فقط على المسارات المفتوحة)",
      "x-content-type-options" in TestClient(app).get("/api/status").headers)

_sec.LOGIN_USER_LIMITER.clear(); _sec.LOGIN_USER_LIMITER.limit = 3
_cx = TestClient(app)
_codes = [_cx.post("/api/login", json={"username": "nobody-rl", "password": "bad"}).status_code
          for _ in range(5)]
check("تحديد محاولات الدخول الفاشلة: 429 بعد الحد", _codes[:3] == [401] * 3 and _codes[3] == 429, str(_codes))
_r = _cx.post("/api/login", json={"username": "nobody-rl", "password": "bad"})
check("429 الدخول يحمل Retry-After", "retry-after" in {k.lower() for k in _r.headers})
_sec.LOGIN_USER_LIMITER.limit = 1000; _sec.LOGIN_USER_LIMITER.clear()
_r = _cx.post("/api/login", json={"username": "azoom", "password": "Azoom@2026"})
check("بعد فك الحظر يعمل الدخول (وكوكي http بلا Secure)",
      _r.status_code == 200 and "secure" not in _r.headers.get("set-cookie", "").lower())
_cs = TestClient(app, base_url="https://testserver")
_r = _cs.post("/api/login", json={"username": "azoom", "password": "Azoom@2026"})
check("كوكي الجلسة Secure تحت HTTPS", "secure" in _r.headers.get("set-cookie", "").lower())
check("ترويسات الأمان (nosniff + HSTS تحت HTTPS)",
      _r.headers.get("x-content-type-options") == "nosniff" and "strict-transport-security" in _r.headers)
_r = _cx.post("/api/login", json={"username": ["x"], "password": 5})
check("تسجيل دخول بحمولة مشوّهة → 401 لا 500", _r.status_code == 401, str(_r.status_code))
_sec.SIGNUP_IP_LIMITER.clear(); _sec.SIGNUP_IP_LIMITER.limit = 1
_s1 = _cx.post("/api/signup", json={"name": "", "cr_no": "", "owner_username": ""}).status_code
_s2 = _cx.post("/api/signup", json={"name": "", "cr_no": "", "owner_username": ""}).status_code
check("التسجيل الذاتي المفتوح مقيَّد لكل عنوان (429)", _s1 == 400 and _s2 == 429, f"{_s1},{_s2}")
_sec.SIGNUP_IP_LIMITER.limit = 1000; _sec.SIGNUP_IP_LIMITER.clear()
_sec.SIGNUP_GLOBAL_LIMITER.clear(); _sec.SIGNUP_GLOBAL_LIMITER.limit = 1
_g1 = _cx.post("/api/signup", json={"name": "", "cr_no": "", "owner_username": ""}).status_code
_g2 = _cx.post("/api/signup", json={"name": "", "cr_no": "", "owner_username": ""}).status_code
check("والتسجيل الذاتي مقيَّد عالمياً أيضاً (429)", _g1 == 400 and _g2 == 429, f"{_g1},{_g2}")
_sec.SIGNUP_GLOBAL_LIMITER.limit = 1000; _sec.SIGNUP_GLOBAL_LIMITER.clear()

_rq = lambda host, fwd: _ty.SimpleNamespace(client=_ty.SimpleNamespace(host=host),
                                            headers={"x-forwarded-for": fwd} if fwd else {})
check("عنوان العميل: وكيل خاص (Docker/nginx) يُصدَّق وآخر عنوان مُضاف منه، وعميل عام لا يُصدَّق",
      _sec.client_ip(_rq("172.17.0.1", "9.9.9.9, 5.6.7.8")) == "5.6.7.8"
      and _sec.client_ip(_rq("8.8.8.8", "1.2.3.4")) == "8.8.8.8"
      and _sec.client_ip(_rq("testclient", "1.2.3.4")) == "testclient")

# --- 24.2 الإعدادات: لا أسرار ولا مفاتيح داخلية، وكتابة للأدمن فقط بقيم صالحة ---
_sa = c.get("/api/settings").json()
check("الإعدادات: الأسرار لا تخرج أبداً (علم set فقط)",
      not any(k in _sa for k in ("smtp_pass", "whatsapp_token", "forsah_password"))
      and _sa.get("smtp_pass_set") == "1", str([k for k in _sa if "pass" in k or "token" in k]))
check("الإعدادات: لا مفاتيح داخلية (auth_secret / محرك الذكاء)",
      not any(k in _sa for k in ("auth_secret", "active_claude_model", "model_pinned", "model_update_log")))
_sv = c3.get("/api/settings").json()
check("المُشاهد يقرأ التسعير لا القنوات ولا الحسابات الخارجية",
      "vat_rate" in _sv and not any(k.startswith(("smtp_", "whatsapp_", "notify_")) for k in _sv)
      and "forsah_email" not in _sv and "etimad_national_id" not in _sv)
c.post("/api/members", json={"username": "edcheck", "password": "Edit@12345", "role": "editor"})
c_ed = TestClient(app)
c_ed.post("/api/login", json={"username": "edcheck", "password": "Edit@12345"})
check("المحرر لا يعدّل إعدادات الشركة (403)",
      c_ed.put("/api/settings", json={"profit_pct": "99"}).status_code == 403)
check("المحرر لا يرى أسرار ولا قنوات الإشعارات",
      not any(k.startswith(("smtp_", "whatsapp_")) for k in c_ed.get("/api/settings").json()))
check("إعداد مجهول/داخلي مرفوض (400)",
      c.put("/api/settings", json={"auth_secret": "x"}).status_code == 400
      and c.put("/api/settings", json={"active_claude_model": "x"}).status_code == 400)
check("نسبة مالية خارج النطاق أو غير رقمية مرفوضة (400)",
      c.put("/api/settings", json={"profit_pct": "250"}).status_code == 400
      and c.put("/api/settings", json={"vat_rate": "abc"}).status_code == 400)
check("منفذ/تشفير SMTP/لون العلامة/بادئة الرقم تُتحقق",
      c.put("/api/settings", json={"smtp_port": "99999"}).status_code == 400
      and c.put("/api/settings", json={"smtp_security": "weird"}).status_code == 400
      and c.put("/api/settings", json={"brand_color": "red"}).status_code == 400
      and c.put("/api/settings", json={"ref_prefix": "بادئة"}).status_code == 400)
c.put("/api/settings", json={"smtp_pass": "Keep-Me-1"})
c.put("/api/settings", json={"smtp_pass": ""})
check("سر فارغ لا يمسح المحفوظ", _gs(1).get("smtp_pass") == "Keep-Me-1")
c.put("/api/settings", json={"_clear": ["smtp_pass", "whatsapp_token"]})
check("المسح الصريح للسر عبر _clear",
      _gs(1).get("smtp_pass") == "" and _gs(1).get("whatsapp_token") == "")

# --- 24.3 تبديل الشركة لمدير المنصة + حدود المقاطع + دورة الحياة ---
_r = c.post(f"/api/session/company/{_cid5}")
_m = c.get("/api/me").json()
check("مدير المنصة يبدّل فعلاً إلى شركة ليس عضواً فيها",
      _r.status_code == 200 and _m["company_id"] == _cid5 and _m["is_admin"], str(_m)[:150])
check("...وتُقرأ إعدادات تلك الشركة لا شركته",
      c.get("/api/settings").json().get("company_name") == "شركة فحص الوكيلين")
c.post("/api/session/company/1")
check("والعودة إلى شركته", c.get("/api/me").json()["company_id"] == 1)
check("شركة غير موجودة → 404", c.post("/api/session/company/987654").status_code == 404)
check("مطابقة المسارات على حدود المقطع",
      _main._under("/api/me/companies", ("/api/me",)) and not _main._under("/api/members", ("/api/me",))
      and not _main._under("/api/paragraphs-x", ("/api/paragraphs",)))
check("مهندس الموقع لا يصل /api/members (403)", c_eng.get("/api/members").status_code == 403)
c.put(f"/api/companies/{_cid4}", json={"status": "suspended"})
_r = c4.post(f"/api/session/company/{_cid4}")
check("شركة موقوفة: يحجب عملها (402) ولا يحبس المستخدم (تبديل/خروج/هوية مسموحة)",
      c4.get("/api/proposals").status_code == 402 and _r.status_code == 200
      and c4.get("/api/me").status_code == 200 and c4.post("/api/logout").status_code == 200)
c.put(f"/api/companies/{_cid4}", json={"status": "active"})
c4.post("/api/login", json={"username": "signupcheck", "password": "Sign@12345"})
check("وإعادة التفعيل تعيد العمل",
      c4.get("/api/proposals").status_code == 200)

# --- 24.4 المعالجات المتزامنة وسقف الرفع ---
_sync_names = ("generate_proposal", "agents_analyze", "opportunity", "repo_upload",
               "import_prices_csv", "onboarding_technical_upload", "upload_company_logo")
check("معالجات الرفع والتوليد `def` لا `async` (لا تجمّد حلقة الأحداث)",
      not any(_insp.iscoroutinefunction(getattr(_main, n)) for n in _sync_names))
_old_cap = _sec.MAX_UPLOAD_BYTES; _sec.MAX_UPLOAD_BYTES = 1000
_r = c.post("/api/opportunity", data={"title": "t"}, files=[("files", ("big.txt", b"x" * 5000, "text/plain"))])
_sec.MAX_UPLOAD_BYTES = _old_cap
check("سقف حجم الرفع (413)", _r.status_code == 413, str(_r.status_code))

# --- 24.5 الشعار: صورة حقيقية فقط، WebP→PNG، ولأعضاء الشركة فقط ---
_r = c5.post(f"/api/companies/{_cid5}/logo", files={"logo": ("evil.png", b"<svg onload=alert(1)>", "image/png")})
check("ملف مزيّف بامتداد صورة مرفوض (415)", _r.status_code == 415, str(_r.status_code))
from PIL import Image as _Img
_wb = io.BytesIO(); _Img.new("RGB", (60, 40), (10, 120, 60)).save(_wb, format="WEBP")
_r = c5.post(f"/api/companies/{_cid5}/logo", files={"logo": ("l.webp", _wb.getvalue(), "image/webp")})
_png_path = _DATA / "branding" / f"logo_{_cid5}.png"
check("شعار WebP يُحوَّل إلى PNG ولا يبقى WebP",
      _r.status_code == 200 and _png_path.exists() and not (_DATA / "branding" / f"logo_{_cid5}.webp").exists())
_r = c5.get(f"/api/proposals/{_p5['id']}/export/docx")
_d5b = _Doc(io.BytesIO(_r.content))
check("Word بعد شعار WebP: الشعار مُدرج فعلاً",
      any(rel.reltype.endswith("/image") for rel in _d5b.part.rels.values()))
check("شعار شركة لا يقرؤه غير أعضائها (403)", c2.get(f"/api/companies/{_cid5}/logo").status_code == 403)
check("ويقرؤه أعضاؤها ومدير المنصة",
      c5.get(f"/api/companies/{_cid5}/logo").status_code == 200
      and c.get(f"/api/companies/{_cid5}/logo").status_code == 200)

# --- 24.6 التصدير: متزامن آمن، هوية كل شركة، وبلا بصمات عزوم للمستأجر ---
_az_pid = c.get("/api/proposals").json()[0]["id"]


def _export_job(args):
    who, pid = args
    cl = TestClient(app)
    cl.cookies.update((c if who == "az" else c5).cookies)
    resp = cl.get(f"/api/proposals/{pid}/export/docx")
    if resp.status_code != 200:
        return who, None
    try:
        with _zf.ZipFile(io.BytesIO(resp.content)) as z:
            return who, z.read("word/document.xml").decode("utf-8") + z.read("word/footer1.xml").decode("utf-8") \
                if "word/footer1.xml" in z.namelist() else z.read("word/document.xml").decode("utf-8")
    except Exception:
        return who, None


with _TPE(max_workers=8) as _pool:
    _res = list(_pool.map(_export_job, [("az", _az_pid), ("t5", _p5["id"])] * 12))
_ok_all = all(x is not None for _, x in _res)
_az_hex = _main._brand_color(1).lstrip("#").upper()
_az_ok = all(_az_hex in x and "5A3E86" not in x for w, x in _res if w == "az" and x)
_t5_ok = all("5A3E86" in x and _az_hex not in x and "2E9E5B" not in x for w, x in _res if w == "t5" and x)
check("24 تصديراً متزامناً لشركتين: كلها سليمة (لا ملف تالف)", _ok_all)
check("عزوم: وثائقها بأخضر هويتها الرسمي لا لون لوحة المستأجرين", _az_hex == "1E6B3C")
check("ولكل شركة لونها فقط (لا تسرّب هوية بين الطلبات المتزامنة)", _az_ok and _t5_ok)
import app.export_docx as _ed
check("لا متغيرات هوية عامة قابلة للتبادل في مُصدّر Word",
      not hasattr(_ed, "PRIMARY") and not hasattr(_ed, "_PRIMARY_HEX"))
_s5 = c5.get("/api/settings").json()
check("مستأجر جديد: بيانات عزوم لا تُورَّث (آيبان/شروط دفع/خدمات/تأسيس فارغة)",
      all(_s5.get(k, "") == "" for k in ("company_iban", "payment_terms", "company_services", "company_founded",
                                        "company_legal_form", "company_bank", "company_cr")), str(_s5)[:200])
check("مستأجر جديد: بادئة رقم العرض PR لا AZM",
      _p5["ref_no"].startswith("PR-") and _s5.get("ref_prefix") == "PR", _p5["ref_no"])
_t5b = "\n".join(p.text for p in _d5b.paragraphs)
check("Word المستأجر بلا عنوان «شروط الدفع» الفارغ", "شروط الدفع" not in _t5b)

# --- 24.7 الوكيلان: بناء واحد، اعتماد بلا تكرار، وحد الخطة قبل التكلفة ---
_calls = {"n": 0}
_orig_build = _main._build_proposal_data


def _counted(*a, **k):
    _calls["n"] += 1
    return _orig_build(*a, **k)


_main._build_proposal_data = _counted
_r = c.post("/api/agents/analyze", data={"title": "مشروع فحص التخزين المؤقت", "client": "جهة", "entity_type": "private"})
_sid = _r.json()["session_id"]
_g1 = c.post("/api/agents/generate", json={"session_id": _sid})
_g2 = c.post("/api/agents/generate", json={"session_id": _sid})
check("تحليل + اعتماد = بناء واحد فقط (لا استدعاء ذكاء ثانٍ)",
      _g1.status_code == 200 and _calls["n"] == 1, str(_calls))
check("اعتماد مكرر يعيد العرض نفسه لا نسخة ثانية",
      _g2.status_code == 200 and _g2.json()["id"] == _g1.json()["id"])
c.delete(f"/api/proposals/{_g1.json()['id']}")
_lim = _tn.PLAN_LIMITS["trial"]["proposals_month"]; _tn.PLAN_LIMITS["trial"]["proposals_month"] = 0
_calls["n"] = 0
_r = c5.post("/api/agents/analyze", data={"title": "x", "client": "y"})
_tn.PLAN_LIMITS["trial"]["proposals_month"] = _lim
check("التحليل عند بلوغ حد الخطة: 402 قبل أي بناء/تكلفة", _r.status_code == 402 and _calls["n"] == 0, str(_calls))
_main._build_proposal_data = _orig_build
_old_ts = "2020-01-01T00:00:00+00:00"
with _gdb() as _db:
    _old_sid = _db.execute(
        "INSERT INTO agent_sessions (company_id, title, client, entity_type, files_text, analysis, created_at) "
        "VALUES (1, 'old', 'x', 'government', '', '{}', ?)", (_old_ts,)).lastrowid
_tok = _tn.set_context(1, "owner", 1, True)
_stale = _ag.get_session(_old_sid)
_tn.reset_context(_tok)
check("جلسة الوكيل تنتهي بعد TTL فعلاً", _stale is None)
check("نوع جهة غير معروف مرفوض (400)",
      c.post("/api/proposals/generate", data={"title": "x", "client": "y", "entity_type": "nope"}).status_code == 400)

# --- 24.8 محرك Claude: هوية المستأجر في التعليمات + طبقة الأسلوب نفسها ---
from app.style_engine import DEFAULT_BANNED as _DB
_captured = {}
_payload = {"summary": "s", "scope": ["a"], "compliance_matrix": [], "plan": [], "duration_weeks": 4,
            "assumptions": [], "team": [],
            "technical_sections": [
                {"title": "قسم خاص بالمشروع", "body": f"جملة أولى تحوي {_DB[0]} هنا. وجملة ثانية سليمة وطويلة تصف نطاق المشروع بدقة."}],
            "boq": [{"code": "", "name": "بند", "unit": "م2", "qty": 10, "unit_price": 100}]}


class _FakeStream:
    def __init__(self, kw): _captured.update(kw)
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def get_final_message(self):
        blk = _ty.SimpleNamespace(type="text", text=_json.dumps(_payload, ensure_ascii=False))
        return _ty.SimpleNamespace(stop_reason="end_turn", content=[blk])


_fake = _ty.ModuleType("anthropic")
_fake.Anthropic = lambda **k: _ty.SimpleNamespace(messages=_ty.SimpleNamespace(stream=lambda **kw: _FakeStream(kw)))
_real_anthropic = sys.modules.get("anthropic"); sys.modules["anthropic"] = _fake
from app.ai_engine import generate_proposal_ai as _gen_ai
_tok = _tn.set_context(_cid5, "owner", 1, False)
try:
    _ai = _gen_ai("مشروع فحص محرك Claude", "جهة", "government", "نص", [])
finally:
    _tn.reset_context(_tok)
    if _real_anthropic is not None: sys.modules["anthropic"] = _real_anthropic
    else: sys.modules.pop("anthropic", None)
_sys_txt = _captured["system"][0]["text"]
check("تعليمات Claude باسم المستأجر لا «عزوم»", "شركة فحص الوكيلين" in _sys_txt and "عزوم" not in _sys_txt)
check("مخرجات Claude تمر بطبقة الأسلوب (source + style + فئة المشروع)",
      isinstance(_ai.get("style"), dict) and _ai.get("project_kind")
      and all(s.get("source") in ("bank", "new") for s in _ai["technical_sections"]))
check("والعبارات القالبية المحظورة تُنقّى من نص Claude",
      not any(_DB[0] in s["body"] for s in _ai["technical_sections"]))

# --- 24.9 الفوترة والاشتراكات ---
check("قائمة الشركات تعرض السعر الشهري الفعلي",
      all("monthly_price" in x for x in c.get("/api/companies").json()))
check("ترقية شركة لغير مدير المنصة مرفوضة (403)",
      c2.put(f"/api/companies/{_cid2}", json={"plan": "pro"}).status_code == 403)
check("خطة غير معروفة مرفوضة (400)", c.put(f"/api/companies/{_cid2}", json={"plan": "gold"}).status_code == 400)
_r = c.put(f"/api/companies/{_cid2}", json={"plan": "pro"})
check("ترقية شركة تجريبية إلى احترافي تلغي انتهاء التجربة",
      _r.status_code == 200 and _r.json()["plan"] == "pro" and not _r.json().get("trial_ends_at"), _r.text[:120])
check("لا رجوع من مدفوع إلى تجريبي (400)",
      c.put(f"/api/companies/{_cid2}", json={"plan": "trial"}).status_code == 400)
c.put(f"/api/companies/{_cid5}", json={"plan": "basic", "custom_price": 1500})
c.put(f"/api/companies/{_cid4}", json={"plan": "enterprise"})
_i1 = c.post("/api/platform/invoices/issue").json()
_inv = c.get("/api/platform/metrics").json()["invoices"]
check("الفوترة: تصدر لكل شركة مدفوعة مسعّرة (2) وتُبلِّغ بالمؤسسي بلا سعر",
      _i1["issued"] == 2 and len(_i1["unpriced"]) >= 1, str(_i1))
check("أرقام الفواتير فريدة (لا تكرار مع أكثر من شركة)",
      len({i["ref"] for i in _inv}) == len(_inv) >= 2, str([i["ref"] for i in _inv]))
check("الفاتورة بالسعر المتفاوض عليه (1500) لا سعر الخطة",
      any(i["company_id"] == _cid5 and i["amount"] == 1500 for i in _inv))
check("إعادة الإصدار في الشهر نفسه لا تكرر الفواتير", c.post("/api/platform/invoices/issue").json()["issued"] == 0)
_ent = c.post("/api/companies", json={"name": "شركة مؤسسية للفحص " + _suf, "plan": "enterprise"}).json()
_i2 = c.post("/api/platform/invoices/issue").json()
check("مؤسسي بلا سعر متفق عليه لا يُفوتَر بل يُبلَّغ عنه", _i2["issued"] == 0 and _ent["name"] in _i2["unpriced"], str(_i2))
c.put(f"/api/companies/{_ent['id']}", json={"custom_price": 8000})
check("المؤسسي يُفوتَر بعد الاتفاق على سعره", c.post("/api/platform/invoices/issue").json()["issued"] == 1)
_mt = c.get("/api/platform/metrics").json()
check("الإيراد الشهري المتكرر يشمل الأسعار المتفاوض عليها (3900+1500+8000)", _mt["mrr"] == 13400, str(_mt["mrr"]))
check("الفهرس الفريد يمنع فاتورتين لنفس الشركة والفترة", _dbm.issue_monthly_invoices()["issued"] == 0)

# --- 24.10 الأعضاء وجهات الاتصال ---
c.post(f"/api/session/company/{_cid2}")
_r = c.delete(f"/api/members/{me2['user_id']}")
c.post("/api/session/company/1")
check("لا إزالة لآخر مالك للحساب (400)", _r.status_code == 400, _r.text[:100])
check("لا تخفيض لآخر مالك للحساب (400)",
      c2.put(f"/api/members/{me2['user_id']}", json={"role": "admin"}).status_code == 400)
_eu = next(m["id"] for m in c.get("/api/members").json() if m["username"] == "engcheck")
check("بريد غير صالح مرفوض (400)",
      c.post(f"/api/members/{_eu}/contact", json={"email": "not-an-email", "phone": ""}).status_code == 400)
check("جوال غير صالح مرفوض (400)",
      c.post(f"/api/members/{_eu}/contact", json={"email": "", "phone": "12"}).status_code == 400)
_r = c.post(f"/api/members/{_eu}/contact", json={"email": "eng@example.com", "phone": "0501234567"})
check("الجوال السعودي المحلي يُطبَّع إلى E.164", _r.status_code == 200 and _r.json()["phone"] == "+966501234567")
check("الدعوة برقم جوال غير صالح لا تُنشئ حساباً يتيماً",
      c.post("/api/members", json={"username": "orphancheck", "password": "Orph@12345", "role": "viewer",
                                   "phone": "zzz"}).status_code == 400
      and TestClient(app).post("/api/login", json={"username": "orphancheck", "password": "Orph@12345"}).status_code == 401)

# --- 24.11 محدّث الموديل ---
_saved_mu = (_mu.ANTHROPIC_API_KEY, _mu.fetch_available_models, _mu.validate_model)
_mu.ANTHROPIC_API_KEY = "test-key"
_mu.fetch_available_models = lambda: [{"id": "claude-sonnet-9", "created_at": "2030-01-01"},
                                      {"id": "claude-opus-9", "created_at": "2031-01-01"}]
_vc = {"n": 0}
def _val_ok(m): _vc["n"] += 1; return True
def _val_no(m): _vc["n"] += 1; return False
_mu.validate_model = _val_ok
_ups({"model_pinned": "claude-sonnet-5", "active_claude_model": "", "model_rejected": ""}, company_id=1)
_r = _mu.refresh_active_model(force=True)
check("موديل مثبّت يدوياً: لا تجربة ولا تبديل ولا إشعارات",
      _r.get("reason") == "pinned" and _vc["n"] == 0 and not _r.get("switched"), str(_r))
check("لا سقوط صامت لفئة أخرى عند خلوّ الفئة المطلوبة",
      _mu.choose_latest([{"id": "claude-opus-9", "created_at": "2031"}], "sonnet") == "")
check("تثبيت اسم موديل خاطئ مرفوض (صيغة/غير موجود)",
      c.put("/api/platform/model", json={"pinned": "bad model!"}).status_code == 400
      and c.put("/api/platform/model", json={"pinned": "claude-nonexistent-1"}).status_code == 400
      and c.put("/api/platform/model", json={"pinned": "claude-sonnet-9"}).status_code == 200)
c.put("/api/platform/model", json={"pinned": ""})
_ups({"model_pinned": ""}, company_id=1)
from app.auth import create_user as _cu
_p2 = _cu("plat2check", "Plat@12345", "مدير منصة ثانٍ")
with _gdb() as _db:
    _db.execute("UPDATE users SET is_platform_admin = 1 WHERE id = ?", (_p2["id"],))
_dbm.set_membership(_p2["id"], 1, "owner")
_r = _mu.refresh_active_model()
with _gdb() as _db:
    _notified = {x["user_id"] for x in _db.execute(
        "SELECT user_id FROM notifications WHERE kind = 'model_update'")}
check("التبديل التلقائي يُشعر كل مديري المنصة لا حساباً بعينه",
      _r.get("switched") and {me["user_id"], _p2["id"]} <= _notified, f"{_r} {_notified}")
_ups({"active_claude_model": "", "model_rejected": ""}, company_id=1)
_vc["n"] = 0; _mu.validate_model = _val_no
_mu.refresh_active_model(); _mu.refresh_active_model()
check("موديل رُفض في التجربة لا يُعاد اختباره كل دورة", _vc["n"] == 1, str(_vc))
_mu.ANTHROPIC_API_KEY, _mu.fetch_available_models, _mu.validate_model = _saved_mu
_ups({"active_claude_model": "", "model_rejected": "", "model_pinned": ""}, company_id=1)

# --- 24.12 قنوات الإشعارات ---
check("تطبيع الجوال: محلي/دولي/عربي-هندي",
      _nc.normalize_phone("0501234567") == "+966501234567"
      and _nc.normalize_phone("00966 50 123 4567") == "+966501234567"
      and _nc.normalize_phone("٠٥٠١٢٣٤٥٦٧") == "+966501234567")
_used = []
class _FS:
    def __init__(self, *a, **k): _used.append(type(self).__name__)
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def starttls(self, **k): _used.append("starttls")
    def login(self, *a): pass
    def send_message(self, m): _used.append("sent")
class _FSSL(_FS): pass
_real_smtp = (_nc.smtplib.SMTP, _nc.smtplib.SMTP_SSL)
_nc.smtplib.SMTP, _nc.smtplib.SMTP_SSL = _FS, _FSSL
_nc.send_email({"smtp_host": "h", "smtp_port": "465"}, "a@b.co", "s", "b")
_ssl_used = list(_used); _used.clear()
_nc.send_email({"smtp_host": "h", "smtp_port": "587"}, "a@b.co", "s", "b")
_tls_used = list(_used); _used.clear()
_nc.send_email({"smtp_host": "h", "smtp_port": "25", "smtp_security": "none"}, "a@b.co", "s", "b")
_none_used = list(_used)
_nc.smtplib.SMTP, _nc.smtplib.SMTP_SSL = _real_smtp
check("SMTP: المنفذ 465 → SSL مباشر، 587 → STARTTLS، none → بلا تشفير",
      _ssl_used == ["_FSSL", "sent"] and _tls_used == ["_FS", "starttls", "sent"]
      and _none_used == ["_FS", "sent"], f"{_ssl_used} {_tls_used} {_none_used}")
_sent = {}
class _Resp:
    def read(self): return b"{}"
def _fake_urlopen(req, timeout=15):
    _sent["url"], _sent["body"] = req.full_url, _json.loads(req.data.decode()); return _Resp()
_real_urlopen = _nc.urllib.request.urlopen
_nc.urllib.request.urlopen = _fake_urlopen
_nc.send_whatsapp({"whatsapp_token": "t", "whatsapp_phone_id": "123", "whatsapp_template": "alert_tpl"},
                  "+966500000000", "عنوان\nنص")
_tpl = dict(_sent)
_nc.send_whatsapp({"whatsapp_token": "t", "whatsapp_phone_id": "123"}, "+966500000000", "نص حر")
_txt = dict(_sent)
check("واتساب: قالب معتمد حين يُضبط (بلا أسطر جديدة) ونص حر حين لا",
      _tpl["body"]["type"] == "template" and _tpl["body"]["template"]["name"] == "alert_tpl"
      and "\n" not in _tpl["body"]["template"]["components"][0]["parameters"][0]["text"]
      and _txt["body"]["type"] == "text" and "/v21.0/" in _tpl["url"])
def _boom(req, timeout=15):
    raise _nc.urllib.error.HTTPError(req.full_url, 400, "Bad", {}, io.BytesIO(b'{"error":{"message":"Template not approved"}}'))
_nc.urllib.request.urlopen = _boom
_ups({"notify_whatsapp_enabled": "1", "whatsapp_token": "t", "whatsapp_phone_id": "1"}, company_id=1)
_dbm.set_user_contact(me["user_id"], "", "+966500000001")
_nc._dispatch_sync(1, me["user_id"], "عنوان", "نص")
_nc.urllib.request.urlopen = _real_urlopen
check("فشل واتساب يُسجَّل للأدمن بسبب Meta الفعلي (لا ابتلاع صامت)",
      "Template not approved" in _gs(1).get("notify_last_error", ""), _gs(1).get("notify_last_error", ""))
check("...ويظهر للأدمن في الإعدادات ولا يظهر للمشاهد",
      "Template not approved" in c.get("/api/settings").json().get("notify_last_error", "")
      and "notify_last_error" not in c3.get("/api/settings").json())
_ups({"notify_whatsapp_enabled": "0", "whatsapp_token": "", "notify_last_error": ""}, company_id=1)
_dbm.set_user_contact(me["user_id"], "", "")

# --- 24.13 وكيل الجودة ---
_dq = {"technical_sections": [{"title": "t", "source": "new",
        "body": "نستند في هذا القسم إلى المرجع رقم [1] في وثائق المنافسة، ونفصّل الأعمال المطلوبة بدقة كاملة وشمول كبير. " * 2}],
       "boq": [], "financial": {}}
check("المرجع الرقمي [1] ليس placeholder",
      not any(i["kind"] == "placeholder" for i in _rq2(_dq)["issues"]))
_dq["technical_sections"][0]["body"] += " اسم الجهة: [اسم العميل]"
check("بينما [اسم العميل] placeholder فعلاً",
      any(i["kind"] == "placeholder" for i in _rq2(_dq)["issues"]))
_rp = c.post("/api/proposals/generate", data={"title": "عرض بنسب قديمة", "client": "جهة"}).json()
_ups({"profit_pct": "18"}, company_id=1)
_rev = _rq2(c.get(f"/api/proposals/{_rp['id']}").json()["data"])
_ups({"profit_pct": "15"}, company_id=1)
c.delete(f"/api/proposals/{_rp['id']}")
check("تغيير نسبة الربح لاحقاً لا يجعل عرضاً قديماً «غير متسق»",
      not any(i["kind"] == "finance" and i["level"] == "error" for i in _rev["issues"]), str(_rev["issues"])[:200])

# --- 24.14 CSV الأسعار: سطر معطوب وحد الخطة ---
_csv = "code,category,name,unit,unit_price\nCSV-1,x,سليم,م,10\nCSV-2,x,معطوب,م,abc\n"
_r = c2.post("/api/prices/import/csv", files={"file": ("p.csv", _csv.encode("utf-8"), "text/csv")})
check("استيراد CSV: السطر المعطوب يُتخطى ويُبلَّغ عنه (لا 500)",
      _r.status_code == 200 and _r.json()["imported"] == 1 and len(_r.json()["errors"]) == 1, _r.text[:150])
_big = "code,category,name,unit,unit_price\n" + "\n".join(f"OL-{i},x,بند {i},م,1" for i in range(150))
_tn.PLAN_LIMITS["basic"]["price_items"] = 100     # c5 أُلحقت بالأساسي أعلاه — نضبط حده مؤقتاً
_r = c5.post("/api/prices/import/csv", files={"file": ("b.csv", _big.encode("utf-8"), "text/csv")})
_tn.PLAN_LIMITS["basic"]["price_items"] = 500
_n5 = len(c5.get("/api/prices").json())
check("استيراد CSV يحترم حد بنود الخطة",
      _r.status_code == 200 and _n5 <= 100 and _r.json()["skipped_over_plan_limit"] > 0, f"{_n5} {_r.text[:120]}")

# --- 24.15 أول تشغيل: لا كلمة مرور افتراضية معروفة ---
_env = {k: v for k, v in os.environ.items() if k != "AZOOM_ADMIN_PASSWORD"}
_env["AZOOM_DATA_DIR"] = tempfile.mkdtemp(prefix="azoom-firstrun-")
_code = ("from app.database import init_db; from app.auth import init_auth, authenticate; "
         "init_db(); init_auth(); print('WEAK' if authenticate('azoom', 'Azoom@2026') else 'STRONG')")
_p = _sp.run([sys.executable, "-c", _code], cwd=str(_ROOT), env=_env, capture_output=True, text=True, encoding="utf-8")
_pwfile = Path(_env["AZOOM_DATA_DIR"]) / "INITIAL_ADMIN_PASSWORD.txt"
check("أول تشغيل: كلمة مرور عشوائية في ملف مقيَّد لا افتراضية معروفة",
      "STRONG" in _p.stdout and _pwfile.exists() and "password:" in _pwfile.read_text(encoding="utf-8"),
      (_p.stdout + _p.stderr)[-300:])
shutil.rmtree(_env["AZOOM_DATA_DIR"], ignore_errors=True)


# ---------- الخلاصة ----------
passed = sum(1 for _, ok, _ in RESULTS if ok)
failed = [(n, d) for n, ok, d in RESULTS if not ok]
print(f"\n===== النتيجة: {passed}/{len(RESULTS)} =====")
for n, d in failed:
    print(f"FAILED: {n} — {d}")
sys.exit(1 if failed else 0)
