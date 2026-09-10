/* ---------- الإعدادات ---------- */
async function loadSettings() {
  const s = await api("/api/settings");
  $$("[data-key]").forEach((el) => { el.value = s[el.dataset.key] ?? ""; });
}

async function saveSettings() {
  const values = {};
  $$("[data-key]").forEach((el) => { values[el.dataset.key] = el.value; });
  await api("/api/settings", { method: "PUT", json: values });
  toast(t("msg_settings_saved"));
}
