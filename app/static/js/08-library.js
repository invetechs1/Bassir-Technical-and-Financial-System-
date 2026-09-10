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
