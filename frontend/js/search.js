/* search.js — Busca inteligente / Aleff Thiago Media System */
(function () {
  const API = '/api';

  const CAM_IDLE = [
    'Digite algo ou escolha uma categoria — o acervo responde na hora.',
    'Dica: nomes de pasta funcionam como busca de casal ou cliente.',
  ];
  const CAM_SEARCH = [
    'Câmera no ombro — vasculhando o acervo…',
    'Pulando entre pastas — quase no frame!',
    'Lente aberta: buscando tags e datas…',
    'Um clique, mil memórias — só um segundo.',
  ];
  const CAM_DONE = [
    'Clique! Resultados na tela.',
    'Frame encontrado.',
    'Acervo desbloqueado — achamos coisa boa.',
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
    return '';
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

    setUiState('loading');
    setcamMsg(pick(CAM_SEARCH));
    if (loadingCamTxt) loadingCamTxt.textContent = pick(CAM_SEARCH);
    camWrap?.classList.add('is-searching');
    document.querySelectorAll('.cam-wrap').forEach((el) => el.classList.add('is-searching'));

    try {
      const r = await api(`${API}/search?${buildParams(state.page)}`, { signal: ctrl.signal });
      const payload = await r.json();
      if (!r.ok || payload.status === 'error') throw new Error(payload.message || 'Erro na busca');

      const items = payload.items || [];
      state.total = payload.total || 0;
      state.pages = payload.pages || 1;
      state.page = payload.page || state.page;

      if (resetPage) state.items = items;
      else state.items = state.items.concat(items);

      resCount.innerHTML = state.total
        ? `<strong>${state.total.toLocaleString('pt-BR')}</strong> resultado${state.total === 1 ? '' : 's'}`
        : '';

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
      if (e && e.name === 'AbortError') return;
      console.error(e);
      setUiState('empty');
      setcamMsg('Ops — conexão falhou. Tenta de novo?');
      if (typeof Toast !== 'undefined') Toast.error('Erro na busca', e.message || 'Sem conexão.');
    } finally {
      if (searchCtrl === ctrl) {
        document.querySelectorAll('.cam-wrap').forEach((el) => {
          if (!el.classList.contains('cam-wrap--lg')) el.classList.remove('is-searching');
        });
        camWrap?.classList.remove('is-searching');
      }
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
            ? `<img class="rcard-thumb" src="${safeUrl(item.thumb_url)}" alt="${esc(displayName(item))}" loading="lazy" onerror="this.style.display='none'"/>`
            : `<div class="rcard-ph">${item.tipo === 'video' ? '▶' : '◻'}</div>`
        }
        <span class="rcard-badge-tipo">${item.tipo === 'video' ? 'vídeo' : 'foto'}</span>
        ${item.tipo === 'video' ? '<span class="rcard-vid"></span>' : ''}
        <div class="rcard-ov">
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

  /* ── Lightbox ─────────────────────────────────────── */
  const lb = $('lightbox');
  const lbFront = $('lbFront');
  let lbOpen = false;

  async function openLightbox(idx) {
    state.lbIndex = idx;
    const item = state.items[idx];
    if (!item) return;
    lbOpen = true;
    lb.classList.add('open');
    lb.setAttribute('aria-hidden', 'false');
    $('lbCard').classList.remove('flipped');
    $('lbTitle').textContent = displayName(item);
    $('lbMeta').textContent = [item.categoria, item.autor, item.data_upload].filter(Boolean).join(' · ');
    $('lbCtr').textContent = `${idx + 1} / ${state.items.length}`;
    $('lbDrive').href = item.drive_link || '#';

    lbFront.innerHTML = '<p style="color:#555">Carregando…</p>';
    try {
      const r = await api(`${API}/media/${item.id}`);
      const data = await r.json();
      const full = data.item || data.media || data;
      const url = full.drive_link || full.thumb_url || item.thumb_url;
      const label = (full.pasta || item.pasta || '').trim() || 'Sem pasta';
      if (full.tipo === 'video' && url) {
        lbFront.innerHTML = `<video src="${esc(url)}" controls autoplay playsinline style="max-width:100%;max-height:78vh;border-radius:14px"></video>`;
      } else if (url) {
        lbFront.innerHTML = `<img src="${esc(url)}" alt="${esc(label)}"/>`;
      } else {
        lbFront.innerHTML = `<p style="color:#666">Sem preview</p>`;
      }
      $('lbTitle').textContent = label;
      setTimeout(() => $('lbCard').classList.add('flipped'), 80);
    } catch {
      lbFront.innerHTML = `<p style="color:#e53e3e">Erro ao carregar mídia</p>`;
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
    lbFront.innerHTML = '';
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
