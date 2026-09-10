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
