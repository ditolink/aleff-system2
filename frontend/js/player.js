/* AleffPlayer — cinema controls matching the portfolio aesthetic */
window.AleffPlayer = (() => {
  const ICON = {
    play: '<svg viewBox="0 0 24 24"><polygon points="8 5 19 12 8 19" fill="currentColor" stroke="none"/></svg>',
    pause: '<svg viewBox="0 0 24 24"><rect x="6" y="5" width="4" height="14" fill="currentColor" stroke="none"/><rect x="14" y="5" width="4" height="14" fill="currentColor" stroke="none"/></svg>',
    mute: '<svg viewBox="0 0 24 24"><path d="M11 5 6 9H3v6h3l5 4V5z"/><path d="m22 9-6 6M16 9l6 6"/></svg>',
    vol: '<svg viewBox="0 0 24 24"><path d="M11 5 6 9H3v6h3l5 4V5z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M18.5 5.5a9 9 0 0 1 0 13"/></svg>',
    fs: '<svg viewBox="0 0 24 24"><path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"/></svg>',
    exitFs: '<svg viewBox="0 0 24 24"><path d="M8 3v5H3M16 3v5h5M8 21v-5H3M16 21v-5h5"/></svg>',
  };

  function fmt(sec) {
    if (!Number.isFinite(sec) || sec < 0) return '0:00';
    const s = Math.floor(sec % 60);
    const m = Math.floor(sec / 60) % 60;
    const h = Math.floor(sec / 3600);
    const mm = h ? String(m).padStart(2, '0') : String(m);
    const ss = String(s).padStart(2, '0');
    return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
  }

  function create(opts = {}) {
    const root = document.createElement('div');
    root.className = 'aplayer is-paused is-loading';
    root.innerHTML = `
      <video playsinline preload="metadata"></video>
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
          <button type="button" class="aplayer-btn" data-act="mute" aria-label="Som">${ICON.vol}</button>
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
    const btnFs = root.querySelector('[data-act="fs"]');

    video.controls = false;
    if (opts.poster) video.poster = opts.poster;
    if (opts.src) video.src = opts.src;
    if (opts.title) root.setAttribute('aria-label', opts.title);
    video.loop = !!opts.loop;
    if (opts.muted) {
      video.muted = true;
      btnMute.innerHTML = ICON.mute;
    }

    let hideTimer = null;
    let seeking = false;

    function showChrome(sticky = false) {
      root.classList.add('is-chrome');
      clearTimeout(hideTimer);
      if (!sticky && !video.paused) {
        hideTimer = setTimeout(() => root.classList.remove('is-chrome'), 2200);
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

    async function play() {
      try {
        await video.play();
        setPlaying(true);
      } catch {
        setPlaying(false);
      }
    }

    function pause() {
      video.pause();
      setPlaying(false);
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
      video.muted = !video.muted;
      btnMute.innerHTML = video.muted ? ICON.mute : ICON.vol;
      showChrome(true);
    });
    btnFs.addEventListener('click', async (e) => {
      e.stopPropagation();
      try {
        if (!document.fullscreenElement) {
          await root.requestFullscreen();
        } else {
          await document.exitFullscreen();
        }
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

    video.addEventListener('loadedmetadata', () => {
      root.classList.remove('is-loading');
      if (video.videoWidth && video.videoHeight && video.videoHeight > video.videoWidth) {
        root.classList.add('is-portrait');
      }
      updateProgress();
    });
    video.addEventListener('waiting', () => root.classList.add('is-loading'));
    video.addEventListener('playing', () => {
      root.classList.remove('is-loading');
      setPlaying(true);
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

    if (opts.autoplay !== false) {
      video.muted = video.muted || false;
      play().catch(() => {
        // autoplay blocked → keep paused with big play
        setPlaying(false);
      });
    }

    return {
      root,
      video,
      play,
      pause,
      destroy() {
        clearTimeout(hideTimer);
        pause();
        video.removeAttribute('src');
        video.load();
        root.remove();
      },
    };
  }

  return { create };
})();
