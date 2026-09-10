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
