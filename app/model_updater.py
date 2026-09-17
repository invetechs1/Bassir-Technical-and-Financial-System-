"""التحديث التلقائي لموديل Claude — بلا تدخل بشري.

يفحص واجهة Models API الرسمية من Anthropic دورياً (كل ٦ ساعات وعند الإقلاع):
إن نزل موديل أحدث من الفئة المفضلة (sonnet افتراضياً) يجرّبه بطلب فعلي صغير
أولاً — فإن نجح اعتمده وأشعر مدير المنصة، وإن فشل بقي على الموديل الحالي.
لا يمكن أن يتعطل التوليد بسبب التحديث: الاختيار الجديد لا يُعتمد إلا بعد
نجاح تجربة حقيقية عليه.

الأسبقية: تثبيت يدوي من مدير المنصة > المختار تلقائياً > قيمة CLAUDE_MODEL.
كل تبديل يُسجَّل في سجل التحديثات ويصل إشعاراً داخلياً (وبريد/واتساب إن فُعّلا).
"""
import json
import threading
import urllib.request

from .config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from .database import get_settings, log_audit, now_iso, update_settings

MODELS_URL = "https://api.anthropic.com/v1/models?limit=100"
API_VERSION = "2023-06-01"
CHECK_EVERY_HOURS = 6
_checker_started = False

# الفئات المدعومة للاختيار التلقائي — sonnet التوازن الأمثل للعروض العربية الطويلة
TIERS = ("sonnet", "opus", "haiku")
DEFAULT_TIER = "sonnet"


def _cfg() -> dict:
    """إعدادات المحرك تُخزَّن عالمياً في إعدادات الشركة 1 (قرار منصة لا مستأجر)."""
    return get_settings(company_id=1)


def fetch_available_models() -> list[dict]:
    """قائمة الموديلات المتاحة من منصة Anthropic — [{id, created_at, display_name}]."""
    if not ANTHROPIC_API_KEY:
        return []
    req = urllib.request.Request(MODELS_URL, headers={
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": API_VERSION,
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        payload = json.loads(r.read().decode())
    return [{"id": m.get("id", ""), "created_at": m.get("created_at", ""),
             "display_name": m.get("display_name", "")}
            for m in payload.get("data", []) if m.get("id")]


def choose_latest(models: list[dict], tier: str = DEFAULT_TIER) -> str:
    """أحدث موديل من الفئة المطلوبة (بتاريخ الإصدار) — وإن خلت الفئة فالأحدث مطلقاً."""
    usable = [m for m in models if m["id"].startswith("claude")]
    pool = [m for m in usable if tier and tier in m["id"]] or usable
    if not pool:
        return ""
    return max(pool, key=lambda m: (m.get("created_at") or "", m["id"]))["id"]


def validate_model(model_id: str) -> bool:
    """تجربة حقيقية صغيرة على الموديل قبل اعتماده — فشلها يعني إبقاء الحالي."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        client.messages.create(model=model_id, max_tokens=1,
                               messages=[{"role": "user", "content": "ping"}])
        return True
    except Exception:
        return False


def get_active_model() -> str:
    """الموديل الفعلي للتوليد: المثبت يدوياً ثم المختار تلقائياً ثم الافتراضي."""
    cfg = _cfg()
    pinned = (cfg.get("model_pinned") or "").strip()
    if pinned:
        return pinned
    if cfg.get("auto_model_update", "1") == "1":
        auto = (cfg.get("active_claude_model") or "").strip()
        if auto:
            return auto
    return CLAUDE_MODEL


def _notify_platform_admin(title: str, body: str):
    """إشعار داخلي لمدير المنصة (حساب azoom) — لا يُسقط التحديث إن فشل."""
    try:
        from .auth import get_user
        from .execution import notify
        from .tenancy import set_context, reset_context
        user = get_user("azoom")
        if not user:
            return
        tokens = set_context(1, "owner", user["id"], True)
        try:
            notify(user["id"], title, body, kind="model_update")
        finally:
            reset_context(tokens)
    except Exception:
        pass


def refresh_active_model(force: bool = False) -> dict:
    """الفحص والتبديل التلقائي — يُستدعى دورياً وعند الإقلاع وعند الطلب اليدوي.

    يعيد وصفاً كاملاً لما حدث (لا يرمي استثناءً أبداً — التوليد لا يتأثر)."""
    if not ANTHROPIC_API_KEY:
        return {"ok": False, "reason": "no_api_key",
                "detail": "لا مفتاح ANTHROPIC_API_KEY في بيئة الخادم — التحديث التلقائي متوقف."}
    cfg = _cfg()
    if cfg.get("auto_model_update", "1") != "1" and not force:
        return {"ok": False, "reason": "disabled", "detail": "التحديث التلقائي معطل من مدير المنصة."}
    try:
        models = fetch_available_models()
    except Exception as exc:
        return {"ok": False, "reason": "fetch_failed", "detail": f"تعذر جلب قائمة الموديلات: {exc}"}
    if not models:
        return {"ok": False, "reason": "empty", "detail": "المنصة لم تُرجع أي موديلات."}
    tier = cfg.get("model_tier", DEFAULT_TIER)
    latest = choose_latest(models, tier)
    current = get_active_model()
    update_settings({"model_checked_at": now_iso()}, company_id=1)
    if not latest or latest == current:
        return {"ok": True, "switched": False, "model": current,
                "detail": "أنت على أحدث موديل متاح من الفئة المختارة."}
    if not validate_model(latest):
        return {"ok": False, "reason": "validation_failed", "model": current,
                "detail": f"الموديل الأحدث {latest} لم يجتز تجربة التحقق — بقينا على {current}."}
    # الاعتماد + السجل + الإشعار
    log = []
    try:
        log = json.loads(cfg.get("model_update_log") or "[]")
    except json.JSONDecodeError:
        pass
    log.insert(0, {"from": current, "to": latest, "at": now_iso()})
    update_settings({"active_claude_model": latest,
                     "model_update_log": json.dumps(log[:20], ensure_ascii=False)},
                    company_id=1)
    log_audit("claude_model", latest, "auto_update", f"{current} → {latest}")
    _notify_platform_admin(
        "تحدّث موديل الذكاء الاصطناعي تلقائياً",
        f"نزل إصدار أحدث من منصة Claude فجرّبه النظام بنجاح واعتمده تلقائياً: "
        f"{current} ← {latest}. لا يلزمك أي إجراء.")
    return {"ok": True, "switched": True, "model": latest, "previous": current}


def model_status() -> dict:
    """حالة محرك الذكاء لمدير المنصة."""
    cfg = _cfg()
    log = []
    try:
        log = json.loads(cfg.get("model_update_log") or "[]")
    except json.JSONDecodeError:
        pass
    return {
        "active": get_active_model(),
        "pinned": (cfg.get("model_pinned") or "").strip(),
        "auto_update": cfg.get("auto_model_update", "1") == "1",
        "tier": cfg.get("model_tier", DEFAULT_TIER),
        "checked_at": cfg.get("model_checked_at", ""),
        "api_key_present": bool(ANTHROPIC_API_KEY),
        "default_model": CLAUDE_MODEL,
        "log": log[:10],
    }


def start_background_checker():
    """فاحص دوري كل ٦ ساعات في خيط خلفي — يبدأ مرة واحدة عند إقلاع الخادم."""
    global _checker_started
    if _checker_started or not ANTHROPIC_API_KEY:
        return
    _checker_started = True

    def _loop():
        import time
        while True:
            try:
                refresh_active_model()
            except Exception:
                pass
            time.sleep(CHECK_EVERY_HOURS * 3600)

    threading.Thread(target=_loop, daemon=True).start()
