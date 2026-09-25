"""قنوات الإشعارات الخارجية — بريد إلكتروني وواتساب.

الإشعار الداخلي (الجرس) يصل دائماً؛ وهنا نوصله أيضاً لجوال وبريد المستلم إن
فُعّلت القناة من إعدادات الشركة:
- البريد: أي خادم SMTP (كلمة المرور تُخزَّن مشفرة كبقية الأسرار).
- واتساب: واجهة WhatsApp Cloud API الرسمية من Meta — يكفي إدخال رمز الوصول
  ومعرّف رقم الإرسال من إعدادات الشركة، بلا أي تغيير في الكود.
  قاعدة Meta: الرسالة التي تبدؤها الشركة خارج نافذة الـ24 ساعة تُرفض ما لم تكن
  «قالباً معتمداً» — لذا يدعم الإعداد `whatsapp_template` (قالب بمتغير واحد {{1}}).

الإرسال يجري في خيط منفصل وبأمان: فشل القناة الخارجية لا يعطّل العملية ولا
يُسقط الإشعار الداخلي أبداً.
"""
import json
import re
import smtplib
import ssl
import threading
import urllib.error
import urllib.request
from email.mime.text import MIMEText
from email.header import Header

from .database import get_db, get_settings, now_iso, update_settings

WHATSAPP_API = "https://graph.facebook.com/{version}/{phone_id}/messages"
DEFAULT_WA_VERSION = "v21.0"
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(raw: str) -> str:
    """بريد صالح أو نص فارغ — يرفع ValueError لقيمة غير صالحة."""
    raw = (raw or "").strip()
    if raw and not _EMAIL_RE.match(raw):
        raise ValueError("صيغة البريد الإلكتروني غير صحيحة")
    return raw


def normalize_phone(raw: str) -> str:
    """رقم دولي بالصيغة E.164 (+9665XXXXXXXX) أو نص فارغ.

    يقبل 05XXXXXXXX السعودي (يُحوَّل إلى +9665…) و00966… و+966… مع مسافات أو
    شرطات، ويحوّل الأرقام العربية-الهندية. أي شيء آخر غير صالح → ValueError."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    raw = raw.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    digits = re.sub(r"[\s\-().]", "", raw)
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    if re.fullmatch(r"05\d{8}", digits):
        digits = "+966" + digits[1:]
    elif re.fullmatch(r"[1-9]\d{9,14}", digits):   # E.164 بلا علامة + (مثل 966500000000)
        digits = "+" + digits
    if not re.fullmatch(r"\+[1-9]\d{7,14}", digits):
        raise ValueError("رقم الجوال غير صالح — استخدم الصيغة الدولية مثل +966501234567")
    return digits


def _user_contact(uid: int) -> dict:
    with get_db() as db:
        row = db.execute("SELECT email, phone FROM users WHERE id = ?", (uid,)).fetchone()
    return {"email": (row["email"] or "").strip() if row else "",
            "phone": (row["phone"] or "").strip() if row else ""}


def send_email(cfg: dict, to: str, subject: str, body: str):
    host = cfg.get("smtp_host", "").strip()
    if not host or not to:
        return
    port = int(cfg.get("smtp_port") or 587)
    security = (cfg.get("smtp_security") or "").strip().lower()
    if not security:  # توافق مع الإعداد القديم smtp_tls
        security = "none" if cfg.get("smtp_tls", "1") == "0" else ("ssl" if port == 465 else "starttls")
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = cfg.get("smtp_from") or cfg.get("smtp_user", "")
    msg["To"] = to
    ctx = ssl.create_default_context()
    if security == "ssl":
        server = smtplib.SMTP_SSL(host, port, timeout=15, context=ctx)
    else:
        server = smtplib.SMTP(host, port, timeout=15)
    with server as s:
        if security == "starttls":
            s.starttls(context=ctx)
        if cfg.get("smtp_user"):
            s.login(cfg["smtp_user"], cfg.get("smtp_pass", ""))
        s.send_message(msg)


def send_whatsapp(cfg: dict, phone: str, text: str):
    token = cfg.get("whatsapp_token", "").strip()
    phone_id = cfg.get("whatsapp_phone_id", "").strip()
    if not token or not phone_id or not phone:
        return
    template = (cfg.get("whatsapp_template") or "").strip()
    if template:
        # قالب معتمد من Meta بمتغير نصي واحد {{1}} — الوحيد المسموح خارج نافذة الـ24 ساعة
        clean = " ".join(text.split())[:1000]  # المتغيرات لا تقبل أسطراً جديدة
        message = {"type": "template", "template": {
            "name": template,
            "language": {"code": (cfg.get("whatsapp_template_lang") or "ar").strip()},
            "components": [{"type": "body", "parameters": [{"type": "text", "text": clean}]}],
        }}
    else:
        message = {"type": "text", "text": {"body": text}}
    payload = json.dumps({"messaging_product": "whatsapp", "to": phone.lstrip("+"), **message}).encode()
    url = WHATSAPP_API.format(version=(cfg.get("whatsapp_api_version") or DEFAULT_WA_VERSION).strip(),
                              phone_id=phone_id)
    req = urllib.request.Request(url, data=payload, method="POST",
                                 headers={"Authorization": f"Bearer {token}",
                                          "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=15).read()
    except urllib.error.HTTPError as exc:
        # رسالة Meta الفعلية (مثل: قالب غير معتمد / خارج النافذة) بدل «HTTP 400» المبهمة
        try:
            detail = json.loads(exc.read().decode()).get("error", {}).get("message", "")
        except Exception:
            detail = ""
        raise RuntimeError(f"واتساب رفض الرسالة ({exc.code}): {detail or exc.reason}") from None


def _record_error(company_id: int, channel: str, exc: Exception):
    """آخر خطأ قناة يُحفظ ليراه الأدمن في الإعدادات — بدل الابتلاع الصامت."""
    try:
        update_settings({"notify_last_error": f"{now_iso()} · {channel}: {str(exc)[:300]}"},
                        company_id=company_id)
    except Exception:
        pass


def _dispatch_sync(company_id: int, uid: int, title: str, body: str):
    cfg = get_settings(company_id)
    contact = _user_contact(uid)
    text = f"{title}\n{body}" if body else title
    if cfg.get("notify_email_enabled") == "1" and contact["email"]:
        try:
            send_email(cfg, contact["email"], f"بصير — {title}", text)
        except Exception as exc:
            _record_error(company_id, "email", exc)
    if cfg.get("notify_whatsapp_enabled") == "1" and contact["phone"]:
        try:
            send_whatsapp(cfg, contact["phone"], text)
        except Exception as exc:
            _record_error(company_id, "whatsapp", exc)


def dispatch_external(company_id: int, uid: int, title: str, body: str = ""):
    """إرسال بريد/واتساب في الخلفية — لا يعطّل الطلب الأصلي مهما حدث."""
    try:
        threading.Thread(target=_dispatch_sync, args=(company_id, uid, title, body),
                         daemon=True).start()
    except Exception:
        pass


def test_channels(company_id: int, uid: int) -> dict:
    """اختبار فوري (متزامن) للقناتين — يعيد نتيجة كل قناة للمستخدم الحالي."""
    cfg = get_settings(company_id)
    contact = _user_contact(uid)
    result = {"email": "skipped", "whatsapp": "skipped"}
    if cfg.get("notify_email_enabled") == "1":
        if not contact["email"]:
            result["email"] = "لا بريد مسجّل لحسابك — أضفه من صفحة الأعضاء"
        else:
            try:
                send_email(cfg, contact["email"], "بصير — رسالة اختبار",
                           "قناة البريد تعمل ✅")
                result["email"] = "ok"
            except Exception as exc:
                result["email"] = f"فشل: {exc}"
    if cfg.get("notify_whatsapp_enabled") == "1":
        if not contact["phone"]:
            result["whatsapp"] = "لا جوال مسجّل لحسابك — أضفه من صفحة الأعضاء"
        else:
            try:
                send_whatsapp(cfg, contact["phone"], "بصير — قناة واتساب تعمل ✅")
                result["whatsapp"] = "ok"
            except Exception as exc:
                result["whatsapp"] = f"فشل: {exc}"
    return result
