/**
 * SearchWarmup — view de Pesquisa preparada (vanilla, sem 2º sistema).
 *
 * Home (após masonry + idle, pause na interação):
 *   /api/search?sort=home + stats/tags → gridHtml + plano masonry
 *   → sessionStorage (TTL 90s) → Image() P0/P1 (browser/nginx cache)
 *   Sem DOM pesado na Home.
 *
 * search.html:
 *   bootstrap síncrono injeta gridHtml → search.js ADOTA (bind, sem remontar)
 *   SWR em idle; página 2 só com usuário já na Pesquisa + rede ok.
 *
 * Prioridade: usuário > Home > warmup. AbortController + pause/resume.
 */
(function () {
  'use strict';

  const API = '/api';
  const PER_PAGE = 36;
  const CACHE_KEY = 'aleff_search_warmup_v1';
  const QUERY_CACHE_KEY = 'aleff_search_qcache_v1';
  const NAV_MARK_KEY = 'aleff_search_nav_t';
  const TTL_MS = 90_000;
  const QUERY_TTL_MS = 90_000;
  const PREFETCH_CONCURRENCY = 3;
  const PACK_VERSION = 3;

  const STATUS = {
    NOT_STARTED: 'not_started',
    WARMING: 'warming',
    READY: 'ready',
    STALE: 'stale',
    FAILED: 'failed',
  };

  const metrics = {
    warmup_started: 0,
    warmup_ready: 0,
    warmup_failed: 0,
    warmup_duration: 0,
    thumbnail_prefetch_count: 0,
    cache_hit: 0,
    cache_miss: 0,
    search_swap_duration: 0,
    dom_cards: 0,
  };

  const state = {
    status: STATUS.NOT_STARTED,
    startedAt: null,
    readyAt: null,
    resultCount: 0,
    paused: false,
    abort: null,
    fragment: null,
    stageEl: null,
    booted: false,
    thumbCtrl: null,
  };

  window.__searchWarmup = {
    get status() {
      return state.status;
    },
    get startedAt() {
      return state.startedAt;
    },
    get readyAt() {
      return state.readyAt;
    },
    get resultCount() {
      return state.resultCount;
    },
    metrics,
  };

  function idle(fn, timeout) {
    if (typeof requestIdleCallback === 'function') {
      return requestIdleCallback(fn, { timeout: timeout || 2200 });
    }
    return setTimeout(() => fn({ timeRemaining: () => 16, didTimeout: true }), 500);
  }

  function connectionBudget() {
    try {
      const c = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
      if (!c) return { slow: false, saveData: false, maxThumbs: 20 };
      if (c.saveData) return { slow: true, saveData: true, maxThumbs: 6 };
      const t = String(c.effectiveType || '');
      if (t === '2g' || t === 'slow-2g') return { slow: true, saveData: false, maxThumbs: 6 };
      if (t === '3g') return { slow: true, saveData: false, maxThumbs: 10 };
      return { slow: false, saveData: false, maxThumbs: 20 };
    } catch (_) {
      return { slow: false, saveData: false, maxThumbs: 20 };
    }
  }

  function estimateCols(vw) {
    const w = vw || window.innerWidth || 1200;
    if (w < 900) return 2;
    if (w < 1200) return 3;
    return 4;
  }

  function estimateCardHeight(item, colW) {
    const w = parseInt(item.width, 10) || 0;
    const h = parseInt(item.height, 10) || 0;
    if (w > 0 && h > 0 && colW > 0) return colW * (h / w);
    return colW * 1.25;
  }

  function planMasonry(items, cols, viewportW) {
    const gap = 10;
    const pad = 48;
    const gridW = Math.max(280, (viewportW || window.innerWidth) - pad);
    const colW = cols > 0 ? Math.max(80, (gridW - gap * (cols - 1)) / cols) : 240;
    const heights = Array.from({ length: cols }, () => 0);
    const assignment = [];
    (items || []).forEach((item) => {
      let shortest = 0;
      for (let c = 1; c < cols; c++) {
        if (heights[c] < heights[shortest]) shortest = c;
      }
      assignment.push(shortest);
      heights[shortest] += estimateCardHeight(item, colW) + gap;
    });
    return {
      cols,
      gap,
      colW,
      gridW,
      assignment,
      heights,
      gridHeight: heights.length ? Math.max(...heights) : 0,
    };
  }

  function esc(s) {
    return String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function safeThumb(url) {
    const v = String(url || '');
    if (/^https:\/\/(drive\.google\.com|[\w.-]*googleusercontent\.com)\b/i.test(v)) return esc(v);
    if (/^(\/?fotos\/|\/?videos\/)/i.test(v)) return esc(v);
    if (/^\/api\/media\/\d+\/thumb(?:-small|-medium|-cover)?(?:\?.*)?$/i.test(v)) return esc(v);
    return '';
  }

  function thumbUrl(item, tier) {
    if (!item || !item.id) return '';
    if (item.tipo === 'video') {
      const s = String(item.thumb_small || item.thumb_url || '');
      return s.startsWith('/') || s.startsWith('http') ? s : '';
    }
    if (tier === 'medium') {
      return item.thumb_medium || `/api/media/${item.id}/thumb-medium`;
    }
    return item.thumb_small || `/api/media/${item.id}/thumb-small`;
  }

  function coverUrl(c) {
    if (!c) return '';
    return c.thumb_cover || c.thumb_url || c.thumb_medium || c.thumb_small || '';
  }

  /** HTML de card alinhado a search.js (cardHtml) — small no warmup, medium no 1º viewport. */
  function cardHtml(item, i, preferMedium) {
    const isVid = item.tipo === 'video';
    const raw = isVid
      ? thumbUrl(item, 'small')
      : preferMedium
        ? thumbUrl(item, 'medium') || thumbUrl(item, 'small')
        : thumbUrl(item, 'small') || thumbUrl(item, 'medium');
    const src = safeThumb(raw);
    const w = parseInt(item.width, 10) || 0;
    const h = parseInt(item.height, 10) || 0;
    const ratioStyle = w > 0 && h > 0 ? ` style="aspect-ratio:${w}/${h}"` : '';
    const wh = w > 0 && h > 0 ? ` width="${w}" height="${h}"` : '';
    const lazy = i < 8 ? 'eager' : 'lazy';
    return (
      `<article class="rcard${isVid ? ' is-video' : ''}" data-idx="${i}" data-id="${item.id}" tabindex="0"${ratioStyle}>` +
      (src
        ? `<img class="rcard-thumb" src="${src}" alt="" loading="${lazy}" decoding="async" fetchpriority="${i < 6 ? 'high' : 'auto'}" referrerpolicy="no-referrer"${wh}/>`
        : `<div class="rcard-ph" aria-hidden="true"></div>`) +
      (isVid ? '<span class="rcard-vid" aria-hidden="true"></span>' : '') +
      `</article>`
    );
  }

  /** DOM pré-renderizado: N colunas .res-col (mesmo modelo do search.js). */
  function buildGridHtml(items, masonry) {
    const cols = (masonry && masonry.cols) || estimateCols();
    const assign = (masonry && masonry.assignment) || [];
    const buckets = Array.from({ length: cols }, () => []);
    const firstViewport = cols * 3;
    (items || []).forEach((item, i) => {
      let c = assign[i];
      if (c == null || c < 0 || c >= cols) c = i % cols;
      buckets[c].push(cardHtml(item, i, i < firstViewport));
    });
    return buckets.map((cards) => `<div class="res-col">${cards.join('')}</div>`).join('');
  }

  function readPack() {
    try {
      const raw = sessionStorage.getItem(CACHE_KEY);
      if (!raw) return null;
      return JSON.parse(raw);
    } catch (_) {
      return null;
    }
  }

  function writePack(pack) {
    try {
      sessionStorage.setItem(CACHE_KEY, JSON.stringify(pack));
      return true;
    } catch (_) {
      try {
        const slim = { ...pack, gridHtml: null };
        sessionStorage.setItem(CACHE_KEY, JSON.stringify(slim));
        return true;
      } catch (_) {
        return false;
      }
    }
  }

  function isFresh(pack, ttl) {
    if (!pack || !pack.preparedAt) return false;
    return Date.now() - pack.preparedAt < (ttl || TTL_MS);
  }

  function isViewportOk(pack) {
    if (!pack || !pack.viewportW) return false;
    const dw = Math.abs((window.innerWidth || 0) - pack.viewportW);
    const cols = estimateCols();
    return dw < 120 && (!pack.masonry || pack.masonry.cols === cols);
  }

  function loadImage(url, signal) {
    return new Promise((resolve, reject) => {
      if (!url) {
        resolve(false);
        return;
      }
      if (signal && signal.aborted) {
        reject(new DOMException('aborted', 'AbortError'));
        return;
      }
      const img = new Image();
      const onAbort = () => {
        img.src = '';
        reject(new DOMException('aborted', 'AbortError'));
      };
      if (signal) signal.addEventListener('abort', onAbort, { once: true });
      img.onload = () => {
        if (signal) signal.removeEventListener('abort', onAbort);
        resolve(true);
      };
      img.onerror = () => {
        if (signal) signal.removeEventListener('abort', onAbort);
        resolve(false);
      };
      img.decoding = 'async';
      img.referrerPolicy = 'no-referrer';
      img.src = url;
    });
  }

  async function prefetchThumbs(urls, signal, concurrency) {
    const list = (urls || []).filter(Boolean);
    let i = 0;
    let ok = 0;
    async function worker() {
      while (i < list.length) {
        if (state.paused) {
          await new Promise((r) => setTimeout(r, 220));
          continue;
        }
        if (signal && signal.aborted) return;
        const idx = i++;
        const u = list[idx];
        try {
          if (await loadImage(u, signal)) ok += 1;
        } catch (e) {
          if (e && e.name === 'AbortError') return;
        }
      }
    }
    const n = Math.max(1, Math.min(concurrency || PREFETCH_CONCURRENCY, 4));
    await Promise.all(Array.from({ length: n }, () => worker()));
    metrics.thumbnail_prefetch_count += ok;
    return ok;
  }

  /**
   * Não montamos DOM pesado na Home (competia com a galeria).
   * O “DOM pronto” vive em sessionStorage.gridHtml → bootstrap da search.html.
   * Thumbs aquecem via Image() (browser/nginx cache), sem staging visual.
   */
  function clearOffscreenStage() {
    if (state.stageEl && state.stageEl.parentNode) {
      try {
        state.stageEl.parentNode.removeChild(state.stageEl);
      } catch (_) {}
    }
    state.stageEl = null;
    state.fragment = null;
    const orphan = document.getElementById('aleff-search-prerender');
    if (orphan && orphan.parentNode) {
      try {
        orphan.parentNode.removeChild(orphan);
      } catch (_) {}
    }
  }

  function markReady(pack, opts) {
    const fromCache = !!(opts && opts.fromCache);
    state.status = STATUS.READY;
    state.readyAt = fromCache ? pack.preparedAt || Date.now() : Date.now();
    state.resultCount = (pack.browse && pack.browse.items && pack.browse.items.length) || 0;
    if (!fromCache) {
      metrics.warmup_ready += 1;
      metrics.warmup_duration = state.startedAt ? Date.now() - state.startedAt : 0;
    }
    console.debug(
      '[SearchWarmup] READY',
      fromCache ? 'cache' : 'fresh',
      state.resultCount,
      'thumbsQueued',
      (pack.thumbUrls || []).length,
      (fromCache ? 0 : metrics.warmup_duration) + 'ms'
    );
  }

  function markNav() {
    try {
      sessionStorage.setItem(NAV_MARK_KEY, String(Date.now()));
    } catch (_) {}
    metrics.search_swap_duration = 0;
  }

  function bindNavHints() {
    document.querySelectorAll('a[href*="search.html"]').forEach((a) => {
      a.addEventListener(
        'pointerenter',
        () => {
          if (state.status !== STATUS.READY && state.status !== STATUS.WARMING) {
            idle(() => warm({ urgent: true }), 300);
          } else if (state.status === STATUS.READY) {
            // reforço leve de thumbs P1
            idle(() => {
              const pack = readPack();
              const urls = (pack && pack.thumbUrls) || [];
              if (urls.length) {
                const ctrl = new AbortController();
                prefetchThumbs(urls.slice(0, 8), ctrl.signal, 2);
              }
            }, 200);
          }
        },
        { once: true, passive: true }
      );
      a.addEventListener('click', markNav, { capture: true });
    });
  }

  function prefetchSearchAssets() {
    const assets = [
      { href: 'search.html', as: 'document' },
      { href: 'css/search.css?v=20260810cover2', as: 'style' },
      { href: 'js/search.js?v=20260810warm5', as: 'script' },
    ];
    assets.forEach(({ href, as }) => {
      if (document.querySelector(`link[data-search-warm="${href}"]`)) return;
      const l = document.createElement('link');
      l.rel = 'prefetch';
      l.href = href;
      if (as) l.as = as;
      l.dataset.searchWarm = href;
      document.head.appendChild(l);
    });
  }

  async function fetchJson(url, signal) {
    const r = await fetch(url, { credentials: 'same-origin', signal });
    if (!r.ok) throw new Error('http ' + r.status);
    return r.json();
  }

  async function warm(opts) {
    const urgent = !!(opts && opts.urgent);
    if (state.paused && !urgent) return;
    if (state.status === STATUS.WARMING) return;

    const existing = readPack();
    if (
      isFresh(existing) &&
      isViewportOk(existing) &&
      existing.browse &&
      (existing.browse.items || []).length &&
      existing.version === PACK_VERSION &&
      existing.gridHtml
    ) {
      metrics.cache_hit += 1;
      markReady(existing, { fromCache: true });
      idle(() => {
        const budget = connectionBudget();
        const urls = (existing.thumbUrls || []).slice(0, budget.maxThumbs);
        if (!urls.length) return;
        if (state.thumbCtrl) {
          try {
            state.thumbCtrl.abort();
          } catch (_) {}
        }
        const tCtrl = new AbortController();
        state.thumbCtrl = tCtrl;
        prefetchThumbs(urls, tCtrl.signal, budget.slow ? 2 : PREFETCH_CONCURRENCY);
      }, 600);
      return;
    }

    metrics.cache_miss += 1;
    state.status = STATUS.WARMING;
    state.startedAt = Date.now();
    metrics.warmup_started += 1;

    if (state.abort) {
      try {
        state.abort.abort();
      } catch (_) {}
    }
    if (state.thumbCtrl) {
      try {
        state.thumbCtrl.abort();
      } catch (_) {}
    }
    const ctrl = new AbortController();
    state.abort = ctrl;

    try {
      prefetchSearchAssets();
      const budget = connectionBudget();

      const [browse, stats, tags] = await Promise.all([
        fetchJson(`${API}/search?q=&per_page=${PER_PAGE}&page=1&sort=home`, ctrl.signal),
        fetchJson(`${API}/search/stats`, ctrl.signal),
        fetchJson(`${API}/tags`, ctrl.signal),
      ]);

      if (ctrl.signal.aborted) return;

      const items = browse.items || [];
      const vw = window.innerWidth || 1200;
      const cols = estimateCols(vw);
      const masonry = planMasonry(items, cols, vw);
      const gridHtml = buildGridHtml(items, masonry);
      metrics.dom_cards = items.length;

      const smallUrls = items.map((it) => thumbUrl(it, 'small')).filter(Boolean);
      const mediumFirst = items
        .slice(0, Math.min(items.length, cols * 3))
        .map((it) => thumbUrl(it, 'medium'))
        .filter(Boolean);
      const coverUrls = Object.values(stats.covers || {})
        .map(coverUrl)
        .filter(Boolean);

      const p0 = [];
      const pRest = [];
      const pushUnique = (arr, u) => {
        if (u && !p0.includes(u) && !pRest.includes(u) && !arr.includes(u)) arr.push(u);
      };
      // P0: capas + 1º viewport (small) — necessário pra SEARCH_READY “visível”
      coverUrls.forEach((u) => pushUnique(p0, u));
      smallUrls.slice(0, cols * 3).forEach((u) => pushUnique(p0, u));
      // P1: resto da página small
      smallUrls.slice(cols * 3, budget.maxThumbs).forEach((u) => pushUnique(pRest, u));
      // P2: medium do 1º viewport (só rede ok)
      if (!budget.slow) mediumFirst.slice(0, cols * 2).forEach((u) => pushUnique(pRest, u));

      const thumbUrls = p0.concat(pRest);

      const pack = {
        version: PACK_VERSION,
        status: STATUS.READY,
        preparedAt: Date.now(),
        ttl: TTL_MS,
        viewportW: vw,
        browse: {
          items,
          total: browse.total || items.length,
          pages: browse.pages || 1,
          page: browse.page || 1,
          archiveTotal: browse.archive_total || browse.total || items.length,
          mode: browse.mode || 'home',
        },
        stats: {
          por_categoria: stats.por_categoria || [],
          covers: stats.covers || {},
        },
        tags: tags.tags || [],
        masonry,
        gridHtml,
        thumbUrls,
      };

      writePack(pack);

      try {
        sessionStorage.setItem(
          'aleff_browse_v4',
          JSON.stringify({
            t: pack.preparedAt,
            items: pack.browse.items,
            total: pack.browse.total,
            pages: pack.browse.pages,
            page: pack.browse.page,
            archiveTotal: pack.browse.archiveTotal,
            mode: pack.browse.mode,
          })
        );
      } catch (_) {}

      // READY assim que dados + HTML existem (não espera fila inteira de thumbs)
      markReady(pack);
      cacheQuery('q=&page=1&sort=home', {
        items: pack.browse.items,
        total: pack.browse.total,
        pages: pack.browse.pages,
        page: pack.browse.page,
        archive_total: pack.browse.archiveTotal,
        mode: pack.browse.mode,
      });

      // Thumbs em background — Home continua prioridade via pause()
      const tCtrl = new AbortController();
      state.thumbCtrl = tCtrl;
      const conc = budget.slow ? 2 : PREFETCH_CONCURRENCY;
      // P0 primeiro (await curto), depois resto sem bloquear status
      prefetchThumbs(p0, tCtrl.signal, conc)
        .then(() => {
          if (tCtrl.signal.aborted || state.paused) return;
          return prefetchThumbs(pRest, tCtrl.signal, conc);
        })
        .catch(() => {});

      // Página 2 NÃO na Home — só quando o usuário já está em search.html (ver search.js)
    } catch (e) {
      if (e && e.name === 'AbortError') return;
      state.status = STATUS.FAILED;
      metrics.warmup_failed += 1;
      console.warn('[SearchWarmup] failed', e);
    }
  }

  function pause() {
    state.paused = true;
  }

  function resume() {
    state.paused = false;
    if (state.status !== STATUS.READY && state.status !== STATUS.WARMING) {
      idle(() => warm(), 800);
    }
  }

  function invalidate(reason) {
    state.status = STATUS.STALE;
    clearOffscreenStage();
    if (state.thumbCtrl) {
      try {
        state.thumbCtrl.abort();
      } catch (_) {}
      state.thumbCtrl = null;
    }
    try {
      sessionStorage.removeItem(CACHE_KEY);
    } catch (_) {}
    console.debug('[SearchWarmup] invalidate', reason || '');
  }

  function peekInitial() {
    const pack = readPack();
    if (!pack || !(pack.browse && (pack.browse.items || []).length)) return null;
    const fresh = isFresh(pack);
    const vpOk = isViewportOk(pack);
    return { pack, fresh, viewportOk: vpOk, stale: !fresh };
  }

  function getQueryCache() {
    try {
      return JSON.parse(sessionStorage.getItem(QUERY_CACHE_KEY) || '{}') || {};
    } catch (_) {
      return {};
    }
  }

  function setQueryCache(map) {
    try {
      sessionStorage.setItem(QUERY_CACHE_KEY, JSON.stringify(map));
    } catch (_) {}
  }

  function cacheQuery(key, payload) {
    if (!key || !payload) return;
    const map = getQueryCache();
    map[key] = { t: Date.now(), payload };
    Object.keys(map).forEach((k) => {
      if (!map[k] || Date.now() - (map[k].t || 0) > QUERY_TTL_MS * 2) delete map[k];
    });
    setQueryCache(map);
  }

  function readQuery(key) {
    const map = getQueryCache();
    const hit = map[key];
    if (!hit || !hit.payload) return null;
    if (Date.now() - (hit.t || 0) > QUERY_TTL_MS) {
      return { payload: hit.payload, stale: true };
    }
    return { payload: hit.payload, stale: false };
  }

  function takeNavMark() {
    try {
      const t = parseInt(sessionStorage.getItem(NAV_MARK_KEY) || '0', 10);
      sessionStorage.removeItem(NAV_MARK_KEY);
      return t || 0;
    } catch (_) {
      return 0;
    }
  }

  function boot(opts) {
    // search.html só lê cache — não boot
    const path = (location.pathname || '').toLowerCase();
    if (/search\.html$/.test(path) || path.endsWith('/search')) return;

    const afterHome = !!(opts && opts.afterHome);

    if (!state.booted) {
      state.booted = true;
      bindNavHints();

      let interactTimer = 0;
      const onInteract = () => {
        pause();
        clearTimeout(interactTimer);
        interactTimer = setTimeout(resume, 1000);
      };
      ['pointerdown', 'wheel', 'keydown', 'touchstart'].forEach((ev) => {
        window.addEventListener(ev, onInteract, { passive: true });
      });

      document.addEventListener('visibilitychange', () => {
        if (document.hidden) pause();
        else resume();
      });

      let resizeTimer = 0;
      window.addEventListener(
        'resize',
        () => {
          clearTimeout(resizeTimer);
          resizeTimer = setTimeout(() => {
            const pack = readPack();
            if (pack && !isViewportOk(pack)) {
              invalidate('resize');
              idle(() => warm(), 700);
            }
          }, 280);
        },
        { passive: true }
      );

      window.addEventListener(
        'pagehide',
        () => {
          clearOffscreenStage();
          if (state.thumbCtrl) {
            try {
              state.thumbCtrl.abort();
            } catch (_) {}
          }
        },
        { once: true }
      );
    }

    // main.js já esperou masonry da Home → idle curto; senão espera load
    if (afterHome) {
      idle(() => warm(), 280);
      return;
    }
    const start = () => idle(() => warm(), 1200);
    if (document.readyState === 'complete') start();
    else window.addEventListener('load', () => setTimeout(start, 200), { once: true });
  }

  window.SearchWarmup = {
    STATUS,
    boot,
    warm,
    pause,
    resume,
    invalidate,
    peekInitial,
    readPack,
    cacheQuery,
    readQuery,
    takeNavMark,
    markNav,
    planMasonry,
    estimateCols,
    buildGridHtml,
    clearOffscreenStage,
    metrics,
    getState: () => ({ ...state, status: state.status }),
  };
})();
