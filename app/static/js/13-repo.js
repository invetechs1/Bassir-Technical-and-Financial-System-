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
