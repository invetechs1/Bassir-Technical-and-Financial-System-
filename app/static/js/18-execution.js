/* ---------- تنفيذ المشاريع: الإنتاجية اليومية ومقاولو الباطن ---------- */
let EXEC = { projects: [], executors: [], editing: null };
const escH = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function loadExecution() {
  await Promise.all([loadExecProjects(), loadExecExecutors()]);
  $("#execProfitTabBtn").hidden = !ME.is_admin;
  execTab("reports");
  loadExecRequestsBadge();
}

function execTab(which) {
  $$("[data-exec-tab]").forEach((b) => b.classList.toggle("active", b.dataset.execTab === which));
  const panes = { reports: "execTabReports", summary: "execTabSummary", projects: "execTabProjects",
                  subs: "execTabSubs", requests: "execTabRequests", profit: "execTabProfit" };
  Object.entries(panes).forEach(([k, id]) => { $("#" + id).hidden = k !== which; });
  if (which === "reports") loadExecReports();
  if (which === "summary") loadExecSummary();
  if (which === "projects") renderExecProjects();
  if (which === "subs") loadExecSubs();
  if (which === "requests") loadExecRequests();
  if (which === "profit") initExecProfit();
}

async function loadExecProjects() {
  EXEC.projects = await api("/api/execution/projects");
  const opts = EXEC.projects.filter((p) => p.status !== "مكتمل")
    .map((p) => `<option value="${p.id}">${escH(p.name)}</option>`).join("");
  $("#execRepProject").innerHTML = opts || `<option value="">${t("exec_no_projects")}</option>`;
  $("#execSummaryProject").innerHTML = `<option value="0">${t("exec_all_projects")}</option>` +
    EXEC.projects.map((p) => `<option value="${p.id}">${escH(p.name)}</option>`).join("");
  if (ME.role !== "engineer") {
    try {
      const props = await api("/api/proposals");
      $("#execPjProposal").innerHTML = '<option value="">—</option>' +
        props.map((p) => `<option value="${p.id}">${escH(p.ref_no)} — ${escH(p.title)}</option>`).join("");
    } catch {}
  }
}

async function loadExecExecutors() {
  EXEC.executors = await api("/api/execution/executors");
}

function execExecutorSelect(sel) {
  const cur = sel || "company:0";
  return `<select onchange="">` + EXEC.executors.map((e) => {
    const v = `${e.type}:${e.id}`;
    return `<option value="${v}" ${v === cur ? "selected" : ""}>${escH(e.label)}</option>`;
  }).join("") + "</select>";
}

/* --- نموذج التقرير --- */
function openExecReportForm(report) {
  EXEC.editing = report ? report.id : null;
  $("#execReportForm").hidden = false;
  $("#execReportFormTitle").textContent = report
    ? `${t("exec_report_edit_title")} — ${report.report_date}` : t("exec_report_form_title");
  $("#execRepSaveBtn").textContent = report && ME.role !== "owner" && !ME.is_platform_admin
    ? t("exec_request_edit_btn") : t("exec_save_report_btn");
  $("#execRepDate").value = report ? report.report_date : new Date().toISOString().slice(0, 10);
  $("#execRepNotes").value = report ? (report.notes || "") : "";
  if (report) $("#execRepProject").value = report.project_id;
  $("#execRepLines").innerHTML = "";
  (report ? report.lines : [null]).forEach((l) => addExecLine(l));
  loadExecBoqList();
  $("#execReportForm").scrollIntoView({ behavior: "smooth" });
}

function closeExecReportForm() { $("#execReportForm").hidden = true; EXEC.editing = null; }

function addExecLine(l) {
  const tr = document.createElement("tr");
  const sel = l ? `${l.executor_type}:${l.subcontractor_id || 0}` : "company:0";
  tr.innerHTML = `
    <td><input type="text" class="ex-item" list="execBoqList" value="${escH(l?.item)}" placeholder="${t("exec_line_item_ph")}"></td>
    <td style="width:90px"><input type="text" class="ex-unit" value="${escH(l?.unit)}"></td>
    <td style="width:110px"><input type="number" class="ex-qty" step="0.01" value="${l?.qty ?? ""}"></td>
    <td class="ex-exec">${execExecutorSelect(sel)}</td>
    <td><input type="text" class="ex-notes" value="${escH(l?.notes)}"></td>
    <td><button class="btn sm ghost" onclick="this.closest('tr').remove()">🗑</button></td>`;
  $("#execRepLines").appendChild(tr);
}

async function loadExecBoqList() {
  const pid = Number($("#execRepProject").value || 0);
  if (!pid) { $("#execBoqList").innerHTML = ""; return; }
  try {
    const items = await api(`/api/execution/projects/${pid}/boq`);
    $("#execBoqList").innerHTML = items.map((i) =>
      `<option value="${escH(i.name)}">${escH(i.unit)}</option>`).join("");
  } catch { $("#execBoqList").innerHTML = ""; }
}

function collectExecLines() {
  return [...$("#execRepLines").children].map((tr) => {
    const [type, id] = tr.querySelector(".ex-exec select").value.split(":");
    return {
      item: tr.querySelector(".ex-item").value.trim(),
      unit: tr.querySelector(".ex-unit").value.trim(),
      qty: Number(tr.querySelector(".ex-qty").value || 0),
      executor_type: type,
      subcontractor_id: Number(id || 0),
      notes: tr.querySelector(".ex-notes").value.trim(),
    };
  }).filter((l) => l.item);
}

async function saveExecReport() {
  const body = {
    project_id: Number($("#execRepProject").value || 0),
    report_date: $("#execRepDate").value,
    notes: $("#execRepNotes").value.trim(),
    lines: collectExecLines(),
  };
  if (!body.project_id) return toast(t("exec_msg_pick_project"), true);
  if (!body.lines.length) return toast(t("exec_msg_no_lines"), true);
  try {
    let res;
    if (EXEC.editing) {
      res = await api(`/api/execution/reports/${EXEC.editing}`, { method: "PUT", json: body });
    } else {
      res = await api("/api/execution/reports", { method: "POST", json: body });
    }
    if (res.pending) toast(t("exec_msg_edit_requested"));
    else toast(EXEC.editing ? t("exec_msg_updated") : t("exec_msg_report_locked"));
    closeExecReportForm();
    loadExecReports();
  } catch (e) { toast(e.message, true); }
}

/* --- قائمة التقارير --- */
async function loadExecReports() {
  const rows = await api("/api/execution/reports");
  EXEC.reports = rows;
  $("#execReportsTable").innerHTML = rows.map((r) => `
    <tr>
      <td>${r.report_date}</td>
      <td>${escH(r.project_name)}</td>
      <td>${escH(r.engineer_name)}</td>
      <td>${r.lines.length}</td>
      <td>${r.pending_edit
        ? `<span class="tag" style="background:#f6e3c5">${t("exec_status_pending")}</span>`
        : `<span class="tag admin">🔒 ${t("exec_status_locked")}</span>`}</td>
      <td style="white-space:nowrap">
        <button class="btn sm ghost" onclick="viewExecReport(${r.id})">👁</button>
        <button class="btn sm ghost" onclick="editExecReport(${r.id})" title="${t("exec_edit_btn_hint")}">✏️</button>
        ${ME.role === "owner" || ME.is_platform_admin
          ? `<button class="btn sm ghost" onclick="deleteExecReport(${r.id})">🗑</button>` : ""}
      </td>
    </tr>`).join("") || `<tr><td colspan="6" class="muted">${t("exec_no_reports")}</td></tr>`;
  $("#execReportDetail").hidden = true;
}

function viewExecReport(id) {
  const r = EXEC.reports.find((x) => x.id === id);
  if (!r) return;
  const d = $("#execReportDetail");
  d.hidden = false;
  d.innerHTML = `
    <h3>${escH(r.project_name)} — ${r.report_date} <span class="muted">(${escH(r.engineer_name)})</span></h3>
    ${r.notes ? `<p class="muted">${escH(r.notes)}</p>` : ""}
    <div class="table-wrap"><table>
      <thead><tr><th>${t("exec_line_item")}</th><th>${t("exec_line_unit")}</th>
        <th>${t("exec_line_qty")}</th><th>${t("exec_line_executor")}</th><th>${t("exec_line_notes")}</th></tr></thead>
      <tbody>${r.lines.map((l) => `<tr>
        <td>${escH(l.item)}</td><td>${escH(l.unit)}</td><td>${l.qty}</td>
        <td>${escH(l.executor_name)}</td><td>${escH(l.notes)}</td></tr>`).join("")}</tbody>
    </table></div>`;
  d.scrollIntoView({ behavior: "smooth" });
}

function editExecReport(id) {
  const r = EXEC.reports.find((x) => x.id === id);
  if (!r) return;
  if (r.pending_edit && ME.role !== "owner" && !ME.is_platform_admin)
    return toast(t("exec_msg_already_pending"), true);
  openExecReportForm(r);
}

async function deleteExecReport(id) {
  if (!confirm(t("exec_confirm_delete_report"))) return;
  await api(`/api/execution/reports/${id}`, { method: "DELETE" });
  toast(t("msg_deleted"));
  loadExecReports();
}

/* --- كم اشتغل كل منفّذ --- */
async function loadExecSummary() {
  const pid = Number($("#execSummaryProject").value || 0);
  const rows = await api(`/api/execution/productivity${pid ? `?project_id=${pid}` : ""}`);
  $("#execSummaryTable").innerHTML = rows.map((r) => `
    <tr>
      <td>${r.executor_type === "company" ? "🏗" : "🤝"} ${escH(r.executor)}</td>
      <td>${r.reports}</td>
      <td>${r.lines}</td>
      <td>${r.by_unit.map((u) => `<span class="tag" style="margin-inline-end:6px">${u.qty} ${escH(u.unit)}</span>`).join("")}</td>
    </tr>`).join("") || `<tr><td colspan="4" class="muted">${t("exec_no_data")}</td></tr>`;
}

/* --- مشاريع التنفيذ --- */
function renderExecProjects() {
  $("#execProjectFormPanel").hidden = ME.role === "engineer" || ME.role === "viewer";
  $("#execProjectsTable").innerHTML = EXEC.projects.map((p) => `
    <tr>
      <td>${escH(p.name)}</td><td>${escH(p.client)}</td><td>${p.reports_count}</td>
      <td>${ME.role === "engineer" || ME.role === "viewer" ? escH(p.status)
        : `<button class="btn sm ghost" onclick="toggleExecProject(${p.id})">${escH(p.status)} ⇄</button>`}</td>
    </tr>`).join("") || `<tr><td colspan="4" class="muted">${t("exec_no_projects")}</td></tr>`;
}

async function saveExecProject() {
  const name = $("#execPjName").value.trim();
  if (!name) return toast(t("exec_msg_project_name"), true);
  await api("/api/execution/projects", { method: "POST", json: {
    name, client: $("#execPjClient").value.trim(),
    proposal_id: Number($("#execPjProposal").value || 0) || null,
  } });
  $("#execPjName").value = ""; $("#execPjClient").value = "";
  toast(t("msg_saved"));
  await loadExecProjects();
  renderExecProjects();
}

async function toggleExecProject(id) {
  const p = EXEC.projects.find((x) => x.id === id);
  if (!p) return;
  await api("/api/execution/projects", { method: "POST", json: {
    ...p, status: p.status === "نشط" ? "مكتمل" : "نشط" } });
  await loadExecProjects();
  renderExecProjects();
}

/* --- مقاولو الباطن --- */
async function loadExecSubs() {
  $("#execSubFormPanel").hidden = !ME.is_admin;
  const subs = await api("/api/execution/subcontractors");
  $("#execSubsTable").innerHTML = subs.map((s) => `
    <tr>
      <td>${escH(s.name)}</td><td>${escH(s.trade)}</td><td>${escH(s.phone)}</td>
      <td>${s.active ? "✅" : "⏸"}</td>
      <td style="white-space:nowrap">${ME.is_admin ? `
        <button class="btn sm ghost" onclick="toggleExecSub(${s.id})">${s.active ? "⏸" : "▶️"}</button>
        <button class="btn sm ghost" onclick="deleteExecSub(${s.id})">🗑</button>` : ""}</td>
    </tr>`).join("") || `<tr><td colspan="5" class="muted">${t("exec_no_subs")}</td></tr>`;
  EXEC.subs = subs;
}

async function saveExecSub() {
  const name = $("#execScName").value.trim();
  if (!name) return toast(t("exec_msg_sub_name"), true);
  try {
    await api("/api/execution/subcontractors", { method: "POST", json: {
      name, trade: $("#execScTrade").value.trim(), phone: $("#execScPhone").value.trim() } });
    $("#execScName").value = ""; $("#execScTrade").value = ""; $("#execScPhone").value = "";
    toast(t("msg_saved"));
    await loadExecExecutors();
    loadExecSubs();
  } catch (e) { toast(e.message, true); }
}

async function toggleExecSub(id) {
  const s = EXEC.subs.find((x) => x.id === id);
  if (!s) return;
  await api("/api/execution/subcontractors", { method: "POST", json: { ...s, active: s.active ? 0 : 1 } });
  await loadExecExecutors();
  loadExecSubs();
}

async function deleteExecSub(id) {
  if (!confirm(t("exec_confirm_delete_sub"))) return;
  await api(`/api/execution/subcontractors/${id}`, { method: "DELETE" });
  await loadExecExecutors();
  loadExecSubs();
}

/* --- طلبات التعديل --- */
async function loadExecRequests() {
  const reqs = await api("/api/execution/edit-requests");
  const isOwner = ME.role === "owner" || ME.is_platform_admin;
  $("#execRequestsList").innerHTML = reqs.map((q) => {
    const newLines = (q.payload.lines || []);
    const statusTag = q.status === "pending"
      ? `<span class="tag" style="background:#f6e3c5">${t("exec_req_pending")}</span>`
      : q.status === "approved"
        ? `<span class="tag admin">${t("exec_req_approved")}</span>`
        : `<span class="tag" style="background:#f3d3d0">${t("exec_req_rejected")}</span>`;
    return `
    <div class="panel" style="margin-top:10px">
      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
        <b>${escH(q.project_name)} — ${q.report_date}</b>
        <span class="muted">${t("exec_req_by")} ${escH(q.requested_by_name)}</span>
        ${statusTag}
        <div style="flex:1"></div>
        ${isOwner && q.status === "pending" ? `
          <button class="btn sm" onclick="decideExecRequest(${q.id}, 'approve')">✅ ${t("exec_req_approve")}</button>
          <button class="btn sm ghost" onclick="decideExecRequest(${q.id}, 'reject')">❌ ${t("exec_req_reject")}</button>` : ""}
      </div>
      ${q.reason ? `<p class="muted">${t("exec_req_reason")}: ${escH(q.reason)}</p>` : ""}
      <div class="table-wrap" style="margin-top:8px"><table>
        <thead><tr><th>${t("exec_line_item")}</th><th>${t("exec_line_unit")}</th>
          <th>${t("exec_line_qty")}</th><th>${t("exec_line_executor")}</th></tr></thead>
        <tbody>${newLines.map((l) => `<tr><td>${escH(l.item || l.name)}</td><td>${escH(l.unit)}</td>
          <td>${l.qty}</td><td>${escH(l.executor_name || "")}</td></tr>`).join("")}</tbody>
      </table></div>
      ${q.decision_note ? `<p class="muted">${t("exec_req_decision_note")}: ${escH(q.decision_note)}</p>` : ""}
    </div>`;
  }).join("") || `<p class="muted">${t("exec_no_requests")}</p>`;
}

async function loadExecRequestsBadge() {
  if (ME.role !== "owner" && !ME.is_platform_admin) return;
  try {
    const reqs = await api("/api/execution/edit-requests");
    const n = reqs.filter((q) => q.status === "pending").length;
    $("#execReqBadge").textContent = n ? `(${n})` : "";
  } catch {}
}

async function decideExecRequest(id, action) {
  const note = action === "reject" ? (prompt(t("exec_req_note_prompt")) || "") : "";
  await api(`/api/execution/edit-requests/${id}/decision`, { method: "POST", json: { action, note } });
  toast(action === "approve" ? t("exec_msg_approved") : t("exec_msg_rejected"));
  loadExecRequests();
  loadExecRequestsBadge();
}

/* --- التكلفة والربحية (مالك/أدمن فقط — الخادم يفرضها أيضاً) --- */
function initExecProfit() {
  const sel = $("#execProfitProject");
  sel.innerHTML = EXEC.projects.map((p) => `<option value="${p.id}">${escH(p.name)}</option>`).join("")
    || `<option value="">${t("exec_no_projects")}</option>`;
  $("#execAgExecutor").innerHTML = EXEC.executors.map((e) =>
    `<option value="${e.type}:${e.id}">${escH(e.label)}</option>`).join("");
  loadExecProfit();
}

async function loadExecProfit() {
  const pid = Number($("#execProfitProject").value || 0);
  if (!pid) {
    $("#execAgreementsTable").innerHTML = ""; $("#execProfitTable").innerHTML = "";
    $("#execProfitCards").innerHTML = ""; return;
  }
  try {
    const items = await api(`/api/execution/projects/${pid}/boq`);
    $("#execBoqList").innerHTML = items.map((i) =>
      `<option value="${escH(i.name)}">${escH(i.unit)}</option>`).join("");
  } catch {}
  const ags = await api(`/api/execution/agreements?project_id=${pid}`);
  $("#execAgreementsTable").innerHTML = ags.map((a) => `
    <tr>
      <td>${escH(a.item)}</td><td>${escH(a.executor_name)}</td><td>${escH(a.unit)}</td>
      <td class="num-cell">${fmt(a.unit_rate)}</td>
      <td><button class="btn sm ghost" onclick="deleteExecAgreement(${a.id})">🗑</button></td>
    </tr>`).join("") || `<tr><td colspan="5" class="muted">${t("exec_ag_empty")}</td></tr>`;

  const pr = await api(`/api/execution/profitability?project_id=${pid}`);
  const tt = pr.totals;
  $("#execProfitCards").innerHTML = `
    <div class="card"><div class="num">${fmt(tt.revenue)}</div><div class="lbl">${t("exec_pr_revenue")}</div></div>
    <div class="card"><div class="num">${fmt(tt.cost)}</div><div class="lbl">${t("exec_pr_cost")}</div></div>
    <div class="card"><div class="num" style="color:${tt.profit >= 0 ? "inherit" : "#c0392b"}">${fmt(tt.profit)}</div><div class="lbl">${t("exec_pr_profit")}</div></div>
    <div class="card"><div class="num">${tt.margin_pct != null ? tt.margin_pct + "%" : "—"}</div><div class="lbl">${t("exec_pr_margin")}</div></div>
    ${tt.missing_rates ? `<div class="card"><div class="num" style="color:#c0392b">${tt.missing_rates}</div><div class="lbl">${t("exec_pr_missing")}</div></div>` : ""}`;
  $("#execProfitTable").innerHTML = pr.rows.map((r) => `
    <tr ${r.over_qty ? 'style="background:#fdf3ec"' : ""}>
      <td>${escH(r.item)}</td><td>${escH(r.executor)}</td>
      <td class="num-cell">${r.executed_qty} / ${r.contract_qty ?? "—"} ${escH(r.unit)}
        ${r.over_qty ? ` <span class="tag" style="background:#f3d3d0">${t("exec_pr_over")}</span>` : ""}</td>
      <td class="num-cell">${r.client_price != null ? fmt(r.client_price) : "—"}</td>
      <td class="num-cell">${r.rate != null ? fmt(r.rate) : `<span class="tag" style="background:#f6e3c5">${t("exec_pr_no_rate")}</span>`}</td>
      <td class="num-cell">${r.revenue != null ? fmt(r.revenue) : "—"}</td>
      <td class="num-cell">${r.cost != null ? fmt(r.cost) : "—"}</td>
      <td class="num-cell" style="color:${(r.profit ?? 0) >= 0 ? "inherit" : "#c0392b"}">${r.profit != null ? fmt(r.profit) : "—"}</td>
      <td class="num-cell">${r.margin_pct != null ? r.margin_pct + "%" : "—"}</td>
    </tr>`).join("") || `<tr><td colspan="9" class="muted">${t("exec_no_data")}</td></tr>`;
  if (!pr.project.linked_proposal)
    $("#execProfitTable").innerHTML += `<tr><td colspan="9" class="muted">${t("exec_pr_link_hint")}</td></tr>`;
}

async function saveExecAgreement() {
  const item = $("#execAgItem").value.trim();
  const rate = $("#execAgRate").value;
  if (!item || rate === "") return toast(t("exec_ag_required"), true);
  const [type, id] = $("#execAgExecutor").value.split(":");
  await api("/api/execution/agreements", { method: "POST", json: {
    project_id: Number($("#execProfitProject").value || 0),
    subcontractor_id: type === "subcontractor" ? Number(id) : 0,
    item, unit: $("#execAgUnit").value.trim(), unit_rate: Number(rate),
  } });
  $("#execAgItem").value = ""; $("#execAgUnit").value = ""; $("#execAgRate").value = "";
  toast(t("msg_saved"));
  loadExecProfit();
}

async function deleteExecAgreement(id) {
  await api(`/api/execution/agreements/${id}`, { method: "DELETE" });
  loadExecProfit();
}

async function testNotifyChannels() {
  try {
    const r = await api("/api/notify/test", { method: "POST", json: {} });
    toast(`${t("notify_test_email")}: ${r.email} — ${t("notify_test_wa")}: ${r.whatsapp}`,
          r.email.startsWith("فشل") || r.whatsapp.startsWith("فشل"));
  } catch (e) { toast(e.message, true); }
}
