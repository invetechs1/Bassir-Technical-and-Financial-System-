/* ---------- عارض العرض ---------- */
$$(".tab-btn").forEach((b) => b.addEventListener("click", () => {
  $$(".tab-btn").forEach((x) => x.classList.toggle("active", x === b));
  $$(".tab-pane").forEach((p) => p.classList.toggle("active", p.id === `tab-${b.dataset.tab}`));
}));

function viewProposal(p) {
  currentProposal = p;
  go("viewer");
  $$(".nav-btn").forEach((b) => b.classList.remove("active"));
  $("#vTitle").textContent = `${p.ref_no} — ${p.title}`;
  const engine = p.data.engine === "claude" ? t("engine_claude")
    : p.data.reference ? t("engine_reference") : t("engine_template");
  let meta = `${p.client} • ${t(SECTOR_KEY[p.entity_type]) || p.entity_type} • ${engine}`;
  if (p.data.similar_refs?.length) {
    meta += ` • ${t("built_on_label")} ${p.data.similar_refs.map((r) => `${r.title.slice(0, 30)}… (${r.score}%)`).join("، ")}`;
  }
  $("#vMeta").textContent = meta + (p.data.project_kind ? " • " + t("kind_label") + " " + p.data.project_kind : "");
  $("#vStatus").value = p.status;
  renderTech(p.data);
  renderFin(p.data);
  renderPlan(p.data);
}

let showProvenance = false;
function toggleProvenance() { showProvenance = !showProvenance; renderTech(currentProposal.data); }

function renderTech(d) {
  let html = "";
  const st = d.style || {};
  if (st.total_sections) {
    html += `<div class="alert" style="background:#F4FAF6;border-color:#D8E8DD;color:#4A5B51">
      <div><b>${t("style_bar_title")}</b> <span class="num-cell">${st.score}%</span>
      — ${st.bank_sections} ${t("style_bar_of")} ${st.total_sections} ${t("style_bar_frombank")}</div>
      <button class="btn ghost sm" onclick="toggleProvenance()">${showProvenance ? t("style_bar_hide") : t("style_bar_show")}</button>
    </div>`;
  }
  html += (d.technical_sections || []).map((s) =>
    `<div class="panel section-block"><h4>${s.title}
       ${showProvenance && s.source ? (s.source === "bank"
         ? `<span class="tag src" title="${s.source_ref || ""}">${t("prov_bank")}</span>`
         : `<span class="tag est">${t("prov_new")}</span>`) : ""}</h4><p>${s.body}</p></div>`).join("");

  if (d.team?.length) {
    html += `<div class="panel section-block"><h4>${t("team_title")}</h4>
      <div class="t-wrap"><table><thead><tr><th>${t("th_role")}</th><th>${t("th_count")}</th></tr></thead><tbody>
      ${d.team.map((t2) => `<tr><td>${t2.role}</td><td>${t2.count}</td></tr>`).join("")}
      </tbody></table></div></div>`;
  }
  if (d.compliance_matrix?.length) {
    html += `<div class="panel section-block"><h4>${t("compliance_title")}</h4>
      <div class="t-wrap"><table><thead><tr><th>${t("th_requirement")}</th><th>${t("th_compliance")}</th><th>${t("th_reference")}</th></tr></thead><tbody>
      ${d.compliance_matrix.map((m) => `<tr><td>${m.requirement}</td><td>${m.response}</td><td>${m.reference}</td></tr>`).join("")}
      </tbody></table></div></div>`;
  }
  $("#tab-tech").innerHTML = html;
}

function renderFin(d) {
  const boq = d.boq || [];
  const f = d.financial || {};
  const cur = t("currency");
  $("#tab-fin").innerHTML = `
    <div class="panel">
      <h3>${t("boq_title")} <span class="muted">${t("boq_hint")}</span></h3>
      <div class="t-wrap"><table>
        <thead><tr><th>${t("th_num")}</th><th>${t("th_code")}</th><th>${t("th_item")}</th><th>${t("th_unit")}</th><th>${t("th_qty")}</th><th>${t("th_unit_price")}</th><th>${t("th_total")}</th><th>${t("th_source")}</th><th></th></tr></thead>
        <tbody>${boq.map((l, i) => renderBoqRow(l, i)).join("")}</tbody>
      </table></div>
      <div class="mt"><button class="btn ghost sm" onclick="addBoqLine()">${t("add_item_btn")}</button></div>
    </div>
    <div class="panel fin-summary">
      <h3>${t("fin_summary_title")}</h3>
      <div class="fin-row"><span>${t("fin_direct_cost")}</span><span class="num-cell">${fmt(f.direct_cost)} ${cur}</span></div>
      <div class="fin-row"><span>${t("fin_overhead")} (${f.overhead_pct ?? 0}%)</span><span class="num-cell">${fmt(f.overhead)} ${cur}</span></div>
      <div class="fin-row"><span>${t("fin_risk")} (${f.risk_pct ?? 0}%)</span><span class="num-cell">${fmt(f.risk)} ${cur}</span></div>
      <div class="fin-row"><span>${t("fin_profit")} (${f.profit_pct ?? 0}%)</span><span class="num-cell">${fmt(f.profit)} ${cur}</span></div>
      <div class="fin-row"><span>${t("fin_subtotal")}</span><span class="num-cell">${fmt(f.subtotal)} ${cur}</span></div>
      <div class="fin-row"><span>${t("fin_vat")} (${f.vat_rate ?? 15}%)</span><span class="num-cell">${fmt(f.vat)} ${cur}</span></div>
      <div class="fin-row total"><span>${t("fin_grand_total")}</span><span class="v num-cell">${fmt(f.grand_total)} ${cur}</span></div>
      <p class="muted mt">${t("fin_bid_bond")} (${f.bid_bond_pct ?? 1}%): <b>${fmt(f.bid_bond)} ${cur}</b></p>
      <p class="muted mt" style="border-top:1px solid var(--line);padding-top:8px">🔒 ${t("fin_internal_note")}</p>
    </div>
    ${(d.assumptions || []).length ? `<div class="panel"><h3>${t("assumptions_title")}</h3>${d.assumptions.map((a) => `<p class="muted">• ${a}</p>`).join("")}</div>` : ""}`;
}

function renderBoqRow(l, i) {
  const kids = l.children || [];
  const hasKids = kids.length > 0;
  const parentRow = `
    <tr class="${hasKids ? "boq-parent" : ""}">
      <td>${i + 1}</td>
      <td class="num-cell">${l.code || "—"}</td>
      <td>${l.name}</td>
      <td>${l.unit}</td>
      <td style="width:90px"><input type="number" value="${l.qty}" step="0.01" onchange="editBoq(${i},'qty',this.value)"></td>
      <td style="width:120px">${hasKids
        ? `<input type="number" value="${l.unit_price}" disabled title="${t("boq_computed_hint")}">`
        : `<input type="number" value="${l.unit_price}" step="0.01" onchange="editBoq(${i},'unit_price',this.value)">`}</td>
      <td class="num-cell">${fmt(l.total)}</td>
      <td><span class="tag ${l.source === "قاعدة الأسعار" ? "src" : "est"}">${boqSourceLabel(l.source)}</span></td>
      <td>
        <button class="btn sm ghost" onclick="addBoqSubItem(${i})" title="${t("add_sub_item_hint")}">${t("add_sub_item_btn")}</button>
        <button class="btn sm danger" onclick="removeBoqLine(${i})">✕</button>
      </td>
    </tr>`;
  const subRows = kids.map((c, j) => `
    <tr class="boq-sub-row${j === kids.length - 1 ? " last" : ""}">
      <td class="muted num-cell">${i + 1}.${j + 1}</td>
      <td></td>
      <td><div class="boq-sub-name"><span class="boq-sub-arrow">↳</span><input type="text" value="${c.name}" onchange="editBoqSub(${i},${j},'name',this.value)"></div></td>
      <td style="width:80px"><input type="text" value="${c.unit ?? l.unit}" onchange="editBoqSub(${i},${j},'unit',this.value)"></td>
      <td style="width:90px"><input type="number" value="${c.qty ?? l.qty}" step="0.01" onchange="editBoqSub(${i},${j},'qty',this.value)"></td>
      <td style="width:120px"><input type="number" value="${c.unit_price}" step="0.01" onchange="editBoqSub(${i},${j},'unit_price',this.value)"></td>
      <td class="num-cell muted">${fmt(c.total ?? ((c.qty ?? l.qty) * c.unit_price))}</td>
      <td></td>
      <td><button class="btn sm danger" onclick="removeBoqSub(${i},${j})">✕</button></td>
    </tr>`).join("");
  return parentRow + subRows;
}

function companyStatusTag(status) {
  const map = { active: ["submitted", "status_active"], read_only: ["draft", "status_readonly"],
               suspended: ["lost", "status_suspended"] };
  const [cls, key] = map[status] || ["est", "status_active"];
  return `<span class="tag ${cls}">${t(key)}</span>`;
}

function boqSourceLabel(source) {
  if (source === "قاعدة الأسعار") return t("source_catalog");
  if (source === "معدّل يدوياً") return t("source_manual_edit");
  if (source === "يدوي") return t("source_manual");
  return source || t("source_estimate");
}

function renderPlan(d) {
  const plan = d.plan || [];
  const totalWeeks = plan.reduce((s, p) => s + Number(p.duration_weeks || 0), 0) || 1;
  let start = 0;
  const gantt = plan.map((p) => {
    const width = (p.duration_weeks / totalWeeks) * 100;
    const bar = `<div class="gantt-row">
      <div class="gantt-label">${p.phase}</div>
      <div class="gantt-track"><div class="gantt-bar" style="inset-inline-start:${(start / totalWeeks) * 100}%;width:${width}%"></div></div>
    </div>`;
    start += Number(p.duration_weeks || 0);
    return bar;
  }).join("");

  $("#tab-plan").innerHTML = `
    <div class="panel">
      <h3>${t("plan_title")} ${d.duration_weeks || totalWeeks} ${t("weeks_label")}</h3>
      ${plan.map((p, i) => `
        <div class="phase">
          <h4>${t("phase_label")} ${i + 1}: ${p.phase} <span class="dur">(${p.duration_weeks} ${t("weeks_label_short")})</span></h4>
          <p>${p.description}</p>
          <ul>${(p.deliverables || []).map((x) => `<li>${x}</li>`).join("")}</ul>
        </div>`).join("")}
      <h3 class="mt">${t("timeline_title")}</h3>
      <div class="gantt">${gantt}</div>
    </div>`;
}

async function saveBoqChanges() {
  currentProposal = await api(`/api/proposals/${currentProposal.id}`, {
    method: "PUT",
    json: { data: currentProposal.data },
  });
  renderFin(currentProposal.data);
}

function editBoq(i, field, value) {
  currentProposal.data.boq[i][field] = Number(value);
  if (field === "unit_price") currentProposal.data.boq[i].source = "معدّل يدوياً";
  saveBoqChanges();
}
function removeBoqLine(i) {
  currentProposal.data.boq.splice(i, 1);
  saveBoqChanges();
}
function addBoqLine() {
  const name = prompt(t("new_item_prompt"));
  if (!name) return;
  currentProposal.data.boq.push({ code: "", name, unit: "وحدة", qty: 1, unit_price: 0, source: "يدوي" });
  saveBoqChanges();
}

/* مراحل فرعية داخل بند واحد: نفس الكمية، وسعر البند الأب = مجموع أسعار مراحله */
let _subItemTargetIndex = null;

function addBoqSubItem(i) {
  _subItemTargetIndex = i;
  const line = currentProposal.data.boq[i];
  $("#boqStageLabel").value = "";
  $("#boqStagePrice").value = "0";
  $("#boqStageQty").value = line.qty || 1;
  $("#boqStageUnit").value = line.unit || "وحدة";
  $("#subItemModal").style.display = "flex";
  $("#boqStageLabel").focus();
}
function closeSubItemModal() {
  $("#subItemModal").style.display = "none";
  _subItemTargetIndex = null;
}
function confirmAddSubItem() {
  const name = $("#boqStageLabel").value.trim();
  if (!name) return toast(t("msg_sub_item_name_required"), true);
  const price = Number($("#boqStagePrice").value || 0);
  const line = currentProposal.data.boq[_subItemTargetIndex];
  if (!line.children) line.children = [];
  line.children.push({
    name,
    unit: $("#boqStageUnit").value.trim() || line.unit || "وحدة",
    qty: Number($("#boqStageQty").value || line.qty || 1),
    unit_price: price,
  });
  closeSubItemModal();
  saveBoqChanges();
}
function editBoqSub(i, j, field, value) {
  currentProposal.data.boq[i].children[j][field] =
    (field === "unit_price" || field === "qty") ? Number(value) : value;
  saveBoqChanges();
}
function removeBoqSub(i, j) {
  const line = currentProposal.data.boq[i];
  line.children.splice(j, 1);
  if (!line.children.length) delete line.children;
  saveBoqChanges();
}

async function changeStatus() {
  currentProposal = await api(`/api/proposals/${currentProposal.id}`, {
    method: "PUT", json: { status: $("#vStatus").value },
  });
  toast(t("msg_status_updated"));
}

function exportDocx() { window.location = `/api/proposals/${currentProposal.id}/export/docx`; }
function exportXlsx() { window.location = `/api/proposals/${currentProposal.id}/export/xlsx`; }
