/* ---------- تنقّل ---------- */
function go(page) {
  if (ME.role === "engineer" && page !== "execution") page = "execution";
  if ((ADMIN_PAGES.includes(page) && !ME.is_admin) ||
      (PLATFORM_PAGES.includes(page) && !ME.is_platform_admin)) {
    $$(".page").forEach((p) => p.classList.remove("active"));
    $("#page-denied").classList.add("active");
    $("#deniedRole").textContent = ME.role_ar || ME.role;
    return;
  }
  $$(".page").forEach((p) => p.classList.remove("active"));
  $(`#page-${page}`).classList.add("active");
  $$(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.page === page));
  if (page === "dashboard") loadDashboard();
  if (page === "proposals") loadProposals();
  if (page === "prices") loadPrices();
  if (page === "library") loadLibrary();
  if (page === "etimad") loadEtimad();
  if (page === "forsah") loadForsah();
  if (page === "repo") loadRepo();
  if (page === "docs") loadDocs();
  if (page === "analytics") loadAnalytics();
  if (page === "settings") loadSettings();
  if (page === "tenants") loadTenants();
  if (page === "billing") loadBillingPage();
  if (page === "execution") loadExecution();
  const navBtn = document.querySelector(`.nav-btn[data-page="${page}"]`);
  const titleEl = document.getElementById("pageTitle");
  if (navBtn && titleEl) titleEl.textContent = (navBtn.childNodes[0]?.nodeValue || navBtn.textContent).trim();
}

const setCount = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v ?? "—"; };
async function loadNavCounts() {
  try {
    const c = await api("/api/status");
    setCount("cntProposals", c.proposals);
    setCount("cntPrices", c.price_items);
    setCount("cntLibrary", c.library);
    setCount("cntRepo", c.repo_files);
    setCount("cntEtimad", c.etimad);
    setCount("cntForsah", c.forsah);
    setCount("cntDocs", c.docs);
  } catch {}
}
$$(".nav-btn").forEach((b) => b.addEventListener("click", () => go(b.dataset.page)));

function toast(msg, isErr = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast show" + (isErr ? " err" : "");
  setTimeout(() => t.classList.remove("show"), 3500);
}

async function api(url, opts = {}) {
  if (opts.json) {
    opts.body = JSON.stringify(opts.json);
    opts.headers = { "Content-Type": "application/json" };
    delete opts.json;
  }
  const res = await fetch(url, opts);
  if (res.status === 401) { location.href = "/login"; throw new Error(t("msg_session_expired")); }
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return res.json();
}

async function logout() {
  await fetch("/api/logout", { method: "POST" });
  location.href = "/login";
}

async function savePassword() {
  const oldPw = $("#pwOld").value, newPw = $("#pwNew").value;
  if (!oldPw || !newPw) return toast(t("msg_enter_pw_both"), true);
  try {
    await api("/api/password", { method: "POST", json: { old: oldPw, new: newPw } });
    toast(t("msg_pw_changed"));
    $("#pwOld").value = ""; $("#pwNew").value = "";
  } catch (err) { toast(err.message, true); }
}
