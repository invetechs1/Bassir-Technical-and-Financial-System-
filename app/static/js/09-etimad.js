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
