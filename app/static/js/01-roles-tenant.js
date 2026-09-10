/* ---------- الأدوار والشركات ---------- */
const ADMIN_PAGES = ["prices", "library", "repo", "analytics", "proposals"];
const PLATFORM_PAGES = ["companies", "newco", "billing"];
let ME = { role: "owner", is_admin: true, is_platform_admin: false };

async function loadMe() {
  try { ME = await api("/api/me"); } catch { return; }
  $("#roleChip").textContent = ME.role_ar || ME.role;
  $("#tenantName").textContent = ME.company_name || "—";
  $("#tenantMark").textContent = (ME.company_short || ME.company_name || "ع").slice(0, 1);
  $("#tenantPlan").textContent = ME.plan_ar || "";
  applyBrand();
  const showTenants = ME.is_admin || ME.is_platform_admin;
  $("#navgrpPlatform").hidden = !showTenants;
  $("#navTenants").hidden = !showTenants;
  ["navCompanies", "navNewco", "navBilling"].forEach((id) => { $(`#${id}`).hidden = !ME.is_platform_admin; });
  if (!ME.is_admin) {
    ADMIN_PAGES.forEach((pg) => {
      const btn = document.querySelector(`.nav-btn[data-page="${pg}"]`);
      if (btn) { btn.classList.add("locked"); const c = btn.querySelector(".nav-count"); if (c) c.textContent = "🔒"; }
    });
  }
  // مهندس الموقع: وحدة تنفيذ المشاريع فقط
  if (ME.role === "engineer") {
    $$(".nav-btn[data-page]").forEach((b) => { b.hidden = b.dataset.page !== "execution"; });
    $$(".nav-group").forEach((g) => { g.hidden = true; });
  }
}

function applyBrand() {
  // شعار الشركة النشطة — وشركة بلا شعار تعرض حرفها الأول بلونها، لا شعار غيرها
  const img = $("#brandLogoImg"), init = $("#brandInitial");
  if (ME.logo_url) {
    img.src = ME.logo_url;
    img.hidden = false; init.hidden = true;
  } else {
    img.hidden = true;
    init.hidden = false;
    init.textContent = (ME.company_name || "؟").slice(0, 1);
    init.style.background = ME.brand_color || "#175934";
  }
  if (ME.company_id !== 1) {
    $("#brandWordmark").textContent = ME.company_short || ME.company_name || "";
    $("#brandTagline").textContent = (ME.company_name || "") + " — نظام العروض الفنية والمالية";
  }
}

function toggleTenantMenu() {
  const menu = $("#tenantMenu");
  if (menu.hidden) fillTenantMenu();
  menu.hidden = !menu.hidden;
}
document.addEventListener("click", (e) => {
  if (!e.target.closest(".tenant")) $("#tenantMenu").hidden = true;
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && $("#subItemModal").style.display === "flex") closeSubItemModal();
});

async function fillTenantMenu() {
  const companies = await api("/api/me/companies");
  $("#tenantList").innerHTML = companies.map((c) => `
    <button onclick="switchCompany(${c.id})" ${c.id === ME.company_id ? 'style="background:var(--accent-soft)"' : ""}>
      <span class="tenant-mark">${(c.short_name || c.name).slice(0, 1)}</span>
      <span style="font-size:12.5px;font-weight:500">${c.name}</span>
      <span class="plan" style="margin-inline-start:auto">${t("role_" + c.role) || c.role}</span>
    </button>`).join("") || `<p class="muted" style="padding:8px">${t("tenant_none")}</p>`;
}

async function switchCompany(id) {
  if (id === ME.company_id) { $("#tenantMenu").hidden = true; go("dashboard"); return; }
  await api(`/api/session/company/${id}`, { method: "POST" });
  location.reload();
}
