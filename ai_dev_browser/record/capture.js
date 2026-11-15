// Derived from Mosswork moss-browser. Copyright (c) 2026 OrcaKit.
// MIT terms are retained in MIT-LICENSE.txt. Installed in an isolated world.
(() => {
  const CONFIG = globalThis.__ADB_RECORD_CONFIG__;
  if (!CONFIG || !CONFIG.bindingName || !CONFIG.nonce) return;
  if (globalThis.__adbSemanticRecorder?.recordingId === CONFIG.recordingId) return;
  let active = false;
  let contextNonce = null;
  let retired = false;
  let localSeq = 0;
  const inputTimers = new Map();
  let lastScrollAt = 0;

  const SENSITIVE_RE = /password|token|secret|key|code|otp|auth|session|jwt/i;
  const URL_KEYS = [
    "token", "access_token", "refresh_token", "code", "state", "session",
    "key", "secret", "password", "auth", "jwt", "id_token", "auth_token", "client_secret", "authorization"
  ];

  function text(v, max = 300) {
    if (v == null) return "";
    return String(v).replace(/\s+/g, " ").trim().slice(0, max);
  }

  function cssEscape(v) {
    if (globalThis.CSS && CSS.escape) return CSS.escape(String(v));
    return String(v).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
  }

  function redactUrl(raw) {
    try {
      const u = new URL(raw, location.href);
      if (CONFIG.urlQueryPolicy === "none") return u.toString();
      u.username = "";
      u.password = "";
      function mask(values) {
        const params = new URLSearchParams(values);
        for (const key of Array.from(params.keys())) {
          if (CONFIG.urlQueryPolicy === "mask-all" || URL_KEYS.includes(key.toLowerCase())) {
            params.set(key, "***");
          }
        }
        return params.toString();
      }
      u.search = mask(u.search);
      const fragment = u.hash.slice(1);
      const question = fragment.indexOf("?");
      if (question >= 0) u.hash = fragment.slice(0, question + 1) + mask(fragment.slice(question + 1));
      else if (fragment.includes("=")) u.hash = mask(fragment);
      else if (fragment && CONFIG.urlQueryPolicy === "mask-all") u.hash = "***";
      return u.toString();
    } catch (_) {
      return "";
    }
  }

  function pageInfo() {
    return {
      targetId: CONFIG.targetId || "",
      url: redactUrl(location.href),
      title: text(document.title, 300),
      viewport: {
        width: globalThis.innerWidth,
        height: globalThis.innerHeight,
        scrollX: globalThis.scrollX,
        scrollY: globalThis.scrollY
      }
    };
  }

  function emit(kind, data = {}) {
    try {
      if (!active) return;
      const fn = globalThis[CONFIG.bindingName];
      if (typeof fn !== "function") return;
      localSeq += 1;
      fn(JSON.stringify({
        nonce: CONFIG.nonce,
        contextNonce,
        schemaVersion: "1.0",
        event: {
          localSeq,
          kind,
          ts: new Date().toISOString(),
          targetId: CONFIG.targetId || "",
          page: pageInfo(),
          ...data
        }
      }));
    } catch (_) {}
  }

  function roleOf(el) {
    if (!el || !el.tagName) return "";
    const explicit = el.getAttribute("role");
    if (explicit) return text(explicit, 80);
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute("type") || "").toLowerCase();
    if (tag === "button") return "button";
    if (tag === "a" && el.hasAttribute("href")) return "link";
    if (tag === "textarea") return "textbox";
    if (tag === "select") return "combobox";
    if (tag === "input") {
      if (["button", "submit", "reset", "image"].includes(type)) return "button";
      if (type === "checkbox") return "checkbox";
      if (type === "radio") return "radio";
      if (type === "range") return "slider";
      return "textbox";
    }
    return "";
  }

  function labelOf(el) {
    try {
      if (el.labels && el.labels.length) {
        return text(Array.from(el.labels).map((l) => l.innerText || l.textContent || "").join(" "));
      }
      if (el.id) {
        const label = document.querySelector(`label[for="${cssEscape(el.id)}"]`);
        if (label) return text(label.innerText || label.textContent || "");
      }
      const parent = el.closest && el.closest("label");
      if (parent) return text(parent.innerText || parent.textContent || "");
    } catch (_) {}
    return "";
  }

  function labelledBy(el) {
    const ids = el.getAttribute && el.getAttribute("aria-labelledby");
    if (!ids) return "";
    return text(ids.split(/\s+/).map((id) => document.getElementById(id)?.innerText || "").join(" "));
  }

  function accessibleName(el) {
    if (!el || !el.getAttribute) return "";
    const parts = [
      el.getAttribute("aria-label"),
      labelledBy(el),
      labelOf(el),
      el.getAttribute("alt"),
      el.getAttribute("title"),
      el.getAttribute("placeholder"),
      sensitive(el) ? "" : (el.innerText || el.textContent),
      sensitive(el) ? "" : el.getAttribute("value")
    ];
    for (const p of parts) {
      const s = text(p);
      if (s) return s;
    }
    return "";
  }

  function stableCssPath(el) {
    if (!el || !el.tagName) return "";
    const parts = [];
    let cur = el;
    for (let i = 0; cur && cur.nodeType === 1 && i < 5; i += 1) {
      const tag = cur.tagName.toLowerCase();
      if (cur.id) {
        parts.unshift(`${tag}#${cssEscape(cur.id)}`);
        break;
      }
      let nth = 1;
      let sib = cur;
      while ((sib = sib.previousElementSibling)) {
        if (sib.tagName === cur.tagName) nth += 1;
      }
      parts.unshift(`${tag}:nth-of-type(${nth})`);
      cur = cur.parentElement;
    }
    return parts.join(" > ");
  }

  function selectorCandidates(el) {
    const out = [];
    if (!el || !el.getAttribute) return out;
    for (const attr of ["data-testid", "data-test", "data-cy"]) {
      const v = el.getAttribute(attr);
      if (v) out.push(`[${attr}="${cssEscape(v)}"]`);
    }
    if (el.id) out.push(`#${cssEscape(el.id)}`);
    const tag = el.tagName.toLowerCase();
    const name = el.getAttribute("name");
    if (name) out.push(`${tag}[name="${cssEscape(name)}"]`);
    const aria = el.getAttribute("aria-label");
    if (aria) out.push(`${tag}[aria-label="${cssEscape(aria)}"]`);
    const type = el.getAttribute("type");
    if (type) out.push(`${tag}[type="${cssEscape(type)}"]`);
    const path = stableCssPath(el);
    if (path) out.push(path);
    return Array.from(new Set(out)).slice(0, 8);
  }

  function xpath(el) {
    if (!el || !el.tagName) return "";
    const parts = [];
    let cur = el;
    while (cur && cur.nodeType === 1 && cur !== document.documentElement) {
      let idx = 1;
      let sib = cur.previousElementSibling;
      while (sib) {
        if (sib.tagName === cur.tagName) idx += 1;
        sib = sib.previousElementSibling;
      }
      parts.unshift(`${cur.tagName.toLowerCase()}[${idx}]`);
      cur = cur.parentElement;
    }
    return `/html/${parts.join("/")}`;
  }

  function visible(el, rect) {
    const style = globalThis.getComputedStyle ? getComputedStyle(el) : null;
    return (
      !!rect && rect.width > 0 && rect.height > 0
      && (!style || (style.visibility !== "hidden" && style.display !== "none"))
    );
  }

  function describeElement(node) {
    const el = node && node.nodeType === 1 ? node : node?.parentElement;
    if (!el || !el.tagName) return null;
    const rect = el.getBoundingClientRect();
    const role = roleOf(el);
    const name = accessibleName(el);
    return {
      tag: el.tagName.toLowerCase(),
      role,
      name,
      accessibleName: name,
      text: sensitive(el) ? "" : text(el.innerText || el.textContent || "", 500),
      label: labelOf(el),
      placeholder: text(el.getAttribute("placeholder")),
      ariaLabel: text(el.getAttribute("aria-label")),
      id: text(el.id, 160),
      nameAttr: text(el.getAttribute("name"), 160),
      type: text(el.getAttribute("type"), 80),
      testId: text(el.getAttribute("data-testid") || el.getAttribute("data-test") || el.getAttribute("data-cy"), 160),
      selectorCandidates: selectorCandidates(el),
      xpath: xpath(el),
      bbox: {
        x: Math.round(rect.x), y: Math.round(rect.y),
        width: Math.round(rect.width), height: Math.round(rect.height)
      },
      visible: visible(el, rect),
      enabled: !(el.disabled || el.getAttribute("aria-disabled") === "true"),
      isContentEditable: !!el.isContentEditable,
      framePath: [],
      shadowPath: []
    };
  }

  function sensitive(el) {
    if (!el || !el.getAttribute) return false;
    const hay = [
      el.getAttribute("type"), el.getAttribute("autocomplete"), el.getAttribute("name"),
      el.id, el.getAttribute("placeholder"), el.getAttribute("aria-label")
    ].join(" ");
    return SENSITIVE_RE.test(hay);
  }

  function readValue(el) {
    if (!el) return { value: "", redacted: false };
    if (CONFIG.inputPolicy === "mask-all" || sensitive(el)) return { value: "{{sensitive_value}}", redacted: true };
    const value = el.value != null ? String(el.value) : text(el.textContent || "");
    if (SENSITIVE_RE.test(value) || value.length > 2000) return { value: "{{redacted_value}}", redacted: true };
    return { value, redacted: false };
  }

  function onClick(event) {
    emit("click", {
      target: describeElement(event.target),
      mouse: { clientX: event.clientX, clientY: event.clientY, button: event.button }
    });
  }
  function onDblClick(event) {
    emit("dblclick", { target: describeElement(event.target) });
  }
  function flushInput(el, kind = "input") {
    if (String(el?.type || "").toLowerCase() === "file") {
      emit("file_selection", { target: describeElement(el), fileCount: el.files?.length || 0 });
      return;
    }
    const v = readValue(el);
    const checked = ["checkbox", "radio"].includes(String(el?.type || "").toLowerCase())
      ? !!el.checked
      : el?.getAttribute?.("aria-checked") === "true" ? true
      : el?.getAttribute?.("aria-checked") === "false" ? false : undefined;
    emit(kind, { target: describeElement(el), value: v.value, redacted: v.redacted,
      ...(checked === undefined ? {} : {checked}) });
  }
  function onInput(event) {
    const el = event.target;
    const old = inputTimers.get(el);
    if (old) clearTimeout(old);
    inputTimers.set(el, setTimeout(() => { inputTimers.delete(el); flushInput(el, "input"); }, 300));
  }
  function onChange(event) {
    const old = inputTimers.get(event.target);
    if (old) clearTimeout(old);
    inputTimers.delete(event.target);
    flushInput(event.target, "change");
  }
  function onSubmit(event) {
    emit("submit", { target: describeElement(event.target) });
  }
  function onKeyDown(event) {
    if (!["Enter", "Tab", "Escape", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(event.key)) return;
    emit("keydown", {
      key: event.key,
      target: describeElement(event.target),
      modifiers: { alt: event.altKey, ctrl: event.ctrlKey, meta: event.metaKey, shift: event.shiftKey }
    });
  }
  function onScroll(event) {
    const now = Date.now();
    if (now - lastScrollAt < 500) return;
    lastScrollAt = now;
    emit("scroll", {
      scroll: { x: globalThis.scrollX, y: globalThis.scrollY },
      target: event.target === document ? null : describeElement(event.target)
    });
  }
  function overlay() {
    if (!active || !document.documentElement || CONFIG.showIndicator === false) return;
    if (document.getElementById("__adb_recording_" + CONFIG.recordingId)) return;
    const div = document.createElement("div");
    div.id = "__adb_recording_" + CONFIG.recordingId;
    div.textContent = `● Recording ${CONFIG.recordingId}`;
    div.style.cssText = [
      "position:fixed;right:12px;top:12px;z-index:2147483647;",
      "background:#b91c1c;color:white;font:12px sans-serif;padding:6px 8px;",
      "border-radius:6px;pointer-events:none;opacity:.88"
    ].join("");
    document.documentElement.appendChild(div);
  }

  const listeners = [
    ["click", onClick], ["dblclick", onDblClick], ["input", onInput],
    ["change", onChange], ["submit", onSubmit], ["keydown", onKeyDown], ["scroll", onScroll],
  ];
  function start(documentNonce) {
    if (active || retired) return;
    if (typeof documentNonce !== 'string' || documentNonce.length < 16 || documentNonce.length > 128) return;
    contextNonce = documentNonce;
    active = true;
    for (const [kind, handler] of listeners) document.addEventListener(kind, handler, true);
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", overlay, {once: true});
    else overlay();
    emit("recorder_installed", {url: redactUrl(location.href)});
  }
  function stop(flush = true) {
    if (active && flush) {
      for (const [element, timer] of inputTimers) {
        clearTimeout(timer);
        flushInput(element);
      }
    }
    active = false;
    retired = true;
    for (const timer of inputTimers.values()) clearTimeout(timer);
    inputTimers.clear();
    for (const [kind, handler] of listeners) document.removeEventListener(kind, handler, true);
    document.removeEventListener("DOMContentLoaded", overlay);
    document.getElementById("__adb_recording_" + CONFIG.recordingId)?.remove();
  }
  globalThis.__adbSemanticRecorder = Object.freeze({recordingId: CONFIG.recordingId, start, stop});
})();
