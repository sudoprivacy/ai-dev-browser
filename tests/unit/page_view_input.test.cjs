// Public DOM event contracts; these unit cases do not count as live Chrome.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

const moduleUrl = pathToFileURL(path.resolve(__dirname, '../../ai_dev_browser/remote/page_view.js')).href;
const flush = async () => {
  await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));
};
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
};

async function fixture(send) {
  const { InputSurface } = await import(moduleUrl);
  const image = new EventTarget();
  Object.assign(image, { style: {}, clientHeight: 100, focus() {}, setPointerCapture() {},
    getBoundingClientRect() { return { left: 0, top: 0, width: 100, height: 100 }; } });
  const packets = [];
  const surface = new InputSurface(image, packet => {
    packets.push(packet);
    return send(packet);
  }, { drag: true, liveDrag: true, viewerId: 'owned-viewer' });
  surface.resize(100, 100);
  function pointer(type, x) {
    const event = new Event(type);
    Object.assign(event, { pointerId: 1, button: 0, pointerType: 'mouse', clientX: x, clientY: 20 });
    image.dispatchEvent(event);
  }
  return { image, surface, pointer, packets };
}

test('pointer-up survives a subsequent copy-control blur before begin is acknowledged', async () => {
  const gate = deferred();
  const f = await fixture(packet => packet.phase === 'begin' ? gate.promise : Promise.resolve());
  f.pointer('pointerdown', 10); f.pointer('pointermove', 30);
  await flush();
  f.pointer('pointerup', 60);
  f.image.dispatchEvent(new Event('blur'));
  gate.resolve(); await flush();
  assert.deepEqual(f.packets.map(p => p.phase), ['begin', 'end']);
  assert.equal(f.packets[1].x, 60);
  f.surface.dispose();
});

test('whenIdle waits for the final host acknowledgement, including an already released pointer', async () => {
  const begin = deferred(), end = deferred();
  const f = await fixture(packet => packet.phase === 'begin' ? begin.promise : end.promise);
  f.pointer('pointerdown', 10); f.pointer('pointermove', 30);
  await flush(); f.pointer('pointerup', 60);
  let settled = false;
  const idle = f.surface.whenIdle().then(() => { settled = true; });
  begin.resolve(); await flush();
  assert.equal(settled, false);
  assert.deepEqual(f.packets.map(p => p.phase), ['begin', 'end']);
  end.resolve(); await idle;
  assert.equal(settled, true);
  f.surface.dispose();
});

test('blur while still pressed cancels and waits for the cancellation acknowledgement', async () => {
  const begin = deferred(), cancel = deferred();
  const f = await fixture(packet => packet.phase === 'begin' ? begin.promise : cancel.promise);
  f.pointer('pointerdown', 10); f.pointer('pointermove', 30);
  await flush();
  f.image.dispatchEvent(new Event('blur'));
  const idle = f.surface.whenIdle();
  begin.resolve(); await flush();
  assert.deepEqual(f.packets.map(p => p.phase), ['begin', 'cancel']);
  cancel.resolve(); await idle;
  f.surface.dispose();
});

test('explicit clear still cancels a queued end at an ownership boundary', async () => {
  const begin = deferred();
  const f = await fixture(packet => packet.phase === 'begin' ? begin.promise : Promise.resolve());
  f.pointer('pointerdown', 10); f.pointer('pointermove', 30);
  await flush(); f.pointer('pointerup', 60);
  f.surface.clear();
  const idle = f.surface.whenIdle();
  begin.resolve(); await idle;
  assert.deepEqual(f.packets.map(p => p.phase), ['begin', 'cancel']);
  f.surface.dispose();
});

test('failed input rejects the read barrier without replaying the failed packet', async () => {
  const begin = deferred();
  const f = await fixture(() => begin.promise);
  f.pointer('pointerdown', 10); f.pointer('pointermove', 30);
  await flush(); f.pointer('pointerup', 60);
  const rejected = assert.rejects(f.surface.whenIdle(), /host input failure/);
  begin.reject(new Error('host input failure'));
  await rejected; await flush();
  assert.deepEqual(f.packets.map(p => p.phase), ['begin']);
  await f.surface.whenIdle();
  f.surface.dispose();
});

test('an idle surface has an immediately fulfilled read barrier', async () => {
  const f = await fixture(() => Promise.resolve());
  await f.surface.whenIdle();
  assert.deepEqual(f.packets, []);
  f.surface.dispose();
});
