# صلاحيات الأدمن — حصر خمس صفحات

الصفحات التالية للاطلاع والتعديل وإضافة المحتوى **من الأدمن فقط**:

1. قاعدة الأسعار — `prices`
2. المكتبة الفنية — `library`
3. المستودع المعرفي — `repo`
4. التحليلات — `analytics`
5. أرشيف العروض — `proposals`

المتاح لبقية الأدوار: لوحة التحكم، عرض جديد، عارض العرض، منافسات اعتماد، مشاريع فرصة، وثائق الشركة، الإعدادات.

## الأدوار

| الدور | الصفحات الخمس | إعداد عرض جديد | إدارة المستخدمين والاشتراك |
| --- | --- | --- | --- |
| `owner` مالك الحساب | اطلاع وتعديل | نعم | نعم |
| `admin` أدمن | اطلاع وتعديل | نعم | دعوة مستخدمين فقط |
| `editor` مُحرِّر | لا | نعم، دون نشر | لا |
| `viewer` مُشاهد | لا | لا — قراءة وتصدير فقط | لا |

---

## الخادم — هذا هو الحاجز الفعلي

إخفاء الأزرار في الواجهة ليس حماية. كل مسار يخدم هذه الصفحات يُغلَّف بمُزخرِف.

```python
# app/auth.py
from functools import wraps
from flask import g, jsonify

ADMIN_ROLES = {'owner', 'admin'}

def admin_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if getattr(g, 'role', None) not in ADMIN_ROLES:
            return jsonify({'error': 'هذه الصفحة للأدمن فقط'}), 403
        return fn(*a, **kw)
    return wrapper
```

المسارات المطلوب تغليفها في `app/main.py` — القراءة والكتابة معاً، فالمطلوب حجب الاطلاع لا التعديل فقط:

```
/api/prices           GET POST PUT DELETE
/api/prices/export/csv, /api/prices/import/csv
/api/library          GET POST PUT DELETE
/api/repository       GET POST DELETE
/api/repository/market-compare
/api/analytics/*      GET
/api/proposals        GET            ← قائمة الأرشيف
```

**لا تُغلَّف:**

- `GET /api/proposals/<id>` — عارض العرض متاح لمن أعدّه؛ اربطه بمالك العرض أو بدور `editor` فما فوق.
- `POST /api/proposals` — إنشاء عرض جديد متاح للمُحرِّر.
- `/api/stats` للوحة التحكم — لكن **احذف منها مؤشرات التحليلات** (نسبة الفوز، متوسط الهامش، قيمة العروض الفائزة) لغير الأدمن، وإلا سرّبت لوحةُ التحكم محتوى صفحة التحليلات:

```python
@app.get('/api/stats')
@login_required
def stats():
    data = base_stats()
    if g.role not in ADMIN_ROLES:
        for k in ('win_rate', 'avg_margin', 'won_value'):
            data.pop(k, None)
    return data
```

نقطة نهاية صغيرة تخبر الواجهة بالدور:

```python
@app.get('/api/me')
@login_required
def me():
    return {'role': g.role, 'is_admin': g.role in ADMIN_ROLES,
            'company_id': g.company_id}
```

---

## الواجهة

في `app.js` عند الإقلاع:

```js
const ADMIN_PAGES = ['prices', 'library', 'repo', 'analytics', 'proposals'];
let ME = { role: 'viewer', is_admin: false };

async function loadMe() {
  ME = await api('/api/me');
  document.getElementById('roleChip').textContent =
    { owner: 'مالك الحساب', admin: 'أدمن', editor: 'مُحرِّر', viewer: 'مُشاهد' }[ME.role];
  if (!ME.is_admin) {
    ADMIN_PAGES.forEach(p => {
      const btn = document.querySelector(`.nav-btn[data-page="${p}"]`);
      if (btn) { btn.classList.add('locked'); btn.disabled = true;
                 btn.querySelector('.nav-count')?.replaceChildren('🔒'); }
    });
  }
}
```

وفي `go(page)` حاجز إضافي:

```js
function go(page) {
  if (ADMIN_PAGES.includes(page) && !ME.is_admin) return showDenied();
  // … التنقل كالمعتاد
}
```

حالة المنع:

```html
<section class="page" id="page-denied">
  <div class="denied">
    <div class="lock">🔒</div>
    <h3>هذه الصفحة للأدمن فقط</h3>
    <p>صلاحية الاطلاع والتعديل وإضافة المحتوى في قاعدة الأسعار، المكتبة الفنية،
       المستودع المعرفي، التحليلات، وأرشيف العروض محصورة على الأدمن.
       دورك الحالي: <span id="deniedRole">—</span>.</p>
    <p>اطلب من مالك الحساب ترقية صلاحيتك من صفحة «الشركات والمستخدمون».</p>
  </div>
</section>
```

شارة الصفحة الإدارية في رأس كل صفحة من الخمس:

```html
<h2>قاعدة الأسعار <span class="tag admin">صفحة إدارية — للأدمن فقط</span></h2>
```

---

## نقطتان لا تُنسيان

**١. صفحة «عرض جديد» تقرأ من قاعدة الأسعار والمكتبة الفنية.** المُحرِّر يعد عرضاً، فيستهلك بيانات صفحتين محجوبتين عنه — وهذا مقصود: التوليد يقرأها في الخادم ولا يعرض الجداول. لا تُغلِّف الاستدعاءات الداخلية التي يستعملها `proposal_builder.py`؛ غلّف مسارات الويب فقط.

**٢. الأدوار داخل الشركة الواحدة.** المستخدم قد يكون `admin` في شركة و `viewer` في أخرى. `g.role` يُحسب لكل طلب من `memberships` حسب الشركة الحالية في الجلسة (انظر `backend-multitenancy.md`)، ويتغير فور تبديل الشركة — لا تخزّن الدور في الجلسة.
