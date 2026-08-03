/* main.js — portfólio / lightbox / contato */
(() => {
  'use strict';

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  /* Media pool (lightbox) */
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

  const isMobileUI = () => window.matchMedia('(max-width: 768px), (hover: none)').matches;

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
  function applyVideoFrame(v) {
    const parent = v.closest('.gi');
    if (!parent) return;
    const apply = () => {
      if (!(v.videoWidth > 0 && v.videoHeight > 0)) return;
      // feature-cinema / highlight mantêm faixa larga cinematográfica
      if (parent.classList.contains('feature-cinema') || parent.classList.contains('highlight')) return;
      parent.style.aspectRatio = `${v.videoWidth} / ${v.videoHeight}`;
    };
    if (v.readyState >= 1) apply();
    else v.addEventListener('loadedmetadata', apply, { once: true });
  }

  function initVideoHover() {
    const videos = $$('.gi video, .foto-item video');
    if (!videos.length) return;

    // Evita congestionamento: só metadata quando entra na tela
    videos.forEach((v) => {
      const lazy = v.getAttribute('data-src');
      if (lazy && !v.getAttribute('src')) {
        v.setAttribute('src', lazy);
      }
      v.preload = 'none';
      v.setAttribute('playsinline', '');
      v.muted = true;
      applyVideoFrame(v);
      try { v.load(); } catch { /* ignore */ }
    });

    const warm = (v) => {
      if (!v || v.dataset.warmed === '1') return;
      v.dataset.warmed = '1';
      v.preload = 'metadata';
      try { v.load(); } catch { /* ignore */ }
    };

    if ('IntersectionObserver' in window) {
      const io = new IntersectionObserver((entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) warm(e.target);
        });
      }, { rootMargin: '200px 0px', threshold: 0.01 });
      videos.forEach((v) => io.observe(v));
    } else {
      videos.forEach(warm);
    }

    if (isMobileUI()) return;

    videos.forEach((v) => {
      const parent = v.parentElement;
      if (!parent) return;
      parent.addEventListener('mouseenter', () => {
        warm(v);
        const p = v.play();
        if (p && typeof p.catch === 'function') p.catch(() => {});
      });
      parent.addEventListener('mouseleave', () => {
        v.pause();
        try { v.currentTime = 0; } catch { /* ignore */ }
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
      if (!d) return;
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
            title: d.title || '',
            loop: true,
            autoplay: true,
          });
          front.appendChild(player.root);
        } else {
          const v = document.createElement('video');
          v.src = d.src;
          v.playsInline = true;
          v.preload = 'auto';
          v.autoplay = true;
          v.loop = true;
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
      lb.classList.remove('open');
      document.body.style.overflow = '';
      lbC.innerHTML = '';
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
        opening: 'Copiando mensagem…',
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
            ? 'Instagram não pré-preenche o Direct. Ao enviar, a mensagem é copiada — é só colar.'
            : method === 'whatsapp'
              ? 'No WhatsApp a mensagem já abre preenchida.'
              : 'No Gmail a mensagem já abre no compose.';
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
      syncPreview();
    }

    function selectMethod(next) {
      if (!methods[next]) return;
      method = next;
      channels.forEach((el) => {
        const on = el.dataset.method === method;
        el.classList.toggle('is-active', on);
        el.setAttribute('aria-checked', on ? 'true' : 'false');
      });
      syncSendButton();
    }

    channels.forEach((el) => {
      el.addEventListener('click', () => selectMethod(el.dataset.method));
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
            const subject = encodeURIComponent(subjectRaw);
            const body = encodeURIComponent(texto);
            const mobile = CS?.isMobile ? CS.isMobile() : /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
            openExternal(
              mobile
                ? `mailto:aleffthigo@gmail.com?subject=${subject}&body=${body}`
                : `https://mail.google.com/mail/?view=cm&fs=1&to=aleffthigo@gmail.com&su=${subject}&body=${body}`
            );
          } else if (method === 'instagram') {
            if (CS?.sendInstagram) {
              await CS.sendInstagram(texto, { previewRoot: previewBox });
            } else {
              await copyMessage();
              openExternal('https://ig.me/m/aleffthiagofilms');
            }
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
        el.removeAttribute('aria-label');
        const src = s.src.startsWith('/') ? s.src.slice(1) : s.src;
        const title = String(s.title || 'Trabalho')
          .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
        const cat = String(s.cat || '')
          .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
        if (s.type === 'video') {
          el.innerHTML = `<video src="${src.replace(/"/g, '')}" muted loop playsinline preload="none"></video><div class="gi-ov"><div class="gi-play"></div><p class="gi-title">${title}</p><p class="gi-cat">${cat}</p></div>`;
        } else {
          el.style.aspectRatio = '';
          el.innerHTML = `<img src="${src.replace(/"/g, '')}" alt="${title}" loading="lazy" decoding="async"/><div class="gi-ov"><p class="gi-title">${title}</p><p class="gi-cat">${cat}</p></div>`;
        }
        el.classList.add('rv');
      });
      initVideoHover();
    } catch { /* mantém placeholders */ }
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
    initHero();
    initLightbox();
    initVideoHover();
    initShortcuts();
    initContact();
    whenIdle(() => {
      initPortfolioSlots();
      initCounters();
      if (!isMobileUI()) initMotion();
      initTimeline();
      initTags();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
