/* search.js — Busca inteligente / Aleff Thiago Media System */
(function () {
  const API = '/api';

  const CAM_IDLE = [
    'Digite algo ou escolha uma categoria — o acervo responde na hora.',
    'Dica: nomes de pasta funcionam como busca de casal ou cliente.',
  ];
  const CAM_SEARCH = [
    'Buscando no acervo…',
    'Procurando tags e datas…',
  ];
  const CAM_DONE = [
    'Resultados na tela.',
    'Busca concluída.',
  ];

  const CAT_CARDS = [
    { cat: 'shows', mark: '01', name: 'Shows & palco', big: true, query: 'show' },
    { cat: 'casamento', mark: '02', name: 'Casamento', big: true, theme: 'casamento', query: 'casamento' },
    { cat: 'retratos', mark: '03', name: 'Retratos', query: 'retrato' },
    { cat: 'casais', mark: '04', name: 'Casais', query: 'casal' },
    { cat: 'familia', mark: '05', name: 'Família', query: 'familia' },
    { cat: 'infantil', mark: '06', name: 'Infantil', query: 'infantil' },
    { cat: 'motocross', mark: '07', name: 'Pista & ação', query: 'moto' },
    { cat: 'editorial', mark: '08', name: 'Editorial', query: 'editorial' },
  ];
  const CATEGORY_QUERIES = Object.fromEntries(CAT_CARDS.map((c) => [c.cat, c.query || c.cat || '']));

  let state = {
    q: '',
    tipo: '',
    categoria: '',
    apiCategoria: '',
    page: 1,
    pages: 1,
    total: 0,
    items: [],
    acIndex: -1,
    acItems: [],
    lbIndex: -1,
    camTimer: null,
    sortRecent: false,
  };

  const $ = (id) => document.getElementById(id);

  const searchInput = $('searchInput');
  const siClear = $('siClear');
  const siSubmit = $('siSubmit');
  const siDrop = $('siDrop');
  const siActions = $('siActions');
  const camMsg = $('camMsg');
  const camHint = $('camHint');
  const camWrap = $('camWrap');
  const casamentoActions = $('casamentoActions');
  const resGrid = $('resGrid');
  const resCount = $('resCount');
  const loadMoreWrap = $('loadMoreWrap');
  const lmBtn = $('lmBtn');
  const lmProg = $('lmProg');
  const lmCount = $('lmCount');
  const loadingCamTxt = $('loadingCamTxt');
  let searchCtrl = null;
  let acCtrl = null;
  let idleCtrl = null;

  async function api(url, opts) {
    return fetch(url, { credentials: 'same-origin', ...(opts || {}) });
  }

  function esc(s) {
    return String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function safeUrl(url) {
    const v = String(url || '');
    if (/^https:\/\/(drive\.google\.com|[\w.-]*googleusercontent\.com)\b/i.test(v)) return esc(v);
    if (/^(\/?fotos\/|\/?videos\/|data:image\/)/i.test(v)) return esc(v);
    if (/^\/api\/local\/[a-f0-9]+$/i.test(v)) return esc(v);
    if (/^\/api\/media\/\d+\/thumb(?:\?sz=\d+)?$/i.test(v)) return esc(v);
    if (/^\/api\/media\/\d+\/download$/i.test(v)) return esc(v);
    return '';
  }

  function thumbUrl(item, size = 800) {
    const raw = String(item?.thumb_url || '');
    if (/^\/api\/local\//i.test(raw)) return safeUrl(raw);
    const m = raw.match(/^(\/api\/media\/\d+\/thumb)(?:\?.*)?$/i);
    if (m) return `${m[1]}?sz=${size}`;
    if (item?.id) return `/api/media/${item.id}/thumb?sz=${size}`;
    return safeUrl(raw);
  }

  function mediaStreamUrl(item) {
    if (!item) return '';
    const thumb = String(item.thumb_url || '');
    if (/^\/api\/local\/[a-f0-9]+$/i.test(thumb)) return thumb;
    if (/^(\/?videos\/)/i.test(thumb)) return thumb;
    if (item.id) return `/api/media/${item.id}/download`;
    return safeUrl(thumb);
  }

  const lb = $('lightbox');
  const lbFront = $('lbFront');
  let lbOpen = false;

  function mountLbMedia(item, { stream, poster, label }) {
    lbFront.innerHTML = '';
    if (item.tipo === 'video') {
      if (typeof AleffPlayer !== 'undefined' && stream) {
        const player = AleffPlayer.create({
          src: stream,
          poster: poster || '',
          title: label || displayName(item),
          autoplay: true,
          loop: false,
        });
        lbFront.appendChild(player.root);
        lbFront._aplayer = player;
      } else if (stream) {
        lbFront.innerHTML = `<video src="${esc(stream)}"${poster ? ` poster="${esc(poster)}"` : ''} playsinline preload="auto" autoplay style="max-width:100%;max-height:78vh;border-radius:14px"></video>`;
      } else {
        lbFront.innerHTML = '<p style="color:#666">Vídeo indisponível</p>';
      }
      return;
    }
    if (poster || stream) {
      const src = poster || stream;
      lbFront.innerHTML = `<img src="${esc(src)}" alt="${esc(label || '')}" decoding="async"/>`;
    } else {
      lbFront.innerHTML = '<p style="color:#555">Carregando…</p>';
    }
  }

  /* Lightbox */
  async function openLightbox(idx) {
    state.lbIndex = idx;
    const item = state.items[idx];
    if (!item) return;
    lbOpen = true;
    lb.classList.add('open');
    lb.setAttribute('aria-hidden', 'false');
    $('lbTitle').textContent = displayName(item);
    $('lbMeta').textContent = [item.categoria, item.autor, item.data_upload].filter(Boolean).join(' · ');
    $('lbCtr').textContent = `${idx + 1} / ${state.items.length}`;
    $('lbDrive').href = item.drive_link || '#';
    $('lbDrive').style.display = item.drive_link && !String(item.drive_id || '').startsWith('local:')
      ? ''
      : 'none';

    if (lbFront._aplayer) {
      try { lbFront._aplayer.destroy(); } catch { /* ignore */ }
      lbFront._aplayer = null;
    }

    const card = $('lbCard');
    card.classList.remove('flipped');

    const poster = safeUrl(item.thumb_url);
    const stream = item.tipo === 'video' ? mediaStreamUrl(item) : '';
    const label0 = displayName(item);

    if (item.tipo === 'video') {
      mountLbMedia(item, { stream, poster, label: label0 });
    } else if (poster) {
      mountLbMedia(item, { stream: poster, poster, label: label0 });
    } else {
      lbFront.innerHTML = '<p style="color:#555">Carregando…</p>';
    }

    // Animação de virar a carta (foto e vídeo)
    requestAnimationFrame(() => {
      requestAnimationFrame(() => card.classList.add('flipped'));
    });

    try {
      const r = await api(`${API}/media/${item.id}`);
      const data = await r.json();
      const full = data.item || data.media || data;
      if (!lbOpen || state.lbIndex !== idx) return;
      const nextPoster = safeUrl(full.thumb_url || item.thumb_url);
      const label = (full.pasta || item.pasta || '').trim() || 'Sem pasta';
      const nextStream = full.tipo === 'video'
        ? mediaStreamUrl({ ...item, ...full })
        : '';
      if (full.tipo === 'video') {
        const cur = lbFront._aplayer?.video?.src || '';
        if (!cur || (nextStream && !cur.includes(String(full.id || item.id)))) {
          if (lbFront._aplayer) {
            try { lbFront._aplayer.destroy(); } catch { /* ignore */ }
            lbFront._aplayer = null;
          }
          mountLbMedia({ ...item, ...full }, { stream: nextStream, poster: nextPoster, label });
        }
      } else if (nextPoster) {
        mountLbMedia({ ...item, ...full }, { stream: nextPoster, poster: nextPoster, label });
      } else if (!poster) {
        lbFront.innerHTML = `<p style="color:#666">Sem preview</p>`;
      }
      $('lbTitle').textContent = label;
      if (full.drive_link) $('lbDrive').href = full.drive_link;
    } catch {
      if (!poster && !stream) lbFront.innerHTML = `<p style="color:#e53e3e">Erro ao carregar mídia</p>`;
    }

    $('lbDownload').onclick = async () => {
      try {
        const r = await api(`${API}/media/${item.id}/download`);
        if (!r.ok) throw new Error('Download negado');
        const blob = await r.blob();
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        const base = displayName(item).replace(/[\\/:*?"<>|]+/g, '-');
        a.download = base === 'Sem pasta' ? 'download' : base;
        a.click();
        URL.revokeObjectURL(a.href);
      } catch (e) {
        if (typeof Toast !== 'undefined') Toast.error('Download', e.message || 'Falha');
      }
    };
  }

  function closeLightbox() {
    lbOpen = false;
    lb.classList.remove('open');
    lb.setAttribute('aria-hidden', 'true');
    if (lbFront._aplayer) {
      try { lbFront._aplayer.destroy(); } catch { /* ignore */ }
      lbFront._aplayer = null;
    }
    $('lbCard')?.classList.remove('flipped');
    lbFront.innerHTML = '';
  }

  function setTheme(cat) {
    document.body.classList.remove('theme-casamento', 'theme-generico');
    if (cat === 'casamento') {
      document.body.classList.add('theme-casamento');
      casamentoActions.hidden = false;
    } else {
      document.body.classList.add('theme-generico');
      casamentoActions.hidden = true;
    }
  }

  function pick(arr) {
    return arr[Math.floor(Math.random() * arr.length)];
  }

  function setcamMsg(text, collect) {
    if (!camMsg) return;
    camMsg.classList.add('cam-msg--swap');
    setTimeout(() => {
      camMsg.textContent = text;
      camMsg.classList.remove('cam-msg--swap');
    }, 120);
    if (collect && camHint) {
      camHint.classList.add('cam-hint--pulse');
      setTimeout(() => camHint.classList.remove('cam-hint--pulse'), 520);
    }
  }

  function rotateCamIdle() {
    // Mensagem fixa — evita “piscadas” constantes na página
    clearInterval(state.camTimer);
    state.camTimer = null;
  }

  /* ── Câmera: ciclo completo sincronizado com a busca ─── */
  const CAM_CYCLE_MS = 480;
  const CAM_FINISH_MS = 320;
  let camToken = 0;
  let camStartedAt = 0;

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function allCamWraps() {
    return document.querySelectorAll('.cam-wrap');
  }

  function startCamSearch() {
    camToken += 1;
    camStartedAt = performance.now();
    allCamWraps().forEach((el) => {
      el.classList.remove('is-finishing');
      el.classList.remove('is-searching');
      void el.offsetWidth; // reinicia o ciclo do zero
      el.classList.add('is-searching');
    });
  }

  async function stopCamSearch() {
    const token = camToken;
    const elapsed = performance.now() - camStartedAt;
    // Garante pelo menos 1 ciclo completo; se a busca demorou mais, fecha o ciclo atual
    const cycles = Math.max(1, Math.ceil(elapsed / CAM_CYCLE_MS));
    const remain = cycles * CAM_CYCLE_MS - elapsed;
    if (remain > 12) await sleep(remain);
    if (token !== camToken) return;

    allCamWraps().forEach((el) => {
      el.classList.remove('is-searching');
      el.classList.remove('is-finishing');
      void el.offsetWidth;
      el.classList.add('is-finishing');
    });

    await sleep(CAM_FINISH_MS);
    if (token !== camToken) return;
    allCamWraps().forEach((el) => el.classList.remove('is-finishing'));
  }

  function setUiState(name) {
    ['stIdle', 'stLoading', 'stResults', 'stEmpty'].forEach((id) => {
      $(id).classList.toggle('active', id === 'st' + name.charAt(0).toUpperCase() + name.slice(1));
    });
  }

  function updateClearBtn() {
    const has = searchInput.value.trim().length > 0;
    siClear.classList.toggle('show', has);
    searchInput.parentElement.classList.toggle('has-text', has);
  }

  function buildParams(page) {
    const p = new URLSearchParams();
    if (state.q) p.set('q', state.q);
    if (state.tipo) p.set('tipo', state.tipo);
    if (state.apiCategoria) p.set('categoria', state.apiCategoria);
    p.set('page', String(page || 1));
    p.set('per_page', '24');
    return p;
  }

  function getCategoryQuery(cat) {
    return CATEGORY_QUERIES[cat] || cat || '';
  }

  async function runSearch(resetPage) {
    if (searchCtrl) searchCtrl.abort();
    const ctrl = new AbortController();
    searchCtrl = ctrl;
    if (resetPage) {
      state.page = 1;
      state.items = [];
    }

    const qTrim = searchInput.value.trim();
    state.q = qTrim;

    // Loading só se ainda não há grid — senão troca na hora (busca rápida)
    if (!state.items.length) setUiState('loading');
    setcamMsg(pick(CAM_SEARCH));
    if (loadingCamTxt) loadingCamTxt.textContent = pick(CAM_SEARCH);
    startCamSearch();

    try {
      const t0 = performance.now();
      const r = await api(`${API}/search?${buildParams(state.page)}`, { signal: ctrl.signal });
      const payload = await r.json();
      if (!r.ok || payload.status === 'error') throw new Error(payload.message || 'Erro na busca');
      console.debug('[search]', Math.round(performance.now() - t0) + 'ms', qTrim || '(browse)');

      const items = payload.items || [];
      state.total = payload.total || 0;
      state.pages = payload.pages || 1;
      state.page = payload.page || state.page;

      if (resetPage) state.items = items;
      else state.items = state.items.concat(items);

      resCount.innerHTML = state.total
        ? `<strong>${state.total.toLocaleString('pt-BR')}</strong> resultado${state.total === 1 ? '' : 's'}`
        : '';

      if (searchCtrl === ctrl) stopCamSearch();

      if (!state.items.length) {
        setUiState('empty');
        renderEmptySugs();
        setcamMsg('Nada nesse ângulo ainda. Tente outro filtro.');
      } else {
        setUiState('results');
        renderGrid();
        updateLoadMore();
        setcamMsg(pick(CAM_DONE), true);
      }
    } catch (e) {
      if (e && e.name === 'AbortError') {
        return;
      }
      console.error(e);
      if (searchCtrl === ctrl) stopCamSearch();
      setUiState('empty');
      setcamMsg('Ops — conexão falhou. Tenta de novo?');
      if (typeof Toast !== 'undefined') Toast.error('Erro na busca', e.message || 'Sem conexão.');
    }
  }

  function cardRatio(item) {
    if (item.tipo === 'video') return 'reel';
    const n = (item.nome || '').toLowerCase();
    if (n.includes('banner') || n.includes('wide')) return 'landscape';
    return ['portrait', 'landscape', 'square', 'cinema'][item.id % 4] || 'square';
  }

  function displayName(item) {
    // Só nome da pasta (pessoa/ensaio) — nunca nome do arquivo .jpg
    const pasta = String(item.pasta || '').trim();
    return pasta || 'Sem pasta';
  }

  function renderGrid() {
    resGrid.className = 'res-grid';
    resGrid.innerHTML = state.items
      .map((item, i) => {
        const ratio = cardRatio(item);
        const tags = (item.tags || '')
          .split(',')
          .map((t) => t.trim())
          .filter(Boolean)
          .slice(0, 3);
        return `
      <article class="rcard ${ratio}" data-idx="${i}" tabindex="0">
        ${
          item.thumb_url
            ? `<img class="rcard-thumb" src="${thumbUrl(item, 800)}" alt="${esc(displayName(item))}" loading="${i < 6 ? 'eager' : 'lazy'}" ${i < 4 ? 'fetchpriority="high"' : ''} decoding="async" onerror="this.onerror=null;this.classList.add('is-broken');this.style.opacity='0.15'"/>`
            : `<div class="rcard-ph" aria-hidden="true">${item.tipo === 'video'
                ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="2" y="6" width="14" height="12" rx="2"/><path d="m16 10 6-3.5v11L16 14"/></svg>'
                : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="8.5" cy="10" r="1.6"/><path d="m21 15-5-4-9 7"/></svg>'
              }</div>`
        }
        <span class="rcard-badge-tipo">${item.tipo === 'video' ? 'vídeo' : 'foto'}</span>
        ${item.tipo === 'video' ? '<span class="rcard-vid"></span>' : ''}
        <div class="rcard-ov">
          <p class="rcard-title">${esc(displayName(item))}</p>
          <p class="rcard-meta">${esc(item.categoria || '')}${item.data_upload ? ' · ' + esc(item.data_upload) : ''}</p>
          ${
            tags.length
              ? `<div class="rcard-tags">${tags.map((t) => `<span class="rcard-tag">${esc(t)}</span>`).join('')}</div>`
              : ''
          }
        </div>
      </article>`;
      })
      .join('');

    resGrid.querySelectorAll('.rcard').forEach((el) => {
      el.addEventListener('click', () => openLightbox(parseInt(el.dataset.idx, 10)));
      el.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter') openLightbox(parseInt(el.dataset.idx, 10));
      });
    });
  }

  function updateLoadMore() {
    const hasMore = state.page < state.pages;
    loadMoreWrap.classList.toggle('show', hasMore && state.items.length > 0);
    const shown = state.items.length;
    lmCount.textContent = hasMore ? `(${shown}/${state.total})` : '';
    lmProg.style.width = state.total ? `${Math.min(100, (shown / state.total) * 100)}%` : '0%';
  }

  function renderEmptySugs() {
    const el = $('emptySugs');
    if (!el) return;
    const sugs = ['casamento', 'show', 'retrato', '2024', 'noiva'];
    el.innerHTML = sugs
      .map((s) => `<button type="button" data-q="${esc(s)}">${esc(s)}</button>`)
      .join('');
    el.querySelectorAll('button').forEach((btn) => {
      btn.addEventListener('click', () => {
        searchInput.value = btn.dataset.q;
        updateClearBtn();
        runSearch(true);
      });
    });
  }

  function renderCatGrid(counts) {
    const map = {};
    (counts || []).forEach((c) => {
      map[(c.categoria || '').toLowerCase()] = c.total;
    });
    $('catGrid').innerHTML = CAT_CARDS.map((c) => {
      const n = map[c.cat] || 0;
      const cls = c.big ? 'cat-card big' : 'cat-card';
      return `<button type="button" class="${cls}" data-cat="${esc(c.cat)}" data-theme="${esc(c.theme || '')}" data-q="${esc(c.query || '')}">
        <span class="cat-mark">${esc(c.mark || '·')}</span>
        <span class="cat-name">${esc(c.name)}</span>
        <span class="cat-count">${n ? n + ' itens' : 'explorar'}</span>
      </button>`;
    }).join('');

    $('catGrid').querySelectorAll('.cat-card').forEach((btn) => {
      btn.addEventListener('click', () => {
        applyCategory(btn.dataset.cat, btn.dataset.theme);
        // Acervo veio quase sem coluna categoria — busca por texto/tags/CLIP
        const q = btn.dataset.q || getCategoryQuery(btn.dataset.cat || '') || btn.dataset.cat || '';
        searchInput.value = q;
        state.q = q;
        updateClearBtn();
        syncPills();
        runSearch(true);
      });
    });
  }

  async function loadIdleData() {
    if (idleCtrl) idleCtrl.abort();
    idleCtrl = new AbortController();
    try {
      const [statsRes, tagsRes] = await Promise.allSettled([
        api(`${API}/search/stats`, { signal: idleCtrl.signal }),
        api(`${API}/tags`, { signal: idleCtrl.signal }),
      ]);
      const stats = statsRes.status === 'fulfilled' ? await statsRes.value.json() : {};
      const tags = tagsRes.status === 'fulfilled' ? await tagsRes.value.json() : {};
      renderCatGrid(stats.por_categoria || []);
      const list = tags.tags || [];
      $('popTags').innerHTML = list
        .slice(0, 18)
        .map((t) => `<button type="button" class="ptag" data-q="${esc(t)}">${esc(t)}</button>`)
        .join('');
      $('popTags').querySelectorAll('.ptag').forEach((btn) => {
        btn.addEventListener('click', () => {
          searchInput.value = btn.dataset.q;
          updateClearBtn();
          runSearch(true);
        });
      });

      // Mostra fotos recentes já na entrada (antes de digitar)
      if (!searchInput.value.trim()) {
        const recent = await api(`${API}/search?q=&per_page=24&page=1`, { signal: idleCtrl.signal });
        const payload = await recent.json();
        if (recent.ok && (payload.items || []).length) {
          state.q = '';
          state.page = payload.page || 1;
          state.pages = payload.pages || 1;
          state.total = payload.total || 0;
          state.items = payload.items || [];
          resCount.innerHTML = state.total
            ? `<strong>${state.total.toLocaleString('pt-BR')}</strong> no acervo`
            : '';
          setUiState('results');
          renderGrid();
          updateLoadMore();
          setcamMsg('Acervo recente — digite pra filtrar.');
        }
      }
    } catch (e) {
      if (e && e.name === 'AbortError') return;
      console.warn('Idle data', e);
      renderCatGrid([]);
    }
  }

  function applyCategory(cat, themeHint) {
    state.categoria = cat || '';
    // Não filtrar por coluna categoria: no banco quase tudo veio vazio.
    // Explorar usa busca textual (tags + OpenCLIP).
    state.apiCategoria = '';
    setTheme(themeHint || cat);
  }

  function syncPills() {
    document.querySelectorAll('#catPills .fpill').forEach((p) => {
      p.classList.toggle('active', (p.dataset.cat || '') === state.categoria);
    });
    document.querySelectorAll('.fbtn[data-tipo]').forEach((b) => {
      b.classList.toggle('active', (b.dataset.tipo || '') === state.tipo);
    });
  }

  /* ── Autocomplete ───────────────────────────────────── */
  let acTimer;
  async function fetchAutocomplete(q) {
    if (acCtrl) acCtrl.abort();
    if (q.length < 2) {
      siDrop.classList.remove('open');
      return;
    }
    acCtrl = new AbortController();
    try {
      const r = await api(`${API}/search/autocomplete?q=${encodeURIComponent(q)}`, { signal: acCtrl.signal });
      const data = await r.json();
      const sugs = data.suggestions || [];
      state.acItems = sugs;
      state.acIndex = -1;
      if (!sugs.length) {
        siDrop.classList.remove('open');
        return;
      }
      siDrop.innerHTML = sugs
        .map(
          (s, i) => `
        <div class="ac-row" data-i="${i}" role="option">
          <span class="ac-ico">${esc((s.type || 'tag').slice(0, 1).toUpperCase())}</span>
          <span class="ac-txt">${highlight(s.text, q)}</span>
          <span class="ac-kind">${esc(s.type || '')}</span>
        </div>`
        )
        .join('');
      siDrop.classList.add('open');
      siDrop.querySelectorAll('.ac-row').forEach((row) => {
        row.addEventListener('mousedown', (ev) => {
          ev.preventDefault();
          chooseAc(parseInt(row.dataset.i, 10));
        });
      });
    } catch (e) {
      if (e && e.name === 'AbortError') return;
      siDrop.classList.remove('open');
    }
  }

  function highlight(text, q) {
    const i = text.toLowerCase().indexOf(q.toLowerCase());
    if (i < 0) return esc(text);
    return (
      esc(text.slice(0, i)) +
      '<mark>' +
      esc(text.slice(i, i + q.length)) +
      '</mark>' +
      esc(text.slice(i + q.length))
    );
  }

  function chooseAc(i) {
    const s = state.acItems[i];
    if (!s) return;
    searchInput.value = s.text;
    siDrop.classList.remove('open');
    updateClearBtn();
    runSearch(true);
  }

  function lbStep(dir) {
    if (!lbOpen) return;
    let next = state.lbIndex + dir;
    if (next < 0) next = state.items.length - 1;
    if (next >= state.items.length) next = 0;
    openLightbox(next);
  }

  /* ── Status indicators removidos da busca (ficam no dashboard) ── */

  /* ── Events ─────────────────────────────────────────── */
  searchInput.addEventListener('input', () => {
    updateClearBtn();
    if (searchInput.value.trim()) siActions.classList.add('visible');
    clearTimeout(acTimer);
    acTimer = setTimeout(() => fetchAutocomplete(searchInput.value.trim()), 220);
  });

  searchInput.addEventListener('focus', () => {
    searchInput.parentElement.classList.add('focused');
    siActions.classList.add('visible');
  });
  searchInput.addEventListener('blur', () => {
    setTimeout(() => {
      searchInput.parentElement.classList.remove('focused');
      if (!searchInput.value.trim()) siActions.classList.remove('visible');
      siDrop.classList.remove('open');
    }, 160);
  });

  searchInput.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') {
      ev.preventDefault();
      if (siDrop.classList.contains('open') && state.acIndex >= 0) {
        chooseAc(state.acIndex);
      } else {
        siDrop.classList.remove('open');
        runSearch(true);
      }
      return;
    }
    if (!siDrop.classList.contains('open')) return;
    if (ev.key === 'ArrowDown') {
      ev.preventDefault();
      state.acIndex = Math.min(state.acIndex + 1, state.acItems.length - 1);
      focusAcRow();
    } else if (ev.key === 'ArrowUp') {
      ev.preventDefault();
      state.acIndex = Math.max(state.acIndex - 1, 0);
      focusAcRow();
    } else if (ev.key === 'Escape') {
      siDrop.classList.remove('open');
    }
  });

  function focusAcRow() {
    siDrop.querySelectorAll('.ac-row').forEach((r, i) => {
      r.classList.toggle('focused', i === state.acIndex);
    });
  }

  siClear.addEventListener('click', () => {
    searchInput.value = '';
    updateClearBtn();
    state.q = '';
    siDrop.classList.remove('open');
    setUiState('idle');
    resCount.innerHTML = '';
    rotateCamIdle();
  });

  siSubmit.addEventListener('click', () => runSearch(true));

  siActions.querySelectorAll('.si-act').forEach((btn) => {
    btn.addEventListener('click', () => {
      const act = btn.dataset.act;
      btn.classList.add('si-act--pop');
      setTimeout(() => btn.classList.remove('si-act--pop'), 320);
      if (act === 'foto') {
        state.tipo = 'image';
        syncPills();
      } else if (act === 'video') {
        state.tipo = 'video';
        syncPills();
      } else if (act === 'recent') {
        state.sortRecent = true;
        if (!searchInput.value.trim()) searchInput.value = String(new Date().getFullYear());
      }
      runSearch(true);
    });
  });

  document.querySelectorAll('#quickTags .qtag').forEach((btn) => {
    btn.addEventListener('click', () => {
      searchInput.value = btn.dataset.q;
      updateClearBtn();
      runSearch(true);
    });
  });

  document.querySelectorAll('.cact').forEach((btn) => {
    btn.addEventListener('click', () => {
      searchInput.value = btn.dataset.q;
      updateClearBtn();
      runSearch(true);
    });
  });

  document.querySelectorAll('.fbtn[data-tipo]').forEach((btn) => {
    btn.addEventListener('click', () => {
      state.tipo = btn.dataset.tipo || '';
      syncPills();
      if (state.q || state.categoria) runSearch(true);
    });
  });

  document.querySelectorAll('#catPills .fpill').forEach((pill) => {
    pill.addEventListener('click', () => {
      const cat = pill.dataset.cat || '';
      applyCategory(cat, cat === 'casamento' ? 'casamento' : '');
      syncPills();
      if (!cat && !searchInput.value.trim()) {
        setUiState('idle');
        resCount.innerHTML = '';
        return;
      }
      if (cat) {
        const q = getCategoryQuery(cat) || cat;
        searchInput.value = q;
        state.q = q;
        updateClearBtn();
      }
      runSearch(true);
    });
  });

  lmBtn.addEventListener('click', () => {
    if (state.page >= state.pages) return;
    state.page += 1;
    runSearch(false);
  });

  $('lbClose').addEventListener('click', closeLightbox);
  $('lbPrev').addEventListener('click', () => lbStep(-1));
  $('lbNext').addEventListener('click', () => lbStep(1));
  lb.addEventListener('click', (ev) => {
    if (ev.target === lb) closeLightbox();
  });
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape' && lbOpen) closeLightbox();
    if (lbOpen && ev.key === 'ArrowLeft') lbStep(-1);
    if (lbOpen && ev.key === 'ArrowRight') lbStep(1);
  });

  const params = new URLSearchParams(window.location.search);
  const initialQ = params.get('q');
  if (initialQ) {
    searchInput.value = initialQ;
    updateClearBtn();
  }

  updateClearBtn();
  (async () => {
    rotateCamIdle();
    loadIdleData();
    if (initialQ) runSearch(true);
  })();
})();
