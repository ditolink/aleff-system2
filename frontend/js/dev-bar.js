/* dev-bar.js — toolbar + logout para sessão da equipe */
(() => {
  const API = '/api';

  const LINKS = [
    { href: '/dashboard.html', label: 'Dashboard' },
    { href: '/upload.html', label: 'Upload' },
    { href: '/admin.html', label: 'Galeria' },
    { href: '/slots.html', label: 'Slots' },
    { href: '/search.html', label: 'Busca' },
  ];

  async function me() {
    try {
      const r = await fetch(`${API}/auth/me`, {
        credentials: 'same-origin',
        cache: 'no-store',
      });
      return await r.json();
    } catch {
      return { logged_in: false };
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
    location.href = '/loginsite.html';
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

  function buildAdminBar(user) {
    const bar = el('div', {
      className: 'dev-bar admin-bar',
      id: 'devBar',
      role: 'navigation',
      'aria-label': 'Ferramentas admin',
    });

    bar.appendChild(el('span', { className: 'dev-bar-label', text: 'Admin' }));
    [
      ['/dashboard.html', 'Dashboard'],
      ['/upload.html', 'Upload'],
      ['/admin.html', 'Galeria'],
      ['/slots.html', 'Slots'],
      ['/search.html', 'Busca'],
    ].forEach(([href, label]) => {
      bar.appendChild(el('a', {
        className: 'dev-pill',
        href,
        text: label,
        onClick: (e) => go(href, e),
      }));
    });

    bar.appendChild(el('span', { className: 'dev-bar-user', text: user || 'admin' }));
    bar.appendChild(el('button', {
      className: 'dev-pill dev-pill--out',
      type: 'button',
      text: 'Sair',
      onClick: (e) => {
        e.preventDefault();
        doLogout();
      },
    }));

    document.body.prepend(bar);
    document.body.classList.add('has-dev-bar');
  }

  function buildDevBar(user) {
    const bar = el('div', {
      className: 'dev-bar',
      id: 'devBar',
      role: 'navigation',
      'aria-label': 'Ferramentas dev',
    });

    bar.appendChild(el('span', { className: 'dev-bar-label', text: 'Dev' }));

    const drive = el('a', {
      className: 'dev-pill',
      id: 'devDrivePill',
      href: '/dashboard.html',
      'data-state': '',
      html: '<span class="dot"></span><span class="txt">Drive…</span>',
      onClick: (e) => go('/dashboard.html', e),
    });
    bar.appendChild(drive);

    const clip = el('a', {
      className: 'dev-pill',
      id: 'devClipPill',
      href: '/dashboard.html',
      'data-state': '',
      html: '<span class="dot"></span><span class="txt">OpenCLIP…</span>',
      onClick: (e) => go('/dashboard.html', e),
    });
    bar.appendChild(clip);

    bar.appendChild(el('span', { className: 'dev-bar-sep' }));

    LINKS.forEach(({ href, label }) => {
      bar.appendChild(el('a', {
        className: 'dev-pill',
        href,
        text: label,
        onClick: (e) => go(href, e),
      }));
    });

    bar.appendChild(el('span', { className: 'dev-bar-user', text: user || 'dev' }));

    const out = el('button', {
      className: 'dev-pill dev-pill--out',
      type: 'button',
      text: 'Sair',
      onClick: (e) => {
        e.preventDefault();
        doLogout();
      },
    });
    bar.appendChild(out);

    document.body.prepend(bar);
    document.body.classList.add('has-dev-bar');
  }

  function injectNavLogout(user, role) {
    const host =
      document.querySelector('.nav-right') ||
      document.querySelector('.search-nav') ||
      document.querySelector('.site-nav');
    if (!host || document.getElementById('navLogoutBtn')) return;

    const wrap = el('div', { className: 'nav-session', id: 'navSession' });
    wrap.appendChild(el('span', {
      className: 'nav-session-user',
      text: role === 'dev' ? `${user || 'dev'} · dev` : (user || 'equipe'),
    }));
    wrap.appendChild(el('button', {
      className: 'nav-logout-btn',
      id: 'navLogoutBtn',
      type: 'button',
      text: 'Sair',
      onClick: (e) => {
        e.preventDefault();
        doLogout();
      },
    }));

    if (host.classList.contains('search-nav')) {
      const spacer = host.querySelector('.nav-spacer');
      if (spacer) spacer.replaceWith(wrap);
      else host.appendChild(wrap);
    } else {
      host.appendChild(wrap);
    }
  }

  async function refreshStatus() {
    const drivePill = document.getElementById('devDrivePill');
    const clipPill = document.getElementById('devClipPill');
    if (!drivePill || !clipPill) return;

    try {
      const r = await fetch(`${API}/drive/status`, {
        credentials: 'same-origin',
        cache: 'no-store',
      });
      const d = await r.json();
      const on = r.ok && d.online === true && d.status !== 'error';
      drivePill.dataset.state = on ? 'on' : 'off';
      const t = drivePill.querySelector('.txt');
      if (t) t.textContent = on ? 'Drive on' : 'Drive off';
    } catch {
      drivePill.dataset.state = 'off';
      const t = drivePill.querySelector('.txt');
      if (t) t.textContent = 'Drive off';
    }

    try {
      const r = await fetch(`${API}/ai/clip/status`, {
        credentials: 'same-origin',
        cache: 'no-store',
      });
      const d = await r.json();
      const info = d.clip || {};
      const ready = !!(info.installed || info.loaded);
      clipPill.dataset.state = ready ? 'on' : (info.installed === false ? 'warn' : 'off');
      const t = clipPill.querySelector('.txt');
      if (t) t.textContent = ready ? 'CLIP on' : 'CLIP off';
    } catch {
      clipPill.dataset.state = 'off';
      const t = clipPill.querySelector('.txt');
      if (t) t.textContent = 'CLIP off';
    }
  }

  document.addEventListener('DOMContentLoaded', async () => {
    const data = await me();
    if (!data || !data.logged_in) return;

    const isDev = data.role === 'dev' || (data.perms || []).includes('system');
    if (isDev) {
      buildDevBar(data.user);
      refreshStatus();
      setInterval(refreshStatus, 30000);
    } else if (data.role === 'admin') {
      buildAdminBar(data.user);
    } else {
      // admin / equipe: só logout no topo das páginas públicas
      injectNavLogout(data.user, data.role);
    }
  });
})();
