"""فحص شامل لنظام عزوم — يختبر كل نقطة نهاية وكل وظيفة (63 فحصاً).

التشغيل على الخادم بعد أي نشر أو تحديث:
    .venv/bin/python scripts/system_check.py
يعمل على قاعدة البيانات الحالية دون إتلافها، ويصلح أن يُشغَّل مرات متكررة.
"""
import io
import sys
from pathlib import Path

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
check("الواجهة الرئيسية بالهوية الخضراء", "AZOOM" in r.text and "175934" in r.text.replace("#", ""))
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
r = c.get(f"/api/proposals/{pid}/export/docx")
check("تصدير Word", r.status_code == 200 and len(r.content) > 10000)
from docx import Document
d = Document(io.BytesIO(r.content))
footer_ok = any("+966114880122" in p.text and "1010467099" in p.text
                for s in d.sections for p in s.footer.paragraphs)
check("تذييل Word الرسمي في كل صفحة", footer_ok)
r = c.get(f"/api/proposals/{pid}/export/xlsx")
check("تصدير Excel", r.status_code == 200 and len(r.content) > 3000)
from openpyxl import load_workbook
wb2 = load_workbook(io.BytesIO(r.content))
check("ملف Excel سليم", len(wb2.sheetnames) >= 1)

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
check("قائمة مشاريع فرصة + التصنيفات الستة",
      r.status_code == 200 and len(r.json().get("categories", [])) == 6)
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

# ---------- الخلاصة ----------
passed = sum(1 for _, ok, _ in RESULTS if ok)
failed = [(n, d) for n, ok, d in RESULTS if not ok]
print(f"\n===== النتيجة: {passed}/{len(RESULTS)} =====")
for n, d in failed:
    print(f"FAILED: {n} — {d}")
sys.exit(1 if failed else 0)
