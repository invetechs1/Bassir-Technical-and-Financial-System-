"""قنوات الإشعارات الخارجية — بريد إلكتروني وواتساب.

الإشعار الداخلي (الجرس) يصل دائماً؛ وهنا نوصله أيضاً لجوال وبريد المستلم إن
فُعّلت القناة من إعدادات الشركة:
- البريد: أي خادم SMTP (كلمة المرور تُخزَّن مشفرة كبقية الأسرار).
- واتساب: واجهة WhatsApp Cloud API الرسمية من Meta — يكفي إدخال رمز الوصول
  ومعرّف رقم الإرسال من إعدادات الشركة، بلا أي تغيير في الكود.

الإرسال يجري في خيط منفصل وبأمان: فشل القناة الخارجية لا يعطّل العملية ولا
يُسقط الإشعار الداخلي أبداً.
"""
import json
import smtplib
import threading
import urllib.request
from email.mime.text import MIMEText
from email.header import Header

from .database import get_db, get_settings

WHATSAPP_API = "https://graph.facebook.com/v20.0/{phone_id}/messages"


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
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = cfg.get("smtp_from") or cfg.get("smtp_user", "")
    msg["To"] = to
    with smtplib.SMTP(host, port, timeout=15) as s:
        if cfg.get("smtp_tls", "1") != "0":
            s.starttls()
        if cfg.get("smtp_user"):
            s.login(cfg["smtp_user"], cfg.get("smtp_pass", ""))
        s.send_message(msg)


def send_whatsapp(cfg: dict, phone: str, text: str):
    token = cfg.get("whatsapp_token", "").strip()
    phone_id = cfg.get("whatsapp_phone_id", "").strip()
    if not token or not phone_id or not phone:
        return
    payload = json.dumps({
        "messaging_product": "whatsapp",
        "to": phone.lstrip("+"),
        "type": "text",
        "text": {"body": text},
    }).encode()
    req = urllib.request.Request(
        WHATSAPP_API.format(phone_id=phone_id), data=payload, method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=15).read()


def _dispatch_sync(company_id: int, uid: int, title: str, body: str):
    cfg = get_settings(company_id)
    contact = _user_contact(uid)
    text = f"{title}\n{body}" if body else title
    if cfg.get("notify_email_enabled") == "1" and contact["email"]:
        try:
            send_email(cfg, contact["email"], f"بصير — {title}", text)
        except Exception:
            pass
    if cfg.get("notify_whatsapp_enabled") == "1" and contact["phone"]:
        try:
            send_whatsapp(cfg, contact["phone"], text)
        except Exception:
            pass


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
