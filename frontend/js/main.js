/* main.js — portfólio / lightbox / contato */
(() => {
  'use strict';

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  /* Media pool (lightbox) — espelha #galeriaTrabalhos + #galeriaVideos */
  /* Lightbox: medium thumbs (~800px) — nunca originais HD */
  const mediaPool = [
    { type: 'img', src: 'fotos/foto_casal_por_do_sol.jpg' },
    { type: 'img', src: '/api/media/1675/thumb-medium', mediaId: 1675 },
    { type: 'img', src: '/api/media/1855/thumb-medium', mediaId: 1855 },
    { type: 'img', src: '/api/media/1709/thumb-medium', mediaId: 1709 },
    { type: 'img', src: '/api/media/27/thumb-medium', mediaId: 27 },
    { type: 'img', src: '/api/media/75/thumb-medium', mediaId: 75 },
    { type: 'img', src: '/api/media/61/thumb-medium', mediaId: 61 },
    { type: 'img', src: '/api/media/1953/thumb-medium', mediaId: 1953 },
    { type: 'img', src: '/api/media/2034/thumb-medium', mediaId: 2034 },
    { type: 'img', src: '/api/media/2033/thumb-medium', mediaId: 2033 },
    { type: 'img', src: '/api/media/2156/thumb-medium', mediaId: 2156 },
    { type: 'img', src: '/api/media/1285/thumb-medium', mediaId: 1285 },
    { type: 'img', src: '/api/media/1942/thumb-medium', mediaId: 1942 },
    { type: 'video', src: 'videos/video_casamento21.mp4', poster: 'fotos/thumb_casamento21.jpg' },
    { type: 'video', src: 'videos/VIDEORAPS.mp4', poster: 'fotos/thumb_videoraps.jpg' },
  ];

  const fotoPool = [
    { type: 'video', src: 'videos/Reel01.mp4' },
    { type: 'video', src: 'videos/Reel02.mp4' },
    { type: 'video', src: 'videos/video67.mp4' },
    { type: 'video', src: 'videos/video12.mp4' },
    { type: 'video', src: 'videos/COMERCIAL01.mp4' },
    { type: 'video', src: 'videos/Reel03.mp4' },
  ];

  /* ── Helpers ──────────────────────────────────────────── */
  function rafThrottle(fn) {
    let locked = false;
    return (...args) => {
      if (locked) return;
      locked = true;
      requestAnimationFrame(() => {
        fn(...args);
        locked = false;
      });
    };
  }

  const isMobileUI = () => window.matchMedia('(max-width: 768px), (hover: none)').matches;

  /* ── Scroll: F5 + logo do rodapé → parallax (hero) ─── */
  const scrollRestore = (() => {
    const storageKey = `aleff_scroll:${location.pathname || '/index.html'}`;
    const navEntry = performance.getEntriesByType?.('navigation')?.[0];
    const isReload = navEntry?.type === 'reload';
    const hash = location.hash || '';
    const wantHero = isReload || !hash || hash === '#top' || hash === '#hero';
    /** Enquanto true, o masonry não “puxa” a tela de volta pra baixo. */
    let lockTop = wantHero;
    let pendingHash = wantHero ? '' : hash;

    try {
      if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
    } catch (_) {}

    if (wantHero) {
      try {
        sessionStorage.removeItem(storageKey);
      } catch (_) {}
    }

    function withInstantScroll(fn) {
      const html = document.documentElement;
      const prev = html.style.scrollBehavior;
      html.style.scrollBehavior = 'auto';
      try {
        fn();
      } finally {
        html.style.scrollBehavior = prev;
      }
    }

    function scrollToHero({ smooth = false } = {}) {
      const hero = document.getElementById('hero') || document.getElementById('top');
      if (smooth) {
        if (hero) hero.scrollIntoView({ block: 'start', behavior: 'smooth' });
        else window.scrollTo({ top: 0, behavior: 'smooth' });
      } else {
        withInstantScroll(() => {
          window.scrollTo(0, 0);
          if (hero) hero.scrollIntoView({ block: 'start', behavior: 'instant' });
        });
      }
      window.dispatchEvent(new Event('scroll'));
    }

    function goParallax({ smooth = false } = {}) {
      lockTop = true;
      pendingHash = '';
      try {
        sessionStorage.removeItem(storageKey);
      } catch (_) {}
      try {
        history.replaceState(null, '', `${location.pathname}${location.search}#hero`);
      } catch (_) {}
      scrollToHero({ smooth });
      // Liberar depois do smooth / do pack inicial
      window.setTimeout(() => {
        lockTop = false;
      }, smooth ? 1400 : 900);
    }

    function captureAnchor() {
      if (lockTop || window.scrollY < 60) return null;
      const x = Math.min(Math.max(window.innerWidth * 0.5, 8), window.innerWidth - 8);
      const probeY = Math.min(96, window.innerHeight * 0.22);
      let node = document.elementFromPoint(x, probeY);
      while (node && node !== document.body && node !== document.documentElement) {
        if (node.id) return { id: node.id, offset: node.getBoundingClientRect().top };
        node = node.parentElement;
      }
      return { y: window.scrollY };
    }

    function restoreAnchor(anchor) {
      if (!anchor || lockTop) return;
      if (anchor.id) {
        const el = document.getElementById(anchor.id);
        if (el) {
          const delta = el.getBoundingClientRect().top - anchor.offset;
          if (Math.abs(delta) > 0.5) {
            withInstantScroll(() => window.scrollTo(0, window.scrollY + delta));
          }
          return;
        }
      }
      if (typeof anchor.y === 'number' && anchor.y > 0) {
        withInstantScroll(() => window.scrollTo(0, anchor.y));
      }
    }

    function applyPending() {
      if (lockTop) {
        scrollToHero({ smooth: false });
        return;
      }
      if (pendingHash && pendingHash !== '#top' && pendingHash !== '#hero') {
        const el = document.querySelector(pendingHash);
        if (el) {
          withInstantScroll(() => el.scrollIntoView({ block: 'start', behavior: 'instant' }));
          window.dispatchEvent(new Event('scroll'));
        }
      }
    }

    function shouldAnchorPack() {
      return !lockTop && window.scrollY >= 60;
    }

    function init() {
      if (wantHero) scrollToHero({ smooth: false });

      window.addEventListener(
        'wheel',
        () => { lockTop = false; },
        { passive: true, once: true }
      );
      window.addEventListener(
        'touchstart',
        () => { lockTop = false; },
        { passive: true, once: true }
      );
      window.addEventListener(
        'keydown',
        (e) => {
          if (['ArrowDown', 'PageDown', 'Space', 'End', 'Home'].includes(e.code)) {
            lockTop = false;
          }
        },
        { passive: true, once: true }
      );

      const retry = () => applyPending();
      window.addEventListener(
        'load',
        () => {
          retry();
          setTimeout(retry, 100);
          setTimeout(retry, 400);
          setTimeout(() => { lockTop = false; }, 1000);
        },
        { once: true }
      );
      if (document.readyState === 'complete') setTimeout(retry, 0);
    }

    return {
      init,
      captureAnchor,
      restoreAnchor,
      applyPending,
      shouldAnchorPack,
      goParallax,
    };
  })();

  /* ── Hero: parallax no rosto + nav some no scroll ───── */
  function initHero() {
    const heroBg = $('#heroBg');
    const heroContent = $('#heroContent');
    const nav = $('#siteNav');
    if (!heroBg || !heroContent) return;
    const lightParallax = isMobileUI();

    const onScroll = rafThrottle(() => {
      const sy = window.scrollY;
      if (sy < 900) {
        // Celular: parallax bem suave (não zera)
        const py = lightParallax ? 0.04 : 0.12;
        const cy = lightParallax ? 0.02 : 0.06;
        heroBg.style.transform = `translateY(${sy * py}px)`;
        heroContent.style.transform = `translateY(${sy * cy}px)`;
        const fade = Math.min(1, sy / 520);
        heroContent.style.opacity = String(Math.max(0, 1 - Math.pow(fade, 1.5)));
      }
      if (nav) {
        // Some junto com o parallax (Trabalhos / Contato / Buscar)
        const navFade = Math.min(1, sy / 280);
        const opacity = Math.max(0, 1 - Math.pow(navFade, 1.35));        nav.style.opacity = String(opacity);
        nav.style.transform = `translateY(${sy * 0.04}px)`;
        nav.style.pointerEvents = opacity < 0.12 ? 'none' : 'auto';
        nav.classList.toggle('is-scrolled', sy > 40);
        nav.classList.toggle('is-fading', sy > 24);
      }
    });

    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }

  /* ── Helpers HTTP (não usados no portfólio público) ───── */
  // Status/manutenção ficam só em admin.html

  /* ── Vídeos: lazy + hover (não baixa tudo de uma vez) ─── */
  function isAutoplayTile(v) {
    const parent = v?.closest?.('.gi, .foto-item');
    return !!(
      v?.hasAttribute?.('autoplay') ||
      v?.dataset?.autoplay === '1' ||
      parent?.classList?.contains('gi-autoplay') ||
      parent?.dataset?.autoplay === '1'
    );
  }

  function playMutedLoop(v) {
    if (!v) return;
    v.muted = true;
    v.loop = true;
    v.setAttribute('playsinline', '');
    const p = v.play();
    if (p && typeof p.catch === 'function') p.catch(() => {});
  }

  function resumeAutoplayVideos() {
    $$('.gi.gi-autoplay video, .gi[data-autoplay="1"] video, video[autoplay]').forEach((v) => {
      if (!v.closest('.gi, .foto-item')) return;
      playMutedLoop(v);
    });
  }

  function applyVideoFrame(v) {
    const parent = v.closest('.gi, .foto-item');
    if (!parent) return;
    const apply = () => {
      if (!(v.videoWidth > 0 && v.videoHeight > 0)) return;
      parent.style.aspectRatio = `${v.videoWidth} / ${v.videoHeight}`;
      parent.classList.toggle('is-portrait', v.videoHeight > v.videoWidth * 1.05);
      parent.classList.toggle('is-landscape', v.videoWidth > v.videoHeight * 1.05);
      parent.classList.toggle('is-square', Math.abs(v.videoWidth - v.videoHeight) <= v.videoWidth * 0.05);
    };
    if (v.readyState >= 1) apply();
    else v.addEventListener('loadedmetadata', apply, { once: true });
  }

  function videoSrcOf(v) {
    return v.getAttribute('src') || v.dataset.src || '';
  }

  /** Após play, o poster some — reinicia o elemento pra mostrar o poster de novo. */
  function restorePoster(v) {
    const poster = v.getAttribute('poster');
    if (!poster) {
      try { v.currentTime = 0; } catch { /* ignore */ }
      return;
    }
    const src = videoSrcOf(v);
    if (!src) return;
    try {
      v.pause();
      v.removeAttribute('src');
      v.load();
      v.setAttribute('src', src);
      v.preload = 'none';
      v.dataset.warmed = '0';
    } catch { /* ignore */ }
  }

  function initVideoHover() {
    const videos = $$('.gi video, .foto-item video');
    if (!videos.length) return;

    // Evita congestionamento: só metadata quando entra na tela
    videos.forEach((v) => {
      const auto = isAutoplayTile(v);
      if (v.dataset.videoInit === '1') {
        if (auto) playMutedLoop(v);
        return;
      }
      v.dataset.videoInit = '1';
      const lazy = v.getAttribute('data-src');
      if (lazy && !v.getAttribute('src')) {
        v.setAttribute('src', lazy);
      }
      v.preload = auto ? 'auto' : 'none';
      v.setAttribute('playsinline', '');
      v.muted = true;
      v.loop = true;
      if (auto) v.setAttribute('autoplay', '');
      applyVideoFrame(v);
      // Com poster custom: não chamar load() no init — mantém o thumbnail visível
      if (auto || !v.getAttribute('poster')) {
        try { v.load(); } catch { /* ignore */ }
      }
    });

    const warm = (v, { force = false } = {}) => {
      if (!v || v.dataset.warmed === '1') return;
      const auto = isAutoplayTile(v);
      // Poster custom fica no repouso até hover/play (force)
      if (!force && !auto && v.getAttribute('poster')) return;
      v.dataset.warmed = '1';
      v.preload = auto ? 'auto' : 'metadata';
      try { v.load(); } catch { /* ignore */ }
      if (auto) playMutedLoop(v);
    };

    if ('IntersectionObserver' in window) {
      const io = new IntersectionObserver((entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) warm(e.target);
        });
      }, { rootMargin: '200px 0px', threshold: 0.01 });
      videos.forEach((v) => {
        if (v.dataset.ioBound === '1') {
          if (isAutoplayTile(v)) playMutedLoop(v);
          return;
        }
        v.dataset.ioBound = '1';
        io.observe(v);
      });
    } else {
      videos.forEach((v) => warm(v));
    }

    if (isMobileUI()) {
      // Toque: aquecer no primeiro pointerdown pra não trocar o poster cedo demais
      videos.forEach((v) => {
        if (isAutoplayTile(v) || !v.getAttribute('poster')) return;
        const parent = v.parentElement;
        if (!parent || parent.dataset.tapWarm === '1') return;
        parent.dataset.tapWarm = '1';
        parent.addEventListener('pointerdown', () => warm(v, { force: true }), { once: true });
      });
      return;
    }

    videos.forEach((v) => {
      if (isAutoplayTile(v)) return;
      const parent = v.parentElement;
      if (!parent || parent.dataset.hoverBound === '1') return;
      parent.dataset.hoverBound = '1';
      parent.addEventListener('mouseenter', () => {
        warm(v, { force: true });
        const p = v.play();
        if (p && typeof p.catch === 'function') p.catch(() => {});
      });
      parent.addEventListener('mouseleave', () => {
        v.pause();
        restorePoster(v);
      });
    });
  }

  /* ── Contadores ───────────────────────────────────────── */
  function initCounters() {
    function animCount(el, target, suffix) {
      let start = null;
      const dur = 1800;
      const run = (ts) => {
        if (!start) start = ts;
        const p = Math.min((ts - start) / dur, 1);
        const e = 1 - Math.pow(1 - p, 3);
        el.textContent = Math.floor(e * target) + (p < 1 ? '' : suffix);
        if (p < 1) requestAnimationFrame(run);
        else el.textContent = target + suffix;
      };
      requestAnimationFrame(run);
    }

    const obs = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (!e.isIntersecting) return;
        e.target.querySelectorAll('.num-val[data-target]').forEach((el) => {
          animCount(el, +el.dataset.target, el.dataset.suffix || '');
          el.removeAttribute('data-target');
        });
        obs.unobserve(e.target);
      });
    }, { threshold: 0.3 });

    $$('.numbers-wrap').forEach((el) => obs.observe(el));
  }

  /* ── Lightbox ─────────────────────────────────────────── */
  function initLightbox() {
    const lb = $('#lb');
    const lbC = $('#lbContent');
    const lbCtr = $('#lbCtr');
    const lbNm = $('#lbName');
    if (!lb || !lbC) return;

    let ci = 0;
    let cp = mediaPool;
    let activePlayer = null;

    function destroyActivePlayer() {
      if (!activePlayer) return;
      try { activePlayer.destroy(); } catch { /* ignore */ }
      activePlayer = null;
    }

    function pauseGridVideos() {
      $$('.gi video, .foto-item video').forEach((v) => {
        try {
          v.pause();
        } catch { /* ignore */ }
      });
    }

    function openLb(pool, idx) {
      cp = pool;
      ci = idx;
      const d = pool[idx];
      if (!d) return;
      destroyActivePlayer();
      pauseGridVideos();
      lbC.innerHTML = '';

      const card = document.createElement('div');
      card.className = 'lb-card';

      const back = document.createElement('div');
      back.className = 'lb-card-back';
      back.innerHTML = `
        <svg viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <g stroke="#f5f5f5" stroke-width="1.3" stroke-linecap="round" opacity="0.85">
            <path d="M9 8 Q8 5 9.5 2"/><path d="M15 7 Q14 4 15.5 1"/><path d="M21 8 Q20 5 21.5 2"/>
          </g>
          <path d="M7.5 11 L22.5 11 L20.5 23 Q20.3 24 19 24 L11 24 Q9.7 24 9.5 23 Z" fill="#f5f5f5"/>
        </svg>
        <span>Aleff Thiago</span>`;

      const front = document.createElement('div');
      front.className = 'lb-card-front';

      if (d.type === 'video') {
        if (typeof AleffPlayer !== 'undefined') {
          const player = AleffPlayer.create({
            src: d.src,
            poster: d.poster || '',
            title: d.title || '',
            loop: true,
            autoplay: true,
            preload: 'metadata',
          });
          activePlayer = player;
          front.appendChild(player.root);
        } else {
          const v = document.createElement('video');
          v.src = d.src;
          if (d.poster) v.poster = d.poster;
          v.playsInline = true;
          v.preload = 'metadata';
          v.autoplay = true;
          v.muted = true;
          v.loop = true;
          v.style.objectFit = 'contain';
          front.appendChild(v);
        }
      } else {
        const img = document.createElement('img');
        img.src = d.src;
        img.alt = d.title || '';
        img.decoding = 'async';
        img.fetchPriority = 'high';
        img.loading = 'eager';
        front.appendChild(img);
        // Prefetch só vizinhos (não a galeria inteira)
        const warm = (j) => {
          const n = pool[j];
          if (!n || n.type === 'video' || !n.src) return;
          try {
            const im = new Image();
            im.decoding = 'async';
            im.src = n.src;
          } catch { /* ignore */ }
        };
        warm((idx + 1) % pool.length);
        warm((idx - 1 + pool.length) % pool.length);
      }

      card.appendChild(back);
      card.appendChild(front);
      lbC.appendChild(card);

      // Flip carta → foto/vídeo (mesma animação de "olhar")
      card.classList.remove('flipped');
      requestAnimationFrame(() => {
        requestAnimationFrame(() => card.classList.add('flipped'));
      });

      lbCtr.textContent = `${String(idx + 1).padStart(2, '0')} / ${String(pool.length).padStart(2, '0')}`;
      lbNm.textContent = d.title || '';
      lb.classList.add('open');
      document.body.style.overflow = 'hidden';
    }

    function closeLb() {
      destroyActivePlayer();
      lb.classList.remove('open');
      document.body.style.overflow = '';
      lbC.innerHTML = '';
      resumeAutoplayVideos();
    }

    // Delegação: funciona também em slots preenchidos depois
    document.addEventListener('click', (e) => {
      const gi = e.target.closest('.gi:not(.gi-slot)');
      if (gi && gi.closest('.grid')) {
        const idx = Number.parseInt(gi.dataset.idx || '', 10);
        if (!Number.isFinite(idx)) return;
        openLb(mediaPool, idx);
        return;
      }
      const foto = e.target.closest('.foto-item');
      if (foto) {
        const items = $$('.foto-item');
        const i = items.indexOf(foto);
        if (i >= 0) openLb(fotoPool, i);
      }
    });

    $('#lbClose')?.addEventListener('click', closeLb);
    $('#lbPrev')?.addEventListener('click', () => openLb(cp, (ci - 1 + cp.length) % cp.length));
    $('#lbNext')?.addEventListener('click', () => openLb(cp, (ci + 1) % cp.length));
    document.addEventListener('keydown', (e) => {
      if (!lb.classList.contains('open')) return;
      if (e.key === 'Escape') closeLb();
      if (e.key === 'ArrowLeft') openLb(cp, (ci - 1 + cp.length) % cp.length);
      if (e.key === 'ArrowRight') openLb(cp, (ci + 1) % cp.length);
    });
    lb.addEventListener('click', (e) => { if (e.target === lb) closeLb(); });
  }

  /* ── Reveal / motion ──────────────────────────────────── */
  function initMotion() {
    const revObs = new IntersectionObserver((entries) => {
      entries.forEach((e) => { if (e.isIntersecting) e.target.classList.add('on'); });
    }, { threshold: 0.07 });
    $$('.rv').forEach((el) => revObs.observe(el));

    $$('.gi:not(.gi-slot)').forEach((el) => {
      if (el.querySelector('video')) return;
      let raf = null;
      el.addEventListener('mouseenter', () => {
        el.style.willChange = 'transform';
        el.style.transformStyle = 'preserve-3d';
      });
      el.addEventListener('mousemove', (e) => {
        if (raf) return;
        raf = requestAnimationFrame(() => {
          const r = el.getBoundingClientRect();
          const x = (e.clientX - r.left) / r.width - 0.5;
          const y = (e.clientY - r.top) / r.height - 0.5;
          el.style.transform = `perspective(800px) rotateX(${y * -6}deg) rotateY(${x * 6}deg) scale(1.01)`;
          raf = null;
        });
      });
      el.addEventListener('mouseleave', () => {
        el.style.transform = 'perspective(800px) rotateX(0) rotateY(0) scale(1)';
        el.style.willChange = 'auto';
      });
    });

    $$('.card-btn').forEach((el) => {
      let raf = null;
      el.addEventListener('mousemove', (e) => {
        if (raf) return;
        raf = requestAnimationFrame(() => {
          const r = el.getBoundingClientRect();
          const x = (e.clientX - r.left - r.width / 2) * 0.06;
          const y = (e.clientY - r.top - r.height / 2) * 0.06;
          el.style.transform = `translate(${x}px, ${y}px) scale(1.015)`;
          raf = null;
        });
      });
      el.addEventListener('mouseleave', () => { el.style.transform = ''; });
    });
  }

  /* ── Timeline ─────────────────────────────────────────── */
  function initTimeline() {
    const timeline = $('#timeline');
    const progress = $('#timelineProgress');
    if (!timeline || !progress) return;

    const items = $$('.tl-item', timeline);
    const update = rafThrottle(() => {
      const rect = timeline.getBoundingClientRect();
      const viewportLine = window.innerHeight * 0.7;
      const traveled = Math.min(Math.max(viewportLine - rect.top, 0), rect.height);
      progress.style.height = `${traveled}px`;
      items.forEach((item) => {
        const itemTop = item.getBoundingClientRect().top - rect.top;
        item.classList.toggle('lit', traveled >= itemTop + 7);
      });
    });

    window.addEventListener('scroll', update, { passive: true });
    update();
  }

  /* ── Tags cascade ─────────────────────────────────────── */
  function initTags() {
    const wrap = $('#sobreTags');
    if (!wrap) return;
    const tags = $$('.tag-rv', wrap);
    const obs = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (!e.isIntersecting) return;
        tags.forEach((tag, i) => setTimeout(() => tag.classList.add('on'), i * 80));
        obs.disconnect();
      });
    }, { threshold: 0.3 });
    obs.observe(wrap);
  }

  /* ── Contato ──────────────────────────────────────────── */
  function initContact() {
    const ta = $('#ccMsg');
    const out = $('#ccCounter');
    const previewBody = $('#msgProntaBody');
    const previewDest = $('#msgProntaDest');
    const previewChars = $('#msgProntaChars');
    const form = $('#contatoForm');
    const previewBox = $('#msgPronta');
    const btnCopy = $('#btnCopyMsg');

    const CS = typeof ContactSend !== 'undefined' ? ContactSend : null;

    const methods = {
      whatsapp: {
        label: 'Mandar no WhatsApp',
        opening: 'Abrindo WhatsApp…',
        cls: 'is-wa',
        dest: 'WhatsApp',
        icon: `<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/></svg>`,
      },
      gmail: {
        label: 'Enviar no Gmail',
        opening: 'Abrindo Gmail…',
        cls: 'is-em',
        dest: 'Gmail',
        icon: `<svg width="16" height="16" viewBox="0 0 48 48"><path fill="#EA4335" d="M6 10l18 13L42 10H6z"/><path fill="#34A853" d="M42 10v28H6V10l18 13z"/><path fill="#FBBC05" d="M6 10v28l10-14z"/><path fill="#4285F4" d="M42 10v28L32 24z"/><path fill="#C5221F" d="M6 38l10-14 8 5.6L32 24l10 14H6z"/></svg>`,
      },
      instagram: {
        label: 'Enviar pelo Instagram',
        opening: 'Abrindo Instagram…',
        cls: 'is-ig',
        dest: 'Instagram',
        icon: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="2" y="2" width="20" height="20" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r="1.2" fill="currentColor" stroke="none"/></svg>`,
      },
    };

    let method = 'whatsapp';
    const btn = $('#btnSend');
    const channels = $$('.contato-channels .ch');

    function formValues() {
      return {
        nome: ($('#ccNome')?.value || '').trim(),
        contato: ($('#ccContato')?.value || '').trim(),
        tipo: ($('#ccTipo')?.value || '').trim(),
        mensagem: ($('#ccMsg')?.value || '').trim(),
      };
    }

    function buildMessage() {
      const fields = formValues();
      if (CS?.buildStudioMessage) return CS.buildStudioMessage(fields, method);
      const { nome, contato, tipo, mensagem } = fields;
      if (method === 'gmail') {
        if (CS?.buildGmailMessage) return CS.buildGmailMessage(fields);
        let texto = nome
          ? `Olá, Aleff,\n\nMeu nome é ${nome}. Conheci seu trabalho pelo portfólio e gostaria de alinhar um projeto.`
          : 'Olá, Aleff,\n\nConheci seu trabalho pelo portfólio e gostaria de alinhar um projeto.';
        if (mensagem) texto += `\n\nSobre o que preciso:\n${mensagem}`;
        texto += `\n\nDados para retorno\n────────────────\nNome: ${nome || '—'}\nContato: ${contato || '—'}\nTipo de projeto: ${tipo || '—'}`;
        texto += `\n\nAtenciosamente,\n${nome || 'Aguardando retorno'}`;
        return texto;
      }
      let texto = nome
        ? `Olá, Aleff!\n\nVi seu portfólio e gostaria de conversar sobre um projeto.\n\nMeu nome:\n${nome}`
        : 'Olá, Aleff!\n\nVi seu portfólio e gostaria de conversar sobre um projeto.';
      if (contato) texto += `\n\nMeu contato:\n${contato}`;
      if (tipo) texto += `\n\nProjeto:\n${tipo}`;
      if (mensagem) texto += `\n\nMensagem:\n${mensagem}`;
      texto += '\n\nObrigado!';
      return texto;
    }

    async function copyMessage() {
      const texto = buildMessage();
      syncPreview();
      const ok = CS?.copyToClipboard
        ? await CS.copyToClipboard(texto)
        : false;
      if (previewBox && CS?.showCopyFlash) {
        CS.showCopyFlash(previewBox, {
          sub: method === 'instagram'
            ? 'Cole no Direct do Instagram.'
            : 'Mensagem na área de transferência.',
        });
      } else if (window.Toast?.success && ok) {
        Toast.success('Mensagem copiada', 'Cole onde quiser enviar.');
      }
      if (btnCopy) {
        const prev = btnCopy.textContent;
        btnCopy.textContent = ok ? 'Copiado ✓' : 'Falhou';
        btnCopy.classList.toggle('is-done', ok);
        setTimeout(() => {
          btnCopy.textContent = prev || 'Copiar mensagem';
          btnCopy.classList.remove('is-done');
        }, 1600);
      }
      return ok;
    }

    function syncFormForMethod() {
      const contatoInp = $('#ccContato');
      if (!contatoInp) return;
      if (method === 'gmail') {
        contatoInp.type = 'email';
        contatoInp.placeholder = 'Seu e-mail';
        contatoInp.setAttribute('autocomplete', 'email');
      } else if (method === 'instagram') {
        contatoInp.type = 'text';
        contatoInp.placeholder = 'Seu @ ou WhatsApp';
        contatoInp.setAttribute('autocomplete', 'username');
      } else {
        contatoInp.type = 'tel';
        contatoInp.placeholder = 'WhatsApp com DDD';
        contatoInp.setAttribute('autocomplete', 'tel');
      }
    }

    function syncPreview() {
      const texto = buildMessage();
      if (previewBody) previewBody.textContent = texto;
      if (previewDest) previewDest.textContent = methods[method]?.dest || '';
      if (previewChars) {
        const n = texto.length;
        previewChars.textContent = `${n} caractere${n === 1 ? '' : 's'}`;
      }
      if (previewBox) {
        previewBox.dataset.method = method;
        const tip = $('#msgProntaTip');
        if (tip) {
          tip.textContent = method === 'instagram'
            ? 'No Instagram o Direct já abre na hora.'
            : method === 'whatsapp'
              ? 'No WhatsApp a mensagem já abre preenchida.'
              : 'No Gmail a mensagem já abre preenchida no compose.';
        }
      }
      if (ta && out) out.textContent = `${ta.value.length}/500`;
    }

    function syncSendButton() {
      const cfg = methods[method];
      if (!btn || !cfg) return;
      btn.dataset.method = method;
      btn.classList.remove('is-wa', 'is-em', 'is-ig');
      btn.classList.add(cfg.cls);
      btn.innerHTML = `<span class="send-icon" aria-hidden="true">${cfg.icon}</span><span class="send-label">${cfg.label}</span>`;
      syncFormForMethod();
      syncPreview();
    }

    function selectMethod(next) {
      if (!methods[next]) return;
      method = next;
      channels.forEach((el) => {
        const on = el.dataset.method === method;
        el.classList.toggle('is-active', on);
        el.setAttribute('aria-checked', on ? 'true' : 'false');
        el.tabIndex = on ? 0 : -1;
      });
      syncSendButton();
    }

    channels.forEach((el) => {
      el.addEventListener('click', () => selectMethod(el.dataset.method));
      el.addEventListener('keydown', (ev) => {
        const order = ['whatsapp', 'gmail', 'instagram'];
        const idx = order.indexOf(method);
        if (ev.key === 'ArrowRight' || ev.key === 'ArrowDown') {
          ev.preventDefault();
          selectMethod(order[(idx + 1) % order.length]);
          channels.find((c) => c.dataset.method === method)?.focus();
        } else if (ev.key === 'ArrowLeft' || ev.key === 'ArrowUp') {
          ev.preventDefault();
          selectMethod(order[(idx - 1 + order.length) % order.length]);
          channels.find((c) => c.dataset.method === method)?.focus();
        }
      });
    });

    ['input', 'change'].forEach((evt) => {
      form?.addEventListener(evt, syncPreview);
    });

    btnCopy?.addEventListener('click', () => { copyMessage(); });

    /* Pausa zoom/escala da foto enquanto edita o formulário */
    const section = form?.closest('.contato') || $('#contato');
    const isFormField = (el) =>
      el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT');

    if (form && section) {
      form.addEventListener('focusin', (e) => {
        if (isFormField(e.target)) section.classList.add('is-form-focus');
      });
      form.addEventListener('focusout', () => {
        requestAnimationFrame(() => {
          const active = document.activeElement;
          if (!isFormField(active) || !form.contains(active)) {
            section.classList.remove('is-form-focus');
          }
        });
      });
    }

    function openExternal(url, opts) {
      if (CS?.openExternal) return CS.openExternal(url, opts);
      window.open(url, '_blank', 'noopener,noreferrer');
    }

    if (btn) {
      btn.addEventListener('click', async () => {
        const active = document.querySelector('.contato-channels .ch.is-active');
        method = active?.dataset.method || method || 'whatsapp';
        const cfg = methods[method];
        if (!cfg) return;

        const texto = buildMessage();
        syncPreview();
        btn.disabled = true;
        btn.innerHTML = `<span class="send-label">${cfg.opening}</span>`;

        try {
          if (method === 'whatsapp') {
            openExternal(`https://wa.me/5538999078483?text=${encodeURIComponent(texto)}`);
          } else if (method === 'gmail') {
            const fields = formValues();
            const subjectRaw = CS?.buildGmailSubject
              ? CS.buildGmailSubject(fields)
              : 'Contato via portfólio — Aleff Thiago';
            const gmailUrl = CS?.buildGmailUrl
              ? CS.buildGmailUrl(texto, { subject: subjectRaw })
              : `https://mail.google.com/mail/?view=cm&fs=1&tf=1&to=aleffthigo@gmail.com&su=${encodeURIComponent(subjectRaw)}&body=${encodeURIComponent(texto)}`;
            openExternal(gmailUrl);
          } else if (method === 'instagram') {
            const igUrl = CS?.buildInstagramUrl
              ? CS.buildInstagramUrl(texto)
              : `https://ig.me/m/aleffthiagofilms?text=${encodeURIComponent(texto)}`;
            openExternal(igUrl);
          }
        } finally {
          setTimeout(() => {
            btn.disabled = false;
            syncSendButton();
          }, 1600);
        }
      });
    }

    syncSendButton();
  }

  /* ── Atalho / ─────────────────────────────────────────── */
  function initShortcuts() {
    document.addEventListener('keydown', (e) => {
      const tag = document.activeElement?.tagName;
      if (e.key === '/' && tag !== 'INPUT' && tag !== 'TEXTAREA') {
        e.preventDefault();
        window.location.href = 'search.html';
      }
    });
  }

  /* ── Slots do portfólio (API) ─────────────────────────── */
  async function initPortfolioSlots() {
    const nodes = $$('.gi-slot[data-slot-id]');
    if (!nodes.length) return;
    try {
      const r = await fetch('/api/portfolio/slots', { cache: 'no-store' });
      const data = await r.json();
      const slots = data.slots || {};
      nodes.forEach((el) => {
        const id = el.dataset.slotId;
        const s = slots[id];
        if (!s || !s.filled || !s.src) return;
        el.classList.remove('gi-slot');
        el.style.display = '';
        el.removeAttribute('aria-label');
        // Só paths relativos fotos/|videos/ — bloqueia javascript:/http XSS
        let src = String(s.src || '').replace(/\\/g, '/').replace(/^\/+/, '');
        if (
          src.includes('..') ||
          /^(https?:|data:|javascript:)/i.test(src) ||
          !(src.startsWith('fotos/') || src.startsWith('videos/'))
        ) {
          return;
        }
        const title = String(s.title || 'Trabalho')
          .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
        const cat = String(s.cat || '')
          .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
        const safeSrc = src.replace(/"/g, '');
        if (s.type === 'video') {
          el.innerHTML = `<video src="${safeSrc}" muted loop playsinline preload="none"></video><div class="gi-ov"><div class="gi-play"></div><p class="gi-title">${title}</p><p class="gi-cat">${cat}</p></div>`;
        } else {
          el.style.aspectRatio = '';
          el.innerHTML = `<img src="${safeSrc}" alt="${title}" loading="lazy" decoding="async"/><div class="gi-ov"><p class="gi-title">${title}</p><p class="gi-cat">${cat}</p></div>`;
        }
        el.classList.add('rv', 'on');
        if (!el.dataset.idx) {
          const idx = mediaPool.length;
          el.dataset.idx = String(idx);
          mediaPool.push({
            type: s.type === 'video' ? 'video' : 'img',
            src,
            title: s.title || 'Trabalho',
          });
        }
      });
      initVideoHover();
    } catch { /* mantém placeholders (só staff vê) */ }
  }

  /* ── Grade do index: NÃO sobrescreve a curadoria estática ─ */
  async function initPortfolioHomeLayout() {
    const root = $('#galeriaTrabalhos');
    if (!root) return;
    // Curadoria manual em index.html (Thalles, shows, casais…) — não trocar por API
    if (root.querySelector('[data-idx]')) return;
    try {
      const r = await fetch('/api/portfolio/home?limit=22', { cache: 'no-store' });
      if (!r.ok) return;
      const data = await r.json();
      const items = data.items || [];
      const photos = items.filter((it) => it.type === 'photo' && (it.thumb_url || it.id));
      // Só troca a grade se o acervo tiver material suficiente
      if (photos.length < 8) return;

      const esc = (s) => String(s || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/"/g, '&quot;');

      const frag = document.createDocumentFragment();
      const newPool = [];
      let idx = 0;

      items.forEach((it) => {
        if (it.type === 'break') {
          const br = document.createElement('div');
          br.className = 'grid-break';
          br.setAttribute('role', 'presentation');
          br.innerHTML = `<span>${esc(it.label || '')}</span>`;
          frag.appendChild(br);
          return;
        }
        if (it.type !== 'photo') return;
        const layout = it.layout === 'l-wide' ? 'l-wide' : 'p-tall';
        const src = it.thumb_url || (it.id ? `/api/media/${it.id}/thumb?sz=720` : '');
        if (!src) return;
        const title = it.title || it.pasta || it.nome || 'Trabalho';
        const cat = it.cat_label || it.categoria || it.pasta || '';
        const el = document.createElement('div');
        el.className = `gi ${layout} rv on`;
        el.dataset.idx = String(idx);
        el.innerHTML =
          `<img src="${esc(src)}" alt="${esc(title)}" loading="${idx < 6 ? 'eager' : 'lazy'}" decoding="async"/>` +
          `<div class="gi-ov"><p class="gi-title">${esc(title)}</p><p class="gi-cat">${esc(cat)}</p></div>`;
        frag.appendChild(el);
        newPool.push({ type: 'img', src, title, id: it.id });
        idx += 1;
      });

      if (idx < 8) return;

      root.innerHTML = '';
      root.appendChild(frag);
      mediaPool.length = 0;
      newPool.forEach((m) => mediaPool.push(m));

      if (typeof root._workMasonryPack === 'function') root._workMasonryPack();
      else requestAnimationFrame(() => {
        if (typeof root._workMasonryPack === 'function') root._workMasonryPack();
      });
    } catch (e) {
      console.warn('[portfolio-home]', e);
    }
  }

  async function initContatoReel() {
    const frame = document.querySelector('.contato-reel');
    const up = document.getElementById('contatoReelUp');
    const down = document.getElementById('contatoReelDown');
    if (!frame || !up || !down) return;

    const FALLBACK = [
      { src: 'fotos/foto_thalles.jpg', key: 'thalles' },
      { src: 'fotos/foto_show_unico_marks.png', key: 'unico' },
      { src: 'fotos/foto20.webp', key: 'praia' },
      { src: 'fotos/foto_jotaquest.webp', key: 'jota' },
      { src: 'fotos/foto_gravata.png', key: 'gravata' },
      { src: 'fotos/foto40.webp', key: 'casal40' },
      { src: 'fotos/foto_casal_reflexo.png', key: 'reflexo' },
      { src: 'fotos/foto_detonautas.webp', key: 'detonautas' },
      { src: 'fotos/foto_sorriso.png', key: 'sorriso' },
      { src: 'fotos/foto11i.jpg', key: 'piscina' },
      { src: 'fotos/foto_motocross.png', key: 'moto' },
      { src: 'fotos/foto12.jpg', key: 'xadrez' },
      { src: 'fotos/foto_cafe.png', key: 'cafe' },
      { src: 'fotos/foto60.webp', key: 'luz' },
      { src: 'fotos/foto94.webp', key: '94' },
      { src: 'fotos/fotojoy01.jpg', key: 'joy' },
      { src: 'fotos/foto55.jpg', key: 'trancas' },
    ];

    const GENERIC_PASTA = /^(sem\s*edi[cç][aã]o|originais|site(\s*\(local\))?|local|geral|misc|upload|uploads|fotos?|imagens?)$/i;
    const NON_PHOTO_PASTA = /(logo|logos|marca|marcas|identidade|branding|mockup|design|vetor)/i;

    function isPhotoItem(it) {
      const pasta = String(it.pasta || '');
      const nome = String(it.nome || '');
      if (NON_PHOTO_PASTA.test(pasta) || NON_PHOTO_PASTA.test(nome)) return false;
      return true;
    }

    function thumbOf(it) {
      if (it.src) return it.src;
      const raw = String(it.thumb_url || '');
      if (/^\/api\/local\//i.test(raw)) return raw;
      const m = raw.match(/^(\/api\/media\/\d+\/thumb)/i);
      if (m) return `${m[1]}?sz=480`;
      if (it.id) return `/api/media/${it.id}/thumb?sz=480`;
      return raw;
    }

    function personKey(it) {
      if (it.key) return String(it.key).toLowerCase();
      if (it.face_cluster != null && it.face_cluster !== '') {
        return `face:${it.face_cluster}`;
      }
      const pasta = String(it.pasta || '').trim();
      if (pasta && !GENERIC_PASTA.test(pasta)) {
        return pasta.toLowerCase().normalize('NFD').replace(/\p{M}/gu, '');
      }
      const tags = String(it.tags || '')
        .split(',')
        .map((t) => t.trim().toLowerCase())
        .filter((t) => t && t.length > 2);
      const skip = new Set(['foto', 'fotos', 'image', 'show', 'shows', 'retrato', 'casamento', 'ensaio', 'video']);
      const tag = tags.find((t) => !skip.has(t));
      if (tag) return `tag:${tag}`;
      const nome = String(it.nome || '')
        .replace(/\.[a-z0-9]+$/i, '')
        .replace(/[_-]+/g, ' ')
        .trim()
        .toLowerCase();
      if (nome.length >= 4) return `nome:${nome.slice(0, 18)}`;
      return `id:${it.id}`;
    }

    function shuffle(arr) {
      const a = arr.slice();
      for (let i = a.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [a[i], a[j]] = [a[j], a[i]];
      }
      return a;
    }

    /** No máximo maxPerKey por pessoa; prioriza variedade. */
    function pickDiverse(pool, limit, maxPerKey = 1) {
      const byKey = new Map();
      for (const it of shuffle(pool)) {
        const k = personKey(it);
        if (!byKey.has(k)) byKey.set(k, []);
        const bucket = byKey.get(k);
        if (bucket.length < maxPerKey) bucket.push(it);
      }
      const keys = shuffle([...byKey.keys()]);
      const out = [];
      let guard = 0;
      while (out.length < limit && keys.length && guard < limit * 4) {
        guard += 1;
        for (let i = 0; i < keys.length && out.length < limit; i++) {
          const k = keys[i];
          const bucket = byKey.get(k);
          if (!bucket || !bucket.length) continue;
          const next = bucket.shift();
          const prev = out[out.length - 1];
          if (prev && personKey(prev) === personKey(next)) continue;
          out.push(next);
        }
        for (let i = keys.length - 1; i >= 0; i--) {
          if (!(byKey.get(keys[i]) || []).length) keys.splice(i, 1);
        }
      }
      if (out.length > 2 && personKey(out[0]) === personKey(out[out.length - 1])) {
        for (let i = 1; i < out.length - 1; i++) {
          if (personKey(out[i]) !== personKey(out[0])) {
            const tmp = out[i];
            out[i] = out[out.length - 1];
            out[out.length - 1] = tmp;
            break;
          }
        }
      }
      return out;
    }

    function interleaveColumns(pool) {
      const a = [];
      const b = [];
      for (let i = 0; i < pool.length; i++) {
        (i % 2 === 0 ? a : b).push(pool[i]);
      }
      const fix = (col) => {
        for (let i = 1; i < col.length; i++) {
          if (personKey(col[i]) !== personKey(col[i - 1])) continue;
          for (let j = i + 1; j < col.length; j++) {
            if (personKey(col[j]) !== personKey(col[i - 1])) {
              const t = col[i];
              col[i] = col[j];
              col[j] = t;
              break;
            }
          }
        }
        return col;
      };
      return [fix(a), fix(b)];
    }

    function fillTrack(track, list) {
      track.innerHTML = '';
      const frag = document.createDocumentFragment();
      const make = (it) => {
        const img = document.createElement('img');
        img.src = thumbOf(it);
        img.alt = '';
        img.loading = 'lazy';
        img.decoding = 'async';
        img.dataset.person = personKey(it);
        img.addEventListener('click', () => {
          location.href = 'search.html';
        });
        return img;
      };
      list.forEach((it) => frag.appendChild(make(it)));
      list.forEach((it) => frag.appendChild(make(it)));
      track.appendChild(frag);
      track.style.animation = 'none';
      void track.offsetWidth;
      track.style.animation = '';
    }

    let pool = [];
    let faceMeta = null;

    // Preferência: backend já devolve 1 foto por rosto (InsightFace)
    try {
      const r = await fetch('/api/contato/reel?limit=24', { credentials: 'same-origin' });
      if (r.ok) {
        const data = await r.json();
        faceMeta = data.face || null;
        pool = (data.items || []).filter((it) => it && (it.thumb_url || it.id) && isPhotoItem(it));
      }
    } catch (e) {
      console.warn('[contato-reel] api', e);
    }

    // Fallback antigo (busca) se o endpoint ainda não indexou rostos
    if (pool.length < 8) {
      async function fetchBucket(q, n = 16) {
        const qs = new URLSearchParams({
          q: q || '',
          tipo: 'image',
          per_page: String(n),
          page: '1',
        });
        const r = await fetch(`/api/search?${qs}`, { credentials: 'same-origin' });
        if (!r.ok) return [];
        const data = await r.json();
        return data.items || [];
      }
      try {
        const batches = await Promise.allSettled([
          fetchBucket('show', 14),
          fetchBucket('retrato', 14),
          fetchBucket('casamento', 12),
          fetchBucket('casal', 12),
          fetchBucket('', 24),
        ]);
        const seen = new Set(pool.map((it) => Number(it.id)).filter(Boolean));
        for (const res of batches) {
          if (res.status !== 'fulfilled') continue;
          for (const it of res.value) {
            if (!it || it.tipo === 'video') continue;
            const id = Number(it.id);
            if (!id || seen.has(id)) continue;
            if (!it.thumb_url && !it.id) continue;
            seen.add(id);
            pool.push(it);
          }
        }
      } catch (e) {
        console.warn('[contato-reel]', e);
      }
    }

    const uniqueKeys = new Set(pool.map(personKey));
    if (uniqueKeys.size < 8) {
      for (const fb of FALLBACK) {
        if (pool.length >= 40) break;
        pool.push(fb);
      }
    }

    let diverse = pickDiverse(pool, 24, 1);
    if (diverse.length < 12) {
      diverse = pickDiverse(pool.concat(FALLBACK), 24, 2);
    }
    if (diverse.length < 8) {
      diverse = pickDiverse(FALLBACK, 16, 1);
    }

    if (faceMeta && typeof faceMeta.missing === 'number' && faceMeta.missing > 0) {
      console.info(
        `[contato-reel] rostos indexados: ${faceMeta.with_face || 0} · clusters: ${faceMeta.clusters || 0} · faltam: ${faceMeta.missing}`
      );
    }

    const [colA, colB] = interleaveColumns(diverse);
    fillTrack(up, colA.length >= 6 ? colA : diverse.filter((_, i) => i % 2 === 0));
    fillTrack(down, colB.length >= 6 ? colB : diverse.filter((_, i) => i % 2 === 1));
    frame.classList.add('is-ready');
  }

  /* ── Footer Aleff Thiago → sobe pro parallax (hero) ───── */
  function initFooterBrandScroll() {
    const brand = $('#footerBrand');
    if (!brand) return;
    brand.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      scrollRestore.goParallax({ smooth: true });
      brand.blur();
    });
  }

  /* ── Trabalhos: JS masonry (shortest-column packer) ───── */
  function initWorkMasonry() {
    const root = $('#galeriaTrabalhos');
    if (!root || root.dataset.masonryInit === '1') return;
    root.dataset.masonryInit = '1';

    let debounceTimer = 0;
    let rafId = 0;
    let packing = false;

    function readCols() {
      const raw = getComputedStyle(root).getPropertyValue('--cols').trim();
      const n = parseInt(raw, 10);
      if (n === 1 || n === 2 || n === 3 || n === 4) return n;
      const w = window.innerWidth;
      if (w <= 768) return 2;
      if (w <= 1100) return 3;
      return 4;
    }

    function readGap() {
      const raw = getComputedStyle(root).getPropertyValue('--gap').trim();
      const n = parseFloat(raw);
      return Number.isFinite(n) ? n : 2;
    }

    function isVisible(el) {
      if (!(el instanceof HTMLElement)) return false;
      if (el.hidden) return false;
      const cs = getComputedStyle(el);
      return cs.display !== 'none' && cs.visibility !== 'hidden';
    }

    /** Wide/hero: span 2 com ≥3 cols; l-hero em 4 cols tenta span 4 (faixa). */
    function itemSpan(el, cols) {
      if (el.classList.contains('gi-slot')) return 1;
      if (el.querySelector(':scope > video')) return 1;
      if (!el.querySelector(':scope > img')) return 1;
      if (el.classList.contains('l-hero') && cols >= 4) return cols;
      if (el.classList.contains('l-hero') && cols >= 3) return 2;
      if (cols < 3) return 1;
      if (el.classList.contains('l-wide') || el.classList.contains('l-hero')) return 2;
      return 1;
    }

    function pack() {
      if (packing) return;
      packing = true;
      const anchor = scrollRestore.shouldAnchorPack() ? scrollRestore.captureAnchor() : null;
      try {
        const cols = readCols();
        const gap = readGap();
        const cs = getComputedStyle(root);
        const padL = parseFloat(cs.paddingLeft) || 0;
        const padR = parseFloat(cs.paddingRight) || 0;
        const contentW = Math.max(0, root.clientWidth - padL - padR);
        if (contentW < 40 || cols < 1) return;

        const colW = (contentW - gap * (cols - 1)) / cols;
        const children = [...root.children].filter((el) => {
          if (el.classList.contains('grid-break')) return isVisible(el);
          if (el.classList.contains('gi')) return isVisible(el);
          return false;
        });

        root.classList.add('is-packed');

        /* 1) widths first so heights reflect real rendered media */
        children.forEach((el) => {
          el.style.position = 'absolute';
          el.style.margin = '0';
          el.style.right = 'auto';
          el.style.bottom = 'auto';
          el.style.boxSizing = 'border-box';
          if (el.classList.contains('grid-break')) {
            el.style.width = `${contentW}px`;
            el.style.left = `${padL}px`;
            el.dataset.mSpan = 'full';
            return;
          }
          const span = itemSpan(el, cols);
          el.dataset.mSpan = String(span);
          const w = span * colW + (span - 1) * gap;
          el.style.width = `${w}px`;
          el.style.maxWidth = 'none';
        });

        const heights = new Array(cols).fill(0);

        children.forEach((el) => {
          if (el.classList.contains('grid-break')) {
            const y = heights.length ? Math.max(...heights) : 0;
            el.style.top = `${y}px`;
            el.style.left = `${padL}px`;
            el.style.width = `${contentW}px`;
            const h = el.offsetHeight;
            const next = y + h + gap;
            for (let i = 0; i < cols; i++) heights[i] = next;
            return;
          }

          const span = Math.min(cols, parseInt(el.dataset.mSpan, 10) || 1);
          let bestCol = 0;
          let bestY = Infinity;

          if (span <= 1) {
            for (let c = 0; c < cols; c++) {
              if (heights[c] < bestY) {
                bestY = heights[c];
                bestCol = c;
              }
            }
          } else {
            for (let c = 0; c <= cols - span; c++) {
              let y = 0;
              for (let s = 0; s < span; s++) y = Math.max(y, heights[c + s]);
              if (y < bestY) {
                bestY = y;
                bestCol = c;
              }
            }
          }

          el.style.left = `${padL + bestCol * (colW + gap)}px`;
          el.style.top = `${bestY}px`;
          const h = el.offsetHeight;
          const bottom = bestY + h + gap;
          for (let s = 0; s < span; s++) heights[bestCol + s] = bottom;
        });

        const tallest = heights.length ? Math.max(...heights) : 0;
        root.style.height = `${Math.max(0, tallest - gap)}px`;
      } finally {
        packing = false;
        if (anchor) scrollRestore.restoreAnchor(anchor);
        else if (scrollRestore.shouldAnchorPack()) scrollRestore.applyPending();
        /* Não disparar scroll sintético a cada pack — evita trabalho em listeners */
      }
    }

    function schedulePack() {
      if (packing) return;
      clearTimeout(debounceTimer);
      debounceTimer = window.setTimeout(() => {
        cancelAnimationFrame(rafId);
        rafId = requestAnimationFrame(pack);
      }, 120);
    }

    /* Coalesce image loads — 1 pack por rajada, não 1 por foto */
    let imgPackPending = false;
    const onMediaSettle = () => {
      if (imgPackPending) return;
      imgPackPending = true;
      requestAnimationFrame(() => {
        imgPackPending = false;
        schedulePack();
      });
    };
    root.querySelectorAll('img').forEach((img) => {
      if (!img.complete) img.addEventListener('load', onMediaSettle, { passive: true, once: true });
      img.addEventListener('error', onMediaSettle, { passive: true, once: true });
    });
    root.querySelectorAll('video').forEach((v) => {
      v.addEventListener('loadedmetadata', onMediaSettle, { passive: true, once: true });
    });

    window.addEventListener('resize', schedulePack, { passive: true });
    if (document.fonts?.ready) document.fonts.ready.then(schedulePack).catch(() => {});

    if (typeof ResizeObserver !== 'undefined') {
      let lastW = 0;
      const ro = new ResizeObserver((entries) => {
        const w = entries[0]?.contentRect?.width ?? 0;
        if (Math.abs(w - lastW) < 2) return;
        lastW = w;
        schedulePack();
      });
      ro.observe(root);
    }

    /* Só childList — evita reflow loop com class/hidden no body */
    const mo = new MutationObserver((mutations) => {
      if (packing) return;
      for (const m of mutations) {
        if (m.type === 'childList' && (m.addedNodes.length || m.removedNodes.length)) {
          schedulePack();
          break;
        }
      }
    });
    mo.observe(root, { childList: true });

    root._workMasonryPack = schedulePack;
    /* Um pack inicial — aspect-ratio do CSS já estabiliza altura */
    requestAnimationFrame(pack);
  }

  /* ── Boot ─────────────────────────────────────────────── */
  function whenIdle(fn) {
    if (typeof requestIdleCallback === 'function') {
      requestIdleCallback(() => fn(), { timeout: 1800 });
    } else {
      setTimeout(fn, 120);
    }
  }

  function boot() {
    scrollRestore.init();
    initHero();
    initWorkMasonry();
    initLightbox();
    initVideoHover();
    initShortcuts();
    initContact();
    initContatoReel();
    initFooterBrandScroll();
    whenIdle(() => {
      initPortfolioHomeLayout().finally(() => {
        initPortfolioSlots().finally(() => {
          const root = $('#galeriaTrabalhos');
          if (root && typeof root._workMasonryPack === 'function') root._workMasonryPack();
          scrollRestore.applyPending();
          if (!isMobileUI()) initMotion();
          // Warmup da Pesquisa SÓ depois da home estável (não compete com a galeria)
          scheduleSearchWarmup();
        });
      });
      initCounters();
      initTimeline();
      initTags();
    });
  }

  function scheduleSearchWarmup() {
    const start = () => {
      const run = () => {
        try {
          if (typeof SearchWarmup !== 'undefined' && SearchWarmup.boot) {
            // afterHome: main.js já esperou masonry — sem segundo delay longo
            SearchWarmup.boot({ afterHome: true });
            return;
          }
        } catch (_) {}
        if (document.querySelector('script[data-search-warmup]')) return;
        const s = document.createElement('script');
        s.src = 'js/search-warmup.js?v=20260810warm5';
        s.dataset.searchWarmup = '1';
        s.onload = () => {
          try {
            if (window.SearchWarmup && SearchWarmup.boot) {
              SearchWarmup.boot({ afterHome: true });
            }
          } catch (_) {}
        };
        document.head.appendChild(s);
      };
      if (typeof requestIdleCallback === 'function') {
        requestIdleCallback(run, { timeout: 3000 });
      } else {
        setTimeout(run, 800);
      }
    };
    // Folga após pack da galeria — Home primeiro
    setTimeout(start, 1800);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
