/* auth.js — sessão equipe via /api/auth/*  →  /loginsite.html */
const Auth = (() => {
  const API = '/api';
  const LOGIN_PATH = '/loginsite.html';
  let _me = null;
  let _csrf = '';

  async function ensureCsrf(force = false) {
    if (_csrf && !force) return _csrf;
    const r = await window.fetch(`${API}/auth/csrf`, {
      credentials: 'same-origin',
      cache: 'no-store',
    });
    if (!r.ok) throw new Error('Não foi possível iniciar a sessão. Recarregue a página.');
    const data = await r.json();
    _csrf = data.csrf || '';
    if (!_csrf) throw new Error('CSRF ausente. Recarregue a página.');
    return _csrf;
  }

  async function me(force = false) {
    if (_me && !force) return _me;
    try {
      const r = await window.fetch(`${API}/auth/me`, {
        credentials: 'same-origin',
        cache: 'no-store',
      });
      _me = await r.json().catch(() => ({ logged_in: false }));
      return _me;
    } catch {
      _me = { logged_in: false };
      return _me;
    }
  }

  async function login(username, password) {
    let lastErr = null;
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        await ensureCsrf(attempt > 0);
        const r = await window.fetch(`${API}/auth/login`, {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRF-Token': _csrf || '',
          },
          body: JSON.stringify({ username, password, csrf: _csrf }),
        });
        const data = await r.json().catch(() => ({}));
        if (r.status === 403 && attempt === 0) {
          _csrf = '';
          lastErr = new Error(data.message || 'Sessão inválida');
          continue;
        }
        if (!r.ok) {
          const err = new Error(data.message || 'Login falhou');
          err.status = r.status;
          err.data = data;
          throw err;
        }
        if (data.csrf) _csrf = data.csrf;
        _me = data;
        return data;
      } catch (e) {
        lastErr = e;
        if (attempt === 0 && /csrf|sessão|sessao|inválid/i.test(String(e.message || ''))) {
          _csrf = '';
          continue;
        }
        throw e;
      }
    }
    throw lastErr || new Error('Login falhou');
  }

  async function logout() {
    try {
      try { await ensureCsrf(); } catch { /* ignore */ }
      await window.fetch(`${API}/auth/logout`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: _csrf ? { 'X-CSRF-Token': _csrf } : {},
      });
    } catch { /* ignore */ }
    _me = { logged_in: false };
    _csrf = '';
  }

  function headers(extra = {}) {
    const h = { ...extra };
    if (_csrf) h['X-CSRF-Token'] = _csrf;
    return h;
  }

  function goLogin() {
    if (/loginsite(\.html)?$/i.test(location.pathname)) return;
    const next = encodeURIComponent(location.pathname + location.search);
    location.href = `${LOGIN_PATH}?next=${next}`;
  }

  async function fetch(url, options = {}) {
    const opts = { ...options, credentials: 'same-origin' };
    const method = String(opts.method || 'GET').toUpperCase();
    if (method !== 'GET' && method !== 'HEAD') {
      try { await ensureCsrf(); } catch { /* se falhar, o backend recusa CSRF */ }
    }
    const baseHeaders = opts.headers || {};
    const isForm = typeof FormData !== 'undefined' && opts.body instanceof FormData;
    opts.headers = isForm ? { ...baseHeaders } : headers(baseHeaders);
    if (isForm) {
      if (opts.headers['Content-Type']) delete opts.headers['Content-Type'];
      if (_csrf) opts.headers['X-CSRF-Token'] = _csrf;
    }
    const res = await window.fetch(url, opts);
    if (res.status === 401) {
      const data = await res.clone().json().catch(() => ({}));
      if (typeof Toast !== 'undefined') {
        Toast.error('Sessão expirada', data.message || 'Faça login novamente.');
      }
      setTimeout(goLogin, 500);
    }
    return res;
  }

  async function requireLogin() {
    const data = await me(true);
    if (data && data.logged_in) return data;
    goLogin();
    return null;
  }

  function can(perm) {
    const perms = (_me && _me.perms) || [];
    return perms.includes(perm);
  }

  function role() {
    return (_me && _me.role) || null;
  }

  function getKey() { return ''; }
  function setKey() {}
  function clear() { return logout(); }
  function hasKey() { return false; }
  function ensureKey() { goLogin(); return ''; }

  return {
    me, login, logout, fetch, headers, requireLogin, can, role, ensureCsrf,
    getKey, setKey, clear, hasKey, ensureKey, LOGIN_PATH,
  };
})();
