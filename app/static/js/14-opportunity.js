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
