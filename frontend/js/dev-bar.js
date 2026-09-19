/* studio-bar — toolbar da equipe + sessão no portfólio */
(() => {
  const API = `${window.API_BASE_URL}/api`;

  /* English labels — clear studio navigation */
  const STUDIO_LINKS = [
    { href: '/index.html', label: 'Site', home: true },
    { href: '/dashboard.html', label: 'Dashboard' },
    { href: '/upload.html', label: 'Upload' },
    { href: '/admin.html', label: 'Gallery' },
    { href: '/slots.html', label: 'Slots' },
    { href: '/search.html', label: 'Search' },
  ];

  /* Só DEV — admin nunca vê estes links */
  const DEV_ONLY_LINKS = [
    { href: '/settings.html', label: 'Config' },
    { href: '/code.html', label: 'Code' },
  ];

  const PREF_KEY = 'aleffDevPrefs';

  function readDevPrefs() {
    try {
      return JSON.parse(localStorage.getItem(PREF_KEY) || '{}') || {};
    } catch {
      return {};
    }
  }

    async function me() {
    if (typeof Auth !== 'undefined' && Auth.me) {
      try { return await Auth.me(); } catch { /* fallback */ }
    }
    try {
      const r = await fetch(`${API}/auth/me`, {
        credentials: 'same-origin',
        cache: 'no-store',
      });
      if (!r.ok) {
        try {
          const sticky = JSON.parse(localStorage.getItem('authMeSticky') || 'null');
          if (sticky?.data?.logged_in) return { ...sticky.data, offline: true };
        } catch { /* ignore */ }
        return { logged_in: false, offline: true };
      }
      return await r.json();
    } catch {
      try {
        const sticky = JSON.parse(localStorage.getItem('authMeSticky') || 'null');
        if (sticky?.data?.logged_in) return { ...sticky.data, offline: true };
      } catch { /* ignore */ }
      return { logged_in: false, offline: true };
    }
  }

  async function doLogout() {
    try {
      if (typeof Auth !== 'undefined' && Auth.logout) {
        await Auth.logout();
      } else {
        await fetch(`${API}/auth/logout`, {
          method: 'POST',
          credentials: 'same-origin',
        });
      }
    } catch { /* ignore */ }
    try {
      sessionStorage.removeItem('studioStatusCache');
      sessionStorage.removeItem('authMeCache');
      localStorage.removeItem('authMeSticky');
    } catch { /* ignore */ }
  }

  async function switchAccount() {
    await doLogout();
    if (typeof Auth !== 'undefined' && Auth.flashLoggedOut) Auth.flashLoggedOut();
    else {
      try {
        sessionStorage.setItem('authFlash', JSON.stringify({
          type: 'success',
          title: 'Sessão apagada',
          message: 'Você saiu da conta.',
        }));
      } catch { /* ignore */ }
    }
    location.href = '/loginsite.html?apagado=1';
  }

  async function signOut() {
    if (typeof Auth !== 'undefined' && Auth.logoutToLogin) {
      await Auth.logoutToLogin();
      return;
    }
    await doLogout();
    try {
      sessionStorage.setItem('authFlash', JSON.stringify({
        type: 'success',
        title: 'Sessão apagada',
        message: 'Você saiu da conta.',
      }));
    } catch { /* ignore */ }
    location.href = '/loginsite.html?apagado=1';
  }

  function el(tag, attrs = {}) {
    const n = document.createElement(tag);
    Object.entries(attrs).forEach(([k, v]) => {
      if (v == null || v === false) return;
      if (k === 'className') n.className = v;
      else if (k === 'text') n.textContent = v;
      else if (k === 'html') n.innerHTML = v;
      else if (k === 'onClick') n.addEventListener('click', v);
      else n.setAttribute(k, v);
    });
    return n;
  }

  function go(href, e) {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    window.location.assign(href);
  }

  function prefetch(href) {
    if (!href || document.querySelector(`link[data-studio-prefetch="${href}"]`)) return;
    const l = document.createElement('link');
    l.rel = 'prefetch';
    l.as = 'document';
    l.href = href;
    l.dataset.studioPrefetch = href;
    document.head.appendChild(l);
  }

  function warmStudioPages(extra = []) {
    [...STUDIO_LINKS, ...extra].forEach((item) => prefetch(item.href));
  }

  function isActive(href) {
    const path = (location.pathname || '').toLowerCase();
    const target = href.toLowerCase();
    if (target === '/index.html') {
      return path === '/' || path.endsWith('/index.html') || path === '';
    }
    return path.endsWith(target) || path.endsWith(target.replace('.html', ''));
  }

  function link(href, label, extraClass = '') {
    const cls = ['dev-link', extraClass, isActive(href) ? 'is-active' : '']
      .filter(Boolean)
      .join(' ');
    const a = el('a', {
      className: cls,
      href,
      text: label,
      onClick: (e) => go(href, e),
    });
    a.addEventListener('pointerenter', () => prefetch(href), { once: true });
    return a;
  }

  function accountBlock(user, roleLabel) {
    const wrap = el('div', { className: 'studio-account' });
    const meta = el('div', { className: 'studio-user' });
    meta.appendChild(el('span', { className: 'studio-user-name', text: user || 'equipe' }));
    meta.appendChild(el('span', { className: 'studio-user-role', text: roleLabel }));
    wrap.appendChild(meta);
    wrap.appendChild(el('button', {
      className: 'studio-btn studio-btn--switch',
      type: 'button',
      html: '<span class="lbl-full">Switch</span><span class="lbl-short">Switch</span>',
      title: 'Sign out and use another account',
      onClick: (e) => {
        e.preventDefault();
        switchAccount();
      },
    }));
    wrap.appendChild(el('button', {
      className: 'studio-btn studio-btn--out',
      type: 'button',
      text: 'Logout',
      onClick: (e) => {
        e.preventDefault();
        signOut();
      },
    }));
    return wrap;
  }

  function buildStudioNav(includeDev = false) {
    const nav = el('div', { className: 'dev-bar-nav' });
    STUDIO_LINKS.forEach((item, i) => {
      if (i === 1) nav.appendChild(el('span', { className: 'dev-bar-sep' }));
      nav.appendChild(link(item.href, item.label, item.home ? 'dev-link--home' : ''));
    });
    if (includeDev) {
      nav.appendChild(el('span', { className: 'dev-bar-sep' }));
      DEV_ONLY_LINKS.forEach((item) => {
        nav.appendChild(link(item.href, item.label, 'dev-link--dev'));
      });
    }
    return nav;
  }

  function buildAdminBar(user) {
    const bar = el('div', {
      className: 'dev-bar admin-bar',
      id: 'devBar',
      role: 'navigation',
      'aria-label': 'Admin toolbar',
    });

    const chip = el('span', { className: 'studio-chip' });
    chip.appendChild(el('span', { className: 'studio-chip-dot', 'aria-hidden': 'true' }));
    chip.appendChild(document.createTextNode('Admin'));
    bar.appendChild(chip);

    bar.appendChild(buildStudioNav(false));
    bar.appendChild(accountBlock(user || 'admin', 'Admin'));

    document.body.prepend(bar);
    document.body.classList.add('has-dev-bar');
    warmStudioPages();
  }

  function buildDevBar(user) {
    const bar = el('div', {
      className: 'dev-bar',
      id: 'devBar',
      role: 'navigation',
      'aria-label': 'Dev toolbar',
    });

    const chip = el('span', { className: 'studio-chip' });
    chip.appendChild(el('span', { className: 'studio-chip-dot', 'aria-hidden': 'true' }));
    chip.appendChild(document.createTextNode('Dev'));
    bar.appendChild(chip);

    bar.appendChild(buildStudioNav(true));

    const prefs = readDevPrefs();
    if (prefs.statusPills !== false) {
      const status = el('div', { className: 'dev-status', title: 'System status' });
      status.appendChild(el('a', {
        className: 'dev-link',
        id: 'devDrivePill',
        href: '/settings.html',
        'data-state': '',
        html: '<span class="dot"></span><span class="txt">Drive…</span>',
        onClick: (e) => go('/settings.html', e),
      }));
      status.appendChild(el('a', {
        className: 'dev-link',
        id: 'devClipPill',
        href: '/settings.html',
        'data-state': '',
        html: '<span class="dot"></span><span class="txt">CLIP…</span>',
        onClick: (e) => go('/settings.html', e),
      }));
      bar.appendChild(status);
    }

    bar.appendChild(accountBlock(user || 'dev', 'Dev'));

    document.body.prepend(bar);
    document.body.classList.add('has-dev-bar');
    warmStudioPages(DEV_ONLY_LINKS);
  }

  function hideLoginButtons() {
    document.body.classList.add('is-logged-in');
    document.querySelectorAll('#navLoginBtn, a[href="loginsite.html"].nav-search-btn, a[href="loginsite.html"].back-btn')
      .forEach((node) => {
        if (node && /entrar/i.test(node.textContent || '')) node.hidden = true;
      });
  }

  function injectPublicSession(user, role, isDev) {
    hideLoginButtons();

    const host =
      document.querySelector('.nav-right') ||
      document.querySelector('.search-nav') ||
      document.querySelector('.site-nav');
    if (!host || document.getElementById('navSession')) return;

    const wrap = el('div', {
      className: `nav-session${role === 'admin' && !isDev ? ' is-admin' : ''}`,
      id: 'navSession',
    });

    const meta = el('div', { className: 'nav-session-meta' });
    meta.appendChild(el('span', {
      className: 'nav-session-role',
      text: isDev ? 'Dev' : (role === 'admin' ? 'Admin' : 'Team'),
    }));
    meta.appendChild(el('span', {
      className: 'nav-session-user',
      text: user || 'team',
    }));
    wrap.appendChild(meta);

    wrap.appendChild(el('a', {
      className: 'studio-btn',
      href: '/dashboard.html',
      html: '<span class="lbl-full">Dashboard</span><span class="lbl-short">Dash</span>',
      title: 'Open dashboard',
      onClick: (e) => go('/dashboard.html', e),
    }));

    wrap.appendChild(el('button', {
      className: 'studio-btn studio-btn--switch',
      type: 'button',
      html: '<span class="lbl-full">Switch</span><span class="lbl-short">Switch</span>',
      onClick: (e) => {
        e.preventDefault();
        switchAccount();
      },
    }));

    wrap.appendChild(el('button', {
      className: 'studio-btn studio-btn--out',
      id: 'navLogoutBtn',
      type: 'button',
      text: 'Logout',
      onClick: (e) => {
        e.preventDefault();
        signOut();
      },
    }));

    if (host.classList.contains('search-nav')) {
      const spacer = host.querySelector('.nav-spacer');
      const login = host.querySelector('#navLoginBtn, a.back-btn[href="loginsite.html"]');
      if (login) login.replaceWith(wrap);
      else if (spacer) spacer.replaceWith(wrap);
      else host.appendChild(wrap);
    } else {
      const login = host.querySelector('#navLoginBtn, a.nav-search-btn[href="loginsite.html"]');
      if (login) login.replaceWith(wrap);
      else host.appendChild(wrap);
    }
  }

  const STATUS_KEY = 'studioStatusCache';

  function readStatusCache() {
    try {
      const raw = sessionStorage.getItem(STATUS_KEY);
      if (!raw) return null;
      const data = JSON.parse(raw);
      if (!data || !data.at || (Date.now() - data.at) > 30000) return null;
      return data;
    } catch {
      return null;
    }
  }

  function writeStatusCache(partial) {
    try {
      let prev = {};
      try {
        prev = JSON.parse(sessionStorage.getItem(STATUS_KEY) || '{}') || {};
      } catch { /* ignore */ }
      sessionStorage.setItem(STATUS_KEY, JSON.stringify({
        ...prev,
        ...partial,
        at: Date.now(),
      }));
    } catch { /* ignore */ }
  }

  function applyStatus(driveState, driveTxt, clipState, clipTxt) {
    const drivePill = document.getElementById('devDrivePill');
    const clipPill = document.getElementById('devClipPill');
    if (drivePill && driveState) {
      drivePill.dataset.state = driveState;
      const t = drivePill.querySelector('.txt');
      if (t && driveTxt) t.textContent = driveTxt;
    }
    if (clipPill && clipState) {
      clipPill.dataset.state = clipState;
      const t = clipPill.querySelector('.txt');
      if (t && clipTxt) t.textContent = clipTxt;
    }
  }

  async function refreshStatus() {
    const drivePill = document.getElementById('devDrivePill');
    const clipPill = document.getElementById('devClipPill');
    if (!drivePill || !clipPill) return;

    const opts = { credentials: 'same-origin', cache: 'no-store' };

    const [driveRes, clipRes] = await Promise.allSettled([
      fetch(`${API}/drive/status`, opts).then((r) => r.json().then((d) => ({ ok: r.ok, d }))),
      fetch(`${API}/ai/clip/status`, opts).then((r) => r.json().then((d) => ({ ok: r.ok, d }))),
    ]);

    if (driveRes.status === 'fulfilled') {
      const { ok, d } = driveRes.value;
      const on = ok && d.online === true && d.status !== 'error';
      const state = on ? 'on' : 'off';
      const txt = on ? 'Drive' : 'Drive off';
      applyStatus(state, txt, null, null);
      writeStatusCache({ drive: state, driveTxt: txt });
    }
    // se falhar/timeout: mantém último estado (não pisca "off")

    if (clipRes.status === 'fulfilled') {
      const { d } = clipRes.value;
      const info = d.clip || {};
      const ready = !!(info.installed || info.loaded || info.ready);
      const state = ready ? 'on' : (info.installed === false || info.enabled === false ? 'warn' : 'off');
      const txt = ready ? 'CLIP' : 'CLIP off';
      applyStatus(null, null, state, txt);
      writeStatusCache({ clip: state, clipTxt: txt });
    }
  }

  function startStatusLoop() {
    const cached = readStatusCache();
    if (cached) {
      applyStatus(cached.drive, cached.driveTxt, cached.clip, cached.clipTxt);
    }
    refreshStatus();
    if (window.__studioStatusTimer) clearInterval(window.__studioStatusTimer);
    // 8s: cache backend 12s — UI estável, sem abort/erro piscando
    window.__studioStatusTimer = setInterval(refreshStatus, 8000);
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') refreshStatus();
    });
  }

  document.addEventListener('DOMContentLoaded', async () => {
    const data = await me();
    if (!data || !data.logged_in) return;

    const path = (location.pathname || '').toLowerCase();
    const publicPage = /(^|\/)(index\.html)?$/.test(path)
      || path.endsWith('/search.html')
      || path.endsWith('/loginsite.html')
      || path.endsWith('/search')
      || path.endsWith('/loginsite')
      || path === '/'
      || path === '';

    const isDev = data.role === 'dev' || (data.perms || []).includes('system');
    const isStaff = isDev || data.role === 'admin';
    if (isStaff) document.body.classList.add('is-studio-staff');

    if (publicPage) {
      if (!path.endsWith('/loginsite.html') && !path.endsWith('/loginsite')) {
        injectPublicSession(data.user, data.role, isDev);
      }
      return;
    }

    if (isDev) {
      buildDevBar(data.user);
      startStatusLoop();
    } else if (data.role === 'admin') {
      buildAdminBar(data.user);
    } else {
      injectPublicSession(data.user, data.role, false);
    }
  });
})();
