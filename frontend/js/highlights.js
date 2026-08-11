/* highlights.js — StoryViewer único (imersivo · glass sutil · design Aleff) */
(() => {
  'use strict';

  const DEFAULT_IMG_MS = 6000;
  const NAV_COOLDOWN_MS = 280;
  const HOLD_MS = 220;
  const TAP_MAX_MS = 320;
  const TAP_MAX_MOVE = 12;
  const DRAG_ARM = 10;
  const SWIPE_X = 72;
  const SWIPE_Y = 110;
  const SWIPE_VX = 0.45;
  const SWIPE_VY = 0.55;

  function $(sel, root = document) {
    return root.querySelector(sel);
  }

  function esc(s) {
    return String(s ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/"/g, '&quot;');
  }

  function safeMediaPath(src) {
    const p = String(src || '').replace(/\\/g, '/').replace(/^\/+/, '');
    if (!p || p.includes('..') || /^(https?:|data:|javascript:)/i.test(p)) return '';
    if (!(p.startsWith('fotos/') || p.startsWith('videos/') || p.startsWith('api/'))) return '';
    return p;
  }

  function mediaIdOf(item) {
    const id = Number(item?.mediaId ?? item?.media_id ?? 0);
    if (id > 0) return id;
    const p = String(item?.src || '');
    const m = p.match(/\/api\/media\/(\d+)\b/i) || p.match(/^api\/media\/(\d+)\b/i);
    return m ? Number(m[1]) : 0;
  }

  /** Qualidade do Story: preview adequado à tela — nunca original HD */
  function storyThumbUrl(mediaId, tier) {
    const id = Number(mediaId);
    if (!(id > 0)) return '';
    if (tier === 'low') return `api/media/${id}/thumb-small`;
    if (tier === 'mid') return `api/media/${id}/thumb-medium`;
    // high: medium + sz limitado (retina), ainda preview — não original
    return `api/media/${id}/thumb?sz=1200`;
  }

  function storySrcPair(item) {
    const raw = safeMediaPath(item?.src);
    const previewRaw = safeMediaPath(item?.preview);
    const mid = mediaIdOf(item);
    const q = netQuality();
    const tier = q === 'low' ? 'low' : q === 'mid' ? 'mid' : 'high';

    if (mid > 0) {
      const hi = storyThumbUrl(mid, tier);
      const lo = previewRaw || storyThumbUrl(mid, 'low') || hi;
      if (tier === 'low') return { display: lo || hi, upgrade: '' };
      return { display: lo || hi, upgrade: hi && hi !== lo ? hi : '' };
    }

    // API path sem mediaId explícito — sobe o sz se for thumb
    if (raw && /^api\/media\/\d+\//i.test(raw)) {
      const m = raw.match(/^api\/media\/(\d+)/i);
      if (m) {
        const hi = storyThumbUrl(m[1], tier);
        const lo = /thumb-medium|thumb-small/i.test(raw) ? raw : storyThumbUrl(m[1], 'low');
        if (tier === 'low') return { display: lo || hi, upgrade: '' };
        return { display: lo || raw, upgrade: hi };
      }
    }

    return { display: raw, upgrade: '' };
  }

  function netQuality() {
    try {
      const c = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
      if (!c) return 'high';
      if (c.saveData) return 'low';
      const t = String(c.effectiveType || '');
      if (t === 'slow-2g' || t === '2g') return 'low';
      if (t === '3g') return 'mid';
      return 'high';
    } catch {
      return 'high';
    }
  }

  const prefetchCache = new Set();
  function prefetch(src, { priority = 'low' } = {}) {
    const p = safeMediaPath(src);
    if (!p || prefetchCache.has(p)) return;
    if (netQuality() === 'low' && priority === 'low') return;
    prefetchCache.add(p);
    if (prefetchCache.size > 24) {
      const first = prefetchCache.values().next().value;
      prefetchCache.delete(first);
    }
    if (/\.(mp4|webm|mov)(\?|$)/i.test(p)) {
      if (netQuality() === 'low') return;
      const v = document.createElement('video');
      v.preload = 'metadata';
      v.muted = true;
      v.playsInline = true;
      v.src = p;
      return;
    }
    const img = new Image();
    img.decoding = 'async';
    if ('fetchPriority' in img) img.fetchPriority = priority === 'high' ? 'high' : 'low';
    img.src = p;
  }

  async function loadConfig() {
    try {
      const r = await fetch('/data/highlights.json', { cache: 'no-store' });
      if (!r.ok) throw new Error('highlights.json');
      return await r.json();
    } catch {
      return { title: 'Destaques', items: [] };
    }
  }

  const CHEV_L = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M15 6 9 12l6 6"/></svg>';
  const CHEV_R = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>';

  /* Capas tipo Highlights — ícones line art (não fotos) */
  const HL_ICONS = {
    chat: `<svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M14 36.5c0-6.4 5.6-11.5 12.5-11.5H30c6.9 0 12.5 5.1 12.5 11.5S36.9 48 30 48h-2.8L22 54v-6.2c-4.8-1.2-8-5.4-8-11.3z"/><path d="M34 28c1.2-4.8 6-8.2 11.8-8.2 7 0 12.7 4.8 12.7 10.8S52.8 41.4 45.8 41.4h-2.2L40 46v-5.4"/><circle cx="45.5" cy="30.5" r="1.5" fill="currentColor" stroke="none"/><path d="M45.5 34.2v4.2" stroke-width="2.6"/></svg>`,
    camera: `<svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M18 22h-2a6 6 0 0 0-6 6v22a6 6 0 0 0 6 6h36a6 6 0 0 0 6-6V28a6 6 0 0 0-6-6h-2l-3.2-6.5A3 3 0 0 0 44 20H28a3 3 0 0 0-2.7 1.6L22 22z"/><circle cx="32" cy="38" r="10"/><circle cx="32" cy="38" r="5.5"/><path d="M29.6 36.2c.7-1 1.8-1.5 3-1.2 1.4.3 2.3 1.4 2.3 2.8 0 1.8-1.5 3.1-3.3 3.1-.8 0-1.5-.3-2.1-.7" stroke-width="2"/><path d="M30.6 39.4 32.4 41l3.2-3.6" stroke-width="2"/><circle cx="46.5" cy="29.5" r="1.8" fill="currentColor" stroke="none"/></svg>`,
    vanity: `<svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="26" cy="26" r="13"/><ellipse cx="26" cy="26" rx="8" ry="10"/><path d="M26 39v10M20 49h12"/><rect x="42" y="34" width="7" height="16" rx="2"/><path d="M45.5 34V22"/><path d="M53 20c3 4 5 9 5 14" stroke-width="2.2"/><path d="M53 20c.2 2.5.8 4.5 2 6.5" stroke-width="2.2"/></svg>`,
    clapper: `<svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><rect x="10" y="28" width="44" height="26" rx="2"/><path d="M10 28l9-16 12 7-7 9"/><path d="M32 19l11 6.5-6.5 9.5"/><path d="M44 25.5 54 31"/><path d="M19 16.5 26 28M35 21l5.5 9"/><path d="M10 38h44"/></svg>`,
  };

  function resolveIcon(h) {
    const key = String(h?.icon || h?.id || '').toLowerCase();
    if (HL_ICONS[key]) return HL_ICONS[key];
    const map = {
      destaques: 'chat',
      'behind-fotos': 'camera',
      behind_fotos: 'camera',
      ensaios: 'vanity',
      'behind-video': 'clapper',
      'behind-vídeo': 'clapper',
      behind_video: 'clapper',
    };
    return HL_ICONS[map[key]] || '';
  }

  function createViewer() {
    let el = $('#hlViewer');
    if (el) return el;
    el = document.createElement('div');
    el.id = 'hlViewer';
    el.className = 'hl-viewer';
    el.setAttribute('aria-hidden', 'true');
    el.innerHTML = `
      <div class="hl-viewer-bg" data-hl-close tabindex="-1"></div>
      <div class="hl-viewer-shell" role="dialog" aria-modal="true" aria-label="Explorar sequência">
        <div class="hl-ambient" id="hlAmbient" hidden></div>

        <div class="hl-viewer-stage" id="hlStage">
          <div class="hl-peek" id="hlPeek" aria-hidden="true"></div>
          <div class="hl-frame" id="hlFrame"></div>
        </div>
        <div class="hl-privacy-veil" id="hlPrivacyVeil" hidden aria-hidden="true"></div>

        <div class="hl-chrome">
          <div class="hl-progress" id="hlProgress" role="group" aria-label="Progresso da sequência"></div>
          <header class="hl-viewer-top">
            <div class="hl-viewer-meta">
              <img class="hl-viewer-avatar" id="hlAvatar" alt="" width="34" height="34"/>
              <div class="hl-viewer-text">
                <span class="hl-viewer-label" id="hlLabel"></span>
                <span class="hl-viewer-sub" id="hlSub"></span>
              </div>
            </div>
            <div class="hl-viewer-actions">
              <button type="button" class="hl-glass" id="hlMute" aria-label="Ativar som" hidden>
                <svg class="hl-ico-mute" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M11 5 6 9H3v6h3l5 4V5z"/><path d="m22 9-6 6M16 9l6 6"/></svg>
                <svg class="hl-ico-unmute" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" hidden><path d="M11 5 6 9H3v6h3l5 4V5z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/></svg>
              </button>
              <button type="button" class="hl-glass" data-hl-close aria-label="Fechar">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M6 6l12 12M18 6L6 18"/></svg>
              </button>
            </div>
          </header>
        </div>

        <div class="hl-bridge" id="hlBridge" hidden>
          <p class="hl-bridge-kicker">Próximo capítulo</p>
          <p class="hl-bridge-title" id="hlBridgeTitle"></p>
          <div class="hl-bridge-actions">
            <button type="button" class="hl-bridge-cta" id="hlBridgeGo">Continuar</button>
            <button type="button" class="hl-bridge-ghost" data-hl-close>Fechar</button>
          </div>
        </div>

        <button type="button" class="hl-nav hl-nav-prev" id="hlPrev" aria-label="Foto anterior">
          <span class="hl-nav-glyph">${CHEV_L}</span>
        </button>
        <button type="button" class="hl-nav hl-nav-next" id="hlNext" aria-label="Próxima foto">
          <span class="hl-nav-glyph">${CHEV_R}</span>
        </button>
      </div>`;
    document.body.appendChild(el);
    return el;
  }

  function initHighlights(config) {
    const root = $('#highlightsRail');
    if (!root || !config?.items?.length) return;

    const titleEl = $('#highlightsTitle');
    if (titleEl && config.title) titleEl.textContent = config.title;

    root.innerHTML = '';
    const highlights = config.items.filter((h) => h && h.label && Array.isArray(h.items) && h.items.length);
    const openers = [];

    highlights.forEach((h, hi) => {
      const cover = safeMediaPath(h.cover) || safeMediaPath(h.items[0]?.src) || '';
      const iconSvg = resolveIcon(h);
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'hl-circle';
      btn.setAttribute('role', 'listitem');
      btn.setAttribute('aria-label', `Abrir ${h.label}`);
      const thumbInner = iconSvg
        ? `<span class="hl-icon" aria-hidden="true">${iconSvg}</span>`
        : (cover ? `<img src="${esc(cover)}" alt="" width="152" height="152" loading="lazy" decoding="async"/>` : '');
      btn.innerHTML = `
        <span class="hl-ring" aria-hidden="true">
          <span class="hl-thumb${iconSvg ? ' hl-thumb--icon' : ''}">
            ${thumbInner}
          </span>
        </span>
        <span class="hl-name">${esc(h.label)}</span>`;
      btn.addEventListener('click', () => openHighlight(highlights, hi, 0, btn));
      openers[hi] = btn;
      root.appendChild(btn);
    });

    const viewer = createViewer();
    const shell = viewer.querySelector('.hl-viewer-shell');
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)').matches;

    let state = {
      list: highlights,
      hi: 0,
      ii: 0,
      timer: null,
      startedAt: 0,
      slideTotalMs: DEFAULT_IMG_MS,
      elapsedMs: 0,
      paused: false,
      video: null,
      closing: false,
      holding: false,
      lastNavAt: 0,
      scrollY: 0,
      opener: null,
      bridge: false,
      muted: true,
      suppressClick: false,
      navDir: 0,
      peekSrc: '',
      scrollLocked: false,
      privacyPaused: false,
    };

    function clearTimer() {
      if (state.timer) {
        clearTimeout(state.timer);
        state.timer = null;
      }
    }

    function stopMedia() {
      clearTimer();
      if (state.video) {
        try {
          state.video.pause();
          state.video.removeAttribute('src');
          state.video.load();
        } catch { /* ignore */ }
        state.video = null;
      }
    }

    function canNav() {
      const now = performance.now();
      if (now - state.lastNavAt < NAV_COOLDOWN_MS) return false;
      state.lastNavAt = now;
      return true;
    }

    function spentMs() {
      if (state.paused || state.bridge) return state.elapsedMs;
      if (!state.startedAt) return state.elapsedMs;
      return state.elapsedMs + (performance.now() - state.startedAt);
    }

    function frameEl() {
      return $('#hlFrame', viewer);
    }

    function peekEl() {
      return $('#hlPeek', viewer);
    }

    function currentMedia() {
      return frameEl()?.querySelector('.hl-media');
    }

    function neighborItem(dir) {
      const h = state.list[state.hi];
      if (!h) return null;
      if (dir < 0) {
        if (state.ii < h.items.length - 1) return h.items[state.ii + 1];
        return state.list[state.hi + 1]?.items?.[0] || null;
      }
      if (dir > 0) {
        if (state.ii > 0) return h.items[state.ii - 1];
        const prevH = state.list[state.hi - 1];
        if (!prevH) return null;
        return prevH.items[prevH.items.length - 1] || null;
      }
      return null;
    }

    function peekVisualSrc(item) {
      if (!item) return '';
      if (item.type === 'video') {
        return safeMediaPath(item.poster) || '';
      }
      const pair = storySrcPair(item);
      return pair.display || pair.upgrade || '';
    }

    function clearPeek() {
      const peek = peekEl();
      if (!peek) return;
      peek.classList.remove('is-on');
      peek.style.transition = 'none';
      peek.style.transform = '';
      peek.style.opacity = '';
      peek.innerHTML = '';
      state.peekSrc = '';
    }

    function ensurePeek(dir) {
      const peek = peekEl();
      if (!peek || reduced) return;
      const item = neighborItem(dir);
      let src = peekVisualSrc(item);
      if (!src && item?.type === 'video') {
        // sem poster: não força vídeo no peek
        clearPeek();
        return;
      }
      if (!src) {
        clearPeek();
        return;
      }
      if (state.peekSrc !== src) {
        peek.innerHTML = '';
        const img = document.createElement('img');
        img.className = 'hl-media hl-media--fill';
        img.src = src;
        img.alt = '';
        img.decoding = 'async';
        peek.appendChild(img);
        state.peekSrc = src;
      }
      peek.classList.add('is-on');
    }

    function resetTransforms({ animate = false } = {}) {
      const frame = frameEl();
      const peek = peekEl();
      const m = currentMedia();
      const ease = '0.28s cubic-bezier(0.22, 1, 0.36, 1)';
      [frame, peek, m].forEach((node) => {
        if (!node) return;
        node.style.transition = animate && !reduced ? `transform ${ease}, opacity ${ease}` : 'none';
        node.style.transform = '';
        node.style.opacity = '';
      });
      viewer.style.opacity = '';
      if (!animate) clearPeek();
      else {
        setTimeout(() => clearPeek(), reduced ? 0 : 280);
      }
    }

    function applyDrag(dx, dy) {
      const frame = frameEl();
      const peek = peekEl();
      const m = currentMedia();
      if (!frame || !m) return;
      const absX = Math.abs(dx);
      const absY = Math.abs(dy);
      viewer.classList.add('is-dragging');
      frame.style.transition = 'none';
      m.style.transition = 'none';
      if (peek) peek.style.transition = 'none';

      if (absY > absX && dy > 0) {
        clearPeek();
        const t = Math.min(1, dy / 420);
        frame.style.transform = `translate3d(0, ${dy}px, 0) scale(${1 - t * 0.05})`;
        frame.style.opacity = String(Math.max(0.45, 1 - t * 0.5));
        viewer.style.opacity = String(Math.max(0.55, 1 - t * 0.35));
        return;
      }

      const w = shell?.clientWidth || window.innerWidth || 360;
      const follow = dx * 0.9;
      frame.style.transform = `translate3d(${follow}px, 0, 0)`;
      frame.style.opacity = String(Math.max(0.5, 1 - absX / 480));

      // dir < 0: arrasta esquerda → próxima à direita
      if (dx < -8) {
        ensurePeek(-1);
        if (peek?.classList.contains('is-on')) {
          const ox = w + follow;
          peek.style.transform = `translate3d(${ox}px, 0, 0)`;
          peek.style.opacity = String(Math.min(1, absX / 90));
        }
      } else if (dx > 8) {
        ensurePeek(1);
        if (peek?.classList.contains('is-on')) {
          const ox = -w + follow;
          peek.style.transform = `translate3d(${ox}px, 0, 0)`;
          peek.style.opacity = String(Math.min(1, absX / 90));
        }
      } else {
        clearPeek();
      }
    }

    function setAmbient(src) {
      const amb = $('#hlAmbient', viewer);
      if (!amb) return;
      if (!src || /\.(mp4|webm|mov)(\?|$)/i.test(src)) {
        amb.hidden = true;
        amb.style.backgroundImage = '';
        return;
      }
      amb.hidden = false;
      amb.style.backgroundImage = `url("${src}")`;
    }

    function lockBodyScroll() {
      if (state.scrollLocked) return;
      const y = window.scrollY || window.pageYOffset || document.documentElement.scrollTop || 0;
      state.scrollY = y;
      state.scrollLocked = true;
      document.documentElement.classList.add('hl-noscroll');
      document.body.classList.add('hl-noscroll');
      document.body.style.position = 'fixed';
      document.body.style.top = `-${y}px`;
      document.body.style.left = '0';
      document.body.style.right = '0';
      document.body.style.width = '100%';
      document.body.style.overflow = 'hidden';
    }

    function restoreScrollY(y) {
      const top = Math.max(0, Number(y) || 0);
      const html = document.documentElement;
      const prev = html.style.scrollBehavior;
      html.style.scrollBehavior = 'auto';
      html.scrollTop = top;
      if (document.body) document.body.scrollTop = top;
      window.scrollTo(0, top);
      // Reaplica após o paint — iOS/WebKit às vezes zera o scroll ao tirar position:fixed
      requestAnimationFrame(() => {
        html.scrollTop = top;
        window.scrollTo(0, top);
        requestAnimationFrame(() => {
          window.scrollTo(0, top);
          html.style.scrollBehavior = prev;
        });
      });
    }

    function unlockBodyScroll() {
      if (!state.scrollLocked) return;
      const y = state.scrollY || 0;
      state.scrollLocked = false;
      document.documentElement.classList.remove('hl-noscroll');
      document.body.classList.remove('hl-noscroll');
      document.body.style.position = '';
      document.body.style.top = '';
      document.body.style.left = '';
      document.body.style.right = '';
      document.body.style.width = '';
      document.body.style.overflow = '';
      restoreScrollY(y);
    }

    function updateMeta() {
      const h = state.list[state.hi];
      const label = $('#hlLabel', viewer);
      const sub = $('#hlSub', viewer);
      const avatar = $('#hlAvatar', viewer);
      if (!h || !label) return;
      label.textContent = h.label || '';
      if (sub) sub.textContent = h.subtitle || '';
      const cover = safeMediaPath(h.cover) || '';
      if (avatar) {
        avatar.src = cover || '';
        avatar.hidden = !cover;
      }
    }

    function renderProgress() {
      const bar = $('#hlProgress', viewer);
      const h = state.list[state.hi];
      if (!bar || !h) return;
      bar.innerHTML = h.items.map((_, i) => {
        let cls = 'hl-seg';
        if (i < state.ii) cls += ' is-done';
        if (i === state.ii) cls += ' is-active';
        return `<button type="button" class="${cls}" data-seg="${i}" aria-label="Ir para item ${i + 1}"><i></i></button>`;
      }).join('');
    }

    function setProgressVisual(pct, { animateMs = 0 } = {}) {
      const seg = viewer.querySelector('.hl-seg.is-active i');
      if (!seg) return;
      const p = Math.min(1, Math.max(0, pct));
      seg.style.transition = 'none';
      seg.style.transform = `scaleX(${p})`;
      if (animateMs > 0 && !reduced && !state.paused && !state.bridge) {
        void seg.offsetWidth;
        seg.style.transition = `transform ${animateMs}ms linear`;
        seg.style.transform = 'scaleX(1)';
      }
    }

    function setMuteUI() {
      const btn = $('#hlMute', viewer);
      if (!btn) return;
      btn.hidden = !state.video;
      const muteIco = btn.querySelector('.hl-ico-mute');
      const unIco = btn.querySelector('.hl-ico-unmute');
      if (muteIco) muteIco.hidden = !state.muted;
      if (unIco) unIco.hidden = !!state.muted;
      btn.setAttribute('aria-label', state.muted ? 'Ativar som' : 'Silenciar');
    }

    function scheduleAdvance(remaining) {
      clearTimer();
      if (state.paused || state.bridge || remaining <= 0) return;
      state.startedAt = performance.now();
      const total = state.slideTotalMs || remaining;
      const done = Math.min(total, Math.max(0, total - remaining));
      setProgressVisual(done / total, { animateMs: remaining });
      state.timer = setTimeout(() => {
        if (!state.paused && !state.bridge) goNext({ force: true });
      }, remaining);
    }

    function pauseStory() {
      if (state.paused || state.bridge) return;
      state.paused = true;
      clearTimer();
      state.elapsedMs = spentMs();
      state.startedAt = 0;
      const total = state.slideTotalMs || DEFAULT_IMG_MS;
      setProgressVisual(Math.min(1, state.elapsedMs / total), { animateMs: 0 });
      if (state.video && !state.video.paused) {
        try { state.video.pause(); } catch { /* ignore */ }
      }
      viewer.classList.add('is-paused');
    }

    function resumeStory() {
      if (!state.paused || state.bridge) return;
      state.paused = false;
      viewer.classList.remove('is-paused');
      if (state.video) state.video.play()?.catch?.(() => {});
      const total = state.slideTotalMs || DEFAULT_IMG_MS;
      const left = Math.max(200, total - state.elapsedMs);
      scheduleAdvance(left);
    }

    function togglePause() {
      if (state.paused) resumeStory();
      else pauseStory();
    }

    function prefetchNeighbors() {
      const h = state.list[state.hi];
      if (!h) return;
      const next = h.items[state.ii + 1] || state.list[state.hi + 1]?.items?.[0];
      const prev = h.items[state.ii - 1];
      const q = netQuality();
      const pref = (it) => {
        if (!it) return;
        if (it.type === 'video') {
          prefetch(it.src, { priority: 'high' });
          return;
        }
        const pair = storySrcPair(it);
        prefetch(pair.upgrade || pair.display, { priority: 'high' });
        if (pair.display && pair.upgrade) prefetch(pair.display, { priority: 'low' });
      };
      pref(next);
      if (prev && q !== 'low') pref(prev);
    }

    function hideBridge() {
      state.bridge = false;
      const bridge = $('#hlBridge', viewer);
      if (bridge) bridge.hidden = true;
      viewer.classList.remove('is-bridge');
    }

    function showBridge(nextHi) {
      stopMedia();
      clearPeek();
      state.bridge = true;
      state.paused = true;
      viewer.classList.add('is-bridge', 'is-paused');
      const next = state.list[nextHi];
      const bridge = $('#hlBridge', viewer);
      const title = $('#hlBridgeTitle', viewer);
      if (title) title.textContent = next?.label || 'Continuar';
      if (bridge) bridge.hidden = false;
      const go = $('#hlBridgeGo', viewer);
      if (go) {
        go.onclick = () => {
          hideBridge();
          state.hi = nextHi;
          state.ii = 0;
          state.paused = false;
          state.navDir = 1;
          viewer.classList.remove('is-paused');
          showSlide();
        };
      }
    }

    function enterClass() {
      if (reduced || !state.navDir) return 'hl-media hl-media--fill hl-media--enter';
      if (state.navDir > 0) return 'hl-media hl-media--fill hl-media--enter-next';
      return 'hl-media hl-media--fill hl-media--enter-prev';
    }

    function showSlide() {
      stopMedia();
      hideBridge();
      clearPeek();
      state.paused = false;
      state.elapsedMs = 0;
      state.holding = false;
      state.muted = true;
      viewer.classList.remove('is-paused', 'is-dragging');
      viewer.style.opacity = '';

      const h = state.list[state.hi];
      const item = h?.items?.[state.ii];
      const frame = frameEl();
      if (!h || !item || !frame) return;

      updateMeta();
      renderProgress();
      frame.innerHTML = '';
      frame.style.transform = '';
      frame.style.opacity = '';
      prefetchNeighbors();

      const q = netQuality();
      const cls = enterClass();

      if (item.type === 'video') {
        const src = safeMediaPath(item.src);
        if (!src) {
          goNext({ force: true });
          return;
        }
        setAmbient(safeMediaPath(item.poster) || safeMediaPath(h.cover) || '');
        const v = document.createElement('video');
        v.className = cls;
        v.src = src;
        v.playsInline = true;
        v.setAttribute('playsinline', '');
        v.setAttribute('webkit-playsinline', '');
        v.preload = q === 'low' ? 'metadata' : 'auto';
        v.controls = false;
        v.loop = false;
        v.muted = true;
        v.setAttribute('muted', '');
        if (item.poster) {
          const poster = safeMediaPath(item.poster);
          if (poster) v.poster = poster;
        }
        frame.appendChild(v);
        state.video = v;
        setMuteUI();

        const arm = () => {
          const ms = (v.duration && Number.isFinite(v.duration) && v.duration > 0)
            ? v.duration * 1000
            : 12000;
          state.slideTotalMs = ms;
          scheduleAdvance(ms);
        };
        if (v.readyState >= 1) arm();
        else v.addEventListener('loadedmetadata', arm, { once: true });
        v.addEventListener('ended', () => {
          if (!state.paused && !state.bridge) goNext({ force: true });
        }, { once: true });
        v.play()?.catch?.(() => {});
      } else {
        const pair = storySrcPair(item);
        const src = pair.display || pair.upgrade;
        if (!src) {
          goNext({ force: true });
          return;
        }
        setAmbient(src);
        const img = document.createElement('img');
        img.className = cls;
        img.src = src;
        img.alt = (item.title || h.label || '');
        img.decoding = 'async';
        if ('fetchPriority' in img) img.fetchPriority = 'high';
        frame.appendChild(img);

        // Upgrade progressivo para resolução maior (sem bloquear a UI)
        if (pair.upgrade && pair.upgrade !== src) {
          const hi = new Image();
          hi.decoding = 'async';
          if ('fetchPriority' in hi) hi.fetchPriority = 'high';
          hi.onload = () => {
            if (img.isConnected) img.src = pair.upgrade;
          };
          hi.src = pair.upgrade;
        }

        setMuteUI();
        const sec = Number(item.duration);
        const ms = (sec > 0 ? sec : DEFAULT_IMG_MS / 1000) * 1000;
        state.slideTotalMs = ms;
        scheduleAdvance(ms);
      }
      state.navDir = 0;
    }

    function goNext(opts = {}) {
      if (!opts.force && !canNav() && !state.bridge) return;
      const h = state.list[state.hi];
      if (!h) return;
      state.navDir = 1;
      if (state.ii < h.items.length - 1) {
        state.ii += 1;
        showSlide();
        return;
      }
      if (state.hi < state.list.length - 1) {
        showBridge(state.hi + 1);
        return;
      }
      closeViewer();
    }

    function goPrev() {
      if (!canNav()) return;
      if (state.bridge) {
        hideBridge();
        state.paused = false;
        viewer.classList.remove('is-paused');
        state.navDir = -1;
        showSlide();
        return;
      }
      if (spentMs() > 1200) {
        state.navDir = 0;
        showSlide();
        return;
      }
      state.navDir = -1;
      if (state.ii > 0) {
        state.ii -= 1;
        showSlide();
        return;
      }
      if (state.hi > 0) {
        state.hi -= 1;
        state.ii = Math.max(0, (state.list[state.hi].items.length || 1) - 1);
        showSlide();
        return;
      }
      state.navDir = 0;
      showSlide();
    }

    function openHighlight(list, hi, ii, opener) {
      state.list = list;
      state.hi = hi;
      state.ii = ii;
      state.closing = false;
      state.navDir = 0;
      state.opener = opener || openers[hi] || null;
      viewer.classList.add('is-open');
      viewer.setAttribute('aria-hidden', 'false');
      lockBodyScroll();
      showSlide();
      setPrivacyVeil(false);
      requestAnimationFrame(() => {
        viewer.querySelector('[data-hl-close].hl-glass')?.focus({ preventScroll: true });
      });
    }

    function closeViewer() {
      if (state.closing) return;
      state.closing = true;
      stopMedia();
      hideBridge();
      clearPeek();
      setPrivacyVeil(false);
      viewer.classList.remove('is-open', 'is-paused', 'is-bridge', 'is-dragging');
      viewer.setAttribute('aria-hidden', 'true');
      viewer.style.opacity = '';
      setAmbient('');
      unlockBodyScroll();
      // Não focar o opener no touch — WebKit ignora preventScroll e joga a página
      if (finePointer) {
        requestAnimationFrame(() => {
          try { state.opener?.focus({ preventScroll: true }); } catch { /* ignore */ }
        });
      }
      const frame = frameEl();
      if (frame) frame.innerHTML = '';
    }

    function setPrivacyVeil(on) {
      const veil = $('#hlPrivacyVeil', viewer);
      if (!veil) return;
      veil.hidden = !on;
      veil.setAttribute('aria-hidden', on ? 'false' : 'true');
      viewer.classList.toggle('is-privacy', !!on);
      if (on) {
        if (!state.paused) {
          state.privacyPaused = true;
          pauseStory();
        }
      } else if (state.privacyPaused) {
        state.privacyPaused = false;
        if (!state.holding && !state.bridge) resumeStory();
      }
    }

    document.addEventListener('visibilitychange', () => {
      if (!viewer.classList.contains('is-open')) return;
      if (document.visibilityState === 'hidden') setPrivacyVeil(true);
      else setPrivacyVeil(false);
    });

    $('#hlStage', viewer)?.addEventListener('contextmenu', (e) => {
      e.preventDefault();
    });
    $('#hlStage', viewer)?.addEventListener('dragstart', (e) => {
      e.preventDefault();
    });

    viewer.addEventListener('click', (e) => {
      if (e.target.closest('[data-hl-close]')) closeViewer();
    });

    // Navegação por botão: desktop (fine pointer). Touch usa gestos.
    const bindNav = (el, fn) => {
      el?.addEventListener('click', (e) => {
        if (state.suppressClick) {
          e.preventDefault();
          e.stopPropagation();
          return;
        }
        // Em touch, o pointerup do shell já navega — evita double
        if (!finePointer && e.detail !== 0) {
          // still allow if activated without gesture (keyboard/SR often detail=0)
        }
        e.preventDefault();
        e.stopPropagation();
        fn();
      });
    };
    bindNav($('#hlPrev', viewer), goPrev);
    bindNav($('#hlNext', viewer), goNext);

    $('#hlMute', viewer)?.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (!state.video) return;
      state.muted = !state.muted;
      state.video.muted = state.muted;
      if (!state.muted) state.video.removeAttribute('muted');
      else state.video.setAttribute('muted', '');
      setMuteUI();
      state.video.play()?.catch?.(() => {});
    });

    $('#hlProgress', viewer)?.addEventListener('click', (e) => {
      const seg = e.target.closest('[data-seg]');
      if (!seg) return;
      e.stopPropagation();
      if (!canNav()) return;
      const idx = Number.parseInt(seg.getAttribute('data-seg') || '', 10);
      if (!Number.isFinite(idx)) return;
      hideBridge();
      state.navDir = idx > state.ii ? 1 : idx < state.ii ? -1 : 0;
      state.ii = idx;
      state.paused = false;
      viewer.classList.remove('is-paused');
      showSlide();
    });

    let holdTimer = null;
    let gesture = null;

    function clearHoldTimer() {
      if (holdTimer) {
        clearTimeout(holdTimer);
        holdTimer = null;
      }
    }

    function isChromeUI(target) {
      return !!target?.closest?.(
        '.hl-chrome, .hl-bridge, [data-hl-close], #hlMute, .hl-glass'
      );
    }

    function zoneFromX(clientX) {
      const rect = shell.getBoundingClientRect();
      const x = (clientX - rect.left) / Math.max(1, rect.width);
      if (x < 0.42) return 'prev';
      if (x > 0.58) return 'next';
      return 'center';
    }

    shell?.addEventListener('pointerdown', (e) => {
      if (!viewer.classList.contains('is-open')) return;
      if (e.pointerType === 'mouse' && e.button !== 0) return;
      if (isChromeUI(e.target)) return;
      if (state.bridge) return;

      try { shell.setPointerCapture?.(e.pointerId); } catch { /* ignore */ }

      gesture = {
        id: e.pointerId,
        x0: e.clientX,
        y0: e.clientY,
        t0: performance.now(),
        x: e.clientX,
        y: e.clientY,
        t: performance.now(),
        dragging: false,
        axis: null,
        fromNav: !!e.target.closest('.hl-nav'),
      };
      state.suppressClick = false;

      clearHoldTimer();
      holdTimer = setTimeout(() => {
        if (!gesture || gesture.dragging) return;
        state.holding = true;
        pauseStory();
      }, HOLD_MS);
    });

    shell?.addEventListener('pointermove', (e) => {
      if (!gesture || e.pointerId !== gesture.id) return;
      const dx = e.clientX - gesture.x0;
      const dy = e.clientY - gesture.y0;
      gesture.x = e.clientX;
      gesture.y = e.clientY;
      gesture.t = performance.now();

      if (!gesture.dragging) {
        if (Math.hypot(dx, dy) < DRAG_ARM) return;
        gesture.dragging = true;
        state.suppressClick = true;
        clearHoldTimer();
        if (state.holding) state.holding = false;
        else pauseStory();
        gesture.axis = Math.abs(dy) > Math.abs(dx) ? 'y' : 'x';
      }

      if (gesture.axis === 'y') applyDrag(0, Math.max(0, dy));
      else applyDrag(dx, 0);
    });

    function endGesture(e) {
      if (!gesture || (e && e.pointerId !== gesture.id)) return;
      const g = gesture;
      gesture = null;
      clearHoldTimer();
      viewer.classList.remove('is-dragging');

      const dx = (e?.clientX ?? g.x) - g.x0;
      const dy = (e?.clientY ?? g.y) - g.y0;
      const dt = Math.max(16, (e ? performance.now() : g.t) - g.t0);
      const vx = Math.abs(dx) / dt;
      const vy = Math.abs(dy) / dt;

      if (state.holding && !g.dragging) {
        state.holding = false;
        resumeStory();
        return;
      }

      if (g.dragging) {
        state.suppressClick = true;
        setTimeout(() => { state.suppressClick = false; }, 100);

        const dismiss = (dy > SWIPE_Y && Math.abs(dy) > Math.abs(dx))
          || (dy > 60 && vy > SWIPE_VY && dy > Math.abs(dx));
        if (dismiss) {
          closeViewer();
          return;
        }

        const goX = (Math.abs(dx) > SWIPE_X && Math.abs(dx) > Math.abs(dy))
          || (Math.abs(dx) > 48 && vx > SWIPE_VX && Math.abs(dx) > Math.abs(dy));

        if (goX) {
          clearPeek();
          resetTransforms();
          state.lastNavAt = 0;
          if (dx < 0) goNext();
          else goPrev();
          return;
        }

        resetTransforms({ animate: true });
        if (!state.bridge) resumeStory();
        return;
      }

      const isTap = dt <= TAP_MAX_MS && Math.hypot(dx, dy) <= TAP_MAX_MOVE;
      if (!isTap) {
        if (!state.bridge && state.paused) resumeStory();
        return;
      }

      // Desktop: clique no nav → deixa o click handler do botão agir
      if (finePointer && g.fromNav) {
        return;
      }

      state.suppressClick = true;
      setTimeout(() => { state.suppressClick = false; }, 100);

      const zone = zoneFromX(g.x0);
      if (zone === 'center') {
        togglePause();
        return;
      }
      state.lastNavAt = 0;
      if (zone === 'prev') goPrev();
      else goNext();
    }

    shell?.addEventListener('pointerup', endGesture);
    shell?.addEventListener('pointercancel', endGesture);
    shell?.addEventListener('lostpointercapture', endGesture);

    document.addEventListener('keydown', (e) => {
      if (!viewer.classList.contains('is-open')) return;
      if (e.key === 'Escape') {
        e.preventDefault();
        closeViewer();
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        goNext();
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        goPrev();
      } else if (e.key === ' ') {
        e.preventDefault();
        togglePause();
      }
    });

    let orientTimer = null;
    const onOrient = () => {
      if (!viewer.classList.contains('is-open')) return;
      clearTimeout(orientTimer);
      orientTimer = setTimeout(() => {
        resetTransforms();
        const stage = $('#hlStage', viewer);
        if (stage) void stage.offsetHeight;
      }, 120);
    };
    window.addEventListener('orientationchange', onOrient);
    window.addEventListener('resize', onOrient);
  }

  document.addEventListener('DOMContentLoaded', async () => {
    if (!$('#highlightsRail')) return;
    const config = await loadConfig();
    initHighlights(config);
  });
})();
