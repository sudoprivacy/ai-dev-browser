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
// NEVER attach to a tab the user opened. The rule is opener-based: a new tab is
// followed only if its opener is a tab we already drive.
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

async function attachTab(tabId) {
  // Attach chrome.debugger to a tab WE own. Idempotent.
  if (attached.has(tabId)) { autoTabs.add(tabId); return; }
  try {
    await chrome.debugger.attach(dbg(tabId), PROTOCOL);
  } catch (e) {
    if (!/already|Another debugger/i.test(String(e))) throw e;
  }
  autoTabs.add(tabId);
  attached.add(tabId);
  markTab(tabId);
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
    catch { autoTabs.delete(tabId); attached.delete(tabId); continue; }
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
      autoTabs.delete(id); attached.delete(id);
      return { success: true };
    }
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
chrome.tabs.onCreated.addListener(async (tab) => {
  if (!ws || ws.readyState !== 1) return;
  if (tab.id == null || tab.openerTabId == null) return;
  if (!autoTabs.has(tab.openerTabId)) return;
  try { await attachTab(tab.id); } catch { /* couldn't attach — leave it */ }
});

// A followed tab closed (e.g. OAuth popup after consent) → forget it. adb's next
// Target.getTargets no longer lists it; get_active_tab falls back to the opener.
chrome.tabs.onRemoved.addListener((tabId) => {
  autoTabs.delete(tabId); attached.delete(tabId);
  if (tabId === mainTabId) mainTabId = null;
});

// Debugger detached out from under us (devtools opened on that tab, tab crash,
// user cancelled the debugging banner) → forget it.
chrome.debugger.onDetach.addListener((src) => {
  if (src.tabId == null) return;
  attached.delete(src.tabId);
  autoTabs.delete(src.tabId);
  if (src.tabId === mainTabId) mainTabId = null;
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
if (chrome.action && chrome.action.onClicked) chrome.action.onClicked.addListener(connect);
chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onInstalled.addListener(connect);
connect();
