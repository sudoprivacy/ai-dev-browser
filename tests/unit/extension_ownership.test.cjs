// Deterministic state/race tests. These are unit tests, not live Chrome evidence.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const event = () => ({ handlers: [], addListener(fn) { this.handlers.push(fn); } });

test('selected page diagnostics expose only owned tab/window observations', async () => {
  const { run, tabs, windows } = await fixture();
  run('claim(11)');
  tabs.get(11).active = true;
  windows.get(101).focused = false;
  const state = await run("browserLevel('AiDevBrowser.debugState',{},'11')");
  assert.equal(state.selectedTarget.targetId, '11');
  assert.equal(state.selectedTarget.tabActive, true);
  assert.equal(state.selectedTarget.windowFocused, false);
  assert.equal(state.selectedTarget.windowState, 'normal');
  assert(state.selectedTarget.observedAt > 0);
  assert(!JSON.stringify(state.selectedTarget).includes('neutral.test'));
  await assert.rejects(run('selectedPageState(99)'), /not an owned automation tab \(unowned\)/);
});

test('consent revocation during visibility observation wins over diagnostic metadata', async () => {
  const { run, chrome } = await fixture();
  run('claim(11)');
  const get = chrome.windows.get;
  chrome.windows.get = async (...args) => {
    const result = await get(...args);
    run("forget(11,'revoked')");
    return result;
  };
  await assert.rejects(run('selectedPageState(11)'), /revoked/);
});

test('tab moving windows during observation cannot produce a stale window report', async () => {
  const { run, chrome, tabs } = await fixture();
  run('claim(11)');
  const get = chrome.windows.get;
  chrome.windows.get = async (...args) => {
    tabs.get(11).windowId = 102;
    return get(...args);
  };
  await assert.rejects(run('selectedPageState(11)'), /changed windows during observation/);
});

test('closing a revoked main preserves consent across restore and every implicit creation route', async () => {
  const { chrome, tabs, run, saved } = await fixture();
  run('claim(11); mainTabId=11; forget(11, "revoked", {reason:"canceled_by_user"})');
  const time = run('ownershipError(11).ownership.time');
  tabs.delete(11);
  await chrome.tabs.onRemoved.handlers[0](11);
  assert.equal(run('mainTabId'), 11);
  assert.equal(run('ownershipError(11).ownership.time'), time);
  assert.equal(run('ownershipError(11).ownership.reason'), 'canceled_by_user');
  const restored = await fixture(saved);
  await assert.rejects(restored.run('ensureDedicatedTab()'), /revoked/);
  await assert.rejects(restored.run("browserLevel('Target.createTarget', {url:'about:blank'})"), /revoked/);
  await assert.rejects(restored.run(`adoptLaunch({id:12,url:'about:blank#adb-launch=${'0'.repeat(32)}'})`), /revoked/);
  assert.equal(restored.run('mainTabId'), 11);
  assert.equal(restored.run('autoTabs.size'), 0);
});

test('human action creates a fresh visible authorization; a healthy action reuses it', async () => {
  const { chrome, tabs, windows, run, saved } = await fixture();
  assert.equal(chrome.action.onClicked.handlers.length, 1);
  run('claim(11); mainTabId=11; forget(11, "revoked", {reason:"canceled_by_user"})');
  const oldIdentity = run('sessionId');
  let created = 0;
  chrome.windows.getAll = async () => [...windows.values()];
  chrome.tabs.create = async options => {
    created++;
    const tab = {id:201, windowId:options.windowId, url:options.url};
    tabs.set(tab.id, tab);
    return tab;
  };
  chrome.tabs.update = async (id, changes) => Object.assign(tabs.get(id), changes);
  await run('onToolbarAction()');
  const fresh = run('sessionId');
  assert.notEqual(fresh, oldIdentity);
  assert.equal(saved.adbSessionId, fresh);
  assert.equal(run('profileId'), 'profile');
  assert.equal(run('mainTabId'), 201);
  assert.equal(run('revokedTabs.has(11) && !autoTabs.has(11) && !autoTabs.has(99)'), true);
  assert.equal(tabs.get(201).url, 'about:blank');
  assert.equal(tabs.get(201).active, true);
  assert.equal(windows.get(101).focused, true);
  assert.equal(tabs.has(11) && tabs.has(99), true);
  await run('onToolbarAction()');
  assert.equal(created, 1);
  assert.equal(run('sessionId'), fresh);
});

for (const history of [[], [{event:'revoked', tabId:11, time:123456789, reason:'canceled_by_user'}]]) {
  test(`legacy revocation time is ${history.length ? 'proven by stored history' : 'unknown without evidence'}`, async () => {
    const {run} = await fixture({adbMainTabId:11, adbRevokedTabs:[11],
      adbTabStates:[[11,{state:'revoked', reason:'canceled_by_user'}]], adbOwnershipLog:history});
    assert.equal(run('ownershipError(11).ownership.time'), history.length ? 123456789 : null);
  });
}

test('selected-tab frame discovery refreshes a provisional empty URL after document load', async () => {
  const { chrome, run } = await fixture();
  let currentUrl = '';
  chrome.debugger.sendCommand = async (debuggee, method) => method === 'Target.getTargetInfo'
    ? { targetInfo: { targetId: 'child', type: 'iframe', url: currentUrl } } : {};
  run("globalThis.navigator={userAgent:'Chrome/156.0.0.0'};claim(11)");
  await chrome.debugger.onEvent.handlers[0]({ tabId: 11 }, 'Target.attachedToTarget',
    { sessionId: 'child-session', targetInfo: { targetId: 'child', type: 'iframe', url: '', parentFrameId: 'root' } });
  assert.equal(run("frameSessions.get(11).get('child-session').info.url"), '');
  currentUrl = 'https://child.test/loaded';
  const result = await run("browserLevel('Target.getTargets',{},'11')");
  assert.equal(result.targetInfos.find(info => info.targetId === 'child').url, currentUrl);
});

test('revocation during frame metadata refresh refuses the pending discovery result', async () => {
  const { chrome, run } = await fixture();
  chrome.debugger.sendCommand = async () => ({});
  run("globalThis.navigator={userAgent:'Chrome/156.0.0.0'};claim(11)");
  await chrome.debugger.onEvent.handlers[0]({ tabId: 11 }, 'Target.attachedToTarget',
    { sessionId: 'child-session', targetInfo: { targetId: 'child', type: 'iframe', url: '', parentFrameId: 'root' } });
  let release, requested;
  const started = new Promise(resolve => { requested = resolve; });
  chrome.debugger.sendCommand = async () => new Promise(resolve => { release = resolve; requested(); });
  const pending = run("browserLevel('Target.getTargets',{},'11')");
  await Promise.race([started, pending.then(() => { throw new Error('Frame metadata was not refreshed'); })]);
  run("forget(11,'revoked')");
  release({ targetInfo: { targetId: 'child', type: 'iframe', url: 'https://child.test/late' } });
  await assert.rejects(pending, error => error.ownership?.state === 'revoked');
  assert.equal(run('frameSessions.has(11)'), false);
});

test('child sessions route only within their owning tab and die with its consent', async () => {
  const { chrome, run } = await fixture();
  const commands = [];
  chrome.debugger.sendCommand = async (debuggee, method, params) => {
    commands.push({ debuggee, method, params }); return {};
  };
  run("globalThis.navigator={userAgent:'Chrome/156.0.0.0'};globalThis.messages=[];ws={readyState:1,send:value=>messages.push(JSON.parse(value))};announcedSocket=ws;claim(11);claim(12)");
  const attach = async (tabId, sessionId, targetId, parentSessionId = null) => chrome.debugger.onEvent.handlers[0](
    { tabId, ...(parentSessionId ? { sessionId: parentSessionId } : {}) }, 'Target.attachedToTarget',
    { sessionId, targetInfo: { targetId, type: 'iframe', url: 'https://child.test/', parentFrameId: parentSessionId ? 'frame-a' : `root-${tabId}` }, waitingForDebugger: false }
  );
  await attach(11, 'session-a', 'frame-a');
  await attach(12, 'session-b', 'frame-b');
  await attach(11, 'nested-a', 'nested-frame', 'session-a');
  const infos = await run("browserLevel('Target.getTargets',{},'11')");
  assert.deepEqual(Array.from(infos.targetInfos, item => item.targetId).sort(), ['11', 'frame-a', 'nested-frame']);
  await run("handleCommand(1,'11','Runtime.evaluate',{expression:'read'},'session-b')");
  assert.match(run('messages.at(-1).error.message'), /not owned by this automation tab/);
  assert(!commands.some(item => item.method === 'Runtime.evaluate'));
  await run("handleCommand(2,'11','Runtime.evaluate',{expression:'read'},'session-a')");
  assert(commands.some(item => item.method === 'Runtime.evaluate' && item.debuggee.tabId === 11 && item.debuggee.sessionId === 'session-a'));
  await chrome.debugger.onEvent.handlers[0]({ tabId: 11 }, 'Target.targetInfoChanged', { targetInfo: { targetId: 'frame-a', url: 'https://child.test/updated' } });
  assert.equal(run("frameSessions.get(11).get('session-a').info.url"), 'https://child.test/updated');
  run("forget(11,'revoked',{reason:'canceled_by_user'})");
  assert.equal(run('frameSessions.has(11)'), false);
  assert.equal(run("frameSessions.get(12).has('session-b')"), true);
  const before = run('messages.filter(item => item._event_tab !== undefined).length');
  await chrome.debugger.onEvent.handlers[0]({ tabId: 11, sessionId: 'session-a' }, 'Runtime.consoleAPICalled', { marker: 'stale-frame-event' });
  assert.equal(run('messages.filter(item => item._event_tab !== undefined).length'), before);
  assert.equal(run("messages.some(item => item.params?.marker === 'stale-frame-event')"), false);
});

test('child setup cannot resume after consent is revoked during metadata lookup', async () => {
  const { chrome, run } = await fixture();
  const commands = [];
  let release;
  chrome.debugger.sendCommand = async (debuggee, method) => {
    commands.push({ debuggee, method });
    if (method === 'Target.getTargetInfo') return new Promise(resolve => { release = resolve; });
    return {};
  };
  run("globalThis.navigator={userAgent:'Chrome/156.0.0.0'};claim(11)");
  const pending = chrome.debugger.onEvent.handlers[0]({ tabId: 11 }, 'Target.attachedToTarget',
    { sessionId: 'child', targetInfo: { targetId: 'frame', type: 'iframe', parentFrameId: 'root' } });
  assert(release);
  run("forget(11,'revoked')");
  release({});
  await pending;
  assert.equal(run('frameSessions.has(11)'), false);
  assert(!commands.some(item => item.method === 'Target.setAutoAttach'));
});

test('restored child events cannot precede the extension hello or replace its session identity', async () => {
  const { chrome, run } = await fixture();
  run("globalThis.navigator={userAgent:'Chrome/156.0.0.0'};globalThis.messages=[];ws={readyState:1,send:value=>messages.push(JSON.parse(value))};claim(11)");
  await chrome.debugger.onEvent.handlers[0]({ tabId: 11 }, 'Target.attachedToTarget',
    { sessionId: 'child', targetInfo: { targetId: 'frame', type: 'iframe', parentFrameId: 'root' } });
  assert.equal(run('messages.length'), 0);
  await run('announce()');
  assert.equal(run('messages[0]._hello'), true);
  assert.equal(run("messages[0].session_id === sessionId && typeof sessionId === 'string'"), true);
  const state = await run("browserLevel('AiDevBrowser.debugState',{},'11')");
  assert.equal(state.sessionId, run('sessionId'));
  await chrome.debugger.onEvent.handlers[0]({ tabId: 11, sessionId: 'child' }, 'Runtime.consoleAPICalled', { marker: true });
  assert.equal(run('messages.at(-1).sessionId'), 'child');
});

test('older Chrome retains tab operation without advertising unsupported flat children', async () => {
  const { chrome, run } = await fixture();
  const commands = [];
  chrome.debugger.sendCommand = async (_debuggee, method) => { commands.push(method); return {}; };
  run("globalThis.navigator={userAgent:'Chrome/124.0.0.0'};claim(11)");
  await run('attachTab(11)');
  assert.equal(run('attached.has(11)'), true);
  assert(!commands.includes('Target.setAutoAttach'));
});
async function fixture(saved = {}, beforeRestore = null) {
  const tabs = new Map([[11, { id: 11, url: 'https://neutral.test/consent?secret=yes#token' }], [12, { id: 12, url: 'https://neutral.test/result' }], [99, { id: 99, url: 'https://neutral.test/private' }]]);
  for (const [id, tab] of tabs) tab.windowId = id === 99 ? 102 : 101;
  const windows = new Map([[101, {id:101, state:'normal', left:10, top:20, width:800, height:600}], [102, {id:102, state:'normal'}]]);
  const chrome = {
    tabs: { onCreated: event(), onUpdated: event(), onRemoved: event(), onReplaced: event(),
      get: async id => { if (!tabs.has(id)) throw Error('closed'); return tabs.get(id); },
      query: async () => [...tabs.values()], update: async id => tabs.get(id) },
    windows: { get: async (id, options) => ({...windows.get(id), ...(options?.populate ? {tabs:[...tabs.values()].filter(tab => tab.windowId === id)} : {})}), update: async (id, changes) => Object.assign(windows.get(id), changes) },
    debugger: { onDetach: event(), onEvent: event(), attach: async () => {}, detach: async () => {}, sendCommand: async () => ({}) },
    storage: { local: { get: async () => ({ adbProfileId: 'profile' }), set: async () => {} },
      session: { get: async () => saved, set: async data => Object.assign(saved, structuredClone(data)) },
      managed: { get: async () => ({ ManagedBrowserProfile: false }) }, onChanged: event() },
    runtime: { getManifest: () => ({ version: 'test' }), onStartup: event(), onInstalled: event() },
    action: { onClicked: event(), setBadgeText() {}, setBadgeBackgroundColor() {} },
    webNavigation: { onCreatedNavigationTarget: event() },
  };
  const ctx = vm.createContext({ chrome, console, URL, crypto: require('node:crypto').webcrypto,
    setInterval: () => 1, clearInterval() {}, setTimeout, clearTimeout,
    WebSocket: class { readyState = 0; } });
  vm.runInContext(fs.readFileSync('ai_dev_browser/extension/background.js', 'utf8'), ctx);
  if (beforeRestore) beforeRestore(chrome);
  await vm.runInContext('boot()', ctx);
  const run = code => vm.runInContext(code, ctx);
  return { chrome, tabs, windows, saved, run };
}

test('Chrome replacement transfers only proven ownership and reports successor', async () => {
  const { chrome, run } = await fixture();
  run('claim(11); mainTabId=11; attached.add(11)');
  await chrome.tabs.onReplaced.handlers[0](12, 11);
  await new Promise(setImmediate);
  assert.equal(run('mainTabId'), 12);
  assert.equal(run('autoTabs.has(12) && !autoTabs.has(11)'), true);
  assert.equal(run('ownershipError(11).ownership.successorTargetId'), '12');
  await chrome.tabs.onRemoved.handlers[0](11);
  assert.equal(run('ownershipError(11).ownership.state'), 'replaced');
  await chrome.tabs.onReplaced.handlers[0](88, 99);
  assert.equal(run('autoTabs.has(88) || autoTabs.has(99)'), false);
});

test('windowless startup creates one owned window/page before announcing readiness', async () => {
  const { chrome, tabs, windows, run } = await fixture();
  tabs.clear();
  windows.clear();
  const writes = [];
  chrome.windows.getAll = async () => [...windows.values()];
  chrome.windows.create = async options => {
    writes.push({ kind: 'window', options });
    windows.set(200, { id: 200, focused: false });
    tabs.set(201, { id: 201, windowId: 200, url: options.url });
    return windows.get(200);
  };
  chrome.tabs.query = async filter => [...tabs.values()].filter(tab => !filter?.windowId || tab.windowId === filter.windowId);
  await run('ensureDedicatedTab()');
  assert.equal(writes.length, 1);
  assert.equal(writes[0].kind, 'window');
  assert.equal(writes[0].options.url, 'about:blank');
  assert.equal(writes[0].options.focused, false);
  assert.equal(run('mainTabId'), 201);
  assert.equal(run('autoTabs.has(201) && attached.has(201)'), true);
});

test('explicit target creation chooses a normal window and dispatches once', async () => {
  const { chrome, tabs, windows, run } = await fixture();
  windows.get(102).focused = true;
  const writes = [];
  chrome.windows.getAll = async () => [...windows.values()];
  chrome.tabs.create = async options => {
    writes.push(options);
    const tab = { id: 202, windowId: options.windowId, url: options.url };
    tabs.set(tab.id, tab);
    return tab;
  };
  const created = await run("browserLevel('Target.createTarget', {url:'https://neutral.test/created'})");
  assert.equal(writes.length, 1);
  assert.equal(writes[0].windowId, 102);
  assert.equal(writes[0].active, false);
  assert.equal(created.targetId, '202');
  assert.equal(run('autoTabs.has(202) && attached.has(202)'), true);
  assert.equal(run('autoTabs.has(99)'), false);
});

for (const route of ['initial', 'late']) {
  test(`launch handshake keeps its owned page until the caller navigates (${route})`, async () => {
    const { chrome, tabs, run } = await fixture();
    const token = '0'.repeat(32);
    const marker = { id: 12, url: `http://127.0.0.1:9522/adb-launch/${token}` };
    tabs.set(12, marker);
    const navigation = [];
    chrome.tabs.update = async (id, change) => {
      navigation.push({ id, change });
      return Object.assign(tabs.get(id), change);
    };
    if (route === 'initial') await run('ensureDedicatedTab()');
    else await run(`adoptLaunch(${JSON.stringify(marker)})`);
    assert.deepEqual(navigation, []);
    assert.equal(run('mainTabId'), 12);
    assert.equal(run('attached.has(12)'), true);
    assert.equal(run('autoTabs.size'), 1);
    assert.equal(run('autoTabs.has(99)'), false);
    assert.equal(run('launchToken'), token);
    assert.equal(tabs.get(12).url, marker.url);
  });
}

test('cancellation interrupts pending attachment and survives managed discovery/worker restore', async () => {
  const state = await fixture();
  const { chrome, run, saved } = state;
  run('claim(11); mainTabId=11');
  let finishAttach;
  chrome.debugger.attach = () => new Promise(resolve => { finishAttach = resolve; });
  const attaching = run('attachTab(11)');
  const refused = assert.rejects(attaching, /revoked/);
  chrome.debugger.onDetach.handlers[0]({ tabId: 11 }, 'canceled_by_user');
  finishAttach();
  await refused;
  run('managedPolicyValue=true');
  await run('targetInfos()');
  assert.equal(run('autoTabs.has(11) || attached.has(11)'), false);
  assert.equal(run('mainTabId'), 11);
  const restored = await fixture(saved);
  await assert.rejects(restored.run('ensureDedicatedTab()'), /revoked/);
  assert.equal(restored.run('autoTabs.has(11)'), false);
});

test('cancellation wins while same-tab target_closed recovery is pending', async () => {
  const { chrome, run } = await fixture();
  run('claim(11); attached.add(11)');
  let finishGet;
  const get = chrome.tabs.get;
  chrome.tabs.get = () => new Promise(resolve => { finishGet = resolve; });
  chrome.debugger.onDetach.handlers[0]({ tabId: 11 }, 'target_closed');
  chrome.debugger.onDetach.handlers[0]({ tabId: 11 }, 'canceled_by_user');
  chrome.tabs.get = get;
  finishGet({ id: 11 });
  await new Promise(setImmediate);
  assert.equal(run('autoTabs.has(11) || attached.has(11)'), false);
  assert.equal(run('ownershipError(11).ownership.state'), 'revoked');
});

test('a cancellation waking a suspended worker waits for restored ownership', async () => {
  const { run } = await fixture({ adbMainTabId: 11, adbAutoTabs: [11] }, chrome => {
    chrome.debugger.onDetach.handlers[0]({ tabId: 11 }, 'canceled_by_user');
  });
  await new Promise(setImmediate);
  assert.equal(run('autoTabs.has(11) || attached.has(11)'), false);
  assert.equal(run('ownershipError(11).ownership.state'), 'revoked');
});

test('late proven child survives parent closure; revocation and unrelated tabs do not grant access', async () => {
  const { chrome, run } = await fixture();
  run('claim(11)');
  await chrome.tabs.onRemoved.handlers[0](11);
  await chrome.webNavigation.onCreatedNavigationTarget.handlers[0]({ tabId: 12, sourceTabId: 11 });
  await new Promise(setImmediate);
  assert.equal(run('autoTabs.has(12)'), true);
  run('forget(12, "revoked", {reason:"canceled_by_user"})');
  await chrome.webNavigation.onCreatedNavigationTarget.handlers[0]({ tabId: 88, sourceTabId: 12 });
  assert.equal(run('autoTabs.has(88)'), false);
  await assert.rejects(run('browserLevel("Browser.getWindowForTarget", {targetId:"99"}, null)'), /unowned/);
  await assert.rejects(run('browserLevel("Target.getTargetInfo", {targetId:"99"}, null)'), /unowned/);
});

test('ownership diagnostics are bounded and omit query/fragment and unrelated URLs', async () => {
  const { chrome, run } = await fixture();
  run('claim(11)');
  for (let i=0; i<140; i++) chrome.tabs.onUpdated.handlers[0](11, {url:'https://neutral.test/next?secret=credential#token'}, { id:11 });
  chrome.tabs.onUpdated.handlers[0](99, {url:'https://neutral.test/private?secret=credential'}, { id:99 });
  const log = run('JSON.stringify(ownershipLog)');
  assert.equal(run('ownershipLog.length'), 100);
  assert.ok(log.includes('https://neutral.test/next'));
  assert.ok(!log.includes('credential') && !log.includes('#token') && !log.includes('/private'));
});

test('window bounds use native window APIs only for the selected owned tab', async () => {
  const { run, windows } = await fixture();
  run('claim(11)');
  await run('browserLevel("Browser.setWindowBounds", {windowId:101,bounds:{windowState:"minimized"}}, "11")');
  assert.equal(windows.get(101).state, 'minimized');
  const observed = await run('browserLevel("Browser.getWindowBounds", {windowId:101}, "11")');
  assert.equal(observed.bounds.windowState, 'minimized');
  for (const method of ['Browser.getWindowBounds', 'Browser.setWindowBounds']) {
    await assert.rejects(run(`browserLevel(${JSON.stringify(method)}, {windowId:102,bounds:{windowState:"minimized"}}, "11")`), /does not contain/);
    await assert.rejects(run(`browserLevel(${JSON.stringify(method)}, {windowId:102}, "99")`), /unowned/);
  }
  assert.equal(windows.get(102).state, 'normal');
});

test('consent revocation during window lookup prevents native mutation', async () => {
  const { chrome, run, windows } = await fixture();
  run('claim(11)');
  let release;
  chrome.tabs.get = () => new Promise(resolve => { release = resolve; });
  const setting = run('browserLevel("Browser.setWindowBounds", {windowId:101,bounds:{windowState:"minimized"}}, "11")');
  const refused = assert.rejects(setting, /revoked/);
  run('forget(11, "revoked")');
  release({id:11, windowId:101});
  await refused;
  assert.equal(windows.get(101).state, 'normal');
});
