# تعديلات `app/static/index.html`

كل ما يلي **ماركب فقط**. لا يُحذف أي عنصر له معالج في `app.js`، ولا يتغير أي `id` أو `data-i18n` قائم. أي `id` مذكور بصيغة جديدة يحتاج سطراً في `app.js` — مُشار إليه صراحة.

---

## ١. الخطوط في `<head>`

```html
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Kufi+Arabic:wght@400;500;600;700&family=IBM+Plex+Sans+Arabic:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/styles.css">
```

---

## ٢. كتلة الهوية `.brand`

الشعار الحالي SVG مرسوم داخل الماركب. استبدله بالشعار الرسمي، وأصلح انقلاب «United Co.»:

```html
<div class="brand">
  <div class="logo" title="AZOOM United Co.">
    <img src="/static/img/azoom-mark.png" alt="AZOOM">
  </div>
  <div>
    <h1>AZOOM</h1>
    <p data-i18n="brand_tagline"><span dir="ltr">United Co.</span> — نظام العروض الفنية والمالية</p>
  </div>
  <button class="lang-btn" id="langToggle" onclick="toggleLang()">EN</button>
</div>
```

انسخ `assets/azoom-mark-sq.png` من هذه الحزمة إلى `app/static/img/azoom-mark.png`.

`.brand` صار `display:flex` أفقياً، فالعناصر الثلاثة تتوزع تلقائياً بلا تعديل إضافي.

---

## ٣. تجميع القائمة الجانبية

نفس الأزرار ونفس `data-page` — أُضيفت عناوين مجموعات وعدّادات فقط:

```html
<div class="nav-group">العمل اليومي</div>
<button class="nav-btn active" data-page="dashboard" data-i18n="nav_dashboard">لوحة التحكم</button>
<button class="nav-btn" data-page="new" data-i18n="nav_new">عرض جديد</button>
<button class="nav-btn" data-page="proposals" data-i18n="nav_proposals">أرشيف العروض<span class="nav-count" id="cntProposals">—</span></button>

<div class="nav-group">قواعد المعرفة</div>
<button class="nav-btn" data-page="prices" data-i18n="nav_prices">قاعدة الأسعار<span class="nav-count" id="cntPrices">—</span></button>
<button class="nav-btn" data-page="library" data-i18n="nav_library">المكتبة الفنية<span class="nav-count" id="cntLibrary">—</span></button>
<button class="nav-btn" data-page="repo" data-i18n="nav_repo">المستودع المعرفي<span class="nav-count" id="cntRepo">—</span></button>

<div class="nav-group">الفرص</div>
<button class="nav-btn" data-page="etimad" data-i18n="nav_etimad">منافسات اعتماد<span class="nav-count" id="cntEtimad">—</span></button>
<button class="nav-btn" data-page="forsah" data-i18n="nav_forsah">مشاريع منصة فرصة<span class="nav-count" id="cntForsah">—</span></button>

<div class="nav-group">الشركة</div>
<button class="nav-btn" data-page="docs" data-i18n="nav_docs">وثائق الشركة<span class="nav-count" id="cntDocs">—</span></button>
<button class="nav-btn" data-page="analytics" data-i18n="nav_analytics">التحليلات</button>
<button class="nav-btn" data-page="settings" data-i18n="nav_settings">الإعدادات</button>

<div class="nav-group">المنصة</div>
<button class="nav-btn" data-page="tenants">الشركات والمستخدمون</button>

<button class="nav-btn" onclick="logout()" style="margin-top:auto" data-i18n="nav_logout">تسجيل الخروج</button>
<div class="engine-badge" id="engineBadge">…</div>
```

**تنبيه i18n:** أُزيلت الإيموجي من النصوص. حدّث القيم المقابلة في `app/static/i18n.js` وإلا أعادها `applyLang()` عند تبديل اللغة. عناوين المجموعات تحتاج مفاتيح جديدة (`navgrp_daily`, `navgrp_knowledge`, `navgrp_opportunities`, `navgrp_company`, `navgrp_platform`).

**في `app.js`:** بعد `loadStats()` املأ العدّادات:

```js
const setCount = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v ?? '—'; };
setCount('cntProposals', stats.proposals_total);
setCount('cntPrices', stats.prices_total);
// …
```

النقطة الملونة يمينَ كل زر تأتي من `::before` في CSS — لا ماركب لها.

---

## ٤. الشريط العلوي (جديد)

يوضع كأول عنصر داخل `<main class="main">`، خارج كل `<section class="page">`. لا يقص القائمة المنسدلة لأن `.topbar` بلا `overflow:hidden` — لا تُضفه.

```html
<div class="topbar">
  <div class="title"><h2 id="pageTitle">لوحة التحكم</h2></div>
  <div class="sep"></div>

  <div class="tenant">
    <button class="tenant-btn" id="tenantBtn" onclick="toggleTenantMenu()">
      <span class="tenant-mark" id="tenantMark">ع</span>
      <span class="name" id="tenantName">شركة عزوم المتحدة</span>
      <span class="plan" id="tenantPlan">مؤسسي</span>
      <span style="font-size:8px;color:#8B9A90">▼</span>
    </button>
    <div class="tenant-menu" id="tenantMenu" hidden>
      <h6>الشركات المسجّلة في المنصة</h6>
      <div id="tenantList"></div>
      <hr>
      <button onclick="openCompanyModal()">
        <span class="tenant-mark" style="background:transparent;border:1px dashed #A9D3B9;color:#2E9E5B">+</span>
        <span style="font-size:12.5px;font-weight:500;color:#175934">إضافة شركة جديدة</span>
      </button>
      <button onclick="go('tenants')">
        <span class="tenant-mark" style="background:#F2F6F3;color:#6B7A70">⚙</span>
        <span style="font-size:12.5px;color:#4A5B51">إدارة الشركات والمستخدمين</span>
      </button>
    </div>
  </div>

  <div class="spacer"></div>
  <span class="tag admin" id="roleChip">أدمن</span>
  <div class="search"><input type="text" id="globalSearch" placeholder="مشروع، بند سعر، منافسة…"></div>
  <button class="btn" onclick="go('new')">+ إنشاء عرض جديد</button>
</div>
```

في `app.js`:

```js
function toggleTenantMenu() {
  document.getElementById('tenantMenu').toggleAttribute('hidden');
}
document.addEventListener('click', e => {                 // إغلاق عند النقر خارجها
  if (!e.target.closest('.tenant')) document.getElementById('tenantMenu').setAttribute('hidden', '');
});
// داخل go(page): حدّث عنوان الشريط العلوي
document.getElementById('pageTitle').textContent =
  document.querySelector(`.nav-btn[data-page="${page}"]`)?.textContent.replace(/\d+$/, '').trim() || '';
```

`.main` صار عمود محتوى: اجعل `<main class="main">` بلا `padding` علوي إن أضفت الشريط داخله، أو لُفّ الأقسام في `<div class="main-scroll">`. الأبسط: أبقِ `.main` كما هو — الشريط سيظهر أعلى المحتوى بحشوة الصفحة.

---

## ٥. كلاسات خلايا الجداول

`app.js` يبني الصفوف بـ `innerHTML`. أضف كلاسات الخلايا عند التوليد — هذا ما يعطي الجداول محاذاتها الصحيحة ويمنع كسر العربية:

| نوع الخلية | الكلاس | مثال |
| --- | --- | --- |
| كود / رقم عرض | `code` | `<td class="code">PR-2026-041</td>` |
| مبلغ أو كمية أو نسبة | `num` | `<td class="num">1,240.00</td>` |
| تاريخ عربي («12 أغسطس»، «3 أيام») | `date` | `<td class="date">12 أغسطس</td>` — **بلا `code`/`num`** |
| نص طويل قد يفيض | `ellipsis` | `<td class="ellipsis">إنشاء وتجهيز مبنى إداري</td>` |
| رأس عمود رقمي | `num` على `<th>` | `<th class="num">السعر (ر.س)</th>` |

شريط الملاءمة في جدولي اعتماد وفرصة:

```html
<td><span class="fit"><i style="width:88%"></i></span> <span class="num-cell">88%</span></td>
<!-- أقل من 70%: <span class="fit low"> -->
```

---

## ٦. مناطق رفع الملفات

`.dropzone .big` كان يحمل إيموجي 📁 / 🗄️. صار سطر أنواع الملفات:

```html
<div class="dropzone" id="dropzone">
  <div class="big">PDF · DOCX · XLSX · TXT</div>
  <span data-i18n="dropzone_text">اسحب الملفات هنا أو اضغط للاختيار</span>
  <input type="file" id="fileInput" multiple hidden accept=".pdf,.docx,.xlsx,.xlsm,.txt,.md,.csv">
</div>
```

رقائق الملفات المرفوعة: أضف `<span class="size">4.8 MB</span>` داخل `.file-chip` عند البناء.

---

## ٧. تنبيه الوثائق في لوحة التحكم

`#docsAlert` يُملأ من `app.js`. الشكل الجديد:

```html
<div class="alert">
  وثيقتان تنتهي صلاحيتهما خلال 30 يوماً: شهادة الزكاة والدخل، رخصة البلدية
  <button class="btn ghost sm" onclick="go('docs')">عرض الوثائق</button>
</div>
```

---

## ٨. حالة التوليد

`.spinner` صار شريط تقدم أفقياً بدل الدائرة الدوارة (`.dot` هو الشريط). الماركب لا يتغير — نفس `<div class="spinner" id="genSpinner"><div class="dot"></div>…</div>`.

---

## ٩. الملخص المالي

```html
<div class="fin-summary">
  <div class="fin-row"><span>إجمالي بنود جدول الكميات</span><span class="v">5,645,500</span></div>
  <!-- … -->
  <div class="fin-row total"><span>الإجمالي بعد الضريبة</span><span class="v">8,742,150</span></div>
</div>
```

---

## ١٠. المخطط الزمني

```html
<div class="gantt-row">
  <span class="gantt-label">الأعمال المدنية والإنشائية</span>
  <span class="gantt-track"><span class="gantt-bar" style="inset-inline-start:10%;width:40%"></span></span>
  <span class="gantt-dur">20 أسبوعاً</span>
</div>
```

**مهم:** استخدم `inset-inline-start` لا `left` — الصفحة RTL، و `left` يقلب اتجاه المخطط.
