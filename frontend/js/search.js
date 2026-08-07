/* search.js — Acervo visual / Aleff Thiago */
(function () {
  const API = '/api';
  const PER_PAGE = 24;
  const GRID_SZ = () => (window.matchMedia('(max-width:900px)').matches ? 900 : 1200);
  const LB_SZ = 1200;

  const CAM_SEARCH = ['Buscando no acervo…', 'Procurando tags e datas…'];
  const CAM_DONE = ['Resultados na tela.', 'Busca concluída.'];

  const CAT_CARDS = [
    { cat: 'shows', mark: '01', name: 'Shows', query: 'show', keys: ['show', 'shows', 'palco'] },
    { cat: 'casamento', mark: '02', name: 'Casamento', theme: 'casamento', query: 'casamento', keys: ['casamento', 'noiva', 'noivo'] },
    { cat: 'retratos', mark: '03', name: 'Retratos', query: 'retrato', keys: ['retrato', 'retratos'] },
    { cat: 'casais', mark: '04', name: 'Casais', query: 'casal', keys: ['casal', 'casais', 'romantico'] },
    { cat: 'familia', mark: '05', name: 'Família', query: 'familia', keys: ['familia', 'familiar'] },
    { cat: 'infantil', mark: '06', name: 'Infantil', query: 'infantil', keys: ['infantil', 'crianca', 'bebe'] },
    { cat: 'motocross', mark: '07', name: 'Pista', query: 'moto', keys: ['moto', 'motocross', 'pista'] },
    { cat: 'editorial', mark: '08', name: 'Editorial', query: 'editorial', keys: ['editorial', 'moda'] },
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
    archiveTotal: 0,
    items: [],
    seenIds: new Set(),
    acIndex: -1,
    acItems: [],
    lbIndex: -1,
    camTimer: null,
    sortRecent: false,
    activeTag: '',
    loadingMore: false,
    coverByCat: {},
  };

  const $ = (id) => document.getElementById(id);
  const searchInput = $('searchInput');
  const siClear = $('siClear');
  const siSubmit = $('siSubmit');
  const siDrop = $('siDrop');
  const siActions = $('siActions');
  const camMsg = $('camMsg');
  const camHint = $('camHint');
  const casamentoActions = $('casamentoActions');
  const resGrid = $('resGrid');
  const loadMoreWrap = $('loadMoreWrap');
  const lmBtn = $('lmBtn');
  const lmProg = $('lmProg');
  const lmCount = $('lmCount');
  const lmStatus = $('lmStatus');
  const loadingCamTxt = $('loadingCamTxt');
  const archiveStat = $('archiveStat');
  const galleryKicker = $('galleryKicker');
  const galleryTitle = $('galleryTitle');
  const galleryMeta = $('galleryMeta');
  const scrollSentinel = $('scrollSentinel');

  let searchCtrl = null;
  let acCtrl = null;
  let idleCtrl = null;
  let io = null;

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

  function thumbUrl(item, size = 1200) {
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

  function fullImageUrl(item) {
    if (!item) return '';
    if (String(item.drive_id || '').startsWith('local:') || /^\/api\/local\//i.test(String(item.thumb_url || ''))) {
      return mediaStreamUrl(item) || thumbUrl(item, LB_SZ);
    }
    if (item.id) return `/api/media/${item.id}/download`;
    return thumbUrl(item, LB_SZ);
  }

  function displayName(item) {
    return String(item.pasta || '').trim() || 'Sem pasta';
  }

  function pick(arr) {
    return arr[Math.floor(Math.random() * arr.length)];
  }

  /* ── Lightbox ── */
  const lb = $('lightbox');
  const lbFront = $('lbFront');
  let lbOpen = false;

  function mountLbMedia(item, { stream, poster, label }) {
    if (lbFront._aplayer) {
      try { lbFront._aplayer.destroy(); } catch { /* ignore */ }
      lbFront._aplayer = null;
    }
    lbFront.innerHTML = '';
    if (item.tipo === 'video') {
      if (typeof AleffPlayer !== 'undefined' && stream) {
        const player = AleffPlayer.create({
          src: stream,
          poster: poster || '',
          title: label || displayName(item),
          autoplay: true,
          loop: false,
          preload: 'metadata',
        });
        lbFront.appendChild(player.root);
        lbFront._aplayer = player;
      } else if (stream) {
        lbFront.innerHTML = `<video src="${esc(stream)}"${poster ? ` poster="${esc(poster)}"` : ''} playsinline preload="metadata" muted autoplay style="max-width:100%;max-height:78vh;object-fit:contain"></video>`;
      } else {
        lbFront.innerHTML = '<p style="color:#666">Vídeo indisponível</p>';
      }
      return;
    }
    const src = stream || poster;
    if (src) {
      lbFront.innerHTML = `<img src="${esc(src)}" alt="${esc(label || '')}" decoding="async"/>`;
    } else {
      lbFront.innerHTML = '<p style="color:#555">Carregando…</p>';
    }
  }

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
    $('lbDrive').style.display =
      item.drive_link && !String(item.drive_id || '').startsWith('local:') ? '' : 'none';

    if (lbFront._aplayer) {
      try { lbFront._aplayer.destroy(); } catch { /* ignore */ }
      lbFront._aplayer = null;
    }

    const card = $('lbCard');
    card.classList.remove('flipped');

    const poster = thumbUrl(item, LB_SZ) || safeUrl(item.thumb_url);
    const stream = item.tipo === 'video' ? mediaStreamUrl(item) : fullImageUrl(item);
    const label0 = displayName(item);

    if (item.tipo === 'video') {
      mountLbMedia(item, { stream, poster, label: label0 });
    } else {
      mountLbMedia(item, { stream: poster, poster, label: label0 });
      if (stream && stream !== poster) {
        const img = new Image();
        img.decoding = 'async';
        img.onload = () => {
          if (!lbOpen || state.lbIndex !== idx) return;
          mountLbMedia(item, { stream, poster: stream, label: label0 });
        };
        img.src = stream;
      }
    }

    requestAnimationFrame(() => {
      requestAnimationFrame(() => card.classList.add('flipped'));
    });

    try {
      const r = await api(`${API}/media/${item.id}`);
      const data = await r.json();
      const full = data.item || data.media || data;
      if (!lbOpen || state.lbIndex !== idx) return;
      const label = (full.pasta || item.pasta || '').trim() || 'Sem pasta';
      $('lbTitle').textContent = label;
      if (full.drive_link) $('lbDrive').href = full.drive_link;
      if (full.tipo === 'video') {
        const nextStream = mediaStreamUrl({ ...item, ...full });
        const nextPoster = thumbUrl({ ...item, ...full }, LB_SZ);
        mountLbMedia({ ...item, ...full }, { stream: nextStream, poster: nextPoster, label });
      }
    } catch {
      /* preview already shown */
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

  function lbStep(dir) {
    if (!lbOpen) return;
    let next = state.lbIndex + dir;
    if (next < 0) next = state.items.length - 1;
    if (next >= state.items.length) next = 0;
    openLightbox(next);
  }

  /* ── UI helpers ── */
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

  const CAM_FINISH_MS = 160;
  let camToken = 0;
  function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }
  function allCamWraps() {
    return document.querySelectorAll('.cam-wrap');
  }
  function startCamSearch() {
    camToken += 1;
    allCamWraps().forEach((el) => {
      el.classList.remove('is-finishing');
      el.classList.add('is-searching');
    });
  }
  function stopCamSearch() {
    const token = camToken;
    allCamWraps().forEach((el) => {
      el.classList.remove('is-searching');
      el.classList.add('is-finishing');
    });
    sleep(CAM_FINISH_MS).then(() => {
      if (token !== camToken) return;
      allCamWraps().forEach((el) => el.classList.remove('is-finishing'));
    });
  }

  function setUiState(name) {
    ['stLoading', 'stResults', 'stEmpty'].forEach((id) => {
      const el = $(id);
      if (!el) return;
      const key = id.replace(/^st/, '').toLowerCase();
      el.classList.toggle('active', key === name);
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
    p.set('per_page', String(PER_PAGE));
    return p;
  }

  function getCategoryQuery(cat) {
    return CATEGORY_QUERIES[cat] || cat || '';
  }

  function updateArchiveStat() {
    if (!archiveStat) return;
    const n = state.archiveTotal || state.total || 0;
    if (!n) {
      archiveStat.textContent = 'Acervo em sincronia…';
      return;
    }
    archiveStat.innerHTML = `<strong>${n.toLocaleString('pt-BR')}</strong> fotografias no acervo`;
  }

  function updateResultsMeta() {
    const q = state.q.trim();
    const shown = state.items.length;
    const total = state.total || 0;

    if (galleryKicker) {
      galleryKicker.textContent = q ? 'Resultados' : 'Resultados do acervo';
    }
    if (galleryTitle) {
      galleryTitle.textContent = q
        ? `Resultados para: ${q}`
        : state.categoria
          ? CAT_CARDS.find((c) => c.cat === state.categoria)?.name || 'Seleção'
          : 'Seleção inicial';
    }
    if (galleryMeta) {
      if (!total && !shown) {
        galleryMeta.textContent = '';
      } else if (q || state.tipo || state.categoria) {
        galleryMeta.innerHTML = total
          ? `<strong>${total.toLocaleString('pt-BR')}</strong> encontradas · exibindo ${shown.toLocaleString('pt-BR')}`
          : `${shown} na tela`;
      } else {
        galleryMeta.innerHTML = total
          ? `Exibindo <strong>${shown.toLocaleString('pt-BR')}</strong> de <strong>${total.toLocaleString('pt-BR')}</strong>`
          : `${shown} na tela`;
      }
    }
  }

  function mergeItems(incoming, reset) {
    if (reset) {
      state.seenIds = new Set();
      state.items = [];
    }
    const added = [];
    for (const it of incoming || []) {
      const id = Number(it.id);
      if (!id || state.seenIds.has(id)) continue;
      state.seenIds.add(id);
      state.items.push(it);
      added.push(it);
    }
    return added;
  }

  function inferCovers(pool) {
    for (const c of CAT_CARDS) {
      if (state.coverByCat[c.cat]) continue;
      const hit = (pool || []).find((it) => {
        const blob = `${it.tags || ''} ${it.categoria || ''} ${it.pasta || ''} ${it.nome || ''}`.toLowerCase();
        return (c.keys || [c.query]).some((k) => blob.includes(k));
      });
      if (hit) state.coverByCat[c.cat] = thumbUrl(hit, 480);
    }
  }

  function cardHtml(item, i) {
    const sz = GRID_SZ();
    const isVid = item.tipo === 'video';
    const src = item.thumb_url || item.id ? thumbUrl(item, sz) : '';
    return `
      <article class="rcard${isVid ? ' is-video' : ''}" data-idx="${i}" data-id="${item.id}" tabindex="0" style="animation-delay:${Math.min(i % 24, 12) * 28}ms">
        ${
          src
            ? `<img class="rcard-thumb" src="${src}" alt="" loading="${i < 10 ? 'eager' : 'lazy'}" ${i < 6 ? 'fetchpriority="high"' : ''} decoding="async" onerror="this.onerror=null;this.closest('.rcard').classList.add('is-broken')"/>`
            : `<div class="rcard-ph" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="8.5" cy="10" r="1.6"/><path d="m21 15-5-4-9 7"/></svg></div>`
        }
        ${isVid ? '<span class="rcard-vid" aria-hidden="true"></span>' : ''}
      </article>`;
  }

  function bindCard(el) {
    el.addEventListener('click', () => openLightbox(parseInt(el.dataset.idx, 10)));
    el.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter') openLightbox(parseInt(el.dataset.idx, 10));
    });
  }

  function renderGrid(opts) {
    const append = !!(opts && opts.append);
    const from = append ? opts.from || 0 : 0;
    const chunk = state.items.slice(from);
    if (!append) {
      resGrid.innerHTML = state.items.map((item, i) => cardHtml(item, i)).join('');
      resGrid.querySelectorAll('.rcard').forEach(bindCard);
      return;
    }
    const wrap = document.createElement('div');
    wrap.innerHTML = chunk.map((item, i) => cardHtml(item, from + i)).join('');
    Array.from(wrap.children).forEach((el) => {
      bindCard(el);
      resGrid.appendChild(el);
    });
  }

  function updateLoadMore() {
    const hasMore = state.page < state.pages && state.items.length > 0;
    loadMoreWrap.classList.toggle('show', hasMore || state.loadingMore);
    const shown = state.items.length;
    if (lmProg) {
      lmProg.style.width = state.total ? `${Math.min(100, (shown / state.total) * 100)}%` : '0%';
    }
    if (lmStatus) {
      lmStatus.textContent = hasMore
        ? state.loadingMore
          ? 'Carregando mais…'
          : `Role para carregar · ${shown}/${state.total}`
        : shown
          ? 'Fim dos resultados'
          : '';
    }
    if (lmBtn) {
      lmBtn.hidden = !hasMore;
      if (lmCount) lmCount.textContent = hasMore ? `(${shown}/${state.total})` : '';
    }
  }

  function setupInfiniteScroll() {
    if (!scrollSentinel || io) return;
    io = new IntersectionObserver(
      (entries) => {
        const hit = entries.some((e) => e.isIntersecting);
        if (!hit || state.loadingMore) return;
        if (state.page >= state.pages) return;
        if (!state.items.length) return;
        state.page += 1;
        runSearch(false);
      },
      { root: null, rootMargin: '640px 0px', threshold: 0 }
    );
    io.observe(scrollSentinel);
  }

  async function runSearch(resetPage) {
    if (searchCtrl) searchCtrl.abort();
    const ctrl = new AbortController();
    searchCtrl = ctrl;
    if (resetPage) {
      state.page = 1;
      state.loadingMore = false;
    } else {
      state.loadingMore = true;
    }

    const qTrim = searchInput.value.trim();
    state.q = qTrim;

    if (resetPage && !state.items.length) setUiState('loading');
    setcamMsg(pick(CAM_SEARCH));
    if (loadingCamTxt) loadingCamTxt.textContent = pick(CAM_SEARCH);
    startCamSearch();
    updateLoadMore();

    try {
      const t0 = performance.now();
      const r = await api(`${API}/search?${buildParams(state.page)}`, { signal: ctrl.signal });
      const payload = await r.json();
      if (!r.ok || payload.status === 'error') throw new Error(payload.message || 'Erro na busca');
      console.debug('[search]', Math.round(performance.now() - t0) + 'ms', qTrim || '(browse)');

      const incoming = payload.items || [];
      state.total = payload.total || 0;
      state.pages = payload.pages || 1;
      state.page = payload.page || state.page;
      if (!qTrim && !state.tipo && !state.categoria && state.total) {
        state.archiveTotal = state.total;
        updateArchiveStat();
      }

      const prevLen = state.items.length;
      const added = mergeItems(incoming, !!resetPage);
      inferCovers(added.length ? added : state.items);

      if (searchCtrl === ctrl) stopCamSearch();
      state.loadingMore = false;

      if (!state.items.length) {
        setUiState('empty');
        renderEmptySugs();
        updateResultsMeta();
        updateLoadMore();
        setcamMsg('Nada nesse ângulo ainda. Tente outro filtro.');
        return;
      }

      setUiState('results');
      if (!resetPage && prevLen > 0) renderGrid({ append: true, from: prevLen });
      else renderGrid();
      updateResultsMeta();
      updateLoadMore();
      setcamMsg(pick(CAM_DONE), true);

      if (!qTrim && resetPage && state.page === 1) {
        try {
          sessionStorage.setItem(
            'aleff_browse_v3',
            JSON.stringify({
              t: Date.now(),
              items: state.items,
              total: state.total,
              pages: state.pages,
              page: state.page,
              archiveTotal: state.archiveTotal,
            })
          );
        } catch (_) {}
      }
      if (Object.keys(state.coverByCat).length) renderCatGrid(state._lastCatCounts || []);
    } catch (e) {
      if (e && e.name === 'AbortError') return;
      console.error(e);
      if (searchCtrl === ctrl) stopCamSearch();
      state.loadingMore = false;
      if (!state.items.length) {
        setUiState('empty');
        setcamMsg('Ops — conexão falhou. Tenta de novo?');
      }
      updateLoadMore();
      if (typeof Toast !== 'undefined') Toast.error('Erro na busca', e.message || 'Sem conexão.');
    }
  }

  function renderEmptySugs() {
    const el = $('emptySugs');
    if (!el) return;
    el.innerHTML = ['casamento', 'show', 'retrato', '2024', 'noiva']
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
    state._lastCatCounts = counts || [];
    const map = {};
    (counts || []).forEach((c) => {
      map[(c.categoria || '').toLowerCase()] = c.total;
    });
    const grid = $('catGrid');
    if (!grid) return;
    grid.innerHTML = CAT_CARDS.map((c, i) => {
      const n = map[c.cat] || 0;
      const cover = state.coverByCat[c.cat] || '';
      const active = state.categoria === c.cat ? ' is-active' : '';
      return `<button type="button" class="cat-btn${active}" style="--i:${i}" data-cat="${esc(c.cat)}" data-theme="${esc(c.theme || '')}" data-q="${esc(c.query || '')}">
        ${cover ? `<span class="cat-btn-cover" style="background-image:url('${cover}')"></span>` : ''}
        <span class="cat-btn-idx">${esc(c.mark)}</span>
        <span class="cat-btn-body">
          <span class="cat-btn-name">${esc(c.name)}</span>
          <span class="cat-btn-meta">${n ? n + ' no acervo' : 'Explorar'}</span>
        </span>
      </button>`;
    }).join('');

    grid.querySelectorAll('.cat-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        applyCategory(btn.dataset.cat, btn.dataset.theme);
        const q = btn.dataset.q || getCategoryQuery(btn.dataset.cat || '') || btn.dataset.cat || '';
        searchInput.value = q;
        state.q = q;
        state.activeTag = '';
        syncTags();
        updateClearBtn();
        syncPills();
        runSearch(true);
      });
    });
  }

  function renderPopTags(list) {
    const wrap = $('popTags');
    if (!wrap) return;
    wrap.innerHTML = (list || [])
      .slice(0, 24)
      .map((t) => `<button type="button" class="ptag${state.activeTag === t ? ' is-active' : ''}" data-q="${esc(t)}">${esc(t)}</button>`)
      .join('');
    wrap.querySelectorAll('.ptag').forEach((btn) => {
      btn.addEventListener('click', () => {
        const q = btn.dataset.q;
        state.activeTag = state.activeTag === q ? '' : q;
        searchInput.value = state.activeTag;
        updateClearBtn();
        syncTags();
        if (state.activeTag) runSearch(true);
        else {
          state.q = '';
          runSearch(true);
        }
      });
    });
  }

  function syncTags() {
    document.querySelectorAll('#popTags .ptag').forEach((t) => {
      t.classList.toggle('is-active', t.dataset.q === state.activeTag);
    });
  }

  function paintBrowsePayload(payload, msg) {
    state.q = '';
    state.page = payload.page || 1;
    state.pages = payload.pages || 1;
    state.total = payload.total || 0;
    if (payload.archiveTotal) state.archiveTotal = payload.archiveTotal;
    else if (state.total) state.archiveTotal = state.total;
    mergeItems(payload.items || [], true);
    inferCovers(state.items);
    updateArchiveStat();
    setUiState('results');
    renderGrid();
    updateResultsMeta();
    updateLoadMore();
    setcamMsg(msg || 'Acervo recente — digite pra filtrar.');
  }

  async function loadIdleData() {
    if (idleCtrl) idleCtrl.abort();
    idleCtrl = new AbortController();
    try {
      if (!searchInput.value.trim()) {
        try {
          const cached = JSON.parse(sessionStorage.getItem('aleff_browse_v3') || 'null');
          if (cached && Date.now() - cached.t < 60_000 && (cached.items || []).length) {
            paintBrowsePayload(cached, 'Acervo (cache) — atualizando…');
          }
        } catch (_) {}
      }

      const browseP = !searchInput.value.trim()
        ? api(`${API}/search?q=&per_page=${PER_PAGE}&page=1`, { signal: idleCtrl.signal })
        : null;
      const [statsRes, tagsRes, recentRes] = await Promise.allSettled([
        api(`${API}/search/stats`, { signal: idleCtrl.signal }),
        api(`${API}/tags`, { signal: idleCtrl.signal }),
        browseP || Promise.resolve(null),
      ]);

      const stats = statsRes.status === 'fulfilled' ? await statsRes.value.json() : {};
      const tags = tagsRes.status === 'fulfilled' ? await tagsRes.value.json() : {};
      renderCatGrid(stats.por_categoria || []);
      renderPopTags(tags.tags || []);

      if (recentRes.status === 'fulfilled' && recentRes.value) {
        const recent = recentRes.value;
        const payload = await recent.json();
        if (recent.ok && (payload.items || []).length) {
          paintBrowsePayload(payload);
          renderCatGrid(stats.por_categoria || []);
          try {
            sessionStorage.setItem(
              'aleff_browse_v3',
              JSON.stringify({
                t: Date.now(),
                items: state.items,
                total: state.total,
                pages: state.pages,
                page: state.page,
                archiveTotal: state.archiveTotal,
              })
            );
          } catch (_) {}
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
    document.querySelectorAll('#catGrid .cat-btn').forEach((b) => {
      b.classList.toggle('is-active', (b.dataset.cat || '') === state.categoria);
    });
  }

  /* Autocomplete */
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

  function focusAcRow() {
    siDrop.querySelectorAll('.ac-row').forEach((r, i) => {
      r.classList.toggle('focused', i === state.acIndex);
    });
  }

  /* Events */
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
      if (siDrop.classList.contains('open') && state.acIndex >= 0) chooseAc(state.acIndex);
      else {
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
    } else if (ev.key === 'Escape') siDrop.classList.remove('open');
  });

  siClear.addEventListener('click', () => {
    searchInput.value = '';
    state.q = '';
    state.activeTag = '';
    state.categoria = '';
    state.tipo = '';
    applyCategory('', '');
    syncPills();
    syncTags();
    updateClearBtn();
    siDrop.classList.remove('open');
    runSearch(true);
  });

  siSubmit.addEventListener('click', () => runSearch(true));

  siActions.querySelectorAll('.si-act').forEach((btn) => {
    btn.addEventListener('click', () => {
      const act = btn.dataset.act;
      btn.classList.add('si-act--pop');
      setTimeout(() => btn.classList.remove('si-act--pop'), 320);
      if (act === 'foto') state.tipo = 'image';
      else if (act === 'video') state.tipo = 'video';
      else if (act === 'recent') {
        state.sortRecent = true;
        if (!searchInput.value.trim()) searchInput.value = String(new Date().getFullYear());
      }
      syncPills();
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
      runSearch(true);
    });
  });

  document.querySelectorAll('#catPills .fpill').forEach((pill) => {
    pill.addEventListener('click', () => {
      const cat = pill.dataset.cat || '';
      applyCategory(cat, cat === 'casamento' ? 'casamento' : '');
      syncPills();
      if (!cat) {
        searchInput.value = '';
        state.q = '';
        state.activeTag = '';
        syncTags();
        updateClearBtn();
        runSearch(true);
        return;
      }
      const q = getCategoryQuery(cat) || cat;
      searchInput.value = q;
      state.q = q;
      updateClearBtn();
      runSearch(true);
    });
  });

  if (lmBtn) {
    lmBtn.addEventListener('click', () => {
      if (state.page >= state.pages || state.loadingMore) return;
      state.page += 1;
      runSearch(false);
    });
  }

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
  setupInfiniteScroll();
  (async () => {
    loadIdleData();
    if (initialQ) runSearch(true);
  })();
})();
