/* ---------- مشاريع منصة فرصة ---------- */
const FS_STATUSES = ["جديد", "مهتمون", "مستبعد", "أُنشئ عرض"];
let forsahCredsLoaded = false;

async function loadForsahCreds() {
  if (forsahCredsLoaded) return;
  const s = await api("/api/settings");
  $("#forsahEmail").value = s.forsah_email || "";
  if (s.forsah_password) $("#forsahPassword").placeholder = "•••••• (محفوظة — اكتب لتغييرها)";
  forsahCredsLoaded = true;
}

async function saveForsahCreds() {
  const email = $("#forsahEmail").value.trim();
  const pw = $("#forsahPassword").value;
  const payload = { forsah_email: email };
  if (pw) payload.forsah_password = pw;
  await api("/api/settings", { method: "PUT", json: payload });
  $("#forsahPassword").value = "";
  $("#forsahPassword").placeholder = "•••••• (محفوظة — اكتب لتغييرها)";
  toast("💾 حُفظت بيانات دخول فرصة محلياً في قاعدة بيانات النظام");
}

async function fetchForsah() {
  $("#forsahFetchBtn").disabled = true;
  $("#fsSpinner").classList.add("on");
  try {
    const r = await api("/api/forsah/fetch", { method: "POST" });
    if (r.ok) {
      const cats = Object.entries(r.by_category || {}).filter(([, n]) => n)
        .map(([c, n]) => `${c}: ${n}`).join("، ");
      toast(`✅ فُحص ${r.scanned} مشروعاً وأُضيف ${r.added} جديداً${cats ? " — " + cats : ""}`);
      if (r.note) setTimeout(() => toast("⚠️ " + r.note, true), 2500);
    } else toast(r.error, true);
    loadForsah();
  } catch (err) {
    toast("فشل السحب: " + err.message, true);
  } finally {
    $("#forsahFetchBtn").disabled = false;
    $("#fsSpinner").classList.remove("on");
  }
}

async function loadForsah() {
  loadForsahCreds();
  const params = new URLSearchParams({
    q: $("#fsQ").value.trim(),
    category: $("#fsCategory").value,
    status: $("#fsStatus").value,
  });
  const data = await api(`/api/forsah?${params}`);
  $("#forsahTable tbody").innerHTML = data.projects.map((p) => `
    <tr>
      <td><a href="${p.details_url}" target="_blank" rel="noopener" style="color:var(--primary);font-weight:600">${p.title.slice(0, 70)}</a>
        ${p.matched_ref ? `<br><span class="muted" style="font-size:11px">أقرب خبرة: ${p.matched_ref.slice(0, 50)}</span>` : ""}</td>
      <td><span class="tag est">${p.category}</span></td>
      <td class="num-cell">${p.budget || "—"}</td>
      <td class="num-cell">${p.deadline || "—"}</td>
      <td><span class="fit${p.relevance < 15 ? " low" : ""}"><i style="width:${Math.min(p.relevance * 2, 100)}%"></i></span> <span class="num-cell">${p.relevance}%</span></td>
      <td><select onchange="setFsStatus(${p.id}, this.value)" style="padding:4px 8px;font-size:12px">
        ${FS_STATUSES.map((s) => `<option ${s === p.status ? "selected" : ""}>${s}</option>`).join("")}</select></td>
      <td>
        <button class="btn sm ghost" onclick="fsToProposal('${p.title.replace(/'/g, "&#39;").slice(0, 90)}')">✨ أنشئ عرضاً</button>
      </td>
    </tr>`).join("") ||
    `<tr><td colspan="7" class="muted">لا مشاريع مخزنة — احفظ بيانات الدخول ثم اضغط «سحب المشاريع من فرصة»</td></tr>`;
}

function setFsStatus(id, status) {
  api(`/api/forsah/${id}`, { method: "PUT", json: { status } }).then(() => toast("تم تحديث الحالة"));
}

function fsToProposal(title) {
  go("new");
  $("#npTitle").value = title;
  $("#npEntity").value = "private";
  suggestSimilar();
  toast("حُمّل اسم المشروع — أدخل اسم العميل وارفع ملفات المشروع ثم اضغط توليد");
}
