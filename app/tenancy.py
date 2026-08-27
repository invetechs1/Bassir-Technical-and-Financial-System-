"""سياق تعدد الشركات (SaaS) — الشركة الحالية ودور المستخدم لكل طلب.

الشركة تُحل في وسيط المصادقة من كوكي `azoom_company` بعد التحقق من العضوية،
وتُخزَّن في متغير سياق (contextvars) تقرؤه طبقة قاعدة البيانات فتعزل كل
استعلام تلقائياً — مسار واحد للقراءة والكتابة، فلا يُنسى شرط العزل أبداً.

خارج سياق الطلبات (البذور، الأدوات، الترحيل) الافتراضي هو الشركة 1 (عزوم).
"""
from contextvars import ContextVar

DEFAULT_COMPANY_ID = 1

_company_id: ContextVar[int] = ContextVar("company_id", default=DEFAULT_COMPANY_ID)
_role: ContextVar[str] = ContextVar("role", default="owner")
_user_id: ContextVar[int] = ContextVar("user_id", default=0)
_platform_admin: ContextVar[bool] = ContextVar("platform_admin", default=False)

ROLES = ("owner", "admin", "editor", "viewer")
ADMIN_ROLES = {"owner", "admin"}
ROLE_AR = {"owner": "مالك الحساب", "admin": "أدمن", "editor": "مُحرِّر", "viewer": "مُشاهد"}

# حدود الخطط — None = غير محدود
PLAN_LIMITS = {
    "trial":      {"users": 2,    "proposals_month": 5,    "price_items": 100,  "platforms": False},
    "basic":      {"users": 3,    "proposals_month": 20,   "price_items": 500,  "platforms": False},
    "pro":        {"users": 10,   "proposals_month": None, "price_items": None, "platforms": True},
    "enterprise": {"users": None, "proposals_month": None, "price_items": None, "platforms": True},
}
PLAN_AR = {"trial": "تجريبي", "basic": "أساسي", "pro": "احترافي", "enterprise": "مؤسسي"}


def cid() -> int:
    return _company_id.get()


def role() -> str:
    return _role.get()


def user_id() -> int:
    return _user_id.get()


def is_admin() -> bool:
    return _role.get() in ADMIN_ROLES


def is_platform_admin() -> bool:
    return _platform_admin.get()


def set_context(company_id: int, user_role: str, uid: int = 0, platform_admin: bool = False):
    """يعيد رموز الاستعادة ليردّها الوسيط بعد انتهاء الطلب."""
    return (
        _company_id.set(int(company_id)),
        _role.set(user_role),
        _user_id.set(uid),
        _platform_admin.set(platform_admin),
    )


def reset_context(tokens):
    _company_id.reset(tokens[0])
    _role.reset(tokens[1])
    _user_id.reset(tokens[2])
    _platform_admin.reset(tokens[3])
