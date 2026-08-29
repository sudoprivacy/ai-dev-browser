// AI Dev Browser — extension bridge.
//
// Connects OUT to ai-dev-browser's local bridge (WS client — extensions can't
// listen), attaches chrome.debugger to the active tab, and relays CDP both ways.
// ai-dev-browser then drives your real Chrome with the same CDP it already
// speaks — over the permissioned extension channel, so it works on your real
// logged-in profile without --remote-debugging-port. Only active while
// ai-dev-browser is connected; detaches otherwise.
//
// NOTE: bridge port is the fixed convention shared with core/extension.py
// (EXTENSION_BRIDGE_PORT). Keep the two in sync.
const BRIDGE = "ws://127.0.0.1:9522";
const PROTOCOL = "1.3";

let ws = null;
let tabId = null; // the DEDICATED automation tab (never the user's tabs)
let connecting = false;

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

async function ensureDedicatedTab() {
  // Reuse our own tab across reconnects; recreate if the user closed it. We
  // NEVER attach to the user's existing tabs — automation gets its own tab so a
  // hijacked/injected page can't act on whatever the user had open.
  if (tabId != null) {
    try { await chrome.tabs.get(tabId); return tabId; } catch { tabId = null; }
  }
  const t = await chrome.tabs.create({ url: "about:blank", active: false });
  tabId = t.id;
  return tabId;
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

// Browser-level CDP that a per-tab chrome.debugger can't answer — served via
// the sanctioned extension APIs. Returns undefined for anything not shimmed, so
// the caller falls through to chrome.debugger.
async function browserLevelShim(method, params) {
  if (method === "Storage.getCookies" || method === "Network.getAllCookies") {
    const cookies = await chrome.cookies.getAll({});
    return { cookies: cookies.map(toCdpCookie) };
  }
  return undefined;
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
    try {
      const id = await ensureDedicatedTab();
      try {
        await chrome.debugger.attach({ tabId: id }, PROTOCOL);
      } catch (e) {
        if (!/already|Another debugger/i.test(String(e))) throw e;
      }
      const account = await profileAccount();
      ws.send(JSON.stringify({ _event: "attached", tabId: id, account }));
    } catch (e) {
      ws.send(JSON.stringify({ _event: "attach_error", error: String(e) }));
    }
  };

  // adb -> extension: { id, method, params } -> chrome.debugger.sendCommand,
  // with browser-level shims for what a per-tab debugger can't do.
  ws.onmessage = async (ev) => {
    let m;
    try { m = JSON.parse(ev.data); } catch { return; }
    if (m.id == null || !m.method) return;
    try {
      const shimmed = await browserLevelShim(m.method, m.params || {});
      const result = shimmed !== undefined
        ? shimmed
        : await chrome.debugger.sendCommand({ tabId }, m.method, m.params || {});
      ws.send(JSON.stringify({ id: m.id, result: result ?? {} }));
    } catch (e) {
      ws.send(JSON.stringify({ id: m.id, error: { message: String(e) } }));
    }
  };

  ws.onclose = () => { connecting = false; ws = null; setTimeout(connect, 1500); };
  ws.onerror = () => { connecting = false; };
}

// extension -> adb: relay CDP events verbatim.
chrome.debugger.onEvent.addListener((_src, method, params) => {
  if (ws && ws.readyState === 1) ws.send(JSON.stringify({ method, params }));
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
