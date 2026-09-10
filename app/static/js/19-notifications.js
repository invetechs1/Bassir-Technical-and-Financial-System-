/* ---------- الإشعارات ---------- */
async function loadNotifs() {
  try {
    const n = await api("/api/notifications");
    const b = $("#notifBadge");
    b.hidden = !n.unread;
    b.textContent = n.unread > 99 ? "99+" : n.unread;
    $("#notifList").innerHTML = n.items.map((i) => `
      <button style="display:block;width:100%;text-align:start;border:0;background:${i.is_read ? "transparent" : "var(--accent-soft)"};padding:8px;border-radius:8px;cursor:pointer;margin-bottom:4px"
              onclick="openNotif(${i.id}, '${escH(i.ref)}')">
        <b style="font-size:12.5px">${escH(i.title)}</b><br>
        <span class="muted" style="font-size:11.5px">${escH(i.body)}</span><br>
        <span class="muted" style="font-size:10.5px">${(i.created_at || "").slice(0, 16).replace("T", " ")}</span>
      </button>`).join("") || `<p class="muted" style="padding:8px">${t("notif_empty")}</p>`;
  } catch {}
}

function toggleNotifMenu() {
  const m = $("#notifMenu");
  m.hidden = !m.hidden;
  if (!m.hidden) loadNotifs();
}
document.addEventListener("click", (e) => {
  if (!e.target.closest("#notifWrap")) $("#notifMenu").hidden = true;
});

async function openNotif(id, ref) {
  await api("/api/notifications/read", { method: "POST", json: { id } });
  $("#notifMenu").hidden = true;
  loadNotifs();
  if ((ref || "").startsWith("edit_request:")) { go("execution"); setTimeout(() => execTab("requests"), 300); }
  else if ((ref || "").startsWith("report:")) { go("execution"); }
}

async function markAllNotifs() {
  await api("/api/notifications/read", { method: "POST", json: {} });
  loadNotifs();
}
