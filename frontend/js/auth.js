/* auth.js — sessão equipe via /api/auth/*  →  /loginsite.html
   Admin/dev permanecem logados até logout explícito. */
const Auth = (() => {
  const API = '/api';
  const LOGIN_PATH = '/loginsite.html';
  const ME_CACHE_KEY = 'authMeCache';
  const ME_STICKY_KEY = 'authMeSticky';
  const ME_TTL_MS = 45000;
  let _me = null;
  let _csrf = '';

  function readMeCache() {
    try {
      const raw = sessionStorage.getItem(ME_CACHE_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!parsed?.data?.logged_in) return null;
      if (!parsed.at || (Date.now() - parsed.at) > ME_TTL_MS) return null;
      return parsed.data;
    } catch {
      return null;
    }
  }

  function readSticky() {
    try {
      const raw = localStorage.getItem(ME_STICKY_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!parsed?.data?.logged_in) return null;
      return parsed.data;
    } catch {
      return null;
    }
  }

  function writeMeCache(data) {
    try {
      if (data && data.logged_in) {
        const payload = JSON.stringify({ at: Date.now(), data });
        sessionStorage.setItem(ME_CACHE_KEY, payload);
        localStorage.setItem(ME_STICKY_KEY, payload);
      } else if (data && data.offline) {
        // offline: não apaga sticky
      } else {
        sessionStorage.removeItem(ME_CACHE_KEY);
        localStorage.removeItem(ME_STICKY_KEY);
      }
    } catch { /* ignore */ }
  }

  function clearLocalSession() {
    _me = { logged_in: false };
    _csrf = '';
    try {
      sessionStorage.removeItem(ME_CACHE_KEY);
      localStorage.removeItem(ME_STICKY_KEY);
      sessionStorage.removeItem('studioStatusCache');
    } catch { /* ignore */ }
  }

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
    if (_me && _me.logged_in && !force) return _me;
    if (!force) {
      const cached = readMeCache();
      if (cached) {
        _me = cached;
        return _me;
      }
    }
    try {
      const r = await window.fetch(`${API}/auth/me`, {
        credentials: 'same-origin',
        cache: 'no-store',
      });
      if (!r.ok) {
        // Erro de servidor/rede — NÃO trata como logout
        if (r.status === 401 || r.status === 403) {
          clearLocalSession();
          return _me;
        }
        const sticky = _me?.logged_in ? _me : readSticky();
        if (sticky?.logged_in) {
          _me = { ...sticky, offline: true };
          return _me;
        }
        return { logged_in: false, offline: true };
      }
      const data = await r.json().catch(() => ({ logged_in: false }));
      _me = data;
      writeMeCache(_me);
      return _me;
    } catch {
      // Falha de rede: mantém sessão local até o servidor confirmar logout
      const sticky = (_me && _me.logged_in) ? _me : readSticky() || readMeCache();
      if (sticky && sticky.logged_in) {
        _me = { ...sticky, offline: true };
        return _me;
      }
      return { logged_in: false, offline: true };
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
        _me = { ...data, logged_in: data.logged_in !== false };
        writeMeCache(_me);
        return _me;
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
    clearLocalSession();
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
      clearLocalSession();
      if (typeof Toast !== 'undefined') {
        Toast.error('Sessão encerrada', data.message || 'Faça login novamente.');
      }
      setTimeout(goLogin, 500);
    }
    return res;
  }

  async function requireLogin() {
    const data = await me(false);
    if (data && data.logged_in) {
      // Revalida em background — só desloga se o servidor confirmar
      me(true).then((fresh) => {
        if (!fresh) return;
        if (fresh.offline) return;
        if (fresh.logged_in === false) goLogin();
      }).catch(() => { /* rede: permanece logado */ });
      return data;
    }
    // Sem sessão confirmada nem sticky
    const sticky = readSticky();
    if (sticky?.logged_in) {
      _me = sticky;
      me(true).then((fresh) => {
        if (fresh && !fresh.offline && fresh.logged_in === false) goLogin();
      }).catch(() => {});
      return sticky;
    }
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
