/* search.js — Acervo visual / Aleff Thiago */
(function () {
  const API = `${window.API_BASE_URL}/api`;
  const PER_PAGE = 36;
  const GRID_SZ = () => (window.matchMedia('(max-width:900px)').matches ? 420 : 560);
  const LB_SZ = 1200;

  const CAM_SEARCH = ['Buscando no acervo…', 'Procurando tags e datas…'];
  const CAM_DONE = ['Resultados na tela.', 'Busca concluída.'];

  const CAT_CARDS = [
    { cat: 'shows', mark: '01', name: 'Shows', query: 'show', keys: ['show', 'shows', 'palco'] },
    { cat: 'casamento', mark: '02', name: 'Casamento', theme: 'casamento', query: 'casamento', keys: ['casamento', 'noiva', 'noivo'] },
    { cat: 'retratos', mark: '03', name: 'Retratos', query: 'retrato', keys: ['retrato', 'retratos', 'close'] },
    { cat: 'casais', mark: '04', name: 'Casais', query: 'casal', keys: ['casal', 'casais', 'romantico'] },
    { cat: 'familia', mark: '05', name: 'Família', query: 'familia', keys: ['familia', 'familiar'] },
    { cat: 'infantil', mark: '06', name: 'Infantil', query: 'infantil', keys: ['infantil', 'crianca', 'bebe'] },
    { cat: 'ensaios', mark: '07', name: 'Ensaios', query: 'ensaio', keys: ['ensaio', 'ensaios', 'externo'] },
    { cat: 'editorial', mark: '08', name: 'Editorial', query: 'editorial', keys: ['editorial', 'moda', 'conceito'] },
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
    coverMeta: {},
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
  const pager = $('pager');
  const pagerPages = $('pagerPages');
  const pagerPrev = $('pagerPrev');
  const pagerNext = $('pagerNext');
  const pagerMeta = $('pagerMeta');
  const loadingCamTxt = $('loadingCamTxt');
  const archiveStat = $('archiveStat');
  const galleryKicker = $('galleryKicker');
  const galleryTitle = $('galleryTitle');
  const galleryMeta = $('galleryMeta');

  let searchCtrl = null;
  let searchGen = 0;
  let acCtrl = null;
  let idleCtrl = null;
  let liveSearchTimer = null;
  let renderToken = 0;
  let masonryColsCached = 0;
  let masonryResizeTimer = 0;
  let masonryRo = null;

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
    if (/^\/api\/media\/\d+\/thumb(?:-small|-medium|-cover)?(?:\?.*)?$/i.test(v)) return esc(v);
    if (/^\/api\/media\/\d+\/download(?:\?.*)?$/i.test(v)) return esc(v);
    return '';
  }

  /* ── Image pipeline: small → medium → HD (dedupe + prefetch) ── */
  const imgInflight = new Map(); // url → Promise
  let prefetchPaused = false;
  let prefetchActive = 0;
  const PREFETCH_MAX = 16;
  const prefetchQueue = [];
  const prefetchSeen = new Set();
  let upgradeObserver = null;
  const browserWarmReady = new Set(); // ids já no cache do browser

  function connectionIsSlow() {
    try {
      const c = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
      if (!c) return false;
      if (c.saveData) return true;
      const t = String(c.effectiveType || '');
      return t === '2g' || t === 'slow-2g';
    } catch (_) {
      return false;
    }
  }

  function loadImageOnce(url) {
    const u = String(url || '');
    if (!u) return Promise.reject(new Error('empty'));
    if (imgInflight.has(u)) return imgInflight.get(u);
    const p = new Promise((resolve, reject) => {
      const im = new Image();
      im.decoding = 'async';
      im.onload = () => resolve(u);
      im.onerror = () => {
        imgInflight.delete(u);
        reject(new Error('img fail'));
      };
      im.referrerPolicy = 'no-referrer';
      im.src = u;
    });
    imgInflight.set(u, p);
    return p;
  }

  function enqueuePrefetch(urls, opts) {
    const burst = !!(opts && opts.burst);
    if (connectionIsSlow() && !burst) return;
    for (const u of urls || []) {
      const url = String(u || '');
      if (!url || prefetchSeen.has(url)) continue;
      prefetchSeen.add(url);
      prefetchQueue.push(url);
    }
    pumpPrefetch(burst ? 24 : PREFETCH_MAX);
  }

  function pumpPrefetch(maxOverride) {
    if (prefetchPaused) return;
    const max = maxOverride || (connectionIsSlow() ? 2 : PREFETCH_MAX);
    while (prefetchActive < max && prefetchQueue.length) {
      const url = prefetchQueue.shift();
      prefetchActive += 1;
      loadImageOnce(url)
        .then(() => {
          const m = String(url).match(/\/api\/media\/(\d+)\/thumb-/);
          if (m) browserWarmReady.add(Number(m[1]));
        })
        .catch(() => {})
        .finally(() => {
          prefetchActive -= 1;
          if (!prefetchPaused) pumpPrefetch(maxOverride);
        });
    }
  }

  function pausePrefetch() {
    prefetchPaused = true;
  }

  function resumePrefetch() {
    prefetchPaused = false;
    pumpPrefetch(PREFETCH_MAX);
  }

  async function startBackgroundPrefetch() {
    // Warm em disco exige login (anti-DoS). Anônimo: prefetch browser + ensure sob demanda.
    try {
      if (typeof Auth !== 'undefined' && Auth.me) {
        const me = await Auth.me();
        if (me && me.logged_in) {
          api(`${API}/thumbs/warm?limit=240&workers=4`).catch(() => {});
        }
      }
    } catch (_) {}

    try {
      const r = await api(`${API}/thumbs/prefetch-plan?limit=240`);
      if (!r.ok) return;
      const data = await r.json();
      const urls = data.urls || (data.ids || []).map((id) => `${API}/media/${id}/thumb-medium`);
      if (urls.length) {
        enqueuePrefetch(urls, { burst: true });
        console.debug('[thumbs] pré-cache browser', urls.length, 'ready_server', data.ready_medium);
      }
    } catch (_) {}
  }

  function thumbSmallUrl(item) {
    if (!item) return '';
    if (item.tipo === 'video') return thumbUrlLegacy(item, 420);
    const s = String(item.thumb_small || '');
    if (/^\/api\/media\/\d+\/thumb-small/i.test(s)) return s;
    if (/^\/api\/local\//i.test(s)) return s;
    if (item.id) return `${API}/media/${item.id}/thumb-small`;
    return thumbUrlLegacy(item, 320);
  }

  function thumbMediumUrl(item) {
    if (!item) return '';
    if (item.tipo === 'video') return thumbUrlLegacy(item, GRID_SZ());
    const s = String(item.thumb_medium || '');
    if (/^\/api\/media\/\d+\/thumb-medium/i.test(s)) return s;
    if (/^\/api\/local\//i.test(s)) return s;
    if (item.id) return `${API}/media/${item.id}/thumb-medium`;
    return thumbUrlLegacy(item, GRID_SZ());
  }

  function thumbUrlLegacy(item, size = 1200) {
    const raw = String(item?.thumb_url || '');
    if (/^\/api\/local\//i.test(raw)) return safeUrl(raw) || '';
    if (/^https:\/\/drive\.google\.com\/thumbnail\?/i.test(raw)) {
      const did = String(item?.drive_id || '').trim();
      if (did && !did.startsWith('local:')) {
        return `https://drive.google.com/thumbnail?id=${encodeURIComponent(did)}&sz=w${size}`;
      }
    }
    const drive = String(item?.thumb_drive || '');
    if (/^https:\/\/drive\.google\.com\/thumbnail\?/i.test(drive)) {
      const did = String(item?.drive_id || '').trim();
      if (did) return `https://drive.google.com/thumbnail?id=${encodeURIComponent(did)}&sz=w${size}`;
    }
    const proxy = String(item?.thumb_proxy || '');
    if (/^\/api\/media\/\d+\/thumb/i.test(proxy)) {
      return proxy.includes('sz=') ? proxy.replace(/([?&]sz=)\d+/i, `$1${size}`) : `${proxy}${proxy.includes('?') ? '&' : '?'}sz=${size}`;
    }
    if (item?.id) return `${API}/media/${item.id}/thumb?sz=${size}`;
    return raw;
  }

  function thumbUrl(item, size = 1200) {
    // Compat: size baixo → small; alto → medium
    if (size <= 400) return thumbSmallUrl(item) || thumbUrlLegacy(item, size);
    if (size <= 1000) return thumbMediumUrl(item) || thumbUrlLegacy(item, size);
    return thumbUrlLegacy(item, size);
  }

  function thumbFallback(item, size = 560) {
    // 1) proxy clássico (JPEG legado em data/thumbs) — renderiza mesmo sem WebP
    if (item?.id) return `${API}/media/${item.id}/thumb?sz=${size}`;
    const drive = String(item?.thumb_drive || '');
    if (/^https:\/\/drive\.google\.com\/thumbnail\?/i.test(drive) || item?.drive_id) {
      const did = String(item?.drive_id || '').trim();
      if (did && !did.startsWith('local:')) {
        return `https://drive.google.com/thumbnail?id=${encodeURIComponent(did)}&sz=w${size}`;
      }
    }
    return thumbUrlLegacy(item, size);
  }

  function observeThumbUpgrades(root) {
    if (!('IntersectionObserver' in window)) {
      // Fallback: upgrade imediato medium
      (root || resGrid).querySelectorAll('img.rcard-thumb[data-medium]').forEach((img) => {
        upgradeThumb(img);
      });
      return;
    }
    if (upgradeObserver) upgradeObserver.disconnect();
    upgradeObserver = new IntersectionObserver(
      (entries) => {
        entries.forEach((en) => {
          if (!en.isIntersecting) return;
          upgradeThumb(en.target);
          upgradeObserver.unobserve(en.target);
        });
      },
      { root: null, rootMargin: '400px 0px', threshold: 0.01 }
    );
    (root || resGrid).querySelectorAll('img.rcard-thumb[data-medium]').forEach((img) => {
      upgradeObserver.observe(img);
    });
  }

  function upgradeThumb(img) {
    if (!img || img.dataset.upgraded === '1') return;
    const med = img.getAttribute('data-medium') || '';
    if (!med || med === img.getAttribute('src')) {
      img.dataset.upgraded = '1';
      return;
    }
    loadImageOnce(med)
      .then((url) => {
        if (img.getAttribute('src') === url) return;
        img.src = url;
        img.classList.add('is-upgraded');
        img.dataset.upgraded = '1';
      })
      .catch(() => {
        img.dataset.upgraded = '1';
      });
  }

  function mediaStreamUrl(item) {
    if (!item) return '';
    const thumb = String(item.thumb_url || '');
    // Vídeo local: stream via /api/local (público só para video/)
    if (/^\/api\/local\/[a-f0-9]+$/i.test(thumb) && item.tipo === 'video') return thumb;
    if (/^(\/?videos\/)/i.test(thumb)) return thumb;
    if (item.tipo === 'video' && item.id) return `${API}/media/${item.id}/download?dl=0`;
    return safeUrl(thumb);
  }

  function fullImageUrl(item) {
    if (!item) return '';
    // Lightbox público: thumb-medium (original HD só com login / download autenticado)
    return thumbMediumUrl(item) || safeUrl(item.thumb_url);
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
    // drive_link não vem mais no card público
    $('lbDrive').href = item.drive_link || '#';
    $('lbDrive').style.display = item.drive_link ? '' : 'none';

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
        if (r.status === 401) {
          throw new Error('Download do original exige login da galeria.');
        }
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

  const CAM_FINISH_MS = 320;
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
    // Sempre melhores fotos (home), exceto botão Recentes
    p.set('sort', state.sortRecent ? 'recent' : 'home');
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
      } else {
        const pageLabel = state.pages > 1
          ? ` · página ${state.page} de ${state.pages}`
          : '';
        if (q || state.tipo || state.categoria) {
          galleryMeta.innerHTML = total
            ? `<strong>${total.toLocaleString('pt-BR')}</strong> encontradas · ${shown.toLocaleString('pt-BR')} nesta página${pageLabel}`
            : `${shown} na tela${pageLabel}`;
        } else {
          galleryMeta.innerHTML = total
            ? `Página <strong>${state.page}</strong> · ${shown.toLocaleString('pt-BR')} de <strong>${total.toLocaleString('pt-BR')}</strong>`
            : `${shown} na tela`;
        }
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
    // Só completa capa se o backend ainda não mandou — e exige pasta/tema coerente
    const usedPastas = new Set(
      Object.keys(state.coverByCat || {})
        .map((k) => String((state.coverMeta || {})[k]?.pasta || '').toLowerCase())
        .filter(Boolean)
    );
    const essayCats = new Set(['retratos', 'ensaios', 'editorial']);
    for (const c of CAT_CARDS) {
      if (state.coverByCat[c.cat]) continue;
      const hit = (pool || []).find((it) => {
        const pasta = String(it.pasta || '').toLowerCase();
        const cat = String(it.categoria || '').toLowerCase();
        if (essayCats.has(c.cat) && pasta && usedPastas.has(pasta)) return false;
        if (c.cat === 'infantil') {
          return cat === 'infantil' || /\banos\b|anivers|infantil|bebe|bebê|crianca/.test(pasta);
        }
        if (c.cat === 'shows') {
          return /show|sonata|palco|bastidor|halloween|haloween|gameplay|banda/.test(pasta);
        }
        if (c.cat === 'casamento' || c.cat === 'casais') {
          return /&|\be\b/.test(pasta) || cat === c.cat;
        }
        if (c.cat === 'familia') return cat === 'familia' || /familia|batismo/.test(pasta);
        if (c.cat === 'editorial') {
          return cat === 'editorial' || /editorial|moda|conceito/.test(pasta);
        }
        if (c.cat === 'ensaios') {
          return cat === 'ensaios' || cat === 'ensaio' || /ensaio/.test(pasta);
        }
        if (c.cat === 'retratos') {
          return cat.indexOf('retrato') >= 0 || /retrato|close|estudio/.test(pasta);
        }
        return false;
      });
      if (hit) {
        state.coverByCat[c.cat] = thumbSmallUrl(hit) || thumbUrl(hit, 320);
        if (hit.pasta) usedPastas.add(String(hit.pasta).toLowerCase());
      }
    }
  }

  function cardHtml(item, i) {
    const isVid = item.tipo === 'video';
    // Página atual: medium direto (qualidade boa) — tudo dispara junto
    const src = isVid
      ? (thumbSmallUrl(item) || thumbUrlLegacy(item, 420))
      : (thumbMediumUrl(item) || thumbSmallUrl(item) || thumbUrlLegacy(item, GRID_SZ()));
    const fb = thumbFallback(item, GRID_SZ());
    const w = parseInt(item.width, 10) || 0;
    const h = parseInt(item.height, 10) || 0;
    // Reserva espaço com proporção original (evita layout shift / buracos)
    const ratioStyle = w > 0 && h > 0 ? ` style="aspect-ratio:${w}/${h}"` : '';
    const wh = w > 0 && h > 0 ? ` width="${w}" height="${h}"` : '';
    const lazy = i < 8 ? 'eager' : 'lazy';
    const onerr = fb
      ? ` onerror="this.onerror=function(){this.onerror=null;var c=this.closest('.rcard');if(c)c.classList.add('is-broken')};this.src='${String(fb).replace(/'/g, '%27')}'"`
      : ` onerror="this.onerror=null;this.closest('.rcard').classList.add('is-broken')"`;
    return `
      <article class="rcard${isVid ? ' is-video' : ''}" data-idx="${i}" data-id="${item.id}" tabindex="0"${ratioStyle}>
        ${
          src
            ? `<img class="rcard-thumb" src="${esc(src)}" alt="" loading="${lazy}" decoding="async" fetchpriority="${i < 6 ? 'high' : 'auto'}" referrerpolicy="no-referrer"${wh}${onerr}/>`
            : `<div class="rcard-ph" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="8.5" cy="10" r="1.6"/><path d="m21 15-5-4-9 7"/></svg></div>`
        }
        ${isVid ? '<span class="rcard-vid" aria-hidden="true"></span>' : ''}
      </article>`;
  }

  function masonryColCount() {
    const section = $('gallerySection');
    if (section) {
      const raw = getComputedStyle(section).getPropertyValue('--gallery-cols').trim();
      const n = parseInt(raw, 10);
      if (n >= 1 && n <= 6) return n;
    }
    const w = (resGrid && resGrid.clientWidth) || window.innerWidth;
    if (w < 650) return 2;
    if (w < 900) return 2;
    if (w < 1200) return 3;
    return 4;
  }

  function masonryGapPx() {
    const section = $('gallerySection');
    if (section) {
      const raw = getComputedStyle(section).getPropertyValue('--gallery-gap').trim();
      const n = parseFloat(raw);
      if (Number.isFinite(n)) return n;
    }
    return 10;
  }

  function estimateCardHeight(item, colW) {
    const w = parseInt(item.width, 10) || 0;
    const h = parseInt(item.height, 10) || 0;
    if (w > 0 && h > 0 && colW > 0) return colW * (h / w);
    // fallback seguro (retrato médio)
    return colW * 1.25;
  }

  function skeletonHtml(n) {
    const cols = masonryColCount();
    const total = Math.max(cols * 2, n || 12);
    const buckets = Array.from({ length: cols }, () => []);
    const shapes = ['tall', '', 'wide', '', 'tall', ''];
    for (let i = 0; i < total; i++) {
      const shape = shapes[i % shapes.length];
      buckets[i % cols].push(
        `<div class="sk-card${shape ? ' ' + shape : ''}"><div class="sk-sh"></div></div>`
      );
    }
    return buckets
      .map((cards) => `<div class="sk-col">${cards.join('')}</div>`)
      .join('');
  }

  function bindCard(el) {
    el.addEventListener('click', () => openLightbox(parseInt(el.dataset.idx, 10)));
    el.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter') openLightbox(parseInt(el.dataset.idx, 10));
    });
  }

  /**
   * Masonry real: N colunas independentes; cada item vai para a coluna mais baixa.
   * Ordem da API preservada (distribuição sequencial).
   */
  function renderGrid() {
    const token = ++renderToken;
    const items = state.items;
    if (!resGrid) return;
    resGrid.innerHTML = '';
    if (!items.length) {
      masonryColsCached = 0;
      return;
    }

    const colsN = masonryColCount();
    const gap = masonryGapPx();
    masonryColsCached = colsN;

    const colEls = [];
    const heights = [];
    for (let c = 0; c < colsN; c++) {
      const col = document.createElement('div');
      col.className = 'res-col';
      resGrid.appendChild(col);
      colEls.push(col);
      heights.push(0);
    }

    const gridW = resGrid.clientWidth || (resGrid.parentElement && resGrid.parentElement.clientWidth) || 0;
    const colW = colsN > 0 ? Math.max(80, (gridW - gap * (colsN - 1)) / colsN) : 240;
    const fragCols = colEls.map(() => document.createDocumentFragment());

    // Plano de masonry do warmup (mesma largura/cols) — evita recalcular do zero
    let warmAssign = null;
    try {
      if (typeof SearchWarmup !== 'undefined' && SearchWarmup.peekInitial) {
        const peek = SearchWarmup.peekInitial();
        const m = peek && peek.pack && peek.pack.masonry;
        if (peek && peek.viewportOk && m && m.cols === colsN && Array.isArray(m.assignment)) {
          warmAssign = m.assignment;
        }
      }
    } catch (_) {}

    items.forEach((item, i) => {
      let shortest = 0;
      if (warmAssign && warmAssign[i] != null && warmAssign[i] >= 0 && warmAssign[i] < colsN) {
        shortest = warmAssign[i];
      } else {
        for (let c = 1; c < colsN; c++) {
          if (heights[c] < heights[shortest]) shortest = c;
        }
      }
      const wrap = document.createElement('div');
      wrap.innerHTML = cardHtml(item, i).trim();
      const el = wrap.firstElementChild;
      if (!el) return;
      el.classList.add('rcard--enter');
      el.style.setProperty('--enter-i', String(Math.min(i, 12)));
      fragCols[shortest].appendChild(el);
      heights[shortest] += estimateCardHeight(item, colW) + gap;
    });

    fragCols.forEach((frag, i) => colEls[i].appendChild(frag));
    resGrid.querySelectorAll('.rcard').forEach((el) => bindCard(el));

    if (token !== renderToken) return;
    enqueuePrefetch(
      items.map((it) => thumbMediumUrl(it) || thumbSmallUrl(it)).filter(Boolean),
      { burst: true }
    );
  }

  function ensureMasonryObserver() {
    if (!resGrid || masonryRo || typeof ResizeObserver === 'undefined') return;
    masonryRo = new ResizeObserver(() => {
      if (!state.items.length) return;
      const next = masonryColCount();
      if (next === masonryColsCached) return;
      clearTimeout(masonryResizeTimer);
      masonryResizeTimer = setTimeout(() => {
        requestAnimationFrame(() => {
          if (!state.items.length) return;
          if (masonryColCount() === masonryColsCached) return;
          renderGrid();
        });
      }, 120);
    });
    masonryRo.observe(resGrid);
  }

  function pageWindow(current, total, maxButtons) {
    const max = Math.max(5, maxButtons || 7);
    const pages = Math.max(1, total || 1);
    const cur = Math.min(Math.max(1, current || 1), pages);
    if (pages <= max) {
      return Array.from({ length: pages }, (_, i) => i + 1);
    }
    const out = [];
    const side = Math.floor((max - 3) / 2);
    let start = Math.max(2, cur - side);
    let end = Math.min(pages - 1, cur + side);
    if (cur - 1 <= side + 1) {
      end = Math.min(pages - 1, max - 1);
      start = 2;
    }
    if (pages - cur <= side + 1) {
      start = Math.max(2, pages - (max - 2));
      end = pages - 1;
    }
    out.push(1);
    if (start > 2) out.push('…');
    for (let p = start; p <= end; p++) out.push(p);
    if (end < pages - 1) out.push('…');
    out.push(pages);
    return out;
  }

  function updatePager() {
    if (!pager) return;
    const pages = Math.max(1, state.pages || 1);
    const page = Math.min(Math.max(1, state.page || 1), pages);
    const show = pages > 1 && (state.items.length > 0 || state.loadingMore);
    pager.hidden = !show;
    if (!show) return;

    if (pagerPrev) pagerPrev.disabled = page <= 1 || state.loadingMore;
    if (pagerNext) pagerNext.disabled = page >= pages || state.loadingMore;

    if (pagerPages) {
      const win = pageWindow(page, pages, 7);
      pagerPages.innerHTML = win
        .map((p) => {
          if (p === '…') return '<span class="pager-gap" aria-hidden="true">…</span>';
          const on = p === page ? ' is-active active' : '';
          const busy = state.loadingMore ? ' disabled' : '';
          return `<button type="button" class="pager-num fbtn${on}" data-page="${p}" role="listitem" aria-label="Página ${p}"${p === page ? ' aria-current="page"' : ''}${busy}>${p}</button>`;
        })
        .join('');
      pagerPages.querySelectorAll('.pager-num').forEach((btn) => {
        btn.addEventListener('click', () => {
          if (btn.disabled || state.loadingMore) return;
          goToPage(parseInt(btn.dataset.page, 10));
        });
      });
    }

    if (pagerMeta) {
      const shown = state.items.length;
      const total = state.total || 0;
      pagerMeta.textContent = total
        ? `Página ${page} de ${pages} · ${shown} nesta página · ${total.toLocaleString('pt-BR')} no total`
        : `Página ${page} de ${pages}`;
    }
  }

  function goToPage(n) {
    const pages = Math.max(1, state.pages || 1);
    const next = Math.min(Math.max(1, parseInt(n, 10) || 1), pages);
    if (state.loadingMore) return;
    if (next === state.page) return;
    state.page = next;
    runSearch(false, { pageNav: true });
  }

  function scrollToResults() {
    const anchor = $('galleryTitle') || $('stResults') || resGrid;
    if (!anchor) return;
    const y = anchor.getBoundingClientRect().top + window.scrollY - 72;
    window.scrollTo({ top: Math.max(0, y), behavior: 'smooth' });
  }

  async function runSearch(resetPage, opts) {
    const live = !!(opts && opts.live);
    const pageNav = !!(opts && opts.pageNav);
    // Pesquisa tem prioridade sobre prefetch de background
    pausePrefetch();
    try {
      if (typeof SearchWarmup !== 'undefined' && SearchWarmup.pause) SearchWarmup.pause();
    } catch (_) {}
    if (searchCtrl) searchCtrl.abort();
    const ctrl = new AbortController();
    searchCtrl = ctrl;
    const gen = ++searchGen;
    if (resetPage) {
      state.page = 1;
      state.loadingMore = false;
    } else if (pageNav) {
      state.loadingMore = true;
    }

    const qTrim = searchInput.value.trim();
    state.q = qTrim;

    const cacheKey = queryCacheKey();
    let servedFromCache = false;
    try {
      if (typeof SearchWarmup !== 'undefined' && SearchWarmup.readQuery) {
        const hit = SearchWarmup.readQuery(cacheKey);
        if (hit && hit.payload && (hit.payload.items || []).length) {
          const payload = hit.payload;
          const incoming = payload.items || [];
          state.total = payload.total || 0;
          state.pages = payload.pages || 1;
          state.page = payload.page || state.page;
          if (payload.archive_total) state.archiveTotal = payload.archive_total;
          mergeItems(incoming, true);
          setUiState('results');
          renderGrid();
          updateResultsMeta();
          updatePager();
          setcamMsg(hit.stale ? 'Resultados (cache) — atualizando…' : pick(CAM_DONE), !hit.stale);
          servedFromCache = true;
          // SWR: continua fetch abaixo sem skeleton
        }
      }
    } catch (_) {}

    const keepGrid =
      live ||
      servedFromCache ||
      (resetPage && state.items.length > 0 && !pageNav);
    if ((resetPage || pageNav) && !keepGrid) {
      // Na troca de página, mantém #stResults (e o pager) visíveis
      if (pageNav) {
        setUiState('results');
        if (pager) pager.hidden = false;
      } else {
        setUiState('loading');
      }
      if (resGrid) resGrid.innerHTML = skeletonHtml(12);
    }
    if (!live && !servedFromCache) {
      setcamMsg(pick(CAM_SEARCH));
      if (loadingCamTxt) loadingCamTxt.textContent = pick(CAM_SEARCH);
      startCamSearch();
    }
    updatePager();

    try {
      const t0 = performance.now();
      const r = await api(`${API}/search?${buildParams(state.page)}`, { signal: ctrl.signal });
      const payload = await r.json();
      if (gen !== searchGen || searchCtrl !== ctrl) return;
      if (!r.ok || payload.status === 'error') throw new Error(payload.message || 'Erro na busca');
      console.debug('[search]', Math.round(performance.now() - t0) + 'ms', qTrim || '(browse)', payload.mode || '', payload.timing || '');
      try {
        if (typeof SearchWarmup !== 'undefined' && SearchWarmup.cacheQuery) {
          SearchWarmup.cacheQuery(cacheKey, payload);
        }
      } catch (_) {}

      const incoming = payload.items || [];
      state.total = payload.total || 0;
      state.pages = payload.pages || 1;
      state.page = payload.page || state.page;
      if (payload.archive_total) {
        state.archiveTotal = payload.archive_total;
        updateArchiveStat();
      } else if (!qTrim && !state.tipo && !state.categoria && state.total) {
        state.archiveTotal = state.total;
        updateArchiveStat();
      }

      // Sempre substitui a página (não acumula como “carregar mais”)
      mergeItems(incoming, true);
      inferCovers(state.items);

      if (searchCtrl === ctrl && !live) stopCamSearch();
      state.loadingMore = false;
      resumePrefetch();

      if (!state.items.length) {
        // Página fora do pool (cache antigo / race) → volta pra última válida
        if (pageNav && state.pages > 1 && state.page > 1) {
          state.page = Math.min(state.page - 1, state.pages);
          runSearch(false, { pageNav: true });
          return;
        }
        setUiState('empty');
        renderEmptySugs();
        updateResultsMeta();
        updatePager();
        setcamMsg('Nada nesse ângulo ainda. Tente outro filtro.');
        return;
      }

      setUiState('results');
      renderGrid();
      updateResultsMeta();
      updatePager();
      if (pageNav) scrollToResults();
      if (!live) setcamMsg(pick(CAM_DONE), true);
      try {
        if (typeof SearchWarmup !== 'undefined' && SearchWarmup.resume) SearchWarmup.resume();
      } catch (_) {}

      if (!qTrim && resetPage && state.page === 1) {
        try {
          sessionStorage.setItem(
            'aleff_browse_v4',
            JSON.stringify({
              t: Date.now(),
              items: state.items,
              total: state.total,
              pages: state.pages,
              page: state.page,
              archiveTotal: state.archiveTotal,
              mode: payload.mode || 'home',
            })
          );
        } catch (_) {}
      }
      if (Object.keys(state.coverByCat).length) renderCatGrid(state._lastCatCounts || []);
    } catch (e) {
      if (e && e.name === 'AbortError') return;
      if (gen !== searchGen) return;
      console.error(e);
      if (searchCtrl === ctrl && !live) stopCamSearch();
      state.loadingMore = false;
      resumePrefetch();
      if (!state.items.length) {
        setUiState('empty');
        setcamMsg('Ops — conexão falhou. Tenta de novo?');
      }
      updatePager();
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
      const cover = safeUrl(state.coverByCat[c.cat] || '') || '';
      const coverCss = cover ? cover.replace(/'/g, '%27').replace(/"/g, '%22') : '';
      const active = state.categoria === c.cat ? ' is-active' : '';
      return `<button type="button" class="cat-btn${active}" style="--i:${i}" data-cat="${esc(c.cat)}" data-theme="${esc(c.theme || '')}" data-q="${esc(c.query || '')}">
        ${coverCss ? `<span class="cat-btn-cover" style="background-image:url('${coverCss}')" aria-hidden="true"></span>` : ''}
        <span class="cat-btn-idx">${esc(c.mark)}</span>
        <span class="cat-btn-body">
          <span class="cat-btn-name">${esc(c.name)}</span>
          <span class="cat-btn-meta">${n ? n + ' fotos' : 'Explorar'}</span>
        </span>
      </button>`;
    }).join('');

    grid.querySelectorAll('.cat-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        applyCategory(btn.dataset.cat, btn.dataset.theme);
        state.sortRecent = false;
        // Sem q: backend usa pool da categoria (ranking completo)
        searchInput.value = '';
        state.q = '';
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

  let hydratedFromWarmup = false;

  function applyCoversFromStats(covers) {
    if (!covers || typeof covers !== 'object') return;
    Object.keys(covers).forEach((cat) => {
      const c = covers[cat];
      if (!c) return;
      const u = c.thumb_cover || c.thumb_url || c.thumb_medium || c.thumb_small || '';
      if (u) state.coverByCat[cat] = u;
      state.coverMeta[cat] = {
        id: c.id,
        pasta: c.pasta || '',
        face_x: c.face_x,
        face_y: c.face_y,
      };
      if (!safeUrl(state.coverByCat[cat] || '') && c.id) {
        state.coverByCat[cat] = `${API}/media/${c.id}/thumb-cover`;
      }
    });
  }

  function itemsFingerprint(items) {
    return (items || []).map((it) => it && it.id).join(',');
  }

  function paintBrowsePayload(payload, msg, opts) {
    const skipGrid = !!(opts && opts.skipGrid);
    const skipIfSame = !!(opts && opts.skipIfSame);
    state.q = '';
    state.page = payload.page || 1;
    state.pages = payload.pages || 1;
    state.total = payload.total || 0;
    if (payload.archive_total || payload.archiveTotal) {
      state.archiveTotal = payload.archive_total || payload.archiveTotal;
    } else if (state.total) {
      state.archiveTotal = state.total;
    }
    const incoming = payload.items || [];
    const domFp = resGrid
      ? [...resGrid.querySelectorAll('.rcard')].map((el) => el.dataset.id).join(',')
      : '';
    const same =
      skipIfSame &&
      !!domFp &&
      itemsFingerprint(incoming) === domFp;

    mergeItems(incoming, true);
    inferCovers(state.items);
    updateArchiveStat();
    setUiState('results');
    if (!skipGrid && !same) {
      renderGrid();
    } else if (skipGrid || same) {
      // Adota DOM já pintado — só rebind / índices
      resGrid.querySelectorAll('.rcard').forEach((el, i) => {
        el.dataset.idx = String(i);
        if (!el.dataset.bound) {
          bindCard(el);
          el.dataset.bound = '1';
        }
      });
      masonryColsCached = masonryColCount();
    }
    updateResultsMeta();
    updatePager();
    setcamMsg(msg || 'Destaques do acervo — digite pra filtrar.');
  }

  /** Adota paint síncrono do bootstrap (gridHtml) — sem remontar cards. */
  function adoptBootPaint(pack, msg) {
    if (!pack || !pack.browse || !(pack.browse.items || []).length) return false;
    if (!resGrid || !resGrid.querySelector('.rcard')) return false;

    applyCoversFromStats(pack.stats && pack.stats.covers);
    if (pack.stats && pack.stats.por_categoria) renderCatGrid(pack.stats.por_categoria);
    if (pack.tags) renderPopTags(pack.tags);

    paintBrowsePayload(
      {
        items: pack.browse.items,
        total: pack.browse.total,
        pages: pack.browse.pages,
        page: pack.browse.page,
        archive_total: pack.browse.archiveTotal,
        mode: pack.browse.mode,
      },
      msg || 'Melhores do acervo — digite pra filtrar.',
      { skipGrid: true }
    );

    // Libera estágio offscreen da Home se ainda existir (mesma sessão / bfcache raro)
    try {
      if (typeof SearchWarmup !== 'undefined' && SearchWarmup.clearOffscreenStage) {
        SearchWarmup.clearOffscreenStage();
      }
    } catch (_) {}
    return true;
  }

  /** Hydrate síncrono a partir do SearchWarmup (Home). */
  function hydrateFromWarmup() {
    const t0 = performance.now();
    const boot = window.__searchWarmBoot;

    // 1) Swap: DOM já pintado pelo bootstrap inline
    if (boot && boot.painted && boot.pack) {
      const ok = adoptBootPaint(
        boot.pack,
        boot.pack && Date.now() - boot.pack.preparedAt > 70_000
          ? 'Acervo (cache) — atualizando…'
          : 'Melhores do acervo — digite pra filtrar.'
      );
      if (ok) {
        hydratedFromWarmup = true;
        let navT = 0;
        try {
          navT =
            typeof SearchWarmup !== 'undefined' && SearchWarmup.takeNavMark
              ? SearchWarmup.takeNavMark()
              : 0;
        } catch (_) {}
        const openMs = navT ? Date.now() - navT : Math.round(performance.now() - t0);
        const paintMs = boot.paintMs != null ? boot.paintMs : openMs;
        console.debug('[search] SEARCH_OPEN_TO_VISIBLE', openMs + 'ms', 'bootPaint', paintMs + 'ms', 'adopt');
        try {
          if (window.__searchWarmup) {
            window.__searchWarmup.lastOpenMs = openMs;
            window.__searchWarmup.hydrated = true;
            window.__searchWarmup.metrics.search_swap_duration = openMs;
          }
        } catch (_) {}
        // evita reutilizar pack como se fosse fragment vivo
        try {
          window.__searchWarmBoot.pack = null;
        } catch (_) {}
        return true;
      }
    }

    let peek = null;
    try {
      if (typeof SearchWarmup !== 'undefined' && SearchWarmup.peekInitial) {
        peek = SearchWarmup.peekInitial();
      }
    } catch (_) {}

    if (!peek || !peek.pack) {
      try {
        const cached = JSON.parse(sessionStorage.getItem('aleff_browse_v4') || 'null');
        if (cached && Date.now() - cached.t < 90_000 && (cached.items || []).length) {
          paintBrowsePayload(cached, 'Acervo pronto — digite pra filtrar.');
          hydratedFromWarmup = true;
          return true;
        }
      } catch (_) {}
      return false;
    }

    const pack = peek.pack;
    // Se bootstrap pintou gridHtml, adopta; senão monta a partir dos dados
    if (pack.gridHtml && resGrid && !resGrid.querySelector('.rcard')) {
      resGrid.innerHTML = pack.gridHtml;
      setUiState('results');
    }

    if (resGrid && resGrid.querySelector('.rcard') && pack.gridHtml) {
      adoptBootPaint(
        pack,
        peek.stale ? 'Acervo (cache) — atualizando…' : 'Melhores do acervo — digite pra filtrar.'
      );
    } else {
      applyCoversFromStats(pack.stats && pack.stats.covers);
      if (pack.stats && pack.stats.por_categoria) renderCatGrid(pack.stats.por_categoria);
      if (pack.tags) renderPopTags(pack.tags);
      paintBrowsePayload(
        {
          items: pack.browse.items,
          total: pack.browse.total,
          pages: pack.browse.pages,
          page: pack.browse.page,
          archive_total: pack.browse.archiveTotal,
          mode: pack.browse.mode,
        },
        peek.stale ? 'Acervo (cache) — atualizando…' : 'Melhores do acervo — digite pra filtrar.'
      );
    }
    hydratedFromWarmup = true;

    let navT = 0;
    try {
      navT =
        typeof SearchWarmup !== 'undefined' && SearchWarmup.takeNavMark
          ? SearchWarmup.takeNavMark()
          : 0;
    } catch (_) {}
    const openMs = navT ? Date.now() - navT : Math.round(performance.now() - t0);
    console.debug(
      '[search] SEARCH_OPEN_TO_VISIBLE',
      openMs + 'ms',
      'warmup',
      peek.fresh ? 'fresh' : 'stale',
      'items',
      state.items.length
    );
    try {
      if (window.__searchWarmup) {
        window.__searchWarmup.lastOpenMs = openMs;
        window.__searchWarmup.hydrated = true;
        window.__searchWarmup.metrics.search_swap_duration = openMs;
      }
    } catch (_) {}
    return true;
  }

  function queryCacheKey() {
    return [
      'q=' + (searchInput.value.trim() || ''),
      'tipo=' + (state.tipo || ''),
      'cat=' + (state.apiCategoria || ''),
      'page=' + (state.page || 1),
      'sort=' + (state.sortRecent ? 'recent' : 'home'),
      'tag=' + (state.activeTag || ''),
    ].join('&');
  }

  async function loadIdleData() {
    if (idleCtrl) idleCtrl.abort();
    idleCtrl = new AbortController();
    try {
      // Se já hidratou do warmup: não pinta skeleton — só SWR em background
      if (!hydratedFromWarmup && !searchInput.value.trim()) {
        try {
          const cached = JSON.parse(sessionStorage.getItem('aleff_browse_v4') || 'null');
          if (cached && Date.now() - cached.t < 60_000 && (cached.items || []).length) {
            paintBrowsePayload(cached, 'Acervo (cache) — atualizando…');
          }
        } catch (_) {}
      }

      // Pack fresco (<45s): não refetch browse no open — evita request duplicada
      let skipBrowse = false;
      if (hydratedFromWarmup && !searchInput.value.trim()) {
        try {
          const peek =
            typeof SearchWarmup !== 'undefined' && SearchWarmup.peekInitial
              ? SearchWarmup.peekInitial()
              : null;
          if (peek && peek.fresh && peek.pack && peek.pack.preparedAt) {
            skipBrowse = Date.now() - peek.pack.preparedAt < 45_000;
          }
        } catch (_) {}
      }

      const browseP =
        !searchInput.value.trim() && !skipBrowse
          ? api(`${API}/search?q=&per_page=${PER_PAGE}&page=1&sort=home`, { signal: idleCtrl.signal })
          : null;
      const [statsRes, tagsRes, recentRes] = await Promise.allSettled([
        api(`${API}/search/stats`, { signal: idleCtrl.signal }),
        api(`${API}/tags`, { signal: idleCtrl.signal }),
        browseP || Promise.resolve(null),
      ]);

      const stats = statsRes.status === 'fulfilled' ? await statsRes.value.json() : {};
      const tags = tagsRes.status === 'fulfilled' ? await tagsRes.value.json() : {};
      applyCoversFromStats(stats.covers);
      renderCatGrid(stats.por_categoria || []);
      renderPopTags(tags.tags || []);

      if (recentRes.status === 'fulfilled' && recentRes.value) {
        const recent = recentRes.value;
        const payload = await recent.json();
        if (recent.ok && (payload.items || []).length) {
          // SWR: se a grade já está correta, não remonta (evita flash)
          paintBrowsePayload(
            payload,
            payload.mode === 'home'
              ? 'Melhores do acervo — digite pra filtrar.'
              : 'Acervo recente — digite pra filtrar.',
            { skipIfSame: hydratedFromWarmup }
          );
          renderCatGrid(stats.por_categoria || []);
          try {
            sessionStorage.setItem(
              'aleff_browse_v4',
              JSON.stringify({
                t: Date.now(),
                items: payload.items,
                total: payload.total,
                pages: payload.pages,
                page: payload.page,
                archiveTotal: payload.archive_total || payload.total,
                mode: payload.mode || 'home',
              })
            );
          } catch (_) {}
          try {
            if (typeof SearchWarmup !== 'undefined' && SearchWarmup.cacheQuery) {
              SearchWarmup.cacheQuery('q=&page=1&sort=home', payload);
            }
          } catch (_) {}
        }
      }
    } catch (e) {
      if (e && e.name === 'AbortError') return;
      console.warn('Idle data', e);
      if (!hydratedFromWarmup) renderCatGrid([]);
    }
  }

  function applyCategory(cat, themeHint) {
    state.categoria = cat || '';
    // Categorias da grade → filtro tema no backend (pool maior / ranking certo)
    state.apiCategoria = cat || '';
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
          <span class="ac-ico">${esc((s.type || 'tag') === 'nome' ? 'N' : (s.type || 'tag').slice(0, 1).toUpperCase())}</span>
          <span class="ac-txt">${highlight(s.text, q)}</span>
          <span class="ac-kind">${esc(s.type === 'nome' ? 'nome' : s.type === 'pasta' ? 'nome' : s.type || '')}</span>
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
    clearTimeout(liveSearchTimer);
    const q = searchInput.value.trim();
    acTimer = setTimeout(() => fetchAutocomplete(q), 160);
    // Busca ao digitar — debounce ~300ms (evita flood)
    if (q.length >= 2) {
      liveSearchTimer = setTimeout(() => runSearch(true, { live: true }), 300);
    } else if (!q) {
      liveSearchTimer = setTimeout(() => runSearch(true, { live: true }), 220);
    }
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
      if (act === 'foto') {
        state.tipo = 'image';
        state.sortRecent = false;
      } else if (act === 'video') {
        state.tipo = 'video';
        state.sortRecent = false;
      } else if (act === 'recent') {
        state.sortRecent = true;
        state.q = '';
        searchInput.value = '';
        updateClearBtn();
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
      state.sortRecent = false;
      applyCategory(cat, cat === 'casamento' ? 'casamento' : '');
      syncPills();
      searchInput.value = '';
      state.q = '';
      state.activeTag = '';
      syncTags();
      updateClearBtn();
      runSearch(true);
    });
  });

  if (pagerPrev) {
    pagerPrev.addEventListener('click', () => goToPage(state.page - 1));
  }
  if (pagerNext) {
    pagerNext.addEventListener('click', () => goToPage(state.page + 1));
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

  /* Manter scroll após F5 (não voltar pro topo da busca) */
  const scrollKey = 'aleff_scroll:/search.html';
  const searchNav = performance.getEntriesByType?.('navigation')?.[0];
  const restoreSearchScroll = searchNav?.type === 'reload';
  try {
    if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
  } catch (_) {}
  let scrollSaveTimer = 0;
  const saveScroll = () => {
    try {
      sessionStorage.setItem(scrollKey, String(window.scrollY));
    } catch (_) {}
  };
  window.addEventListener(
    'scroll',
    () => {
      clearTimeout(scrollSaveTimer);
      scrollSaveTimer = setTimeout(saveScroll, 100);
    },
    { passive: true }
  );
  window.addEventListener('pagehide', saveScroll);
  const restoreScroll = () => {
    if (!restoreSearchScroll) return;
    try {
      const y = parseInt(sessionStorage.getItem(scrollKey) || '0', 10);
      if (y > 80) {
        document.documentElement.style.scrollBehavior = 'auto';
        window.scrollTo(0, y);
        document.documentElement.style.scrollBehavior = '';
      }
    } catch (_) {}
  };
  window.addEventListener('load', () => {
    restoreScroll();
    setTimeout(restoreScroll, 200);
    setTimeout(restoreScroll, 600);
  }, { once: true });

  updateClearBtn();
  updatePager();
  ensureMasonryObserver();

  /** Página 2: só metadados, após paint, rede ok, idle — não na Home. */
  function warmNextPageQuietly() {
    if (state.page !== 1 || state.pages < 2 || searchInput.value.trim()) return;
    try {
      const c = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
      if (c && (c.saveData || c.effectiveType === '2g' || c.effectiveType === 'slow-2g')) return;
    } catch (_) {}
    const key = 'q=&tipo=&cat=&page=2&sort=home&tag=';
    try {
      if (typeof SearchWarmup !== 'undefined' && SearchWarmup.readQuery) {
        const hit = SearchWarmup.readQuery(key);
        if (hit && hit.payload && !hit.stale) return;
      }
    } catch (_) {}
    const run = async () => {
      try {
        const r = await api(`${API}/search?q=&per_page=${PER_PAGE}&page=2&sort=home`);
        if (!r.ok) return;
        const payload = await r.json();
        if (payload && (payload.items || []).length && typeof SearchWarmup !== 'undefined' && SearchWarmup.cacheQuery) {
          SearchWarmup.cacheQuery(key, payload);
        }
      } catch (_) {}
    };
    if (typeof requestIdleCallback === 'function') {
      requestIdleCallback(() => run(), { timeout: 5000 });
    } else {
      setTimeout(run, 2000);
    }
  }

  // 1) Swap instantâneo se a Home já aqueceu a Pesquisa
  const painted = !initialQ && hydrateFromWarmup();

  // 2) Prefetch pesado (/thumbs/…) só depois — não compete com o paint
  const scheduleBgPrefetch = () => {
    if (typeof requestIdleCallback === 'function') {
      requestIdleCallback(() => startBackgroundPrefetch(), { timeout: 4000 });
    } else {
      setTimeout(() => startBackgroundPrefetch(), painted ? 1200 : 400);
    }
  };
  scheduleBgPrefetch();

  // 3) SWR / fallback normal
  (async () => {
    if (initialQ) {
      runSearch(true);
      return;
    }
    if (painted) {
      const revalidate = () => {
        loadIdleData();
        warmNextPageQuietly();
      };
      if (typeof requestIdleCallback === 'function') {
        requestIdleCallback(revalidate, { timeout: 2500 });
      } else {
        setTimeout(revalidate, 500);
      }
    } else {
      await loadIdleData();
      warmNextPageQuietly();
    }
  })();
})();
