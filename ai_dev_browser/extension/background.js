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
let tabId = null;
let connecting = false;

async function activeTab() {
  const [t] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  return t || null;
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
      const t = await activeTab();
      tabId = t && t.id;
      if (tabId == null) {
        ws.send(JSON.stringify({ _event: "attach_error", error: "no active tab" }));
        return;
      }
      try {
        await chrome.debugger.attach({ tabId }, PROTOCOL);
      } catch (e) {
        if (!/already|Another debugger/i.test(String(e))) throw e;
      }
      ws.send(JSON.stringify({ _event: "attached", tabId, url: t.url }));
    } catch (e) {
      ws.send(JSON.stringify({ _event: "attach_error", error: String(e) }));
    }
  };

  // adb -> extension: { id, method, params } -> chrome.debugger.sendCommand
  ws.onmessage = async (ev) => {
    let m;
    try { m = JSON.parse(ev.data); } catch { return; }
    if (m.id == null || !m.method) return;
    try {
      const result = await chrome.debugger.sendCommand({ tabId }, m.method, m.params || {});
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
