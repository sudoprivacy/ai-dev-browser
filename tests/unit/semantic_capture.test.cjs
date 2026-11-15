const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../../ai_dev_browser/record/capture.js'), 'utf8');

function world(overrides = {}) {
  const events = [];
  const listeners = new Map();
  const timers = new Set();
  let reads = 0;
  const root = {nodeType: 1, tagName: 'HTML'};
  const originalPush = () => {};
  const history = {pushState: originalPush, replaceState: () => {}};
  const document = {
    documentElement: root, readyState: 'complete',
    get title() { reads += 1; return 'Fixture'; },
    addEventListener(kind, handler) {
      if (!listeners.has(kind)) listeners.set(kind, new Set());
      listeners.get(kind).add(handler);
    },
    removeEventListener(kind, handler) { listeners.get(kind)?.delete(handler); },
    getElementById() { return null; },
    querySelector() { return null; },
  };
  const context = vm.createContext({
    __ADB_RECORD_CONFIG__: {recordingId: 'original-recording', targetId: 'original-target',
      bindingName: 'captureBinding', nonce: 'fixture-nonce',
      inputPolicy: 'mask-sensitive', urlQueryPolicy: 'mask-sensitive',
      showIndicator: false, ...overrides},
    captureBinding: value => events.push(JSON.parse(value)),
    document, history, location: {href: 'https://example.test/form'},
    innerWidth: 640, innerHeight: 480, scrollX: 0, scrollY: 0,
    URL, URLSearchParams,
    getComputedStyle() { return {visibility: 'visible', display: 'block'}; },
    setTimeout(callback, delay) {
      let timer;
      timer = setTimeout(() => {timers.delete(timer); callback();}, delay);
      timers.add(timer);
      return timer;
    },
    clearTimeout(timer) {timers.delete(timer); clearTimeout(timer);},
  });
  vm.runInContext(source, context);
  function element(attributes = {}, value = '') {
    return {
      nodeType: 1, tagName: 'INPUT', type: attributes.type || 'text',
      id: attributes.id || 'field', value, checked: false, files: [],
      parentElement: root, previousElementSibling: null, labels: [],
      textContent: attributes.textContent || '', innerText: attributes.textContent || '',
      getAttribute(name) {return attributes[name] ?? null;},
      hasAttribute(name) {return attributes[name] !== undefined;},
      closest() {return null;},
      getBoundingClientRect() {return {x: 1, y: 2, width: 100, height: 20};},
    };
  }
  function fire(kind, target) {
    for (const handler of listeners.get(kind) || []) handler({target, key: 'Enter'});
  }
  return {context, events, listeners, timers, history, originalPush, element, fire,
    get reads() {return reads;}};
}

test('definition reads no document and installs no listeners before authorized start', () => {
  const fixture = world();
  assert.equal(fixture.reads, 0);
  assert.equal(fixture.events.length, 0);
  assert.equal(fixture.listeners.size, 0);
  assert.equal(fixture.history.pushState, fixture.originalPush);
  fixture.context.__adbSemanticRecorder.start();
  assert.equal(fixture.reads, 0);
  assert.equal(fixture.listeners.size, 0);
  fixture.context.__adbSemanticRecorder.start('fixture-context-nonce');
  assert.equal(fixture.events[0].event.kind, 'recorder_installed');
  fixture.context.__adbSemanticRecorder.stop(false);
  assert.equal([...fixture.listeners.values()].every(handlers => handlers.size === 0), true);
  fixture.context.__adbSemanticRecorder.start('fixture-context-nonce');
  assert.equal(fixture.events.length, 1, 'a retired instance cannot restart');
  assert.equal(fixture.history.pushState, fixture.originalPush);
});

test('stop flushes exactly the last pending input and clears its timer/listeners', () => {
  const fixture = world();
  fixture.context.__adbSemanticRecorder.start('fixture-context-nonce');
  const input = fixture.element({name: 'query'}, 'first');
  fixture.fire('input', input);
  input.value = 'last original value';
  fixture.fire('input', input);
  assert.equal(fixture.timers.size, 1);
  fixture.context.__adbSemanticRecorder.stop(true);
  assert.deepEqual(fixture.events.map(item => item.event.kind), ['recorder_installed', 'input']);
  assert.equal(fixture.events[1].event.value, 'last original value');
  assert.equal(fixture.timers.size, 0);
  assert.equal([...fixture.listeners.values()].every(handlers => handlers.size === 0), true);
  fixture.fire('change', input);
  assert.equal(fixture.events.length, 2);
});

test('revoked cleanup discards pending field reads instead of flushing', () => {
  const fixture = world();
  fixture.context.__adbSemanticRecorder.start('fixture-context-nonce');
  const input = fixture.element({name: 'query'}, 'private pending value');
  fixture.fire('input', input);
  Object.defineProperty(input, 'value', {get() {throw new Error('must not read after withdrawal');}});
  fixture.context.__adbSemanticRecorder.stop(false);
  assert.equal(fixture.events.length, 1);
  assert.equal(fixture.timers.size, 0);
});

test('password metadata does not fall back to initial value or text', () => {
  const fixture = world();
  fixture.context.__adbSemanticRecorder.start('fixture-context-nonce');
  const password = fixture.element({type: 'password', value: 'private-initial',
    textContent: 'private-initial'}, 'private-typed');
  fixture.fire('change', password);
  const serialized = JSON.stringify(fixture.events);
  assert.equal(serialized.includes('private-initial'), false);
  assert.equal(serialized.includes('private-typed'), false);
  assert.equal(fixture.events.at(-1).event.value, '{{sensitive_value}}');
  fixture.context.__adbSemanticRecorder.stop(false);
});

test('unchecked checkbox state and file metadata retain their actual meaning', () => {
  const fixture = world();
  fixture.context.__adbSemanticRecorder.start('fixture-context-nonce');
  const checkbox = fixture.element({type: 'checkbox'}, 'on');
  checkbox.checked = true;
  fixture.fire('change', checkbox);
  checkbox.checked = false;
  fixture.fire('change', checkbox);
  assert.deepEqual(fixture.events.slice(-2).map(item => item.event.checked), [true, false]);
  const file = fixture.element({type: 'file'});
  file.files = [{name: 'fixture.txt'}];
  Object.defineProperty(file, 'value', {get() {throw new Error('no local path read');}});
  fixture.fire('change', file);
  assert.equal(fixture.events.at(-1).event.kind, 'file_selection');
  assert.equal(fixture.events.at(-1).event.fileCount, 1);
  assert.equal('value' in fixture.events.at(-1).event, false);
  fixture.context.__adbSemanticRecorder.stop(false);
});
