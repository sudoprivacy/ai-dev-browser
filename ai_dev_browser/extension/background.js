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
// Ordinary profiles use a DEDICATED automation tab and FOLLOW tabs automation
// opens (an OAuth "Continue with Google" popup, a magic-link new tab). A
// machine-managed isolated profile can explicitly share all its tabs. Without
// that administrator policy, a new tab is followed only if the tab
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
let profileId = null; // persistent profile identity, not an account/email guess
let sessionId = null; // survives a worker/bridge restart, not a Chrome restart
let launchToken = null; // proves an explicitly launched profile answered

// Automation session state. targetId (string) == chrome tabId as a string.
let mainTabId = null; // the DEDICATED tab we create (never a user's tab)
const autoTabs = new Set(); // chrome tabIds we own + have attached debugger to
const recoveringTabs = new Map();
const attached = new Set(); // subset of autoTabs with a live chrome.debugger
const revokedTabs = new Set(); // a user's cancellation survives worker restart
const tabStates = new Map(); // terminal states, with Chrome-proven successors
const ownershipLog = []; // bounded, redacted diagnostic history
const attachingTabs = new Map();
let restored = false;

const dbg = (tid) => ({ tabId: Number(tid) });

function safeUrl(value) {
  try { const url = new URL(value); return /^https?:$/.test(url.protocol) ? url.origin + url.pathname : url.protocol; }
  catch { return null; }
}

function trace(event, tabId, detail = {}) {
  ownershipLog.push({ event, tabId, time: Date.now(), ...detail });
  if (ownershipLog.length > 100) ownershipLog.shift();
  persist();
}

function ownershipError(tabId) {
  const state = tabStates.get(Number(tabId)) || { state: revokedTabs.has(Number(tabId)) ? "revoked" : "unowned" };
  const successor = state.successorTargetId;
  const details = { target_id: String(tabId), ...state, ownership_log: ownershipLog.slice() };
  if (successor && (!autoTabs.has(Number(successor)) || revokedTabs.has(Number(successor)))) delete details.successorTargetId;
  const error = new Error(`Target is not an owned automation tab (${details.state})`);
  error.ownership = details;
  return error;
}

function requireOwned(tabId) {
  if (revokedTabs.has(tabId) || !autoTabs.has(tabId)) throw ownershipError(tabId);
}

function claim(tabId, sourceTabId = null, reason = "created") {
  if (revokedTabs.has(tabId)) throw ownershipError(tabId);
  autoTabs.add(tabId);
  tabStates.delete(tabId);
  trace(reason, tabId, { sourceTabId });
  syncKeepalive();
}

function sourceOwned(tabId) {
  return !revokedTabs.has(tabId) && (autoTabs.has(tabId) || tabStates.get(tabId)?.state === "closed");
}

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
    chrome.storage.session.set({ adbMainTabId: mainTabId, adbAutoTabs: [...autoTabs],
      adbRevokedTabs: [...revokedTabs], adbTabStates: [...tabStates], adbOwnershipLog: ownershipLog });
  } catch { /* storage unavailable — keepalive still holds in-memory state */ }
}

async function restore() {
  const local = await chrome.storage.local.get("adbProfileId");
  profileId = local.adbProfileId || crypto.randomUUID();
  await chrome.storage.local.set({ adbProfileId: profileId });
  try {
    const s = await chrome.storage.session.get(["adbMainTabId", "adbAutoTabs", "adbSessionId", "adbLaunchToken", "adbRevokedTabs", "adbTabStates", "adbOwnershipLog"]);
    sessionId = s.adbSessionId || crypto.randomUUID();
    launchToken = s.adbLaunchToken || null;
    await chrome.storage.session.set({ adbSessionId: sessionId });
    if (s.adbMainTabId != null) mainTabId = s.adbMainTabId;
    for (const id of s.adbRevokedTabs || []) revokedTabs.add(id);
    for (const [id, value] of s.adbTabStates || []) tabStates.set(id, value);
    ownershipLog.push(...(s.adbOwnershipLog || []).slice(-100));
    if (Array.isArray(s.adbAutoTabs)) {
      for (const id of s.adbAutoTabs) if (!revokedTabs.has(id)) autoTabs.add(id);
    }
  } catch { /* first run / no storage */ }
}

async function attachTab(tabId) {
  // Attach chrome.debugger to a tab WE own. Idempotent.
  requireOwned(tabId);
  if (attachingTabs.has(tabId)) return attachingTabs.get(tabId);
  const operation = (async () => {
    if (!attached.has(tabId)) {
      try {
        await chrome.debugger.attach(dbg(tabId), PROTOCOL);
      } catch (e) {
        if (!/already|Another debugger/i.test(String(e))) throw e;
        // Another extension's debugger must not be mistaken for our attachment.
        await chrome.debugger.sendCommand(dbg(tabId), "Page.enable", {});
      }
      if (!autoTabs.has(tabId) || revokedTabs.has(tabId)) {
        await chrome.debugger.detach(dbg(tabId)).catch(() => {});
        throw ownershipError(tabId);
      }
      attached.add(tabId);
      markTab(tabId);
    }
    syncKeepalive();
    persist();
  })();
  attachingTabs.set(tabId, operation);
  try { return await operation; }
  finally { if (attachingTabs.get(tabId) === operation) attachingTabs.delete(tabId); }
}

// Follow a tab OUR automation opened, retrying briefly — a just-created popup
// can reject the first attach while it's still committing its first navigation.
async function followTab(tabId) {
  for (let i = 0; i < 6; i++) {
    if (!autoTabs.has(tabId) || revokedTabs.has(tabId)) return false;
    try { await attachTab(tabId); return true; }
    catch { await new Promise((r) => setTimeout(r, 250)); }
  }
  return false;
}

function forget(tabId, state = "closed", detail = {}) {
  const wasOwned = autoTabs.has(tabId);
  autoTabs.delete(tabId);
  attached.delete(tabId);
  if (state === "revoked") revokedTabs.add(tabId);
  if (wasOwned || tabStates.has(tabId) || revokedTabs.has(tabId)) {
    // Removal can arrive after replacement/revocation; preserve the more useful state.
    if (state !== "closed" || !tabStates.has(tabId)) tabStates.set(tabId, { state, ...detail });
    while (tabStates.size > 128) tabStates.delete(tabStates.keys().next().value);
    trace(state, tabId, detail);
  }
  if (tabId === mainTabId && state !== "revoked") mainTabId = null;
  syncKeepalive();
  persist();
  announce().catch(() => {});
}

// Startup events and a socket opening can select a tab concurrently. Serialize
// selection so a late nonce tab cannot be overwritten by a newly created blank.
let tabSelection = Promise.resolve();
function selectDedicated(operation) {
  const selected = tabSelection.then(operation);
  tabSelection = selected.catch(() => {});
  return selected;
}

function ensureDedicatedTab() {
  return selectDedicated(ensureDedicatedTabSelected);
}

async function ensureDedicatedTabSelected() {
  // Reuse our own tab across reconnects; recreate if the user closed it. We
  // NEVER attach to the user's existing tabs — automation gets its own tab so a
  // hijacked/injected page can't act on whatever the user had open.
  if (mainTabId != null) {
    if (revokedTabs.has(mainTabId)) throw ownershipError(mainTabId);
    try { await chrome.tabs.get(mainTabId); }
    catch { autoTabs.delete(mainTabId); attached.delete(mainTabId); mainTabId = null; }
  }
  if (mainTabId == null) {
    const tabs = await chrome.tabs.query({});
    const marker = tabs.find(t => launchMarker(t));
    const t = marker || await chrome.tabs.create({ url: "about:blank", active: false });
    if (marker) {
      launchToken = launchMarker(marker);
      await chrome.storage.session.set({ adbLaunchToken: launchToken });
      await chrome.tabs.update(marker.id, { url: "about:blank" });
    }
    mainTabId = t.id;
    claim(t.id);
  }
  await attachTab(mainTabId);
  return mainTabId;
}

function launchMarker(tab) {
  for (const url of [tab.url, tab.pendingUrl]) {
    const prefix = BRIDGE.replace("ws:", "http:") + "/adb-launch/";
    if (url && url.startsWith(prefix) && /^[a-f0-9]{32}$/.test(url.slice(prefix.length))) return url.slice(prefix.length);
    if (/^about:blank#adb-launch=[a-f0-9]{32}$/.test(url || "")) return url.split("=")[1];
  }
  return null;
}

async function announce() {
  if (!ws || ws.readyState !== 1) return;
  ws.send(JSON.stringify({
    _hello: true, account: await profileAccount(), profile_id: profileId,
    session_id: sessionId, launch_token: launchToken,
    automation_target_id: mainTabId == null ? null : String(mainTabId), browser_version: navigator.userAgent,
    extension_version: chrome.runtime.getManifest().version,
  }));
}

function windowBounds(window) {
  return { left: window.left, top: window.top, width: window.width, height: window.height, windowState: window.state || "normal" };
}

async function selectedWindow(tab, windowId) {
  // Window ids alone grant no authority. Resolve through the driver's selected
  // owned tab, including after an asynchronous tab lookup or a tab move.
  const id = Number(tab);
  requireOwned(id);
  const selected = await chrome.tabs.get(id);
  requireOwned(id);
  if (selected.windowId !== windowId) throw new Error("Requested window does not contain the selected automation tab");
  return id;
}

// Chrome can commit the launch URL after the worker's first handshake. Adopt
// only the caller's nonce-marked tab; do not guess at unrelated existing tabs.
function adoptLaunch(tab) {
  const token = launchMarker(tab);
  if (!token) return Promise.resolve();
  return selectDedicated(async () => {
    await boot();
    if (launchToken === token) return;
    const old = mainTabId;
    mainTabId = tab.id;
    launchToken = token;
    await chrome.storage.session.set({ adbLaunchToken: token });
    claim(tab.id, null, "launch");
    await attachTab(tab.id);
    await chrome.tabs.update(tab.id, { url: "about:blank" });
    if (old != null && old !== tab.id && autoTabs.has(old)) {
      const previous = await chrome.tabs.get(old).catch(() => null);
      if (previous && previous.url === "about:blank") {
        await chrome.tabs.remove(old);
        forget(old);
      }
    }
    persist();
    await announce();
  });
}
chrome.tabs.onUpdated.addListener((tabId, change, tab) => {
  if (autoTabs.has(tabId) && change.url) trace("updated", tabId, { url: safeUrl(change.url) });
  adoptLaunch(tab).catch(error => console.error("Launch adoption failed", error));
});
chrome.tabs.onCreated.addListener(tab => {
  adoptLaunch(tab).catch(error => console.error("Launch adoption failed", error));
});

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
  if (await managedProfile()) {
    for (const tab of await chrome.tabs.query({})) if (!revokedTabs.has(tab.id)) autoTabs.add(tab.id);
  }
  // Managed isolated profiles explicitly share their tabs. Ordinary profiles
  // expose only automation tabs, preserving the user's unrelated tabs.
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

let managedPolicyValue = null;
let managedPolicyRead = null;
let managedPolicyGeneration = 0;
let managedPolicyPending = false;
let managedPolicyRetryAt = 0;
async function managedProfile() {
  if (managedPolicyValue !== null) {
    if (managedPolicyValue || managedPolicyPending || Date.now() < managedPolicyRetryAt) return managedPolicyValue;
    managedPolicyValue = null;
    managedPolicyRead = null;
  }
  const generation = managedPolicyGeneration;
  if (!managedPolicyRead) {
    // Some ordinary Windows profiles never settle managed storage reads. Tab
    // discovery must still work without granting access to unrelated user tabs.
    managedPolicyPending = true;
    managedPolicyRead = Promise.resolve()
      .then(() => chrome.storage.managed.get({ ManagedBrowserProfile: false }))
      .then(policy => {
        if (generation !== managedPolicyGeneration) return false;
        managedPolicyPending = false;
        managedPolicyRetryAt = Date.now() + 250;
        return managedPolicyValue = policy.ManagedBrowserProfile === true;
      })
      .catch(() => {
        if (generation === managedPolicyGeneration) {
          managedPolicyPending = false;
          managedPolicyRetryAt = Date.now() + 250;
          managedPolicyValue = false;
        }
        return false;
      });
  }
  let timer;
  try {
    return await Promise.race([
      managedPolicyRead,
      new Promise(resolve => { timer = setTimeout(() => {
        if (generation === managedPolicyGeneration) managedPolicyValue = false;
        resolve(false);
      }, 1000); }),
    ]);
  } finally { clearTimeout(timer); }
}
if (chrome.storage.onChanged) chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "managed") {
    managedPolicyGeneration++;
    managedPolicyValue = null;
    managedPolicyRead = null;
    managedPolicyPending = false;
    managedPolicyRetryAt = 0;
  }
});

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
    case "AiDevBrowser.getActiveTarget": {
      await targetInfos();
      const tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
      const active = tabs.find(tab => autoTabs.has(tab.id));
      return { targetId: active ? String(active.id) : null };
    }
    case "Target.getTargetInfo": {
      const id = (params && params.targetId) || tab;
      const all = await targetInfos();
      const found = all.find((t) => t.targetId === String(id));
      if (!found) throw ownershipError(id);
      return { targetInfo: found };
    }
    case "Target.createTarget": {
      const t = await chrome.tabs.create({ url: (params && params.url) || "about:blank", active: false });
      claim(t.id);
      await attachTab(t.id);
      return { targetId: String(t.id) };
    }
    case "Target.activateTarget": {
      const id = Number((params && params.targetId) || tab);
      requireOwned(id);
      const t = await chrome.tabs.get(id);
      await chrome.tabs.update(id, { active: true });
      if (t.windowId != null) {
        const window = await chrome.windows.get(t.windowId);
        if (window.state === "minimized") {
          await chrome.windows.update(t.windowId, { state: "normal" });
        }
        await chrome.windows.update(t.windowId, { focused: true });
      }
      await attachTab(id);
      await chrome.debugger.sendCommand({ tabId: id }, "Page.bringToFront", {});
      return {};
    }
    case "Target.closeTarget": {
      const id = Number((params && params.targetId) || tab);
      requireOwned(id);
      try { await chrome.tabs.remove(id); } catch { /* already gone */ }
      forget(id);
      return { success: true };
    }
    case "AiDevBrowser.debugState":
      // Introspection for field support (not a real CDP method): which tabs
      // does the extension think it owns / has attached right now?
      return { mainTabId, autoTabs: [...autoTabs], attached: [...attached], profileId, sessionId, launchToken, managedProfile: await managedProfile(), extensionVersion: chrome.runtime.getManifest().version,
        targetStates: [...tabStates].map(([id, state]) => ({ target_id: String(id), ...state })), ownershipLog };
    case "AiDevBrowser.closeBrowser":
      // The Python lifecycle layer verifies PID ownership/authorization first.
      // This is explicit process-wide close; disconnect never calls it.
      if (!params.authorized) throw new Error("Explicit close authorization required");
      setTimeout(async () => {
        for (const window of await chrome.windows.getAll()) await chrome.windows.remove(window.id);
      }, 100);
      return { closing: true };
    case "Storage.getCookies":
    case "Network.getAllCookies": {
      const cookies = await chrome.cookies.getAll({});
      return { cookies: cookies.map(toCdpCookie) };
    }
    case "Browser.getWindowForTarget": {
      // Give adb's scroll-gesture / window ops real bounds instead of erroring.
      const id = Number((params && params.targetId) || tab);
      requireOwned(id);
      const t = await chrome.tabs.get(id);
      const w = await chrome.windows.get(t.windowId);
      return {
        windowId: w.id,
        bounds: windowBounds(w),
      };
    }
    case "Browser.getWindowBounds": {
      await selectedWindow(tab, params.windowId);
      return { bounds: windowBounds(await chrome.windows.get(params.windowId)) };
    }
    case "Browser.setWindowBounds": {
      const id = await selectedWindow(tab, params.windowId);
      const bounds = params.bounds || {};
      const changes = {};
      for (const name of ["left", "top", "width", "height"]) {
        if (bounds[name] != null) changes[name] = bounds[name];
      }
      if (bounds.windowState != null) changes.state = bounds.windowState;
      requireOwned(id);
      await chrome.windows.update(params.windowId, changes);
      return {};
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
      if (recoveringTabs.has(Number(tab))) await recoveringTabs.get(Number(tab));
      requireOwned(Number(tab));
      await attachTab(Number(tab)); // ensure the tab is attached before driving it
      result = await chrome.debugger.sendCommand(dbg(tab), method, params || {});
    }
    ws.send(JSON.stringify({ _gid: gid, result: result ?? {} }));
  } catch (e) {
    ws.send(JSON.stringify({ _gid: gid, error: { message: String(e && e.message || e),
      ...(e.ownership ? { data: { adbOwnership: e.ownership } } : {}) } }));
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
    // Seed the dedicated tab BEFORE announcing readiness, so the first
    // Target.getTargets a driver sends already lists it — no empty-list race
    // that would make adb spin up a second blank tab.
    try { await ensureDedicatedTab(); } catch { /* driver can create one */ }
    await announce();
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
    await boot();
    if (!sourceOwned(d.sourceTabId)) return;
    if (revokedTabs.has(d.tabId)) return;
    claim(d.tabId, d.sourceTabId, "navigation-child");
    followTab(d.tabId);
  });
}

// Fallback follow signal via openerTabId (covers cases webNavigation misses,
// e.g. a foreground opener). Same invariant: only tabs OUR tabs opened.
chrome.tabs.onCreated.addListener(async (tab) => {
  if (tab.id == null || tab.openerTabId == null) return;
  await boot();
  if (!sourceOwned(tab.openerTabId) || revokedTabs.has(tab.id)) return;
  claim(tab.id, tab.openerTabId, "opener-child");
  followTab(tab.id);
});

// A followed tab closed (e.g. OAuth popup after consent) → forget it. adb's next
// Target.getTargets no longer lists it; get_active_tab falls back to the opener.
chrome.tabs.onRemoved.addListener(async (tabId) => { await boot(); forget(tabId); });

// Chrome alone proves replacement; URL similarity never grants ownership.
chrome.tabs.onReplaced.addListener(async (addedTabId, removedTabId) => {
  await boot();
  if (!sourceOwned(removedTabId) || revokedTabs.has(addedTabId)) return;
  claim(addedTabId, removedTabId, "replacement");
  if (mainTabId === removedTabId) mainTabId = addedTabId;
  forget(removedTabId, "replaced", { successorTargetId: String(addedTabId) });
  followTab(addedTabId).then(() => announce()).catch(() => {});
});

// Headless branded Chrome may replace the debugger target on cross-process
// navigation while retaining the SAME authorized tab. Wait for its new target;
// never replay a command or adopt a different/user tab. Explicit cancellation
// and an actual closed tab still release ownership.
function onDetached(src, reason) {
  // An event can wake a suspended worker before storage restoration finishes.
  if (!restored) { boot().then(() => onDetached(src, reason)); return; }
  const tabId = src.tabId;
  if (tabId == null || !autoTabs.has(tabId)) return;
  trace("detached", tabId, { reason });
  // Cancellation wins even while target_closed recovery is awaiting Chrome.
  if (reason !== "target_closed") {
    forget(tabId, "revoked", { reason });
    if (ws && ws.readyState === 1) ws.send(JSON.stringify({ _event_tab: String(tabId), method: "Inspector.detached", params: { reason } }));
    return;
  }
  if (recoveringTabs.has(tabId)) return;
  const recovery = (async () => {
    let tabPresent = false;
    try { await chrome.tabs.get(tabId); tabPresent = true; }
    catch { /* Closed Chrome tab. */ }
    if (reason === "target_closed" && tabPresent) {
      attached.delete(tabId);
      if (await followTab(tabId)) {
        try {
          await chrome.debugger.sendCommand(dbg(tabId), "Page.enable", {});
          trace("recovered", tabId, { reason });
          return;
        } catch { /* Reattachment failed: release below. */ }
      }
    }
    if (ws && ws.readyState === 1 && autoTabs.has(tabId)) {
      ws.send(JSON.stringify({ _event_tab: String(tabId), method: "Inspector.detached", params: { reason, tabPresent } }));
    }
    if (!revokedTabs.has(tabId)) forget(tabId, tabPresent ? "unavailable" : "closed", { reason });
  })();
  recoveringTabs.set(tabId, recovery);
  recovery.finally(() => recoveringTabs.delete(tabId));
}
chrome.debugger.onDetach.addListener(onDetached);

// extension -> adb: relay CDP events, tagged with the tab they came from. The
// bridge delivers each to the drivers holding that tab's connections, so a
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
let booting = null;
function boot() {
  if (!booting) booting = (async () => {
    await restore();
    restored = true;
    trace("worker-start", mainTabId);
    syncKeepalive();
    connect();
  })();
  return booting;
}
if (chrome.action && chrome.action.onClicked) chrome.action.onClicked.addListener(connect);
chrome.runtime.onStartup.addListener(boot);
chrome.runtime.onInstalled.addListener(boot);
boot();
