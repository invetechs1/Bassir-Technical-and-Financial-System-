/* نظام عزوم — منطق الواجهة */
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

const STATUS_KEY = { draft: "st_draft", submitted: "st_submitted", won: "st_won", lost: "st_lost" };
const SECTOR_KEY = { government: "sector_gov", private: "sector_private", pif: "sector_pif", airports: "sector_airports", "": "sector_general" };
const fmt = (n) => Number(n || 0).toLocaleString(getLang() === "ar" ? "ar-SA" : "en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

let currentProposal = null;
let pendingFiles = [];

/* عند تبديل اللغة: أعد رسم أي محتوى ديناميكي معروض حالياً */
function onLangChange() {
  refreshEngineStatus();
  const active = $(".page.active");
  if (active) go(active.id.replace("page-", ""));
  if (currentProposal && active && active.id === "page-viewer") viewProposal(currentProposal);
}

let lastAiEnabled = null;
async function refreshEngineStatus() {
  if (lastAiEnabled === null) {
    try { lastAiEnabled = (await api("/api/status")).ai_enabled; } catch { return; }
  }
  $("#engineBadge").innerHTML = lastAiEnabled ? t("ai_engine_badge_on") : t("ai_engine_badge_off");
  $("#engineHint").textContent = lastAiEnabled ? t("ai_engine_hint_on") : t("ai_engine_hint_off");
}

/* ---------- الأدوار والشركات ---------- */
const ADMIN_PAGES = ["prices", "library", "repo", "analytics", "proposals"];
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
  if (!ME.is_admin) {
    ADMIN_PAGES.forEach((pg) => {
      const btn = document.querySelector(`.nav-btn[data-page="${pg}"]`);
      if (btn) { btn.classList.add("locked"); const c = btn.querySelector(".nav-count"); if (c) c.textContent = "🔒"; }
    });
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
  if (id === ME.company_id) { $("#tenantMenu").hidden = true; return; }
  await api(`/api/session/company/${id}`, { method: "POST" });
  location.reload();
}

/* ---------- تنقّل ---------- */
function go(page) {
  if (ADMIN_PAGES.includes(page) && !ME.is_admin) {
    $$(".page").forEach((p) => p.classList.remove("active"));
    $("#page-denied").classList.add("active");
    $("#deniedRole").textContent = ME.role_ar || ME.role;
    return;
  }
  $$(".page").forEach((p) => p.classList.remove("active"));
  $(`#page-${page}`).classList.add("active");
  $$(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.page === page));
  if (page === "dashboard") loadDashboard();
  if (page === "proposals") loadProposals();
  if (page === "prices") loadPrices();
  if (page === "library") loadLibrary();
  if (page === "etimad") loadEtimad();
  if (page === "forsah") loadForsah();
  if (page === "repo") loadRepo();
  if (page === "docs") loadDocs();
  if (page === "analytics") loadAnalytics();
  if (page === "settings") loadSettings();
  if (page === "tenants") loadTenants();
  const navBtn = document.querySelector(`.nav-btn[data-page="${page}"]`);
  const titleEl = document.getElementById("pageTitle");
  if (navBtn && titleEl) titleEl.textContent = (navBtn.childNodes[0]?.nodeValue || navBtn.textContent).trim();
}

const setCount = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v ?? "—"; };
async function loadNavCounts() {
  try {
    const c = await api("/api/status");
    setCount("cntProposals", c.proposals);
    setCount("cntPrices", c.price_items);
    setCount("cntLibrary", c.library);
    setCount("cntRepo", c.repo_files);
    setCount("cntEtimad", c.etimad);
    setCount("cntForsah", c.forsah);
    setCount("cntDocs", c.docs);
  } catch {}
}
$$(".nav-btn").forEach((b) => b.addEventListener("click", () => go(b.dataset.page)));

function toast(msg, isErr = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast show" + (isErr ? " err" : "");
  setTimeout(() => t.classList.remove("show"), 3500);
}

async function api(url, opts = {}) {
  if (opts.json) {
    opts.body = JSON.stringify(opts.json);
    opts.headers = { "Content-Type": "application/json" };
    delete opts.json;
  }
  const res = await fetch(url, opts);
  if (res.status === 401) { location.href = "/login"; throw new Error(t("msg_session_expired")); }
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return res.json();
}

async function logout() {
  await fetch("/api/logout", { method: "POST" });
  location.href = "/login";
}

async function savePassword() {
  const oldPw = $("#pwOld").value, newPw = $("#pwNew").value;
  if (!oldPw || !newPw) return toast(t("msg_enter_pw_both"), true);
  try {
    await api("/api/password", { method: "POST", json: { old: oldPw, new: newPw } });
    toast(t("msg_pw_changed"));
    $("#pwOld").value = ""; $("#pwNew").value = "";
  } catch (err) { toast(err.message, true); }
}

/* ---------- لوحة التحكم ---------- */
async function loadDashboard() {
  loadNavCounts();
  const [status, proposals] = await Promise.all([api("/api/status"), api("/api/proposals")]);
  lastAiEnabled = status.ai_enabled;
  refreshEngineStatus();

  const won = proposals.filter((p) => p.status === "won").length;
  const submitted = proposals.filter((p) => p.status === "submitted").length;
  $("#statCards").innerHTML = `
    <div class="card gold"><div class="num">${proposals.length}</div><div class="lbl">${t("dash_stat_total")}</div></div>
    <div class="card"><div class="num">${submitted}</div><div class="lbl">${t("dash_stat_submitted")}</div></div>
    <div class="card"><div class="num">${won}</div><div class="lbl">${t("dash_stat_won")}</div></div>
    <div class="card"><div class="num">${status.price_items}</div><div class="lbl">${t("dash_stat_priceitems")}</div></div>`;

  $("#recentTable tbody").innerHTML = proposals.slice(0, 8).map(rowHtml).join("") ||
    `<tr><td colspan="7" class="muted">${t("dash_empty")}</td></tr>`;

  // تنبيهات صلاحية وثائق الشركة
  const docs = await api("/api/docs");
  const expired = docs.filter((d) => d.status === "expired");
  const expiring = docs.filter((d) => d.status === "expiring");
  if (expired.length || expiring.length) {
    const parts = [];
    if (expired.length) parts.push(`⛔ ${t("docs_alert_expired")} ${expired.map((d) => d.name).join("، ")}`);
    if (expiring.length) parts.push(`⚠️ ${t("docs_alert_expiring")} ${expiring.map((d) => `${d.name} (${d.days_left} ${t("docs_alert_days")})`).join("، ")}`);
    $("#docsAlert").innerHTML = `<div class="alert">
      <div><b>${t("docs_alert_title")}</b><br><span style="line-height:1.9">${parts.join("<br>")}</span></div>
      <button class="btn ghost sm" onclick="go('docs')">${t("docs_alert_btn")}</button></div>`;
  } else {
    $("#docsAlert").innerHTML = "";
  }
}

function rowHtml(p) {
  return `<tr>
    <td class="code">${p.ref_no}</td><td class="ellipsis">${p.title}</td><td class="ellipsis">${p.client}</td>
    <td><span class="tag ${p.entity_type === "government" ? "gov" : "private"}">${t(SECTOR_KEY[p.entity_type]) || p.entity_type}</span></td>
    <td><span class="tag ${p.status}">${t(STATUS_KEY[p.status]) || p.status}</span></td>
    <td class="num-cell">${p.created_at.slice(0, 10)}</td>
    <td><button class="btn sm" onclick="openProposal(${p.id})">${t("open_btn")}</button>
        <button class="btn sm danger" onclick="removeProposal(${p.id})">${t("delete_btn")}</button></td>
  </tr>`;
}

/* ---------- عرض جديد ---------- */
const dropzone = $("#dropzone");
const fileInput = $("#fileInput");
dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("drag"); });
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("drag"));
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("drag");
  addFiles(e.dataTransfer.files);
});
fileInput.addEventListener("change", () => addFiles(fileInput.files));

function addFiles(list) {
  for (const f of list) pendingFiles.push(f);
  renderFileList();
}
const fileSize = (b) => b > 1048576 ? (b / 1048576).toFixed(1) + " MB" : Math.ceil(b / 1024) + " KB";
function renderFileList() {
  $("#fileList").innerHTML = pendingFiles.map((f, i) =>
    `<span class="file-chip">${f.name}<span class="size">${fileSize(f.size)}</span><button onclick="pendingFiles.splice(${i},1);renderFileList()">✕</button></span>`
  ).join("");
}

/* اقتراح العروض المشابهة أثناء كتابة اسم المشروع */
let similarTimer;
function suggestSimilar() {
  clearTimeout(similarTimer);
  similarTimer = setTimeout(async () => {
    const q = $("#npTitle").value.trim();
    if (q.length < 5) { $("#similarBox").innerHTML = ""; return; }
    try {
      const matches = await api(`/api/proposals/similar?q=${encodeURIComponent(q)}&sector=${$("#npEntity").value}`);
      if (!matches.length) { $("#similarBox").innerHTML = ""; return; }
      $("#similarBox").innerHTML = `
        <div class="mt" style="border:1px solid var(--accent);border-radius:10px;padding:12px 14px;background:var(--sand)">
          <b style="color:var(--primary)">${t("similar_title")}</b>
          ${matches.map((m) => `
            <div class="row mt" style="justify-content:space-between;font-size:13px">
              <span>${m.title} <span class="muted">(${m.client})</span></span>
              <span class="tag gov">${t("similar_match")} ${m.score}% • ${m.boq_lines} ${t("similar_lines")}</span>
            </div>`).join("")}
        </div>`;
    } catch { /* تجاهل أخطاء الاقتراح */ }
  }, 400);
}

$("#generateBtn").addEventListener("click", async () => {
  const title = $("#npTitle").value.trim();
  const client = $("#npClient").value.trim();
  if (!title || !client) return toast(t("msg_enter_project_client"), true);

  const form = new FormData();
  form.append("title", title);
  form.append("client", client);
  form.append("entity_type", $("#npEntity").value);
  for (const f of pendingFiles) form.append("files", f);

  $("#generateBtn").disabled = true;
  $("#genSpinner").classList.add("on");
  try {
    const proposal = await api("/api/proposals/generate", { method: "POST", body: form });
    pendingFiles = [];
    renderFileList();
    $("#npTitle").value = ""; $("#npClient").value = "";
    if (proposal.data.engine_note) toast(proposal.data.engine_note, true);
    else toast(`${t("msg_proposal_created")} ${proposal.ref_no} ${t("msg_proposal_created_suffix")}`);
    viewProposal(proposal);
  } catch (err) {
    toast(t("msg_gen_failed") + " " + err.message, true);
  } finally {
    $("#generateBtn").disabled = false;
    $("#genSpinner").classList.remove("on");
  }
});

/* ---------- أرشيف العروض ---------- */
async function loadProposals() {
  const proposals = await api("/api/proposals");
  $("#proposalsTable tbody").innerHTML = proposals.map(rowHtml).join("") ||
    `<tr><td colspan="7" class="muted">${t("proposals_empty")}</td></tr>`;
}

async function removeProposal(id) {
  if (!confirm(t("confirm_delete_proposal"))) return;
  await api(`/api/proposals/${id}`, { method: "DELETE" });
  toast(t("msg_proposal_deleted"));
  loadProposals(); loadDashboard();
}

async function openProposal(id) {
  viewProposal(await api(`/api/proposals/${id}`));
}

/* ---------- عارض العرض ---------- */
$$(".tab-btn").forEach((b) => b.addEventListener("click", () => {
  $$(".tab-btn").forEach((x) => x.classList.toggle("active", x === b));
  $$(".tab-pane").forEach((p) => p.classList.toggle("active", p.id === `tab-${b.dataset.tab}`));
}));

function viewProposal(p) {
  currentProposal = p;
  go("viewer");
  $$(".nav-btn").forEach((b) => b.classList.remove("active"));
  $("#vTitle").textContent = `${p.ref_no} — ${p.title}`;
  const engine = p.data.engine === "claude" ? t("engine_claude")
    : p.data.reference ? t("engine_reference") : t("engine_template");
  let meta = `${p.client} • ${t(SECTOR_KEY[p.entity_type]) || p.entity_type} • ${engine}`;
  if (p.data.similar_refs?.length) {
    meta += ` • ${t("built_on_label")} ${p.data.similar_refs.map((r) => `${r.title.slice(0, 30)}… (${r.score}%)`).join("، ")}`;
  }
  $("#vMeta").textContent = meta;
  $("#vStatus").value = p.status;
  renderTech(p.data);
  renderFin(p.data);
  renderPlan(p.data);
}

let showProvenance = false;
function toggleProvenance() { showProvenance = !showProvenance; renderTech(currentProposal.data); }

function renderTech(d) {
  let html = "";
  const st = d.style || {};
  if (st.total_sections) {
    html += `<div class="alert" style="background:#F4FAF6;border-color:#D8E8DD;color:#4A5B51">
      <div><b>${t("style_bar_title")}</b> <span class="num-cell">${st.score}%</span>
      — ${st.bank_sections} ${t("style_bar_of")} ${st.total_sections} ${t("style_bar_frombank")}</div>
      <button class="btn ghost sm" onclick="toggleProvenance()">${showProvenance ? t("style_bar_hide") : t("style_bar_show")}</button>
    </div>`;
  }
  html += (d.technical_sections || []).map((s) =>
    `<div class="panel section-block"><h4>${s.title}
       ${showProvenance && s.source ? (s.source === "bank"
         ? `<span class="tag src" title="${s.source_ref || ""}">${t("prov_bank")}</span>`
         : `<span class="tag est">${t("prov_new")}</span>`) : ""}</h4><p>${s.body}</p></div>`).join("");

  if (d.team?.length) {
    html += `<div class="panel section-block"><h4>${t("team_title")}</h4>
      <div class="t-wrap"><table><thead><tr><th>${t("th_role")}</th><th>${t("th_count")}</th></tr></thead><tbody>
      ${d.team.map((t2) => `<tr><td>${t2.role}</td><td>${t2.count}</td></tr>`).join("")}
      </tbody></table></div></div>`;
  }
  if (d.compliance_matrix?.length) {
    html += `<div class="panel section-block"><h4>${t("compliance_title")}</h4>
      <div class="t-wrap"><table><thead><tr><th>${t("th_requirement")}</th><th>${t("th_compliance")}</th><th>${t("th_reference")}</th></tr></thead><tbody>
      ${d.compliance_matrix.map((m) => `<tr><td>${m.requirement}</td><td>${m.response}</td><td>${m.reference}</td></tr>`).join("")}
      </tbody></table></div></div>`;
  }
  $("#tab-tech").innerHTML = html;
}

function renderFin(d) {
  const boq = d.boq || [];
  const f = d.financial || {};
  const cur = t("currency");
  $("#tab-fin").innerHTML = `
    <div class="panel">
      <h3>${t("boq_title")} <span class="muted">${t("boq_hint")}</span></h3>
      <div class="t-wrap"><table>
        <thead><tr><th>${t("th_num")}</th><th>${t("th_code")}</th><th>${t("th_item")}</th><th>${t("th_unit")}</th><th>${t("th_qty")}</th><th>${t("th_unit_price")}</th><th>${t("th_total")}</th><th>${t("th_source")}</th><th></th></tr></thead>
        <tbody>${boq.map((l, i) => renderBoqRow(l, i)).join("")}</tbody>
      </table></div>
      <div class="mt"><button class="btn ghost sm" onclick="addBoqLine()">${t("add_item_btn")}</button></div>
    </div>
    <div class="panel fin-summary">
      <h3>${t("fin_summary_title")}</h3>
      <div class="fin-row"><span>${t("fin_direct_cost")}</span><span class="num-cell">${fmt(f.direct_cost)} ${cur}</span></div>
      <div class="fin-row"><span>${t("fin_overhead")} (${f.overhead_pct ?? 0}%)</span><span class="num-cell">${fmt(f.overhead)} ${cur}</span></div>
      <div class="fin-row"><span>${t("fin_risk")} (${f.risk_pct ?? 0}%)</span><span class="num-cell">${fmt(f.risk)} ${cur}</span></div>
      <div class="fin-row"><span>${t("fin_profit")} (${f.profit_pct ?? 0}%)</span><span class="num-cell">${fmt(f.profit)} ${cur}</span></div>
      <div class="fin-row"><span>${t("fin_subtotal")}</span><span class="num-cell">${fmt(f.subtotal)} ${cur}</span></div>
      <div class="fin-row"><span>${t("fin_vat")} (${f.vat_rate ?? 15}%)</span><span class="num-cell">${fmt(f.vat)} ${cur}</span></div>
      <div class="fin-row total"><span>${t("fin_grand_total")}</span><span class="v num-cell">${fmt(f.grand_total)} ${cur}</span></div>
      <p class="muted mt">${t("fin_bid_bond")} (${f.bid_bond_pct ?? 1}%): <b>${fmt(f.bid_bond)} ${cur}</b></p>
    </div>
    ${(d.assumptions || []).length ? `<div class="panel"><h3>${t("assumptions_title")}</h3>${d.assumptions.map((a) => `<p class="muted">• ${a}</p>`).join("")}</div>` : ""}`;
}

function renderBoqRow(l, i) {
  const kids = l.children || [];
  const hasKids = kids.length > 0;
  const parentRow = `
    <tr class="${hasKids ? "boq-parent" : ""}">
      <td>${i + 1}</td>
      <td class="num-cell">${l.code || "—"}</td>
      <td>${l.name}</td>
      <td>${l.unit}</td>
      <td style="width:90px"><input type="number" value="${l.qty}" step="0.01" onchange="editBoq(${i},'qty',this.value)"></td>
      <td style="width:120px">${hasKids
        ? `<input type="number" value="${l.unit_price}" disabled title="${t("boq_computed_hint")}">`
        : `<input type="number" value="${l.unit_price}" step="0.01" onchange="editBoq(${i},'unit_price',this.value)">`}</td>
      <td class="num-cell">${fmt(l.total)}</td>
      <td><span class="tag ${l.source === "قاعدة الأسعار" ? "src" : "est"}">${boqSourceLabel(l.source)}</span></td>
      <td>
        <button class="btn sm ghost" onclick="addBoqSubItem(${i})" title="${t("add_sub_item_hint")}">${t("add_sub_item_btn")}</button>
        <button class="btn sm danger" onclick="removeBoqLine(${i})">✕</button>
      </td>
    </tr>`;
  const subRows = kids.map((c, j) => `
    <tr class="boq-sub-row${j === kids.length - 1 ? " last" : ""}">
      <td class="muted num-cell">${i + 1}.${j + 1}</td>
      <td></td>
      <td><div class="boq-sub-name"><span class="boq-sub-arrow">↳</span><input type="text" value="${c.name}" onchange="editBoqSub(${i},${j},'name',this.value)"></div></td>
      <td class="muted">${l.unit}</td>
      <td class="muted num-cell">${l.qty}</td>
      <td style="width:120px"><input type="number" value="${c.unit_price}" step="0.01" onchange="editBoqSub(${i},${j},'unit_price',this.value)"></td>
      <td class="num-cell muted">${fmt(c.total ?? (l.qty * c.unit_price))}</td>
      <td></td>
      <td><button class="btn sm danger" onclick="removeBoqSub(${i},${j})">✕</button></td>
    </tr>`).join("");
  return parentRow + subRows;
}

function boqSourceLabel(source) {
  if (source === "قاعدة الأسعار") return t("source_catalog");
  if (source === "معدّل يدوياً") return t("source_manual_edit");
  if (source === "يدوي") return t("source_manual");
  return source || t("source_estimate");
}

function renderPlan(d) {
  const plan = d.plan || [];
  const totalWeeks = plan.reduce((s, p) => s + Number(p.duration_weeks || 0), 0) || 1;
  let start = 0;
  const gantt = plan.map((p) => {
    const width = (p.duration_weeks / totalWeeks) * 100;
    const bar = `<div class="gantt-row">
      <div class="gantt-label">${p.phase}</div>
      <div class="gantt-track"><div class="gantt-bar" style="inset-inline-start:${(start / totalWeeks) * 100}%;width:${width}%"></div></div>
    </div>`;
    start += Number(p.duration_weeks || 0);
    return bar;
  }).join("");

  $("#tab-plan").innerHTML = `
    <div class="panel">
      <h3>${t("plan_title")} ${d.duration_weeks || totalWeeks} ${t("weeks_label")}</h3>
      ${plan.map((p, i) => `
        <div class="phase">
          <h4>${t("phase_label")} ${i + 1}: ${p.phase} <span class="dur">(${p.duration_weeks} ${t("weeks_label_short")})</span></h4>
          <p>${p.description}</p>
          <ul>${(p.deliverables || []).map((x) => `<li>${x}</li>`).join("")}</ul>
        </div>`).join("")}
      <h3 class="mt">${t("timeline_title")}</h3>
      <div class="gantt">${gantt}</div>
    </div>`;
}

async function saveBoqChanges() {
  currentProposal = await api(`/api/proposals/${currentProposal.id}`, {
    method: "PUT",
    json: { data: currentProposal.data },
  });
  renderFin(currentProposal.data);
}

function editBoq(i, field, value) {
  currentProposal.data.boq[i][field] = Number(value);
  if (field === "unit_price") currentProposal.data.boq[i].source = "معدّل يدوياً";
  saveBoqChanges();
}
function removeBoqLine(i) {
  currentProposal.data.boq.splice(i, 1);
  saveBoqChanges();
}
function addBoqLine() {
  const name = prompt(t("new_item_prompt"));
  if (!name) return;
  currentProposal.data.boq.push({ code: "", name, unit: "وحدة", qty: 1, unit_price: 0, source: "يدوي" });
  saveBoqChanges();
}

/* مراحل فرعية داخل بند واحد: نفس الكمية، وسعر البند الأب = مجموع أسعار مراحله */
let _subItemTargetIndex = null;

function addBoqSubItem(i) {
  _subItemTargetIndex = i;
  $("#boqStageLabel").value = "";
  $("#boqStagePrice").value = "0";
  $("#subItemModal").style.display = "flex";
  $("#boqStageLabel").focus();
}
function closeSubItemModal() {
  $("#subItemModal").style.display = "none";
  _subItemTargetIndex = null;
}
function confirmAddSubItem() {
  const name = $("#boqStageLabel").value.trim();
  if (!name) return toast(t("msg_sub_item_name_required"), true);
  const price = Number($("#boqStagePrice").value || 0);
  const line = currentProposal.data.boq[_subItemTargetIndex];
  if (!line.children) line.children = [];
  line.children.push({ name, unit_price: price });
  closeSubItemModal();
  saveBoqChanges();
}
function editBoqSub(i, j, field, value) {
  currentProposal.data.boq[i].children[j][field] = field === "unit_price" ? Number(value) : value;
  saveBoqChanges();
}
function removeBoqSub(i, j) {
  const line = currentProposal.data.boq[i];
  line.children.splice(j, 1);
  if (!line.children.length) delete line.children;
  saveBoqChanges();
}

async function changeStatus() {
  currentProposal = await api(`/api/proposals/${currentProposal.id}`, {
    method: "PUT", json: { status: $("#vStatus").value },
  });
  toast(t("msg_status_updated"));
}

function exportDocx() { window.location = `/api/proposals/${currentProposal.id}/export/docx`; }
function exportXlsx() { window.location = `/api/proposals/${currentProposal.id}/export/xlsx`; }

/* ---------- قاعدة الأسعار ---------- */
async function loadPrices() {
  const search = $("#prSearch").value || "";
  const cat = $("#prFilterCat").value || "";
  const items = await api(`/api/prices?search=${encodeURIComponent(search)}&category=${encodeURIComponent(cat)}`);

  const cats = [...new Set((await api("/api/prices")).map((i) => i.category))];
  $("#catList").innerHTML = cats.map((c) => `<option value="${c}">`).join("");
  const filterSel = $("#prFilterCat");
  if (filterSel.options.length <= 1) {
    filterSel.innerHTML = `<option value="">${t("all_categories")}</option>` + cats.map((c) => `<option>${c}</option>`).join("");
  } else {
    filterSel.options[0].textContent = t("all_categories");
  }

  $("#pricesTable tbody").innerHTML = items.map((i) => `
    <tr>
      <td class="num-cell">${i.code}</td><td>${i.category}</td><td>${i.name}</td><td>${i.unit}</td>
      <td class="num-cell"><b>${fmt(i.unit_price)}</b></td>
      <td class="num-cell muted">${i.updated_at.slice(0, 10)}</td>
      <td>
        <button class="btn sm ghost" onclick='fillPriceForm(${JSON.stringify(i).replace(/'/g, "&#39;")})'>${t("edit_btn")}</button>
        <button class="btn sm danger" onclick="removePrice(${i.id})">${t("delete_btn")}</button>
      </td>
    </tr>`).join("");
}

function fillPriceForm(i) {
  $("#prCode").value = i.code; $("#prCat").value = i.category;
  $("#prName").value = i.name; $("#prUnit").value = i.unit;
  $("#prPrice").value = i.unit_price;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function savePrice() {
  const item = {
    code: $("#prCode").value.trim(), category: $("#prCat").value.trim(),
    name: $("#prName").value.trim(), unit: $("#prUnit").value.trim(),
    unit_price: Number($("#prPrice").value),
  };
  if (!item.code || !item.name || !item.category || !item.unit) return toast(t("msg_fill_required"), true);
  await api("/api/prices", { method: "POST", json: item });
  toast(t("msg_price_saved"));
  ["prCode", "prCat", "prName", "prUnit", "prPrice"].forEach((id) => $("#" + id).value = "");
  loadPrices();
}

async function removePrice(id) {
  if (!confirm(t("confirm_delete_price"))) return;
  await api(`/api/prices/${id}`, { method: "DELETE" });
  loadPrices();
}

$("#csvImport").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  const res = await api("/api/prices/import/csv", { method: "POST", body: form });
  toast(`${t("msg_csv_imported")} ${res.imported} ${t("msg_csv_imported_suffix")}`);
  loadPrices();
});

/* ---------- المكتبة الفنية ---------- */
async function loadLibrary() {
  const entries = await api("/api/library");
  $("#libraryList").innerHTML = entries.map((e) => `
    <div class="panel">
      <div class="row" style="justify-content:space-between">
        <div><b style="color:var(--primary)">${e.title}</b> <span class="tag gov">${e.category}</span></div>
        <div>
          <button class="btn sm ghost" onclick='fillLibraryForm(${JSON.stringify(e).replace(/'/g, "&#39;")})'>${t("edit_btn")}</button>
          <button class="btn sm danger" onclick="removeLibrary(${e.id})">${t("delete_btn")}</button>
        </div>
      </div>
      <p class="muted mt" style="line-height:1.8">${e.body}</p>
    </div>`).join("");
}

function fillLibraryForm(e) {
  $("#libId").value = e.id; $("#libCat").value = e.category;
  $("#libTitle").value = e.title; $("#libBody").value = e.body;
  window.scrollTo({ top: 0, behavior: "smooth" });
}
function clearLibraryForm() {
  ["libId", "libCat", "libTitle", "libBody"].forEach((id) => $("#" + id).value = "");
}

async function saveLibrary() {
  const entry = {
    id: $("#libId").value ? Number($("#libId").value) : undefined,
    category: $("#libCat").value.trim() || "عام",
    title: $("#libTitle").value.trim(),
    body: $("#libBody").value.trim(),
  };
  if (!entry.title || !entry.body) return toast(t("msg_title_body_required"), true);
  await api("/api/library", { method: "POST", json: entry });
  toast(t("msg_saved"));
  clearLibraryForm();
  loadLibrary();
}

async function removeLibrary(id) {
  if (!confirm(t("confirm_delete_lib"))) return;
  await api(`/api/library/${id}`, { method: "DELETE" });
  loadLibrary();
}

/* ---------- منافسات اعتماد ---------- */
const ET_STATUSES = ["جديدة", "مهتمون", "مستبعدة", "أُنشئ عرض"];
const ET_STATUS_KEY = { "جديدة": "et_status_new", "مهتمون": "et_status_interested", "مستبعدة": "et_status_excluded", "أُنشئ عرض": "et_status_created" };

async function fetchEtimad() {
  $("#etimadFetchBtn").disabled = true;
  $("#etSpinner").classList.add("on");
  try {
    const r = await api("/api/etimad/fetch?pages=3", { method: "POST" });
    if (r.ok) toast(`${t("msg_fetch_ok")} ${r.scanned} ${t("msg_fetch_ok_mid")} ${r.added} ${t("msg_fetch_ok_end")}`);
    else toast(r.error, true);
    loadEtimad();
  } catch (err) {
    toast(t("msg_fetch_failed") + " " + err.message, true);
  } finally {
    $("#etimadFetchBtn").disabled = false;
    $("#etSpinner").classList.remove("on");
  }
}

async function loadEtimad() {
  const params = new URLSearchParams({
    q: $("#etQ").value.trim(),
    status: $("#etStatus").value,
    min_relevance: $("#etRelevant").checked ? 15 : 0,
  });
  const data = await api(`/api/etimad?${params}`);
  $("#etimadSessionNote").style.display = data.session ? "none" : "block";
  $("#etimadTable tbody").innerHTML = data.tenders.map((t3) => `
    <tr>
      <td><a href="${t3.details_url}" target="_blank" rel="noopener" style="color:var(--primary);font-weight:600">${t3.name.slice(0, 70)}</a>
        ${t3.matched_ref ? `<br><span class="muted" style="font-size:11px">${t("closest_experience")} ${t3.matched_ref.slice(0, 50)}</span>` : ""}</td>
      <td>${t3.agency.slice(0, 35)}</td>
      <td class="num-cell">${t3.deadline || "—"}</td>
      <td><span class="tag ${t3.relevance >= 30 ? "src" : t3.relevance >= 15 ? "est" : "draft"}">${t3.relevance}%</span></td>
      <td><select onchange="setEtStatus(${t3.id}, this.value)" style="padding:4px 8px;font-size:12px">
        ${ET_STATUSES.map((s) => `<option value="${s}" ${s === t3.status ? "selected" : ""}>${t(ET_STATUS_KEY[s])}</option>`).join("")}</select></td>
      <td>
        <button class="btn sm ghost" onclick="etToProposal('${t3.name.replace(/'/g, "&#39;").slice(0, 90)}', '${t3.agency.replace(/'/g, "&#39;").slice(0, 60)}')">${t("create_proposal_btn")}</button>
      </td>
    </tr>`).join("") ||
    `<tr><td colspan="6" class="muted">${t("empty_tenders")}</td></tr>`;
}

function setEtStatus(id, status) {
  api(`/api/etimad/${id}`, { method: "PUT", json: { status } }).then(() => toast(t("msg_status_updated")));
}

function etToProposal(name, agency) {
  go("new");
  $("#npTitle").value = name;
  $("#npClient").value = agency;
  $("#npEntity").value = "government";
  suggestSimilar();
  toast(t("msg_etimad_loaded_hint"));
}

/* ---------- المستودع الفني ومحرك الأسلوب ---------- */
function repoTab(which) {
  $$("[data-repo-tab]").forEach((b) => b.classList.toggle("active", b.dataset.repoTab === which));
  $("#repoTabFin").hidden = which !== "fin";
  $("#repoTabTech").hidden = which !== "tech";
  if (which === "tech") loadTechRepo();
}

async function loadTechRepo() {
  const [data, bank] = await Promise.all([
    api("/api/repository/technical"), api("/api/paragraph-bank")]);
  const pr = data.profile || {};
  const gl = JSON.parse(pr.glossary_json || "[]");
  $("#styleProfileBox").innerHTML = pr.sample_count ? `
    <div class="grid-3">
      <div><b>${t("sp_sentence")}</b><br>${pr.avg_sentence_len} ${t("sp_words")}</div>
      <div><b>${t("sp_voice")}</b><br>${pr.voice === "first_person_plural" ? t("sp_voice_we") : t("sp_voice_co")}</div>
      <div><b>${t("sp_secwords")}</b><br>${pr.avg_section_words} ${t("sp_words")}</div>
      <div><b>${t("sp_samples")}</b><br>${pr.sample_count} ${t("sp_paras")} / ${pr.docs} ${t("sp_docs")}</div>
      <div style="grid-column:span 2"><b>${t("sp_glossary")}</b><br><span class="muted">${gl.slice(0, 12).join("، ") || "—"}</span></div>
    </div>
    ${pr.reliable ? "" : `<div class="alert mt">${t("sp_unreliable")}</div>`}` :
    `<div class="alert">${t("sp_empty")}</div>`;

  $("#paraBank").innerHTML = bank.map((b) => `
    <div class="card" style="text-align:start">
      <div class="row mb" style="justify-content:space-between">
        <span class="tag ${b.approved ? "src" : "est"}">${b.title.slice(0, 25)}</span>
        <span class="muted" style="font-size:11px">${t("bank_used")} ${b.use_count}</span>
      </div>
      <p class="muted" style="font-size:12px;line-height:1.8">${b.body.slice(0, 180)}…</p>
      <button class="btn sm ${b.approved ? "ghost" : ""}" onclick="toggleParagraph(${b.id}, ${b.approved ? 0 : 1})">
        ${b.approved ? t("bank_unapprove") : t("bank_approve")}</button>
    </div>`).join("") || `<p class="muted">${t("bank_empty")}</p>`;

  $("#techDocsTable tbody").innerHTML = data.documents.map((d) => `
    <tr>
      <td class="ellipsis">${d.filename}</td>
      <td><span class="tag ${d.doc_kind === "competitor" ? "est" : "gov"}">${d.doc_kind === "competitor" ? t("kind_competitor") : t("kind_azoom")}</span></td>
      <td>${d.project_kind || "—"}</td>
      <td class="num-cell">${d.sections_count}</td>
      <td class="num-cell">${d.paragraphs_count}</td>
      <td>${d.is_style_source ? `<span class="tag src">${t("style_src_yes")}</span>` : "—"}</td>
    </tr>`).join("") || `<tr><td colspan="6" class="muted">${t("tech_docs_empty")}</td></tr>`;
}

async function toggleParagraph(id, approved) {
  await api(`/api/paragraphs/${id}`, { method: "PUT", json: { approved: !!approved } });
  loadTechRepo();
}

async function rebuildStyle() {
  const pr = await api("/api/style-profile/rebuild", { method: "POST" });
  toast(`↻ ${t("style_rebuilt")} — ${pr.sample_count} ${t("sp_paras")}`);
  loadTechRepo();
}

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
          ${["viewer", "editor", "admin", "owner"].map((r) => `<option value="${r}" ${r === m.role ? "selected" : ""}>${t("role_" + r)}</option>`).join("")}
        </select>` : `<span class="tag ${m.role === "owner" || m.role === "admin" ? "admin" : "est"}">${t("role_" + m.role) || m.role}</span>`}</td>
      <td class="num-cell muted">${(m.last_login_at || "").slice(0, 10) || "—"}</td>
      <td>${canManage && m.id !== ME.user_id ? `<button class="btn sm danger" onclick="removeMember(${m.id})">${t("member_remove")}</button>` : ""}</td>
    </tr>`).join("");

  if (ME.is_platform_admin) {
    $("#platformPanel").hidden = false;
    try {
      const mt = await api("/api/platform/metrics");
      $("#platformMetrics").innerHTML = `
        <div class="card gold"><div class="num">${fmt(mt.mrr).replace(/[.٫]00$/, "")}</div><div class="lbl">${t("mt_mrr")}</div></div>
        <div class="card"><div class="num">${mt.paid_count}</div><div class="lbl">${t("mt_paid")}</div></div>
        <div class="card"><div class="num">${mt.trial_count}</div><div class="lbl">${t("mt_trials")}</div></div>
        <div class="card"><div class="num">${mt.companies_total}</div><div class="lbl">${t("mt_companies")}</div></div>`;
    } catch {}
    const companies = await api("/api/companies");
    $("#companiesTable tbody").innerHTML = companies.map((c) => `
      <tr>
        <td><b>${c.name}</b>${c.id === ME.company_id ? ` <span class="tag src">${t("company_current")}</span>` : ""}</td>
        <td><span class="tag est">${t("plan_" + c.plan) || c.plan}</span></td>
        <td class="num-cell">${c.usage.users}</td>
        <td class="num-cell">${c.usage.proposals_month}</td>
        <td class="num-cell">${c.usage.price_items}</td>
        <td><button class="btn sm ghost" onclick="switchCompany(${c.id})">${t("company_open")}</button></td>
      </tr>`).join("");
  }
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

async function inviteMember() {
  const username = $("#invUsername").value.trim();
  if (!username) return toast(t("invite_need_user"), true);
  try {
    await api("/api/members", { method: "POST", json: {
      username, password: $("#invPassword").value, role: $("#invRole").value } });
    toast(t("invite_done"));
    $("#invUsername").value = ""; $("#invPassword").value = "";
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
  } catch (err) { toast(err.message, true); }
}

async function createCompany() {
  const name = $("#ncName").value.trim(), owner = $("#ncOwner").value.trim();
  if (!name || !owner) return toast(t("newco_need_fields"), true);
  try {
    const c = await api("/api/companies", { method: "POST", json: {
      name, plan: $("#ncPlan").value,
      owner_username: owner, owner_password: $("#ncOwnerPass").value } });
    toast(`🏢 ${t("newco_done")} — ${c.name}`);
    $("#ncName").value = ""; $("#ncOwner").value = ""; $("#ncOwnerPass").value = "";
    loadTenants();
  } catch (err) { toast(err.message, true); }
}

/* ---------- مشاريع منصة فرصة ---------- */
const FS_STATUSES = ["جديد", "مهتمون", "مستبعد", "أُنشئ عرض"];
let forsahCredsLoaded = false;

async function loadForsahCreds() {
  if (forsahCredsLoaded) return;
  const s = await api("/api/settings");
  $("#forsahEmail").value = s.forsah_email || "";
  if (s.forsah_password) $("#forsahPassword").placeholder = "•••••• (محفوظة — اكتب لتغييرها)";
  forsahCredsLoaded = true;
}

async function saveForsahCreds() {
  const email = $("#forsahEmail").value.trim();
  const pw = $("#forsahPassword").value;
  const payload = { forsah_email: email };
  if (pw) payload.forsah_password = pw;
  await api("/api/settings", { method: "PUT", json: payload });
  $("#forsahPassword").value = "";
  $("#forsahPassword").placeholder = "•••••• (محفوظة — اكتب لتغييرها)";
  toast("💾 حُفظت بيانات دخول فرصة محلياً في قاعدة بيانات النظام");
}

async function fetchForsah() {
  $("#forsahFetchBtn").disabled = true;
  $("#fsSpinner").classList.add("on");
  try {
    const r = await api("/api/forsah/fetch", { method: "POST" });
    if (r.ok) {
      const cats = Object.entries(r.by_category || {}).filter(([, n]) => n)
        .map(([c, n]) => `${c}: ${n}`).join("، ");
      toast(`✅ فُحص ${r.scanned} مشروعاً وأُضيف ${r.added} جديداً${cats ? " — " + cats : ""}`);
      if (r.note) setTimeout(() => toast("⚠️ " + r.note, true), 2500);
    } else toast(r.error, true);
    loadForsah();
  } catch (err) {
    toast("فشل السحب: " + err.message, true);
  } finally {
    $("#forsahFetchBtn").disabled = false;
    $("#fsSpinner").classList.remove("on");
  }
}

async function loadForsah() {
  loadForsahCreds();
  const params = new URLSearchParams({
    q: $("#fsQ").value.trim(),
    category: $("#fsCategory").value,
    status: $("#fsStatus").value,
  });
  const data = await api(`/api/forsah?${params}`);
  $("#forsahTable tbody").innerHTML = data.projects.map((p) => `
    <tr>
      <td><a href="${p.details_url}" target="_blank" rel="noopener" style="color:var(--primary);font-weight:600">${p.title.slice(0, 70)}</a>
        ${p.matched_ref ? `<br><span class="muted" style="font-size:11px">أقرب خبرة: ${p.matched_ref.slice(0, 50)}</span>` : ""}</td>
      <td><span class="tag est">${p.category}</span></td>
      <td class="num-cell">${p.budget || "—"}</td>
      <td class="num-cell">${p.deadline || "—"}</td>
      <td><span class="fit${p.relevance < 15 ? " low" : ""}"><i style="width:${Math.min(p.relevance * 2, 100)}%"></i></span> <span class="num-cell">${p.relevance}%</span></td>
      <td><select onchange="setFsStatus(${p.id}, this.value)" style="padding:4px 8px;font-size:12px">
        ${FS_STATUSES.map((s) => `<option ${s === p.status ? "selected" : ""}>${s}</option>`).join("")}</select></td>
      <td>
        <button class="btn sm ghost" onclick="fsToProposal('${p.title.replace(/'/g, "&#39;").slice(0, 90)}')">✨ أنشئ عرضاً</button>
      </td>
    </tr>`).join("") ||
    `<tr><td colspan="7" class="muted">لا مشاريع مخزنة — احفظ بيانات الدخول ثم اضغط «سحب المشاريع من فرصة»</td></tr>`;
}

function setFsStatus(id, status) {
  api(`/api/forsah/${id}`, { method: "PUT", json: { status } }).then(() => toast("تم تحديث الحالة"));
}

function fsToProposal(title) {
  go("new");
  $("#npTitle").value = title;
  $("#npEntity").value = "private";
  suggestSimilar();
  toast("حُمّل اسم المشروع — أدخل اسم العميل وارفع ملفات المشروع ثم اضغط توليد");
}

/* ---------- المستودع المعرفي ---------- */
let repoFiles = [];
const repoDrop = $("#repoDrop"), repoInput = $("#repoFileInput");
repoDrop.addEventListener("click", () => repoInput.click());
repoDrop.addEventListener("dragover", (e) => { e.preventDefault(); repoDrop.classList.add("drag"); });
repoDrop.addEventListener("dragleave", () => repoDrop.classList.remove("drag"));
repoDrop.addEventListener("drop", (e) => {
  e.preventDefault(); repoDrop.classList.remove("drag");
  for (const f of e.dataTransfer.files) repoFiles.push(f);
  renderRepoFiles();
});
repoInput.addEventListener("change", () => {
  for (const f of repoInput.files) repoFiles.push(f);
  renderRepoFiles();
});
function renderRepoFiles() {
  $("#repoFileList").innerHTML = repoFiles.map((f, i) =>
    `<span class="file-chip">${f.name}<span class="size">${fileSize(f.size)}</span><button onclick="repoFiles.splice(${i},1);renderRepoFiles()">✕</button></span>`).join("");
}

async function uploadRepo() {
  if (!repoFiles.length) return toast(t("msg_choose_files_first"), true);
  const form = new FormData();
  form.append("source_type", $("#repoSource").value);
  form.append("company", $("#repoCompany").value.trim());
  form.append("notes", $("#repoNotes").value.trim());
  form.append("as_reference", $("#repoAsRef").checked ? "1" : "");
  form.append("sector", $("#repoSector").value);
  for (const f of repoFiles) form.append("files", f);
  $("#repoUploadBtn").disabled = true;
  $("#repoSpinner").classList.add("on");
  try {
    const results = await api("/api/repo/upload", { method: "POST", body: form });
    const total = results.reduce((s, r) => s + r.items_count, 0);
    const refs = results.filter((r) => r.reference);
    const failed = results.filter((r) => r.note || r.reference_note);
    toast(`${t("msg_upload_stored")} ${results.length} ${t("msg_upload_files_word")} ${total} ${t("msg_upload_items_word")}` +
          (refs.length ? ` ${t("msg_upload_refs_word")} ${refs.length} ${t("msg_upload_refs_word2")}` : ""));
    failed.slice(0, 3).forEach((r, i) => setTimeout(() =>
      toast(`⚠️ ${r.filename.slice(0, 35)}: ${r.note || r.reference_note}`, true), 2500 + i * 4000));
    repoFiles = []; renderRepoFiles();
    loadRepo();
  } catch (err) {
    toast(t("msg_upload_failed") + " " + err.message, true);
  } finally {
    $("#repoUploadBtn").disabled = false;
    $("#repoSpinner").classList.remove("on");
  }
}

async function loadRepo() {
  const data = await api("/api/repo");
  $("#repoTable tbody").innerHTML = data.files.map((f) => `
    <tr>
      <td>${f.filename}</td>
      <td><span class="tag ${f.source_type.includes("منافس") ? "est" : "gov"}">${f.source_type}</span></td>
      <td>${t(SECTOR_KEY[f.sector || ""]) || t("sector_general")}</td>
      <td>${f.company || "—"}</td>
      <td class="num-cell">${f.items_count}</td>
      <td class="num-cell muted">${f.uploaded_at.slice(0, 10)}</td>
      <td style="white-space:nowrap">
        <button class="btn sm" onclick="makeReference(${f.id})" title="${t("ref_btn_title")}">${t("ref_btn")}</button>
        <button class="btn sm danger" onclick="removeRepoFile(${f.id})">${t("delete_btn")}</button>
      </td>
    </tr>`).join("") ||
    `<tr><td colspan="7" class="muted">${t("repo_empty")}</td></tr>`;
}

async function makeReference(id) {
  try {
    const ref = await api(`/api/repo/${id}/make-reference`, { method: "POST" });
    toast(`${t("msg_ref_created")} ${ref.ref_no} (${ref.boq_lines} ${t("similar_lines")}) — ${t("msg_ref_built_on")}`);
  } catch (err) {
    toast(err.message, true);
  }
}

async function removeRepoFile(id) {
  if (!confirm(t("confirm_delete_repofile"))) return;
  await api(`/api/repo/${id}`, { method: "DELETE" });
  loadRepo();
}

let marketTimer;
$("#marketSector").addEventListener("change", () => $("#marketSearch").dispatchEvent(new Event("input")));
$("#marketSearch").addEventListener("input", () => {
  clearTimeout(marketTimer);
  marketTimer = setTimeout(async () => {
    const q = $("#marketSearch").value.trim();
    const sector = $("#marketSector").value;
    if (q.length < 3) { $("#marketResult").innerHTML = ""; return; }
    const r = await api(`/api/market/search?q=${encodeURIComponent(q)}&sector=${sector}`);
    const b = r.benchmark;
    let html = "";
    if (b.count) {
      html += `<div class="row mb" style="gap:20px">
        <span>${t("msg_market_count")} (${b.count} ${t("msg_market_notes")}):</span>
        <span>${t("msg_market_min")} <b>${fmt(b.min)}</b></span>
        <span>${t("msg_market_avg")} <b style="color:var(--accent)">${fmt(b.avg)}</b></span>
        <span>${t("msg_market_max")} <b>${fmt(b.max)}</b></span></div>`;
    }
    if (r.azoom.length) {
      html += `<p class="muted mb">${t("msg_azoom_prices_match")} ${r.azoom.slice(0, 3).map((a) => `${a.name.slice(0, 30)} = <b>${fmt(a.unit_price)}</b>`).join(" • ")}</p>`;
    }
    html += r.market.length ? `<div class="t-wrap"><table>
      <thead><tr><th>${t("th_item")}</th><th>${t("th_unit")}</th><th>${t("th_price")}</th><th>${t("th_source")}</th></tr></thead>
      <tbody>${r.market.slice(0, 12).map((m) => `<tr><td>${m.name.slice(0, 60)}</td><td>${m.unit || "—"}</td>
        <td class="num-cell"><b>${fmt(m.unit_price)}</b></td>
        <td class="muted">${m.source_company || m.source_type || m.filename || ""}</td></tr>`).join("")}</tbody>
      </table></div>` : `<p class="muted">${t("msg_no_market_notes")}</p>`;
    $("#marketResult").innerHTML = html;
  }, 400);
});

/* ---------- تحليل فرصة الفوز ---------- */
async function runOpportunity() {
  const title = $("#npTitle").value.trim();
  if (!title) return toast(t("msg_enter_project_first"), true);
  const form = new FormData();
  form.append("title", title);
  form.append("client", $("#npClient").value.trim());
  for (const f of pendingFiles) form.append("files", f);
  $("#oppBtn").disabled = true;
  $("#oppResult").innerHTML = `<div class="spinner on"><div class="dot"></div>${t("opp_analyzing")}</div>`;
  try {
    const a = await api("/api/opportunity", { method: "POST", body: form });
    const colors = { go: "var(--ok)", caution: "var(--warn)", nogo: "#a33" };
    $("#oppResult").innerHTML = `
      <div class="panel mt" style="border-inline-start:5px solid ${colors[a.verdict_class]}">
        <div class="row" style="justify-content:space-between">
          <h3 style="margin:0">${t("opp_score_title")} ${a.score}%</h3>
          <b style="color:${colors[a.verdict_class]}">${a.verdict}</b>
        </div>
        <div class="mt">${a.factors.map((f) => `
          <div class="fin-row"><span>${f.name} <span class="muted">(${t("opp_weight_label")} ${f.weight}%)</span><br>
            <span class="muted" style="font-size:12px">${f.detail}</span></span>
            <b class="num-cell" style="color:${f.score >= 65 ? "var(--ok)" : f.score >= 40 ? "var(--warn)" : "#a33"}">${f.score}%</b></div>`).join("")}
        </div>
        ${a.qualification_warnings.length ? `<div class="mt"><b>${t("opp_warnings_title")}</b>
          ${a.qualification_warnings.map((w) => `<p class="muted" style="margin-top:6px">• ${w}</p>`).join("")}</div>` : ""}
      </div>`;
  } catch (err) {
    $("#oppResult").innerHTML = "";
    toast(t("msg_analysis_failed") + " " + err.message, true);
  } finally {
    $("#oppBtn").disabled = false;
  }
}

/* ---------- وثائق الشركة ---------- */
const DOC_STATUS = {
  expired: ["doc_status_expired", "lost"],
  expiring: ["doc_status_expiring", "est"],
  valid: ["doc_status_valid", "src"],
  missing: ["doc_status_missing", "draft"],
};

async function loadDocs() {
  const docs = await api("/api/docs");
  $("#docsTable tbody").innerHTML = docs.map((d) => {
    const [labelKey, cls] = DOC_STATUS[d.status] || DOC_STATUS.missing;
    const days = d.status === "expiring" ? ` (${d.days_left} ${t("docs_alert_days")})` : "";
    return `<tr>
      <td><b>${d.name}</b></td><td class="num-cell">${d.number || "—"}</td><td>${d.issuer || "—"}</td>
      <td class="num-cell">${d.expiry_date || "—"}</td>
      <td><span class="tag ${cls}">${t(labelKey)}${days}</span></td>
      <td>
        <button class="btn sm ghost" onclick='fillDocForm(${JSON.stringify(d).replace(/'/g, "&#39;")})'>${t("edit_btn")}</button>
        <button class="btn sm danger" onclick="removeDoc(${d.id})">${t("delete_btn")}</button>
      </td></tr>`;
  }).join("");
}

function fillDocForm(d) {
  $("#docId").value = d.id; $("#docName").value = d.name;
  $("#docNumber").value = d.number || ""; $("#docIssuer").value = d.issuer || "";
  $("#docIssue").value = d.issue_date || ""; $("#docExpiry").value = d.expiry_date || "";
  $("#docNotes").value = d.notes || "";
  window.scrollTo({ top: 0, behavior: "smooth" });
}
function clearDocForm() {
  ["docId", "docName", "docNumber", "docIssuer", "docIssue", "docExpiry", "docNotes"]
    .forEach((id) => $("#" + id).value = "");
}

async function saveDoc() {
  const doc = {
    id: $("#docId").value ? Number($("#docId").value) : undefined,
    name: $("#docName").value.trim(),
    number: $("#docNumber").value.trim(),
    issuer: $("#docIssuer").value.trim(),
    issue_date: $("#docIssue").value,
    expiry_date: $("#docExpiry").value,
    notes: $("#docNotes").value.trim(),
  };
  if (!doc.name) return toast(t("msg_doc_name_required"), true);
  await api("/api/docs", { method: "POST", json: doc });
  toast(t("msg_doc_saved"));
  clearDocForm();
  loadDocs();
}

async function removeDoc(id) {
  if (!confirm(t("confirm_delete_doc"))) return;
  await api(`/api/docs/${id}`, { method: "DELETE" });
  loadDocs();
}

/* ---------- التحليلات ---------- */
async function loadAnalytics() {
  const a = await api("/api/analytics");
  const t4 = a.totals;
  $("#anCards").innerHTML = `
    <div class="card gold"><div class="num">${t4.win_rate !== null ? t4.win_rate + "%" : "—"}</div><div class="lbl">${t("an_win_rate")}</div></div>
    <div class="card"><div class="num">${fmt(t4.won_value)}</div><div class="lbl">${t("an_won_value")}</div></div>
    <div class="card"><div class="num">${fmt(t4.pipeline_value)}</div><div class="lbl">${t("an_pipeline_value")}</div></div>
    <div class="card"><div class="num">${t4.by_status.won} / ${t4.by_status.won + t4.by_status.lost}</div><div class="lbl">${t("an_won_decided")}</div></div>`;

  const m = a.margins;
  $("#anMargins").innerHTML = `
    <h3>${t("margin_calib_title")}</h3>
    <div class="row" style="gap:26px">
      <div>${t("avg_won_margin_pre")} <b style="color:var(--ok)">${t("avg_won_margin_word")}</b> ${t("avg_margin_post")}: <b>${m.avg_won_margin !== null ? m.avg_won_margin + "%" : "—"}</b></div>
      <div>${t("avg_won_margin_pre")} <b style="color:#a33">${t("avg_lost_margin_word")}</b> ${t("avg_margin_post")}: <b>${m.avg_lost_margin !== null ? m.avg_lost_margin + "%" : "—"}</b></div>
    </div>
    <p class="muted mt" style="line-height:1.9">💡 ${m.hint}</p>`;

  const ENTITY_KEY = { government: "entity_gov", private: "entity_private", pif: "entity_pif", airports: "entity_airports" };
  $("#anEntityTable tbody").innerHTML = Object.entries(a.by_entity).map(([k, e]) => `
    <tr><td><b>${t(ENTITY_KEY[k])}</b></td><td>${e.total}</td><td>${e.won}</td>
    <td>${e.win_rate !== null ? e.win_rate + "%" : "—"}</td>
    <td class="num-cell">${fmt(e.won_value)}</td></tr>`).join("");

  $("#anClientTable tbody").innerHTML = a.by_client.map((c) => `
    <tr><td>${c.client}</td><td>${c.total}</td><td>${c.won}</td><td>${c.lost}</td>
    <td>${c.win_rate !== null ? c.win_rate + "%" : "—"}</td>
    <td class="num-cell">${fmt(c.won_value)}</td></tr>`).join("") ||
    `<tr><td colspan="6" class="muted">${t("no_data")}</td></tr>`;
}

/* ---------- الإعدادات ---------- */
async function loadSettings() {
  const s = await api("/api/settings");
  $$("[data-key]").forEach((el) => { el.value = s[el.dataset.key] ?? ""; });
}

async function saveSettings() {
  const values = {};
  $$("[data-key]").forEach((el) => { values[el.dataset.key] = el.value; });
  await api("/api/settings", { method: "PUT", json: values });
  toast(t("msg_settings_saved"));
}

/* ---------- بدء التشغيل ---------- */
loadMe().then(() => loadDashboard());
