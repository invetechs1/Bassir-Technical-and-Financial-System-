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
