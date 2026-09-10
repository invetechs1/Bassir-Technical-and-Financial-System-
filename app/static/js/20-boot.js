/* ---------- بدء التشغيل ---------- */
loadMe().then(() => {
  if (ME.role === "engineer") go("execution");
  else loadDashboard();
  loadNotifs();
  setInterval(loadNotifs, 60000);
});
