/* AleffPlayer — player unificado (proporção real, volume global, 1 por vez) */
window.AleffPlayer = (() => {
  const ICON = {
    play: '<svg viewBox="0 0 24 24"><polygon points="8 5 19 12 8 19" fill="currentColor" stroke="none"/></svg>',
    pause: '<svg viewBox="0 0 24 24"><rect x="6" y="5" width="4" height="14" fill="currentColor" stroke="none"/><rect x="14" y="5" width="4" height="14" fill="currentColor" stroke="none"/></svg>',
    mute: '<svg viewBox="0 0 24 24"><path d="M11 5 6 9H3v6h3l5 4V5z"/><path d="m22 9-6 6M16 9l6 6"/></svg>',
    volLow: '<svg viewBox="0 0 24 24"><path d="M11 5 6 9H3v6h3l5 4V5z"/><path d="M15.5 9.5a3.5 3.5 0 0 1 0 5"/></svg>',
    volMid: '<svg viewBox="0 0 24 24"><path d="M11 5 6 9H3v6h3l5 4V5z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/></svg>',
    volHigh: '<svg viewBox="0 0 24 24"><path d="M11 5 6 9H3v6h3l5 4V5z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M18.5 5.5a9 9 0 0 1 0 13"/></svg>',
    volDown: '<svg viewBox="0 0 24 24"><path d="M5 12h14"/></svg>',
    volUp: '<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>',
    fs: '<svg viewBox="0 0 24 24"><path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"/></svg>',
    exitFs: '<svg viewBox="0 0 24 24"><path d="M8 3v5H3M16 3v5h5M8 21v-5H3M16 21v-5h5"/></svg>',
  };

  const VOL_STEP = 0.1;
  const VOL_KEY = 'aleff_player_vol';
  const MUTE_KEY = 'aleff_player_muted';

  /** @type {Set<ReturnType<typeof createInstance>>} */
  const registry = new Set();

  const globalAudio = {
    volume: readVol(),
    muted: readMute(),
  };

  function readVol() {
    try {
      const v = parseFloat(localStorage.getItem(VOL_KEY) || '');
      if (Number.isFinite(v)) return Math.min(1, Math.max(0, v));
    } catch { /* ignore */ }
    return 0.85;
  }

  function readMute() {
    try {
      return localStorage.getItem(MUTE_KEY) === '1';
    } catch { /* ignore */ }
    return false;
  }

  function persistAudio() {
    try {
      localStorage.setItem(VOL_KEY, String(globalAudio.volume));
      localStorage.setItem(MUTE_KEY, globalAudio.muted ? '1' : '0');
    } catch { /* ignore */ }
  }

  function setGlobalVolume(v, { unmute = true } = {}) {
    const next = Math.min(1, Math.max(0, v));
    globalAudio.volume = next;
    if (unmute && next > 0.001) globalAudio.muted = false;
    if (next <= 0.001) {
      globalAudio.muted = true;
    }
    persistAudio();
    registry.forEach((p) => p.applyGlobalAudio());
  }

  function setGlobalMute(on) {
    globalAudio.muted = !!on;
    if (!on && globalAudio.volume < 0.05) globalAudio.volume = 0.7;
    persistAudio();
    registry.forEach((p) => p.applyGlobalAudio());
  }

  function pauseAllExcept(keep) {
    registry.forEach((p) => {
      if (p !== keep) p.pause({ silent: true });
    });
  }

  function fmt(sec) {
    if (!Number.isFinite(sec) || sec < 0) return '0:00';
    const s = Math.floor(sec % 60);
    const m = Math.floor(sec / 60) % 60;
    const h = Math.floor(sec / 3600);
    const mm = h ? String(m).padStart(2, '0') : String(m);
    const ss = String(s).padStart(2, '0');
    return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
  }

  function volIcon() {
    if (globalAudio.muted || globalAudio.volume < 0.01) return ICON.mute;
    if (globalAudio.volume < 0.34) return ICON.volLow;
    if (globalAudio.volume < 0.67) return ICON.volMid;
    return ICON.volHigh;
  }

  function create(opts = {}) {
    return createInstance(opts);
  }

  function createInstance(opts = {}) {
    const root = document.createElement('div');
    root.className = 'aplayer is-paused is-loading';
    root.innerHTML = `
      <div class="aplayer-stage">
        <video playsinline preload="metadata"></video>
      </div>
      <div class="aplayer-shade" aria-hidden="true"></div>
      <button type="button" class="aplayer-big" aria-label="Reproduzir"></button>
      <div class="aplayer-chrome">
        <div class="aplayer-progress" role="slider" aria-label="Progresso" tabindex="0">
          <div class="aplayer-buf"></div>
          <div class="aplayer-fill"></div>
          <div class="aplayer-knob"></div>
        </div>
        <div class="aplayer-row">
          <button type="button" class="aplayer-btn" data-act="toggle" aria-label="Play">${ICON.play}</button>
          <div class="aplayer-vol" role="group" aria-label="Volume">
            <button type="button" class="aplayer-btn" data-act="mute" aria-label="Mudo">${ICON.volHigh}</button>
            <button type="button" class="aplayer-btn aplayer-vol-step" data-act="voldn" aria-label="Diminuir volume">${ICON.volDown}</button>
            <div class="aplayer-vol-track" role="slider" aria-label="Nível de volume" aria-valuemin="0" aria-valuemax="100" tabindex="0">
              <div class="aplayer-vol-fill"></div>
              <div class="aplayer-vol-knob"></div>
            </div>
            <button type="button" class="aplayer-btn aplayer-vol-step" data-act="volup" aria-label="Aumentar volume">${ICON.volUp}</button>
            <span class="aplayer-vol-pct" aria-hidden="true">85%</span>
          </div>
          <span class="aplayer-time">0:00 / 0:00</span>
          <span class="aplayer-spacer"></span>
          <span class="aplayer-tag">Aleff Thiago</span>
          <button type="button" class="aplayer-btn" data-act="fs" aria-label="Tela cheia">${ICON.fs}</button>
        </div>
      </div>`;

    const video = root.querySelector('video');
    const big = root.querySelector('.aplayer-big');
    const fill = root.querySelector('.aplayer-fill');
    const buf = root.querySelector('.aplayer-buf');
    const knob = root.querySelector('.aplayer-knob');
    const progress = root.querySelector('.aplayer-progress');
    const timeEl = root.querySelector('.aplayer-time');
    const btnToggle = root.querySelector('[data-act="toggle"]');
    const btnMute = root.querySelector('[data-act="mute"]');
    const btnVolDn = root.querySelector('[data-act="voldn"]');
    const btnVolUp = root.querySelector('[data-act="volup"]');
    const volTrack = root.querySelector('.aplayer-vol-track');
    const volFill = root.querySelector('.aplayer-vol-fill');
    const volKnob = root.querySelector('.aplayer-vol-knob');
    const volPct = root.querySelector('.aplayer-vol-pct');
    const btnFs = root.querySelector('[data-act="fs"]');

    video.controls = false;
    video.setAttribute('playsinline', '');
    video.setAttribute('webkit-playsinline', '');
    if (opts.poster) video.poster = opts.poster;
    if (opts.src) video.src = opts.src;
    if (opts.title) root.setAttribute('aria-label', opts.title);
    video.loop = !!opts.loop;
    video.preload = opts.preload || 'metadata';

    let hideTimer = null;
    let seeking = false;
    let volDragging = false;
    let destroyed = false;
    let io = null;
    let userPaused = false;

    const api = {
      root,
      video,
      play,
      pause,
      applyGlobalAudio,
      setVolume: (v) => setGlobalVolume(v),
      destroy,
    };

    function applyGlobalAudio() {
      video.volume = globalAudio.volume;
      video.muted = globalAudio.muted;
      syncVolumeUI();
    }

    function syncVolumeUI() {
      const muted = globalAudio.muted || globalAudio.volume < 0.01;
      const pct = Math.round(globalAudio.volume * 100);
      volFill.style.width = `${pct}%`;
      volKnob.style.left = `${pct}%`;
      volTrack.setAttribute('aria-valuenow', String(pct));
      volPct.textContent = `${pct}%`;
      btnMute.innerHTML = volIcon();
      btnMute.setAttribute('aria-label', muted ? 'Ativar som' : 'Mudo');
      root.classList.toggle('is-muted', muted);
    }

    function applyAspect() {
      const w = video.videoWidth;
      const h = video.videoHeight;
      if (!w || !h) return;
      root.style.setProperty('--ap-w', String(w));
      root.style.setProperty('--ap-h', String(h));
      root.style.aspectRatio = `${w} / ${h}`;
      root.classList.remove('is-portrait', 'is-landscape', 'is-square');
      if (h > w * 1.05) root.classList.add('is-portrait');
      else if (w > h * 1.05) root.classList.add('is-landscape');
      else root.classList.add('is-square');
    }

    function showChrome(sticky = false) {
      root.classList.add('is-chrome');
      clearTimeout(hideTimer);
      if (!sticky && !video.paused) {
        hideTimer = setTimeout(() => root.classList.remove('is-chrome'), 2400);
      }
    }

    function setPlaying(on) {
      root.classList.toggle('is-paused', !on);
      btnToggle.innerHTML = on ? ICON.pause : ICON.play;
      btnToggle.setAttribute('aria-label', on ? 'Pausar' : 'Play');
      if (on) showChrome();
      else {
        root.classList.add('is-chrome');
        clearTimeout(hideTimer);
      }
    }

    function nudgeVolume(delta) {
      if (globalAudio.muted && delta > 0) {
        setGlobalMute(false);
        if (globalAudio.volume < 0.05) setGlobalVolume(VOL_STEP);
        else setGlobalVolume(globalAudio.volume);
      } else {
        const base = globalAudio.muted ? 0 : globalAudio.volume;
        setGlobalVolume(base + delta);
      }
      showChrome(true);
    }

    function volFromEvent(e) {
      const rect = volTrack.getBoundingClientRect();
      const x = ('touches' in e ? e.touches[0].clientX : e.clientX) - rect.left;
      const ratio = Math.min(1, Math.max(0, x / rect.width));
      setGlobalVolume(ratio);
    }

    async function play() {
      if (destroyed) return;
      pauseAllExcept(api);
      userPaused = false;
      applyGlobalAudio();
      // Autoplay policies: se mutado globalmente, ok; senão tenta com áudio
      try {
        await video.play();
        setPlaying(true);
      } catch {
        // Fallback: tenta mudo só se ainda não havia preferência de áudio
        if (!globalAudio.muted) {
          try {
            video.muted = true;
            await video.play();
            setPlaying(true);
            // não grava mute global — foi só política do browser
            syncVolumeUI();
            return;
          } catch { /* ignore */ }
        }
        setPlaying(false);
      }
    }

    function pause(optsPause = {}) {
      video.pause();
      setPlaying(false);
      if (!optsPause.silent) userPaused = true;
    }

    function toggle() {
      if (video.paused) play();
      else pause();
    }

    function updateProgress() {
      const dur = video.duration || 0;
      const cur = video.currentTime || 0;
      const pct = dur ? (cur / dur) * 100 : 0;
      fill.style.width = `${pct}%`;
      knob.style.left = `${pct}%`;
      timeEl.textContent = `${fmt(cur)} / ${fmt(dur)}`;
      try {
        if (video.buffered.length) {
          const end = video.buffered.end(video.buffered.length - 1);
          buf.style.width = `${dur ? (end / dur) * 100 : 0}%`;
        }
      } catch { /* ignore */ }
    }

    function seekFromEvent(e) {
      const rect = progress.getBoundingClientRect();
      const x = ('touches' in e ? e.touches[0].clientX : e.clientX) - rect.left;
      const ratio = Math.min(1, Math.max(0, x / rect.width));
      if (video.duration) video.currentTime = ratio * video.duration;
      updateProgress();
    }

    function destroy() {
      destroyed = true;
      clearTimeout(hideTimer);
      if (io) {
        try { io.disconnect(); } catch { /* ignore */ }
        io = null;
      }
      registry.delete(api);
      pause({ silent: true });
      video.removeAttribute('src');
      video.load();
      root.remove();
    }

    big.addEventListener('click', (e) => {
      e.stopPropagation();
      toggle();
    });
    video.addEventListener('click', (e) => {
      e.stopPropagation();
      toggle();
      showChrome();
    });
    btnToggle.addEventListener('click', (e) => {
      e.stopPropagation();
      toggle();
    });
    btnMute.addEventListener('click', (e) => {
      e.stopPropagation();
      setGlobalMute(!globalAudio.muted);
      showChrome(true);
    });
    btnVolDn.addEventListener('click', (e) => {
      e.stopPropagation();
      nudgeVolume(-VOL_STEP);
    });
    btnVolUp.addEventListener('click', (e) => {
      e.stopPropagation();
      nudgeVolume(VOL_STEP);
    });

    volTrack.addEventListener('pointerdown', (e) => {
      e.stopPropagation();
      volDragging = true;
      root.classList.add('is-vol-drag');
      volTrack.setPointerCapture?.(e.pointerId);
      volFromEvent(e);
      showChrome(true);
    });
    volTrack.addEventListener('pointermove', (e) => {
      if (!volDragging) return;
      volFromEvent(e);
    });
    const endVolDrag = () => {
      volDragging = false;
      root.classList.remove('is-vol-drag');
      showChrome();
    };
    volTrack.addEventListener('pointerup', endVolDrag);
    volTrack.addEventListener('pointercancel', endVolDrag);
    volTrack.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowRight' || e.key === 'ArrowUp') {
        e.preventDefault();
        nudgeVolume(VOL_STEP);
      } else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') {
        e.preventDefault();
        nudgeVolume(-VOL_STEP);
      }
    });

    btnFs.addEventListener('click', async (e) => {
      e.stopPropagation();
      try {
        if (!document.fullscreenElement) await root.requestFullscreen();
        else await document.exitFullscreen();
      } catch { /* ignore */ }
    });

    progress.addEventListener('pointerdown', (e) => {
      seeking = true;
      root.classList.add('is-seeking');
      progress.setPointerCapture?.(e.pointerId);
      seekFromEvent(e);
      showChrome(true);
    });
    progress.addEventListener('pointermove', (e) => {
      if (!seeking) return;
      seekFromEvent(e);
    });
    const endSeek = () => {
      seeking = false;
      root.classList.remove('is-seeking');
      showChrome();
    };
    progress.addEventListener('pointerup', endSeek);
    progress.addEventListener('pointercancel', endSeek);

    root.addEventListener('mousemove', () => showChrome());
    root.addEventListener('touchstart', () => showChrome(true), { passive: true });
    root.addEventListener(
      'wheel',
      (e) => {
        if (!root.classList.contains('is-chrome') && !root.classList.contains('is-paused')) return;
        if (Math.abs(e.deltaY) < 2) return;
        e.preventDefault();
        nudgeVolume(e.deltaY > 0 ? -VOL_STEP : VOL_STEP);
      },
      { passive: false }
    );

    video.addEventListener('loadedmetadata', () => {
      root.classList.remove('is-loading');
      applyAspect();
      updateProgress();
      syncVolumeUI();
    });
    video.addEventListener('waiting', () => root.classList.add('is-loading'));
    video.addEventListener('playing', () => {
      root.classList.remove('is-loading');
      setPlaying(true);
      pauseAllExcept(api);
    });
    video.addEventListener('pause', () => setPlaying(false));
    video.addEventListener('timeupdate', updateProgress);
    video.addEventListener('progress', updateProgress);
    video.addEventListener('ended', () => {
      if (!video.loop) setPlaying(false);
    });

    document.addEventListener('fullscreenchange', () => {
      const on = document.fullscreenElement === root;
      root.classList.toggle('is-fs', on);
      btnFs.innerHTML = on ? ICON.exitFs : ICON.fs;
    });

    if ('IntersectionObserver' in window) {
      io = new IntersectionObserver(
        (entries) => {
          entries.forEach((en) => {
            if (en.isIntersecting) return;
            if (document.fullscreenElement === root) return;
            if (!video.paused) pause({ silent: true });
          });
        },
        { threshold: 0.12 }
      );
      io.observe(root);
    }

    applyGlobalAudio();
    registry.add(api);

    // Autoplay: respeita mute global; se preferência é com som, tenta; senão muted
    const wantAutoplay = opts.autoplay !== false;
    if (wantAutoplay) {
      if (opts.forceMuted || globalAudio.muted) {
        video.muted = true;
        play();
      } else {
        play();
      }
    } else {
      setPlaying(false);
    }

    return api;
  }

  return {
    create,
    setGlobalVolume,
    setGlobalMute,
    getGlobalAudio: () => ({ ...globalAudio }),
    pauseAll: () => pauseAllExcept(null),
  };
})();
