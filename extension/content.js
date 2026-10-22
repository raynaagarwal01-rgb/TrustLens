// TrustLens buttons inside pages. Sites like WhatsApp Web replace Chrome's right-click menu with their own,
// so the extension's menu never shows there. Instead:
//   - select text anywhere: a "Fact-check" button appears next to it
//   - on chat sites (WhatsApp Web, Telegram Web): hover an image or video for a "Check" button
(() => {
  if (window.__trustlens) return;
  window.__trustlens = true;

  const CHAT_SITE = /(^|\.)web\.whatsapp\.com$|(^|\.)web\.telegram\.org$/.test(location.hostname);
  const host = document.createElement("div");
  host.style.cssText = "position:fixed;z-index:2147483647;top:0;left:0;pointer-events:none";
  const root = host.attachShadow({ mode: "closed" });
  root.innerHTML = `<style>
    button { pointer-events: auto; position: fixed; display: none; align-items: center; gap: 6px; padding: 6px 10px;
      font: 600 13px/1 "Segoe UI", system-ui, sans-serif; color: #2a2100; background: #f2c230; border: 1px solid #c99a0b;
      border-radius: 6px; box-shadow: 0 2px 8px rgba(20,32,43,.35); cursor: pointer; }
    button:hover { background: #ffd34a; }
    button:focus-visible { outline: 3px solid #14202b; outline-offset: 2px; }
    svg { width: 14px; height: 14px; }
  </style>
  <button id="text" type="button"><svg viewBox="0 0 24 24" fill="none" stroke="#14202b" stroke-width="2.6"><circle cx="10" cy="10" r="6"/><path d="M15 15l5 5"/></svg>Fact-check</button>
  <button id="media" type="button"><svg viewBox="0 0 24 24" fill="none" stroke="#14202b" stroke-width="2.6"><circle cx="10" cy="10" r="6"/><path d="M15 15l5 5"/></svg>Check with TrustLens</button>`;
  (document.body || document.documentElement).append(host);
  const textBtn = root.getElementById("text");
  const mediaBtn = root.getElementById("media");
  const MEDIA_HTML = mediaBtn.innerHTML;
  let selected = "", target = null, hideTimer = 0;

  const send = (job) => chrome.runtime.sendMessage({ type: "check", job: { pageUrl: location.href, pageTitle: document.title, ...job } });

  // ------------------------------------------------------------------ selected text
  function showForSelection() {
    const sel = window.getSelection();
    const text = String(sel || "").trim();
    if (text.length < 20 || !sel.rangeCount) { textBtn.style.display = "none"; return; }
    const rect = sel.getRangeAt(sel.rangeCount - 1).getBoundingClientRect();
    if (!rect.width && !rect.height) return;
    selected = text;
    textBtn.style.display = "inline-flex";
    const top = rect.bottom + 8 + 32 > innerHeight ? rect.top - 40 : rect.bottom + 8;
    textBtn.style.top = `${Math.max(4, top)}px`;
    textBtn.style.left = `${Math.min(innerWidth - 130, Math.max(4, rect.right - 110))}px`;
  }
  document.addEventListener("mouseup", (e) => { if (!e.composedPath().includes(host)) setTimeout(showForSelection, 10); }, true);
  document.addEventListener("keyup", (e) => { if (e.shiftKey || e.key === "Shift") showForSelection(); }, true);
  document.addEventListener("selectionchange", () => { if (!String(window.getSelection()).trim()) textBtn.style.display = "none"; });
  addEventListener("scroll", () => { textBtn.style.display = "none"; }, true);
  textBtn.addEventListener("mousedown", (e) => e.preventDefault()); // keep the selection
  textBtn.addEventListener("click", () => { textBtn.style.display = "none"; send({ kind: "text", text: selected }); });

  // ------------------------------------------------------------------ images and videos on chat sites
  async function grab(src) {
    try {
      const blob = await (await fetch(src)).blob();
      if (blob.size > 6e6) return { grabError: "too_big" };
      const dataUrl = await new Promise((done) => { const r = new FileReader(); r.onload = () => done(r.result); r.readAsDataURL(blob); });
      return { dataUrl, mime: blob.type };
    } catch { return { grabError: "blob" }; }
  }
  if (CHAT_SITE) {
    document.addEventListener("mouseover", (e) => {
      const el = e.target.closest?.("img, video");
      if (!el || e.composedPath().includes(host)) return;
      const r = el.getBoundingClientRect();
      if (r.width < 120 || r.height < 90) return; // avatars, emoji, stickers
      clearTimeout(hideTimer);
      target = el;
      mediaBtn.style.display = "inline-flex";
      mediaBtn.style.top = `${Math.max(4, r.top + 8)}px`;
      mediaBtn.style.left = `${Math.max(4, r.left + 8)}px`;
    }, true);
    document.addEventListener("mouseout", (e) => {
      if (e.target === target) hideTimer = setTimeout(() => { mediaBtn.style.display = "none"; }, 600);
    }, true);
    mediaBtn.addEventListener("mouseenter", () => clearTimeout(hideTimer));
    mediaBtn.addEventListener("click", async () => {
      if (!target) return;
      const kind = target.tagName === "VIDEO" ? "video" : "image";
      const src = target.currentSrc || target.src;
      mediaBtn.textContent = "Reading…";
      const extra = src.startsWith("blob:") || src.startsWith("data:") ? await grab(src) : {};
      mediaBtn.style.display = "none";
      mediaBtn.innerHTML = MEDIA_HTML;
      send({ kind, srcUrl: src, ...extra });
    });
  }
})();
