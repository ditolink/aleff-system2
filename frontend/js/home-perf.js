/* home-perf.js — responsive thumbs + lightbox sob demanda (Home)
   Sem IA no browser. Depende de data-media-id nos tiles. */
(() => {
  'use strict';

  const API_SMALL = (id) => `${window.API_BASE_URL}/api/media/${id}/thumb-small`;
  const API_MED = (id) => `${window.API_BASE_URL}/api/media/${id}/thumb-medium`;

  function sizesFor(gi) {
    if (!gi) return '(max-width: 768px) 48vw, 22vw';
    if (gi.classList.contains('l-hero')) return '100vw';
    if (gi.classList.contains('l-wide') || gi.classList.contains('v-wide')) {
      return '(max-width: 768px) 100vw, (max-width: 1100px) 66vw, 48vw';
    }
    return '(max-width: 768px) 48vw, (max-width: 1100px) 30vw, 22vw';
  }

  /** Wire srcset/sizes on curated Home tiles (keeps local src as fallback). */
  function enhanceGalleryThumbs() {
    const root = document.getElementById('galeriaTrabalhos');
    if (!root) return;
    root.querySelectorAll('.gi[data-media-id] img').forEach((img, i) => {
      const gi = img.closest('.gi');
      const id = Number.parseInt(gi?.dataset.mediaId || '', 10);
      if (!Number.isFinite(id) || id <= 0) return;
      // Barbara local lock — keep PNG, still add medium API as optional denser source
      const local = img.getAttribute('src') || '';
      const small = API_SMALL(id);
      const med = API_MED(id);
      const srcset = local.includes('foto_barbara')
        ? `${med} 800w, ${local} 1200w`
        : `${small} 320w, ${med} 800w, ${local} 1200w`;
      img.setAttribute('srcset', srcset);
      img.setAttribute('sizes', sizesFor(gi));
      img.decoding = 'async';
      // First row after hero: eager; rest lazy
      if (i < 2 && !gi.classList.contains('l-hero')) {
        img.loading = 'eager';
        img.fetchPriority = 'low';
      } else if (!gi.classList.contains('l-hero')) {
        img.loading = 'lazy';
      }
    });
  }

  function warmUrl(url) {
    if (!url || !window.Image) return;
    try {
      const im = new Image();
      im.decoding = 'async';
      im.src = url;
    } catch { /* ignore */ }
  }

  /** Soft-prefetch only neighbors when lightbox opens. */
  function wireLightboxPrefetch() {
    const lb = document.getElementById('lightbox');
    if (!lb || lb.dataset.perfLb === '1') return;
    lb.dataset.perfLb = '1';
    const obs = new MutationObserver(() => {
      if (!lb.classList.contains('open')) return;
      const ctr = document.getElementById('lbCounter')?.textContent || '';
      const m = ctr.match(/(\d+)\s*\/\s*(\d+)/);
      if (!m) return;
      const idx = Number(m[1]) - 1;
      const total = Number(m[2]);
      if (!Number.isFinite(idx) || total < 2) return;
      const prev = (idx - 1 + total) % total;
      const next = (idx + 1) % total;
      document.querySelectorAll('#galeriaTrabalhos .gi[data-idx], #galeriaVideos .gi[data-idx]').forEach((gi) => {
        const i = Number.parseInt(gi.dataset.idx || '', 10);
        if (i !== prev && i !== next) return;
        const mid = Number.parseInt(gi.dataset.mediaId || '', 10);
        if (Number.isFinite(mid) && mid > 0) warmUrl(API_MED(mid));
        else {
          const img = gi.querySelector('img');
          if (img?.currentSrc || img?.src) warmUrl(img.currentSrc || img.src);
        }
      });
    });
    obs.observe(lb, { attributes: true, attributeFilter: ['class'] });
  }

  function boot() {
    enhanceGalleryThumbs();
    wireLightboxPrefetch();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }
})();
