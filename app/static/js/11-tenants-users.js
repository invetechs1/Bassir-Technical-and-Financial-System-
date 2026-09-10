/* ---------- الشركات والمستخدمون ---------- */
async function loadTenants() {
  const members = await api("/api/members");
  const canManage = ME.role === "owner" || ME.is_platform_admin;
  $("#membersTable tbody").innerHTML = members.map((m) => `
    <tr>
      <td class="code">${m.username}</td>
      <td>${m.display_name || "—"}</td>
      <td>${canManage && m.id !== ME.user_id ? `
        <select onchange="changeRole(${m.id}, this.value)" style="padding:4px 8px;font-size:12px">
          ${["viewer", "engineer", "editor", "admin", "owner"].map((r) => `<option value="${r}" ${r === m.role ? "selected" : ""}>${t("role_" + r)}</option>`).join("")}
        </select>` : `<span class="tag ${m.role === "owner" || m.role === "admin" ? "admin" : "est"}">${t("role_" + m.role) || m.role}</span>`}</td>
      <td>${ME.is_admin ? `
        <input type="text" value="${escH(m.email)}" placeholder="email" style="width:150px;font-size:11.5px;margin-bottom:2px" onchange="saveMemberContact(${m.id}, this, 'email')"><br>
        <input type="text" value="${escH(m.phone)}" placeholder="9665xxxxxxxx" style="width:150px;font-size:11.5px" onchange="saveMemberContact(${m.id}, this, 'phone')">`
        : `<span class="muted" style="font-size:11.5px">${escH(m.email) || "—"}<br>${escH(m.phone) || ""}</span>`}</td>
      <td class="num-cell muted">${(m.last_login_at || "").slice(0, 10) || "—"}</td>
      <td>${canManage && m.id !== ME.user_id ? `<button class="btn sm danger" onclick="removeMember(${m.id})">${t("member_remove")}</button>` : ""}</td>
    </tr>`).join("");
  $("#membersTitle").textContent = `${t("members_title_for")} ${ME.company_name || ""}`;

  $("#btnGoNewco").hidden = !ME.is_platform_admin;
  $("#platformOverviewPanel").hidden = !ME.is_platform_admin;
  $("#plansOverviewPanel").hidden = !ME.is_platform_admin;
  if (!ME.is_platform_admin) return;

  const companies = await api("/api/companies");
  const totalProposals = companies.reduce((s, c) => s + c.usage.proposals_total, 0);
  const mt = await api("/api/platform/metrics");
  $("#platformOverviewStats").innerHTML = `
    <div class="card"><div class="num">${totalProposals}</div><div class="lbl">${t("mt_all_proposals")}</div></div>
    <div class="card gold"><div class="num">${fmt(mt.mrr).replace(/[.٫]00$/, "")}</div><div class="lbl">${t("mt_mrr")}</div></div>
    <div class="card"><div class="num">${mt.active_users_30d}</div><div class="lbl">${t("mt_active_users")}</div></div>
    <div class="card"><div class="num">${mt.companies_total}</div><div class="lbl">${t("mt_companies")} <span class="muted">(${mt.paid_count} ${t("mt_paid_label")})</span></div></div>`;
  $("#companiesTableOverview tbody").innerHTML = companies.map((c) => `
    <tr>
      <td><b>${c.name}</b>${c.id === ME.company_id ? ` <span class="tag src">${t("company_current")}</span>` : ""}</td>
      <td><span class="tag est">${t("plan_" + c.plan) || c.plan}</span></td>
      <td>${c.sector || "—"}</td>
      <td class="num-cell">${c.usage.users}</td>
      <td class="num-cell">${c.usage.proposals_total}</td>
      <td class="num-cell">${c.usage.price_items}</td>
      <td>${companyStatusTag(c.effective_status)}</td>
      <td><button class="btn sm ghost" onclick="switchCompany(${c.id})">${t("company_open")}</button></td>
    </tr>`).join("");

  loadPlanCards();
}

async function loadPlanCards() {
  const plans = await api("/api/plans");
  $("#plansCards").innerHTML = plans.map((p) => `
    <div class="card">
      <div class="lbl">${p.name_ar}</div>
      <div class="num">${p.price == null ? t("plan_custom") : (p.price ? fmt(p.price).replace(/[.٫]00$/, "") + " " + t("currency") : t("plan_free"))}</div>
      ${p.price ? `<div class="note">${t("plan_per_month")}</div>` : ""}
      <div class="note mt">${p.users == null ? t("plan_unlimited") : p.users} ${t("mt_paid_of_users")} ·
        ${p.proposals_month == null ? t("plan_unlimited") : p.proposals_month} ${t("plan_proposals_mo")}</div>
    </div>`).join("");
}


/* الاشتراكات والفوترة — الإيراد المتكرر وفواتير كل شركة */
async function loadBillingPage() {
  const mt = await api("/api/platform/metrics");
  const avgRevenue = mt.paid_count ? mt.mrr / mt.paid_count : 0;
  const trialsSoon = mt.trials_ending || [];
  const nextTrial = trialsSoon[0];
  $("#platformMetrics").innerHTML = `
    <div class="card"><div class="num">${trialsSoon.length}</div><div class="lbl">${t("mt_trials_ending")}</div>
      ${nextTrial ? `<div class="note">${nextTrial.name} — ${t("mt_days_left_pre")} ${nextTrial.days_left} ${t("mt_days_left_post")}</div>` : ""}</div>
    <div class="card"><div class="num">${fmt(avgRevenue).replace(/[.٫]00$/, "")}</div><div class="lbl">${t("mt_avg_revenue")}</div></div>
    <div class="card"><div class="num">${mt.paid_count}</div><div class="lbl">${t("mt_paid")} <span class="muted">${t("mt_paid_of")} ${mt.companies_total}</span></div></div>
    <div class="card gold"><div class="num">${fmt(mt.mrr).replace(/[.٫]00$/, "")}</div><div class="lbl">${t("mt_mrr")}</div>
      ${mt.mrr_delta ? `<div class="note">${mt.mrr_delta > 0 ? "+" : ""}${fmt(mt.mrr_delta).replace(/[.٫]00$/, "")} ${t("mt_this_month")}</div>` : ""}</div>`;

  const companies = await api("/api/companies");
  const usageBar = (used, limit) => {
    const pct = limit ? Math.min(100, (used / limit) * 100) : 8;
    const cls = !limit ? "" : pct >= 100 ? "danger" : pct >= 80 ? "warn" : "";
    return `<span class="fit ${cls}"><i style="width:${pct}%"></i></span> <span class="num-cell">${used} / ${limit == null ? "∞" : limit}</span>`;
  };
  $("#planUsageTable tbody").innerHTML = companies.map((c) => `
    <tr>
      <td><b>${c.name}</b></td>
      <td><span class="tag est">${t("plan_" + c.plan) || c.plan}</span></td>
      <td>${usageBar(c.usage.users, c.limits.users)}</td>
      <td>${usageBar(c.usage.proposals_month, c.limits.proposals_month)}</td>
      <td>${usageBar(c.usage.price_items, c.limits.price_items)}</td>
    </tr>`).join("");

  $("#invoicesTable tbody").innerHTML = (mt.invoices || []).map((i) => `
    <tr>
      <td class="code">${i.ref}</td>
      <td>${i.company_name}</td>
      <td><span class="tag est">${t("plan_" + i.plan) || i.plan}</span></td>
      <td class="num-cell">${fmt(i.amount)}</td>
      <td class="date">${i.period_start} → ${i.period_end}</td>
      <td class="date">${i.due_at}</td>
      <td><span class="tag ${i.status === "paid" ? "submitted" : "draft"}">${t("invoice_status_" + i.status) || i.status}</span></td>
    </tr>`).join("") || `<tr><td colspan="7" class="muted">${t("invoices_none")}</td></tr>`;

  loadPlanCompareTable();
}

async function loadPlanCompareTable() {
  const plans = await api("/api/plans");
  const rows = [
    { key: "users", label: t("cmp_users") },
    { key: "proposals_month", label: t("cmp_proposals") },
    { key: "price_items", label: t("cmp_price_items") },
    { key: "integrations", label: t("cmp_integrations") },
    { key: "style_engine", label: t("cmp_style_engine") },
    { key: "audit_days", label: t("cmp_audit") },
    { key: "support", label: t("cmp_support") },
    { key: "price", label: t("cmp_price") },
  ];
  const SUPPORT_BY_PLAN = { trial: t("support_email"), basic: t("support_email"),
                           pro: t("support_email_phone"), enterprise: t("support_dedicated") };
  const fmtCell = (r, p) => {
    if (r.key === "support") return SUPPORT_BY_PLAN[p.id] || "—";
    if (r.key === "price") {
      if (p.price == null) return t("plan_custom");
      return p.price ? `${fmt(p.price).replace(/[.٫]00$/, "")} ${t("currency")}` : t("plan_free");
    }
    if (r.key === "audit_days") {
      const v = p.audit_days;
      if (v == null) return t("plan_unlimited");
      if (!v) return `<span class="tag draft">${t("no")}</span>`;
      return `${v} ${t("cmp_days")}`;
    }
    const v = p[r.key];
    if (typeof v === "boolean") return v ? `<span class="tag submitted">${t("yes")}</span>` : `<span class="tag draft">${t("no")}</span>`;
    if (v == null) return t("plan_unlimited");
    return v;
  };
  $("#planCompareHead").innerHTML = `<th>${t("cmp_feature")}</th>` + plans.map((p) => `<th>${p.name_ar}</th>`).join("");
  $("#planCompareBody").innerHTML = rows.map((r) => `
    <tr><td>${r.label}</td>${plans.map((p) => `<td class="num-cell">${fmtCell(r, p)}</td>`).join("")}</tr>`).join("");
}

async function uploadCompanyLogo() {
  const f = $("#logoInput").files[0];
  if (!f) return;
  const form = new FormData();
  form.append("logo", f);
  try {
    await api(`/api/companies/${ME.company_id}/logo`, { method: "POST", body: form });
    toast(t("logo_uploaded"));
    ME.logo_url = `/api/companies/${ME.company_id}/logo?v=${Date.now()}`;
    applyBrand();
  } catch (err) { toast(err.message, true); }
  $("#logoInput").value = "";
}

async function saveMemberContact(uid, input, field) {
  const row = input.closest("td");
  const inputs = row.querySelectorAll("input");
  await api(`/api/members/${uid}/contact`, { method: "POST", json: {
    email: inputs[0].value.trim(), phone: inputs[1].value.trim() } });
  toast(t("msg_saved"));
}

async function inviteMember() {
  const username = $("#invUsername").value.trim();
  if (!username) return toast(t("invite_need_user"), true);
  try {
    await api("/api/members", { method: "POST", json: {
      username, password: $("#invPassword").value, role: $("#invRole").value,
      email: $("#invEmail").value.trim(), phone: $("#invPhone").value.trim() } });
    toast(t("invite_done"));
    $("#invUsername").value = ""; $("#invPassword").value = "";
    $("#invEmail").value = ""; $("#invPhone").value = "";
    loadTenants();
  } catch (err) { toast(err.message, true); }
}

async function changeRole(uid, role) {
  try {
    await api(`/api/members/${uid}`, { method: "PUT", json: { role } });
    toast(t("role_changed"));
  } catch (err) { toast(err.message, true); loadTenants(); }
}

async function removeMember(uid) {
  if (!confirm(t("member_remove_confirm"))) return;
  try {
    await api(`/api/members/${uid}`, { method: "DELETE" });
    loadTenants();
  } catch (err) { toast(err.message, true); }
}

async function issueInvoices() {
  try {
    const r = await api("/api/platform/invoices/issue", { method: "POST" });
    toast(`🧾 ${t("invoices_issued")}: ${r.issued} — ${t("invoices_skipped")}: ${r.skipped}`);
    loadBillingPage();
  } catch (err) { toast(err.message, true); }
}

async function createCompany() {
  const name = $("#ncName").value.trim(), owner = $("#ncOwner").value.trim();
  const logoFile = $("#ncLogo").files[0];
  if (!name || !owner) return toast(t("newco_need_fields"), true);
  if (!logoFile) return toast(t("newco_need_logo"), true);
  try {
    const c = await api("/api/companies", { method: "POST", json: {
      name, plan: $("#ncPlan").value, sector: $("#ncSector").value.trim(),
      cr_no: $("#ncCr").value.trim(), vat_no: $("#ncVat").value.trim(),
      currency: $("#ncCurrency").value, contact_phone: $("#ncPhone").value.trim(),
      owner_username: owner, owner_password: $("#ncOwnerPass").value } });
    const form = new FormData();
    form.append("logo", logoFile);
    try { await api(`/api/companies/${c.id}/logo`, { method: "POST", body: form }); }
    catch { /* الشركة أُنشئت بنجاح؛ الشعار يمكن رفعه لاحقاً إن فشل */ }
    toast(`🏢 ${t("newco_done")} — ${c.name}`);
    ["ncName", "ncOwner", "ncOwnerPass", "ncCr", "ncVat", "ncSector", "ncPhone"].forEach((id) => $(`#${id}`).value = "");
    $("#ncLogo").value = "";
    $("#ncLogoName").textContent = t("newco_logo_hint");
  } catch (err) { toast(err.message, true); }
}
