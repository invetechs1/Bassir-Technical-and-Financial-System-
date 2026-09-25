"""أدوات الحماية المشتركة: تحديد معدل المحاولات، سقف الرفع، وأمان الكوكيز.

كلها داخل العملية (in-process) — يكفي لنشر بحاوية واحدة كما في الإنتاج؛ عند
التوسع لعدة عمليات يُستبدل مخزن العدّادات بـ Redis دون تغيير الواجهة.
"""
import os
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, UploadFile


class RateLimiter:
    """نافذة منزلقة: `limit` محاولة كل `window` ثانية لكل مفتاح."""

    def __init__(self, limit: int, window: int):
        self.limit, self.window = limit, window
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, q: deque, now: float):
        while q and now - q[0] > self.window:
            q.popleft()

    def blocked(self, key: str) -> int:
        """يعيد عدد الثواني المتبقية للحظر (0 = غير محظور) دون تسجيل محاولة."""
        now = time.time()
        with self._lock:
            q = self._hits[key]
            self._prune(q, now)
            if len(q) >= self.limit:
                return max(1, int(self.window - (now - q[0])))
        return 0

    def hit(self, key: str):
        with self._lock:
            self._hits[key].append(time.time())

    def reset(self, key: str):
        with self._lock:
            self._hits.pop(key, None)

    def clear(self):
        with self._lock:
            self._hits.clear()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


# فشل الدخول: لكل مستخدم ولكل عنوان — يمنع التخمين دون أن يقفل الجميع
LOGIN_USER_LIMITER = RateLimiter(_env_int("LOGIN_MAX_FAILS_USER", 8), 10 * 60)
LOGIN_IP_LIMITER = RateLimiter(_env_int("LOGIN_MAX_FAILS_IP", 40), 10 * 60)
# التسجيل الذاتي المفتوح: لكل عنوان وعالمياً
SIGNUP_IP_LIMITER = RateLimiter(_env_int("SIGNUP_MAX_PER_IP_HOUR", 3), 3600)
SIGNUP_GLOBAL_LIMITER = RateLimiter(_env_int("SIGNUP_MAX_PER_HOUR", 30), 3600)

# بناء العروض/التحليلات لكل شركة بالساعة — كل عملية قد تستدعي الذكاء الاصطناعي (تكلفة)
GENERATE_LIMITER = RateLimiter(_env_int("GENERATE_MAX_PER_HOUR", 60), 3600)

MAX_UPLOAD_BYTES = _env_int("MAX_UPLOAD_MB", 50) * 1024 * 1024


def _from_private_peer(request: Request) -> bool:
    """هل الطرف المتصل مباشرةً وكيل محلي/خاص (loopback أو شبكة Docker/LAN)؟
    عميل من الإنترنت لا يأتي من عنوان خاص، فلا يستطيع انتحال هذا الشرط."""
    import ipaddress
    host = request.client.host if request.client else ""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback


def client_ip(request: Request) -> str:
    """عنوان العميل الحقيقي. X-Forwarded-For لا يُصدَّق إلا من وكيل موثوق: صراحةً
    (TRUSTED_PROXY=1) أو تلقائياً حين يتصل الوكيل من عنوان خاص/محلي (nginx/Docker) —
    وإلا لظهر كل الزوار بعنوان الوكيل نفسه فيُحجب الجميع لفشل واحد، أو لانتحل
    المهاجم عنواناً آخر فتحايل على تحديد المعدل. TRUSTED_PROXY=0 يعطّل الثقة كلياً."""
    setting = os.environ.get("TRUSTED_PROXY", "")
    if setting == "1" or (setting != "0" and _from_private_peer(request)):
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            # آخر عنوان هو الذي أضافه وكيلنا الموثوق؛ ما قبله قد يكون من العميل ومزيّفاً
            return fwd.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def is_https(request: Request) -> bool:
    return (request.url.scheme == "https"
            or request.headers.get("x-forwarded-proto", "").lower() == "https")


def enforce_rate(limiter: RateLimiter, key: str, message: str):
    wait = limiter.blocked(key)
    if wait:
        raise HTTPException(429, f"{message} — أعد المحاولة بعد {max(1, wait // 60)} دقيقة",
                            headers={"Retry-After": str(wait)})


def read_upload(f: UploadFile, max_bytes: int | None = None) -> bytes:
    """قراءة متزامنة لملف مرفوع بسقف حجم — يُستدعى من معالجات `def` (خيط خلفي)
    فلا تُجمّد حلقة الأحداث ولا يمكن إغراق الذاكرة بملف ضخم."""
    cap = max_bytes or MAX_UPLOAD_BYTES
    data = f.file.read(cap + 1)
    if len(data) > cap:
        raise HTTPException(413, f"حجم الملف «{f.filename}» يتجاوز الحد {cap // (1024 * 1024)} ميجابايت")
    return data
