/* ---------- المستودع الفني ومحرك الأسلوب ---------- */
function repoTab(which) {
  $$("[data-repo-tab]").forEach((b) => b.classList.toggle("active", b.dataset.repoTab === which));
  $("#repoTabFin").hidden = which !== "fin";
  $("#repoTabTech").hidden = which !== "tech";
  if (which === "tech") loadTechRepo();
}

async function loadTechRepo() {
  const [data, bank] = await Promise.all([
    api("/api/repository/technical"), api("/api/paragraph-bank")]);
  const pr = data.profile || {};
  const gl = JSON.parse(pr.glossary_json || "[]");
  $("#styleProfileBox").innerHTML = pr.sample_count ? `
    <div class="grid-3">
      <div><b>${t("sp_sentence")}</b><br>${pr.avg_sentence_len} ${t("sp_words")}</div>
      <div><b>${t("sp_voice")}</b><br>${pr.voice === "first_person_plural" ? t("sp_voice_we") : t("sp_voice_co")}</div>
      <div><b>${t("sp_secwords")}</b><br>${pr.avg_section_words} ${t("sp_words")}</div>
      <div><b>${t("sp_samples")}</b><br>${pr.sample_count} ${t("sp_paras")} / ${pr.docs} ${t("sp_docs")}</div>
      <div style="grid-column:span 2"><b>${t("sp_glossary")}</b><br><span class="muted">${gl.slice(0, 12).join("، ") || "—"}</span></div>
    </div>
    ${pr.reliable ? "" : `<div class="alert mt">${t("sp_unreliable")}</div>`}` :
    `<div class="alert">${t("sp_empty")}</div>`;

  $("#paraBank").innerHTML = bank.map((b) => `
    <div class="card" style="text-align:start">
      <div class="row mb" style="justify-content:space-between">
        <span class="tag ${b.approved ? "src" : "est"}">${b.title.slice(0, 25)}</span>
        <span class="muted" style="font-size:11px">${t("bank_used")} ${b.use_count}</span>
      </div>
      <p class="muted" style="font-size:12px;line-height:1.8">${b.body.slice(0, 180)}…</p>
      <button class="btn sm ${b.approved ? "ghost" : ""}" onclick="toggleParagraph(${b.id}, ${b.approved ? 0 : 1})">
        ${b.approved ? t("bank_unapprove") : t("bank_approve")}</button>
    </div>`).join("") || `<p class="muted">${t("bank_empty")}</p>`;

  $("#techDocsTable tbody").innerHTML = data.documents.map((d) => `
    <tr>
      <td class="ellipsis">${d.filename}</td>
      <td><span class="tag ${d.doc_kind === "competitor" ? "est" : "gov"}">${d.doc_kind === "competitor" ? t("kind_competitor") : t("kind_azoom")}</span></td>
      <td>${d.project_kind || "—"}</td>
      <td class="num-cell">${d.sections_count}</td>
      <td class="num-cell">${d.paragraphs_count}</td>
      <td>${d.is_style_source ? `<span class="tag src">${t("style_src_yes")}</span>` : "—"}</td>
    </tr>`).join("") || `<tr><td colspan="6" class="muted">${t("tech_docs_empty")}</td></tr>`;
}

async function toggleParagraph(id, approved) {
  await api(`/api/paragraphs/${id}`, { method: "PUT", json: { approved: !!approved } });
  loadTechRepo();
}

async function rebuildStyle() {
  const pr = await api("/api/style-profile/rebuild", { method: "POST" });
  toast(`↻ ${t("style_rebuilt")} — ${pr.sample_count} ${t("sp_paras")}`);
  loadTechRepo();
}
