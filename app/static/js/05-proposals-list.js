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
