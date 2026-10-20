/** A reusable pixel surface. The host owns authentication and control policy. */
export class PageSurface {
  constructor(image, send, { drag = false } = {}) {
    this.image = image;
    this.send = send;
    this.width = 0;
    this.height = 0;
    this.pointer = null;
    this.events = new AbortController();
    const on = (name, listener, options = {}) =>
      image.addEventListener(name, listener, { ...options, signal: this.events.signal });
    on('dragstart', event => event.preventDefault());
    on('pointerdown', event => {
      if (event.button !== 0 || this.pointer) return;
      const point = this.point(event);
      if (!point) return;
      this.pointer = { id: event.pointerId, lastY: event.clientY, startY: event.clientY, startX: event.clientX,
        moved: false, drag: drag && event.pointerType !== 'touch', points: [point] };
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
      if (this.pointer?.id === event.pointerId && this.pointer.drag && this.pointer.moved) {
        const point = this.point(event);
        if (point) {
          if (this.pointer.points.length === 64) this.pointer.points.pop();
          send({ kind: 'drag', points: [...this.pointer.points, point] });
        }
      }
      if (this.pointer?.id === event.pointerId && !this.pointer.moved) {
        const point = this.point(event);
        if (point) send({ kind: 'click', ...point });
      }
      this.pointer = null;
    });
    on('pointercancel', () => { this.pointer = null; });
    on('wheel', event => {
      event.preventDefault();
      const point = this.point(event);
      if (point) send({ kind: 'wheel', ...point, dy: event.deltaY });
    }, { passive: false });
    on('keydown', event => {
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

  point(event) {
    const box = this.image.getBoundingClientRect();
    if (!box.width || !box.height || !this.width || !this.height) return null;
    return {
      x: Math.max(0, Math.min(this.width - 1, (event.clientX - box.left) * this.width / box.width)),
      y: Math.max(0, Math.min(this.height - 1, (event.clientY - box.top) * this.height / box.height)),
    };
  }

  frame(value) {
    if (!value.data || !Number.isFinite(value.width) || !Number.isFinite(value.height)
        || value.width <= 0 || value.height <= 0) return;
    this.width = value.width;
    this.height = value.height;
    this.image.src = 'data:image/jpeg;base64,' + value.data;
    this.image.style.aspectRatio = value.width + '/' + value.height;
  }

  clear() {
    this.width = this.height = 0;
    this.pointer = null;
    this.image.removeAttribute('src');
  }

  dispose() {
    this.events.abort();
    this.clear();
  }
}
