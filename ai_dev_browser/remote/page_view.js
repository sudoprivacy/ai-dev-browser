/** Shared image/canvas input. The host owns authentication and control policy. */
export class InputSurface {
  constructor(image, send, { drag = false, touchDrag = false, liveDrag = false, viewerId = '' } = {}) {
    if (liveDrag && (!viewerId || viewerId.length > 128)) throw new Error('Live drag requires the attached viewer ID');
    this.image = image;
    this.send = send;
    this.width = 0;
    this.height = 0;
    this.pointer = null;
    this.gesture = null;
    this.liveDrag = liveDrag;
    this.viewerId = viewerId;
    this.events = new AbortController();
    const on = (name, listener, options = {}) =>
      image.addEventListener(name, listener, { ...options, signal: this.events.signal });
    on('dragstart', event => event.preventDefault());
    on('pointerdown', event => {
      if (event.button !== 0 || this.pointer || this.gesture) return;
      const point = this.point(event);
      if (!point) return;
      this.pointer = { id: event.pointerId, lastY: event.clientY, startY: event.clientY, startX: event.clientX,
        moved: false, drag: drag && (event.pointerType !== 'touch' || touchDrag), points: [point] };
      image.setPointerCapture(event.pointerId);
      image.focus({ preventScroll: true });
    });
    on('pointermove', event => {
      if (!this.pointer || this.pointer.id !== event.pointerId) return;
      const delta = this.pointer.lastY - event.clientY;
      if (Math.hypot(event.clientX - this.pointer.startX, event.clientY - this.pointer.startY) > 8) this.pointer.moved = true;
      if (this.pointer.drag) {
        const point = this.point(event);
        if (point) {
          if (liveDrag && this.pointer.moved) {
            if (!this.gesture) this.beginDrag(this.pointer.points[0]);
            this.gesture.latest = point;
            this.pumpDrag();
            return;
          }
          // Keep endpoints and a bounded representative path, never an
          // unbounded event backlog that could outlive the host's lease.
          if (this.pointer.points.length === 64)
            this.pointer.points = this.pointer.points.filter((_, index) => index % 2 === 0);
          this.pointer.points.push(point);
        }
        return;
      }
      if (this.pointer.moved && Math.abs(delta) > 2) {
        const point = this.point(event);
        if (point) send({ kind: 'wheel', ...point, dy: delta * this.height / image.clientHeight });
        this.pointer.lastY = event.clientY;
      }
    });
    on('pointerup', event => {
      if (this.pointer?.id !== event.pointerId) return;
      if (this.pointer?.id === event.pointerId && this.pointer.drag && this.pointer.moved) {
        const point = this.point(event);
        if (point) {
          if (liveDrag) {
            if (this.gesture) this.finishDrag('end', point);
          } else {
            if (this.pointer.points.length === 64) this.pointer.points.pop();
            send({ kind: 'drag', points: [...this.pointer.points, point] });
          }
        }
      }
      if (this.pointer?.id === event.pointerId && !this.pointer.moved) {
        const point = this.point(event);
        if (point) send({ kind: 'click', ...point });
      }
      this.pointer = null;
    });
    const cancel = () => { this.finishDrag('cancel'); this.pointer = null; };
    on('pointercancel', event => { if (this.pointer?.id === event.pointerId) cancel(); });
    on('lostpointercapture', event => { if (this.pointer?.id === event.pointerId) cancel(); });
    // Moving focus after pointer-up must not cancel its queued completion.
    // An unfinished press still releases when the surface loses focus.
    on('blur', () => { if (this.pointer) cancel(); });
    on('wheel', event => {
      event.preventDefault();
      if (this.gesture) return;
      const point = this.point(event);
      if (point) send({ kind: 'wheel', ...point, dy: event.deltaY });
    }, { passive: false });
    on('keydown', event => {
      if (this.gesture) { event.preventDefault(); return; }
      if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === 'a') {
        event.preventDefault();
        send({ kind: 'key', key: 'SelectAll' });
        return;
      }
      if (event.ctrlKey || event.metaKey || event.altKey || event.isComposing) return;
      event.preventDefault();
      if (event.key.length === 1) send({ kind: 'text', text: event.key });
      else send({ kind: 'key', key: event.key, shift: event.shiftKey });
    });
  }

  beginDrag(point) {
    let resolveIdle, rejectIdle;
    const idle = new Promise((resolve, reject) => { resolveIdle = resolve; rejectIdle = reject; });
    // Hosts may wait before reading selection. The normal input error path
    // still reports a failure when no read barrier is currently observing it.
    idle.catch(() => {});
    this.gesture = { id: crypto.randomUUID(), sequence: 0, pending: false,
      begin: point, latest: null, finish: null, last: point, idle, resolveIdle, rejectIdle };
    this.pumpDrag();
  }

  /** Wait for issued live input; this neither replays input nor grants a lease. */
  whenIdle() {
    return this.gesture?.idle || Promise.resolve();
  }

  finishDrag(phase, point) {
    if (!this.gesture) return;
    this.gesture.finish = { phase, point: point || this.gesture.latest || this.gesture.last };
    this.pumpDrag();
  }

  pumpDrag() {
    const gesture = this.gesture;
    if (!gesture || gesture.pending) return;
    let phase, point;
    if (gesture.begin) { phase = 'begin'; point = gesture.begin; gesture.begin = null; }
    else if (gesture.finish) { ({ phase, point } = gesture.finish); }
    else if (gesture.latest) { phase = 'move'; point = gesture.latest; }
    else return;
    gesture.latest = null;
    gesture.last = point;
    gesture.pending = true;
    const packet = { kind: 'drag-stream', phase, gestureId: gesture.id,
      sequence: gesture.sequence++, viewerId: this.viewerId, ...point };
    // The host returns the checked API acknowledgement. Retain only the
    // latest unsent position, so a slow link cannot accumulate stale moves.
    Promise.resolve().then(() => this.send(packet)).then(() => {
      if (this.gesture !== gesture) return;
      gesture.pending = false;
      if (phase === 'end' || phase === 'cancel') {
        this.gesture = null;
        gesture.resolveIdle();
      }
      else this.pumpDrag();
    }).catch(error => {
      // Never replay failed input. Server cleanup releases an abandoned press;
      // the host reports its normal input error and retains the human lease.
      if (this.gesture === gesture) this.gesture = null;
      this.pointer = null;
      gesture.rejectIdle(error);
    });
  }

  point(event) {
    const box = this.image.getBoundingClientRect();
    if (!box.width || !box.height || !this.width || !this.height) return null;
    return {
      x: Math.max(0, Math.min(this.width - 1, (event.clientX - box.left) * this.width / box.width)),
      y: Math.max(0, Math.min(this.height - 1, (event.clientY - box.top) * this.height / box.height)),
    };
  }

  resize(width, height) {
    if (!Number.isFinite(width) || !Number.isFinite(height)
        || width <= 0 || height <= 0 || width > 8192 || height > 8192) return false;
    if (this.width !== width || this.height !== height) {
      this.finishDrag('cancel');
      this.pointer = null;
    }
    this.width = width;
    this.height = height;
    this.image.style.aspectRatio = width + '/' + height;
    return true;
  }

  clear() {
    this.finishDrag('cancel');
    this.width = this.height = 0;
    this.pointer = null;
  }

  dispose() {
    this.events.abort();
    this.clear();
  }
}

/** JPEG presentation using the same checked gesture mapper as streamed canvases. */
export class PageSurface extends InputSurface {
  frame(value) {
    if (!value.data || !this.resize(value.width, value.height)) return;
    this.image.src = 'data:image/jpeg;base64,' + value.data;
  }

  clear() {
    super.clear();
    this.image.removeAttribute('src');
  }
}
