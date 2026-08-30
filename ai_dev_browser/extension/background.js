// AI Dev Browser — extension bridge.
//
// Connects OUT to ai-dev-browser's local bridge (WS client — extensions can't
// listen) and relays CDP both ways. ai-dev-browser then drives your real Chrome
// with the same CDP it already speaks — over the permissioned extension
// channel, so it works on your real logged-in profile without
// --remote-debugging-port. Only active while ai-dev-browser is connected.
//
// This side is a small CDP browser endpoint: it answers the browser-level
// Target/Storage domains from chrome.tabs / chrome.cookies, and forwards
// everything else to chrome.debugger on the addressed tab. That lets adb's
// ordinary tab machinery (tab_list / tab_switch / get_active_tab) work here
// unchanged.
//
// Multi-tab: we drive a DEDICATED automation tab and FOLLOW tabs our automation
// opens (an OAuth "Continue with Google" popup, a magic-link new tab) — but we
// NEVER attach to a tab the user opened. A new tab is followed only if the tab
// whose content opened it is one we already drive — keyed on webNavigation's
// sourceTabId (reliable for a backgrounded caller), with tabs.onCreated's
// openerTabId as a fallback.
//
// Wire protocol with the bridge:
//   bridge -> ext : { _gid, tab, method, params }   (tab = targetId or null)
//   ext -> bridge : { _gid, result } | { _gid, error }        (command reply)
//                 : { _event_tab, method, params }             (CDP event)
//                 : { _hello, account }                        (handshake)
//
// NOTE: bridge port is the fixed convention shared with core/extension.py
// (EXTENSION_BRIDGE_PORT). Keep the two in sync.
const BRIDGE = "ws://127.0.0.1:9522";
const PROTOCOL = "1.3";
const BADGE_COLOR = "#5b49e6"; // sudoprivacy purple

let ws = null;
let connecting = false;

// Automation session state. targetId (string) == chrome tabId as a string.
let mainTabId = null; // the DEDICATED tab we create (never a user's tab)
const autoTabs = new Set(); // chrome tabIds we own + have attached debugger to
const attached = new Set(); // subset of autoTabs with a live chrome.debugger

const dbg = (tid) => ({ tabId: Number(tid) });

async function profileAccount() {
  // Which profile/account is this? So browser_connect can tell you WHICH Chrome
  // it's driving (the extension runs in the profile it was loaded into).
  try {
    const info = await chrome.identity.getProfileUserInfo({ accountStatus: "ANY" });
    return (info && info.email) || null;
  } catch {
    try {
      return await new Promise((res) =>
        chrome.identity.getProfileUserInfo((i) => res((i && i.email) || null)));
    } catch { return null; }
  }
}

function markTab(tabId) {
  // Per-tab toolbar badge so a human can see at a glance which tabs the agent is
  // driving — without injecting anything into the page itself.
  try {
    chrome.action.setBadgeText({ tabId, text: "AI" });
    chrome.action.setBadgeBackgroundColor({ tabId, color: BADGE_COLOR });
  } catch { /* action API unavailable — cosmetic only */ }
}

// --- MV3 lifetime -----------------------------------------------------------
// chrome.debugger sessions drop when the service worker is suspended (~30s
// idle), and a human OAuth-consent step easily exceeds that. Two defenses:
//  (1) keepalive: while we hold any automation tab, ping a trivial async API
//      every 20s to reset the idle timer so the debugger isn't severed mid-flow;
//  (2) persistence: mirror {mainTabId, autoTabs} into chrome.storage.session
//      (survives a worker restart within the browser session) so a woken worker
//      re-adopts the SAME tabs instead of orphaning them / spawning duplicates.
let keepalive = null;

function syncKeepalive() {
  if (autoTabs.size > 0 && keepalive == null) {
    keepalive = setInterval(() => {
      try { chrome.runtime.getPlatformInfo(() => void chrome.runtime.lastError); } catch { /* noop */ }
    }, 20000);
  } else if (autoTabs.size === 0 && keepalive != null) {
    clearInterval(keepalive);
    keepalive = null;
  }
}

function persist() {
  try {
    chrome.storage.session.set({ adbMainTabId: mainTabId, adbAutoTabs: [...autoTabs] });
  } catch { /* storage unavailable — keepalive still holds in-memory state */ }
}

async function restore() {
  try {
    const s = await chrome.storage.session.get(["adbMainTabId", "adbAutoTabs"]);
    if (s.adbMainTabId != null) mainTabId = s.adbMainTabId;
    if (Array.isArray(s.adbAutoTabs)) {
      for (const id of s.adbAutoTabs) autoTabs.add(id);
    }
  } catch { /* first run / no storage */ }
}

async function attachTab(tabId) {
  // Attach chrome.debugger to a tab WE own. Idempotent.
  if (!attached.has(tabId)) {
    try {
      await chrome.debugger.attach(dbg(tabId), PROTOCOL);
    } catch (e) {
      if (!/already|Another debugger/i.test(String(e))) throw e;
    }
    attached.add(tabId);
    markTab(tabId);
  }
  autoTabs.add(tabId);
  syncKeepalive();
  persist();
}

// Follow a tab OUR automation opened, retrying briefly — a just-created popup
// can reject the first attach while it's still committing its first navigation.
async function followTab(tabId) {
  for (let i = 0; i < 6; i++) {
    try { await attachTab(tabId); return; }
    catch { await new Promise((r) => setTimeout(r, 250)); }
  }
}

function forget(tabId) {
  autoTabs.delete(tabId);
  attached.delete(tabId);
  if (tabId === mainTabId) mainTabId = null;
  syncKeepalive();
  persist();
}

async function ensureDedicatedTab() {
  // Reuse our own tab across reconnects; recreate if the user closed it. We
  // NEVER attach to the user's existing tabs — automation gets its own tab so a
  // hijacked/injected page can't act on whatever the user had open.
  if (mainTabId != null) {
    try { await chrome.tabs.get(mainTabId); }
    catch { autoTabs.delete(mainTabId); attached.delete(mainTabId); mainTabId = null; }
  }
  if (mainTabId == null) {
    const t = await chrome.tabs.create({ url: "about:blank", active: false });
    mainTabId = t.id;
  }
  await attachTab(mainTabId);
  return mainTabId;
}

function toCdpCookie(c) {
  const same = { no_restriction: "None", lax: "Lax", strict: "Strict" }[c.sameSite];
  const out = {
    name: c.name, value: c.value, domain: c.domain, path: c.path,
    expires: c.session ? -1 : (c.expirationDate || -1),
    size: (c.name.length + (c.value ? c.value.length : 0)),
    httpOnly: !!c.httpOnly, secure: !!c.secure, session: !!c.session,
    priority: "Medium", sourceScheme: c.secure ? "Secure" : "NonSecure",
    sourcePort: c.secure ? 443 : 80,
  };
  if (same) out.sameSite = same;
  return out;
}

async function targetInfos() {
  // The automation tabs we own, as CDP TargetInfos. Only OUR tabs are ever
  // exposed — adb never sees (or can touch) the user's other tabs.
  const infos = [];
  for (const tabId of [...autoTabs]) {
    let t;
    try { t = await chrome.tabs.get(tabId); }
    catch { forget(tabId); continue; }
    const info = {
      targetId: String(tabId), type: "page",
      title: t.title || "", url: t.url || t.pendingUrl || "",
      attached: attached.has(tabId), canAccessOpener: false,
    };
    if (t.openerTabId != null && autoTabs.has(t.openerTabId)) {
      info.openerId = String(t.openerTabId);
    }
    infos.push(info);
  }
  return infos;
}

// Browser-level CDP a per-tab chrome.debugger can't answer — served via the
// sanctioned extension APIs. Returns undefined for anything not shimmed, so the
// caller falls through to chrome.debugger.
async function browserLevel(method, params, tab) {
  switch (method) {
    case "Target.setDiscoverTargets":
    case "Target.setAutoAttach":
      return {};
    case "Target.getTargets":
      return { targetInfos: await targetInfos() };
    case "Target.getTargetInfo": {
      const id = (params && params.targetId) || tab;
      const all = await targetInfos();
      const found = all.find((t) => t.targetId === String(id));
      return { targetInfo: found || { targetId: String(id), type: "page", title: "", url: "", attached: false, canAccessOpener: false } };
    }
    case "Target.createTarget": {
      const t = await chrome.tabs.create({ url: (params && params.url) || "about:blank", active: false });
      await attachTab(t.id);
      return { targetId: String(t.id) };
    }
    case "Target.activateTarget": {
      const id = Number((params && params.targetId) || tab);
      try {
        const t = await chrome.tabs.get(id);
        await chrome.tabs.update(id, { active: true });
        if (t.windowId != null) await chrome.windows.update(t.windowId, { focused: true });
      } catch { /* tab gone */ }
      return {};
    }
    case "Target.closeTarget": {
      const id = Number((params && params.targetId) || tab);
      try { await chrome.tabs.remove(id); } catch { /* already gone */ }
      forget(id);
      return { success: true };
    }
    case "AiDevBrowser.debugState":
      // Introspection for field support (not a real CDP method): which tabs
      // does the extension think it owns / has attached right now?
      return { mainTabId, autoTabs: [...autoTabs], attached: [...attached] };
    case "Storage.getCookies":
    case "Network.getAllCookies": {
      const cookies = await chrome.cookies.getAll({});
      return { cookies: cookies.map(toCdpCookie) };
    }
    case "Browser.getWindowForTarget": {
      // Give adb's scroll-gesture / window ops real bounds instead of erroring.
      const id = Number((params && params.targetId) || tab);
      const t = await chrome.tabs.get(id);
      const w = await chrome.windows.get(t.windowId);
      return {
        windowId: w.id,
        bounds: { left: w.left, top: w.top, width: w.width, height: w.height, windowState: w.state || "normal" },
      };
    }
    default:
      return undefined;
  }
}

async function handleCommand(gid, tab, method, params) {
  try {
    let result = await browserLevel(method, params || {}, tab);
    if (result === undefined) {
      if (tab == null) throw new Error(`no target for ${method}`);
      await attachTab(Number(tab)); // ensure the tab is attached before driving it
      result = await chrome.debugger.sendCommand(dbg(tab), method, params || {});
    }
    ws.send(JSON.stringify({ _gid: gid, result: result ?? {} }));
  } catch (e) {
    ws.send(JSON.stringify({ _gid: gid, error: { message: String(e && e.message || e) } }));
  }
}

async function connect() {
  if (connecting || (ws && ws.readyState <= 1)) return;
  connecting = true;
  try {
    ws = new WebSocket(BRIDGE);
  } catch (e) {
    connecting = false;
    setTimeout(connect, 1500);
    return;
  }

  ws.onopen = async () => {
    connecting = false;
    const account = await profileAccount();
    // Seed the dedicated tab BEFORE announcing readiness, so the first
    // Target.getTargets a driver sends already lists it — no empty-list race
    // that would make adb spin up a second blank tab.
    try { await ensureDedicatedTab(); } catch { /* driver can create one */ }
    ws.send(JSON.stringify({ _hello: true, account }));
  };

  ws.onmessage = (ev) => {
    let m;
    try { m = JSON.parse(ev.data); } catch { return; }
    if (m._gid == null || !m.method) return;
    handleCommand(m._gid, m.tab, m.method, m.params);
  };

  ws.onclose = () => { connecting = false; ws = null; setTimeout(connect, 1500); };
  ws.onerror = () => { connecting = false; };
}

// Follow tabs OUR automation opened — and only those. A new tab is followed only
// when its opener is a tab we already drive (window.open / target=_blank / an
// OAuth account-chooser popup / a magic-link tab). A user's own new tab has an
// opener outside autoTabs (or none) and is left untouched. This is what makes
// OAuth login drivable in extension mode without ever reaching the user's tabs.
// Follow regardless of the bridge socket state — tracking OUR tab must not
// depend on adb being mid-command (the child may open between calls). Restore
// first so a just-woken worker still knows which tabs are ours.
// Primary follow signal: sourceTabId is the tab whose content initiated the new
// target (window.open / target=_blank), independent of foreground/background —
// unlike tabs.onCreated.openerTabId, which Chrome attributes to the window's
// FOREGROUND tab when the caller is a background tab (our automation tab is
// backgrounded, so openerTabId alone misses it).
if (chrome.webNavigation && chrome.webNavigation.onCreatedNavigationTarget) {
  chrome.webNavigation.onCreatedNavigationTarget.addListener(async (d) => {
    if (d.tabId == null || d.sourceTabId == null) return;
    if (autoTabs.size === 0) await restore();
    if (!autoTabs.has(d.sourceTabId)) return;
    followTab(d.tabId);
  });
}

// Fallback follow signal via openerTabId (covers cases webNavigation misses,
// e.g. a foreground opener). Same invariant: only tabs OUR tabs opened.
chrome.tabs.onCreated.addListener(async (tab) => {
  if (tab.id == null || tab.openerTabId == null) return;
  if (autoTabs.size === 0) await restore();
  if (!autoTabs.has(tab.openerTabId)) return;
  followTab(tab.id);
});

// A followed tab closed (e.g. OAuth popup after consent) → forget it. adb's next
// Target.getTargets no longer lists it; get_active_tab falls back to the opener.
chrome.tabs.onRemoved.addListener((tabId) => forget(tabId));

// Debugger detached out from under us (devtools opened on that tab, tab crash,
// user cancelled the debugging banner) → forget it.
chrome.debugger.onDetach.addListener((src) => {
  if (src.tabId != null) forget(src.tabId);
});

// extension -> adb: relay CDP events, tagged with the tab they came from. The
// bridge delivers each only to the driver holding that tab's connection, so a
// followed-but-idle tab's events never pollute another tab's stream.
chrome.debugger.onEvent.addListener((src, method, params) => {
  if (!ws || ws.readyState !== 1 || src.tabId == null) return;
  if (!autoTabs.has(src.tabId)) return;
  ws.send(JSON.stringify({ _event_tab: String(src.tabId), method, params }));
});

// Auto-reconnect: an MV3 worker is killed after ~30s idle, so a plain timer
// dies. An alarm wakes it to retry — the extension reconnects on its own within
// ~30s of the bridge coming up. No clicking, no ordering to get right.
if (chrome.alarms) {
  chrome.alarms.create("reconnect", { periodInMinutes: 0.5 });
  chrome.alarms.onAlarm.addListener((a) => { if (a.name === "reconnect") connect(); });
}
// Every worker (re)start re-runs this file top-to-bottom: restore which tabs we
// own from storage.session, resume the keepalive, then connect — so a worker
// woken mid-session re-adopts its tabs instead of orphaning them.
async function boot() {
  await restore();
  syncKeepalive();
  connect();
}
if (chrome.action && chrome.action.onClicked) chrome.action.onClicked.addListener(connect);
chrome.runtime.onStartup.addListener(boot);
chrome.runtime.onInstalled.addListener(boot);
boot();
