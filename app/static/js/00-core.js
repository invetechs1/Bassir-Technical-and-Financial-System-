/* نظام عزوم — منطق الواجهة */
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

const STATUS_KEY = { draft: "st_draft", submitted: "st_submitted", won: "st_won", lost: "st_lost" };
const SECTOR_KEY = { government: "sector_gov", private: "sector_private", pif: "sector_pif", airports: "sector_airports", "": "sector_general" };
const fmt = (n) => Number(n || 0).toLocaleString(getLang() === "ar" ? "ar-SA" : "en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

let currentProposal = null;
let pendingFiles = [];

/* عند تبديل اللغة: أعد رسم أي محتوى ديناميكي معروض حالياً */
function onLangChange() {
  refreshEngineStatus();
  const active = $(".page.active");
  if (active) go(active.id.replace("page-", ""));
  if (currentProposal && active && active.id === "page-viewer") viewProposal(currentProposal);
}

let lastAiEnabled = null;
async function refreshEngineStatus() {
  if (lastAiEnabled === null) {
    try { lastAiEnabled = (await api("/api/status")).ai_enabled; } catch { return; }
  }
  $("#engineBadge").innerHTML = lastAiEnabled ? t("ai_engine_badge_on") : t("ai_engine_badge_off");
  $("#engineHint").textContent = lastAiEnabled ? t("ai_engine_hint_on") : t("ai_engine_hint_off");
}
