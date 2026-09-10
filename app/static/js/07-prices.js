/* ---------- قاعدة الأسعار ---------- */
async function loadPrices() {
  const search = $("#prSearch").value || "";
  const cat = $("#prFilterCat").value || "";
  const items = await api(`/api/prices?search=${encodeURIComponent(search)}&category=${encodeURIComponent(cat)}`);

  const cats = [...new Set((await api("/api/prices")).map((i) => i.category))];
  $("#catList").innerHTML = cats.map((c) => `<option value="${c}">`).join("");
  const filterSel = $("#prFilterCat");
  if (filterSel.options.length <= 1) {
    filterSel.innerHTML = `<option value="">${t("all_categories")}</option>` + cats.map((c) => `<option>${c}</option>`).join("");
  } else {
    filterSel.options[0].textContent = t("all_categories");
  }

  $("#pricesTable tbody").innerHTML = items.map((i) => `
    <tr>
      <td class="num-cell">${i.code}</td><td>${i.category}</td><td>${i.name}</td><td>${i.unit}</td>
      <td class="num-cell"><b>${fmt(i.unit_price)}</b></td>
      <td class="num-cell muted">${i.updated_at.slice(0, 10)}</td>
      <td>
        <button class="btn sm ghost" onclick='fillPriceForm(${JSON.stringify(i).replace(/'/g, "&#39;")})'>${t("edit_btn")}</button>
        <button class="btn sm danger" onclick="removePrice(${i.id})">${t("delete_btn")}</button>
      </td>
    </tr>`).join("");
}

function fillPriceForm(i) {
  $("#prCode").value = i.code; $("#prCat").value = i.category;
  $("#prName").value = i.name; $("#prUnit").value = i.unit;
  $("#prPrice").value = i.unit_price;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function savePrice() {
  const item = {
    code: $("#prCode").value.trim(), category: $("#prCat").value.trim(),
    name: $("#prName").value.trim(), unit: $("#prUnit").value.trim(),
    unit_price: Number($("#prPrice").value),
  };
  if (!item.code || !item.name || !item.category || !item.unit) return toast(t("msg_fill_required"), true);
  await api("/api/prices", { method: "POST", json: item });
  toast(t("msg_price_saved"));
  ["prCode", "prCat", "prName", "prUnit", "prPrice"].forEach((id) => $("#" + id).value = "");
  loadPrices();
}

async function removePrice(id) {
  if (!confirm(t("confirm_delete_price"))) return;
  await api(`/api/prices/${id}`, { method: "DELETE" });
  loadPrices();
}

$("#csvImport").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  const res = await api("/api/prices/import/csv", { method: "POST", body: form });
  toast(`${t("msg_csv_imported")} ${res.imported} ${t("msg_csv_imported_suffix")}`);
  loadPrices();
});
