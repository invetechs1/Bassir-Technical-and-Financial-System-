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
