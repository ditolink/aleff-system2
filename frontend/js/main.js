/* ============================================================
   main.js — Portfólio Aleff Thiago
   Módulos: hero, status, lightbox, motion, contato
============================================================ */
(() => {
  'use strict';

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  /* ── Media pools (lightbox) ───────────────────────────── */
  const mediaPool = [
    { type: 'video', src: 'videos/Instagram.mp4', title: 'Reel Instagram' },
    { type: 'video', src: 'videos/REELS1.mp4', title: 'Ação & Movimento' },
    { type: 'img', src: 'fotos/foto_thalles.jpg', title: 'Thalles Roberto — Montes Claros' },
    { type: 'img', src: 'fotos/foto11i.jpg', title: 'Tarde na Piscina' },
    { type: 'img', src: 'fotos/foto20.webp', title: 'Tarde de Praia' },
    { type: 'img', src: 'fotos/foto55.jpg', title: 'Luz da Tarde' },
    { type: 'img', src: 'fotos/foto10.jpg', title: 'Ponte das Bandeiras — SP' },
    { type: 'img', src: 'fotos/foto_detonautas.webp', title: 'Detonautas — Pirapora MG' },
    { type: 'img', src: 'fotos/foto12.jpg', title: 'O Lance Certo' },
    { type: 'img', src: 'fotos/foto_jotaquest.webp', title: 'Jota Quest — Pirapora MG' },
    { type: 'img', src: 'fotos/foto30.jpg', title: 'Estilo & Atitude' },
    { type: 'img', src: 'fotos/foto60.webp', title: 'Retrato Iluminado' },
    { type: 'img', src: 'fotos/foto41.webp', title: 'Brincadeira de Casal' },
    { type: 'img', src: 'fotos/foto40.webp', title: 'Para Sempre' },
    { type: 'video', src: 'videos/video72.mp4', title: 'Natureza Viva' },
    { type: 'video', src: 'videos/VIDEORAPS.mp4', title: 'Sessão de Rap' },
    { type: 'video', src: 'videos/VIDEORAPS.mp4', title: 'Dia Inesquecível' },
    { type: 'video', src: 'videos/video73.mp4', title: 'Frame Perfeito' },
    { type: 'img', src: 'fotos/foto50.webp', title: 'Noite de Halloween' },
    { type: 'video', src: 'videos/video12.mp4', title: 'Produção Especial' },
    { type: 'video', src: 'videos/COMERCIAL01.mp4', title: 'No Estúdio' },
    { type: 'img', src: 'fotos/fotolely01.jpg', title: 'Vento da Tarde' },
    { type: 'img', src: 'fotos/fotojoy01.jpg', title: 'Doce Olhar' },
    { type: 'img', src: 'fotos/fotolely02.jpg', title: 'Dentro do Quadro' },
    { type: 'img', src: 'fotos/foto94.webp', title: 'Suspensa no Tempo' },
  ];

  const fotoPool = [
    { type: 'video', src: 'videos/Reel01.mp4', title: 'Reel 01' },
    { type: 'video', src: 'videos/Reel02.mp4', title: 'Reel 02' },
    { type: 'video', src: 'videos/video67.mp4', title: 'Reel 04' },
    { type: 'video', src: 'videos/video12.mp4', title: 'Reel 05' },
    { type: 'video', src: 'videos/COMERCIAL01.mp4', title: 'Reel 06' },
    { type: 'video', src: 'videos/Reel03.mp4', title: 'Reel 03' },
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

  /* ── Hero: parallax no rosto + nav some no scroll ───── */
  function initHero() {
    const heroBg = $('#heroBg');
    const heroContent = $('#heroContent');
    const nav = $('#siteNav');
    if (!heroBg || !heroContent) return;

    const onScroll = rafThrottle(() => {
      const sy = window.scrollY;
      if (sy < 900) {
        heroBg.style.transform = `translateY(${sy * 0.12}px)`;
        const fade = Math.min(1, sy / 520);
        heroContent.style.transform = `translateY(${sy * 0.06}px)`;
        heroContent.style.opacity = String(Math.max(0, 1 - Math.pow(fade, 1.5)));
      }
      if (nav) {
        // Some junto com o parallax (Trabalhos / Contato / Buscar)
        const navFade = Math.min(1, sy / 280);
        const opacity = Math.max(0, 1 - Math.pow(navFade, 1.35));
        nav.style.opacity = String(opacity);
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

  /* ── Vídeos no hover ──────────────────────────────────── */
  function initVideoHover() {
    $$('.gi video, .foto-item video').forEach((v) => {
      const parent = v.parentElement;
      if (!parent) return;
      parent.addEventListener('mouseenter', () => v.play().catch(() => {}));
      parent.addEventListener('mouseleave', () => {
        v.pause();
        v.currentTime = 0;
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

    function openLb(pool, idx) {
      cp = pool;
      ci = idx;
      const d = pool[idx];
      lbC.innerHTML = '';

      const card = document.createElement('div');
      card.className = 'lb-card';

      const back = document.createElement('div');
      back.className = 'lb-card-back';
      back.innerHTML = `
        <svg viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
          <g stroke="#f5f5f5" stroke-width="1.3" stroke-linecap="round" opacity="0.85">
            <path d="M9 8 Q8 5 9.5 2"/><path d="M15 7 Q14 4 15.5 1"/><path d="M21 8 Q20 5 21.5 2"/>
          </g>
          <path d="M7.5 11 L22.5 11 L20.5 23 Q20.3 24 19 24 L11 24 Q9.7 24 9.5 23 Z" fill="#f5f5f5"/>
        </svg>
        <span>Aleff Thiago</span>`;

      const front = document.createElement('div');
      front.className = 'lb-card-front';

      if (d.type === 'video') {
        const v = document.createElement('video');
        v.src = d.src;
        v.controls = true;
        v.autoplay = true;
        v.loop = true;
        front.appendChild(v);
      } else {
        const img = document.createElement('img');
        img.src = d.src;
        img.alt = d.title || '';
        front.appendChild(img);
      }

      card.appendChild(back);
      card.appendChild(front);
      lbC.appendChild(card);
      requestAnimationFrame(() => requestAnimationFrame(() => card.classList.add('flipped')));

      lbCtr.textContent = `${String(idx + 1).padStart(2, '0')} / ${String(pool.length).padStart(2, '0')}`;
      lbNm.textContent = d.title || '';
      lb.classList.add('open');
      document.body.style.overflow = 'hidden';
    }

    function closeLb() {
      lb.classList.remove('open');
      document.body.style.overflow = '';
      lbC.innerHTML = '';
    }

    $$('.gi:not(.gi-slot)').forEach((el, i) => el.addEventListener('click', () => {
      const idx = Number.parseInt(el.dataset.idx || '', 10);
      openLb(mediaPool, Number.isFinite(idx) ? idx : i);
    }));
    $$('.foto-item').forEach((el, i) => el.addEventListener('click', () => openLb(fotoPool, i)));
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
    if (ta && out) {
      ta.addEventListener('input', () => {
        out.textContent = `${ta.value.length}/500`;
      });
    }

    const btn = $('#btnSend');
    if (btn) {
      btn.addEventListener('click', () => {
        const card = btn.closest('.cc-right') || document;
        const nome = ($('#ccNome')?.value || '').trim();
        const contato = ($('#ccContato')?.value || '').trim();
        const tipo = ($('#ccTipo')?.value || '').trim();
        const mensagem = ($('#ccMsg')?.value || '').trim();

        let texto = nome
          ? `Oi, Aleff! Sou ${nome}, venho em contato pelo site.`
          : 'Oi, Aleff! Venho em contato pelo site.';
        if (contato) texto += `\nMeu contato: ${contato}`;
        if (tipo) texto += `\nProjeto: ${tipo}`;
        if (mensagem) texto += `\n\n${mensagem}`;

        const url = `https://wa.me/5538999078483?text=${encodeURIComponent(texto)}`;
        const original = btn.innerHTML;
        btn.innerHTML = 'Abrindo WhatsApp…';
        setTimeout(() => { btn.innerHTML = original; }, 2000);
        window.open(url, '_blank');
      });
    }

    const emailBtn = $('#emailBtn');
    if (emailBtn && !/Android|iPhone|iPad|iPod/i.test(navigator.userAgent)) {
      emailBtn.addEventListener('click', (e) => {
        e.preventDefault();
        window.open(
          'https://mail.google.com/mail/?view=cm&fs=1&to=aleffthigo@gmail.com&su=' +
            encodeURIComponent('Contato via portfólio'),
          '_blank'
        );
      });
    }
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
        el.removeAttribute('aria-label');
        const src = s.src.startsWith('/') ? s.src.slice(1) : s.src;
        const title = String(s.title || 'Trabalho')
          .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
        const cat = String(s.cat || '')
          .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
        if (s.type === 'video') {
          el.innerHTML = `<video src="${src.replace(/"/g, '')}" muted loop playsinline preload="metadata"></video><div class="gi-ov"><div class="gi-play"></div><p class="gi-title">${title}</p><p class="gi-cat">${cat}</p></div>`;
        } else {
          el.innerHTML = `<img src="${src.replace(/"/g, '')}" alt="${title}" loading="lazy"/><div class="gi-ov"><p class="gi-title">${title}</p><p class="gi-cat">${cat}</p></div>`;
        }
        el.classList.add('rv');
      });
      initVideoHover();
    } catch { /* mantém placeholders */ }
  }

  /* ── Boot ─────────────────────────────────────────────── */
  function boot() {
    initHero();
    initPortfolioSlots();
    initVideoHover();
    initCounters();
    initLightbox();
    initMotion();
    initTimeline();
    initTags();
    initContact();
    initShortcuts();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
