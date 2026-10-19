// Deterministic state/race tests. These are unit tests, not live Chrome evidence.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const event = () => ({ handlers: [], addListener(fn) { this.handlers.push(fn); } });
async function fixture(saved = {}, beforeRestore = null) {
  const tabs = new Map([[11, { id: 11, url: 'https://neutral.test/consent?secret=yes#token' }], [12, { id: 12, url: 'https://neutral.test/result' }], [99, { id: 99, url: 'https://neutral.test/private' }]]);
  const chrome = {
    tabs: { onCreated: event(), onUpdated: event(), onRemoved: event(), onReplaced: event(),
      get: async id => { if (!tabs.has(id)) throw Error('closed'); return tabs.get(id); },
      query: async () => [...tabs.values()], update: async id => tabs.get(id) },
    debugger: { onDetach: event(), onEvent: event(), attach: async () => {}, detach: async () => {}, sendCommand: async () => ({}) },
    storage: { local: { get: async () => ({ adbProfileId: 'profile' }), set: async () => {} },
      session: { get: async () => saved, set: async data => Object.assign(saved, structuredClone(data)) },
      managed: { get: async () => ({ ManagedBrowserProfile: false }) }, onChanged: event() },
    runtime: { getManifest: () => ({ version: 'test' }), onStartup: event(), onInstalled: event() },
    action: { setBadgeText() {}, setBadgeBackgroundColor() {} },
    webNavigation: { onCreatedNavigationTarget: event() },
  };
  const ctx = vm.createContext({ chrome, console, URL, crypto: require('node:crypto').webcrypto,
    setInterval: () => 1, clearInterval() {}, setTimeout, clearTimeout,
    WebSocket: class { readyState = 0; } });
  vm.runInContext(fs.readFileSync('ai_dev_browser/extension/background.js', 'utf8'), ctx);
  if (beforeRestore) beforeRestore(chrome);
  await vm.runInContext('boot()', ctx);
  const run = code => vm.runInContext(code, ctx);
  return { chrome, tabs, saved, run };
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
