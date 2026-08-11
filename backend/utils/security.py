"""
security.py — Login multi-usuário (dev/admin), sessão, SSRF guard
"""
from __future__ import annotations

import hmac
import ipaddress
import os
import re
import secrets
from functools import wraps
from urllib.parse import urlparse

from flask import request, jsonify, session
from werkzeug.security import check_password_hash, generate_password_hash


# Páginas HTML só com login (busca fica pública)
PROTECTED_HTML = frozenset({
    'dashboard.html', 'dashboard',
    'admin.html', 'admin',
    'upload.html', 'upload',
    'slots.html', 'slots',
    'code.html', 'code',
    'settings.html', 'settings',
})

# Páginas exclusivas do papel com perm `code` / `system`
DEV_ONLY_HTML = frozenset({
    'code.html', 'code',
    'settings.html', 'settings',
})

# Permissões por papel
# admin: conteúdo (galeria, upload, slots, edição)
# dev: tudo do admin + sync Drive, CLIP, sistema, código-fonte
ROLE_PERMS = {
    'dev': frozenset({
        'dashboard', 'gallery', 'upload', 'edit', 'delete', 'slots',
        'sync', 'clip', 'system', 'code',
    }),
    'admin': frozenset({
        'dashboard', 'gallery', 'upload', 'edit', 'delete', 'slots',
    }),
}


def _load_users() -> dict:
    """
    Usuários via .env:
      AUTH_USERS=user:SENHA:dev,outro:SENHA:admin
    E/ou:
      ADMIN_USER / ADMIN_PASSWORD (+ role admin)
      DEV_USER / DEV_PASSWORD (+ role dev)
    """
    users = {}

    # Preferência: DEV_* / ADMIN_* (mais simples, sem parse ambíguo)
    admin_user = (os.getenv('ADMIN_USER') or os.getenv('ADMIN_USERNAME') or '').strip().lower()
    admin_pass = (os.getenv('ADMIN_PASSWORD') or '').strip()
    admin_hash = (os.getenv('ADMIN_PASSWORD_HASH') or '').strip()
    if admin_user and (admin_pass or admin_hash):
        users[admin_user] = {
            'password': admin_pass,
            'password_hash': admin_hash,
            'role': 'admin',
        }

    dev_user = (os.getenv('DEV_USER') or '').strip().lower()
    dev_pass = (os.getenv('DEV_PASSWORD') or '').strip()
    dev_hash = (os.getenv('DEV_PASSWORD_HASH') or '').strip()
    if dev_user and (dev_pass or dev_hash):
        users[dev_user] = {
            'password': dev_pass,
            'password_hash': dev_hash,
            'role': 'dev',
        }

    raw = (os.getenv('AUTH_USERS') or '').strip()
    if raw:
        for part in raw.split(','):
            part = part.strip()
            if not part:
                continue
            bits = part.split(':')
            if len(bits) < 2:
                continue
            # user:senha:role — senha pode ter ':' no meio
            if len(bits) >= 3 and bits[-1].strip().lower() in ROLE_PERMS:
                user = bits[0].strip().lower()
                password = ':'.join(bits[1:-1]).strip()
                role = bits[-1].strip().lower()
            else:
                user = bits[0].strip().lower()
                password = bits[1].strip()
                role = 'admin'
            if role not in ROLE_PERMS:
                role = 'admin'
            # AUTH_USERS preenche só se ainda não veio de DEV_*/ADMIN_*
            if user and password and user not in users:
                users[user] = {'password': password, 'role': role}

    return users


def get_users() -> dict:
    return _load_users()


def is_auth_configured() -> bool:
    return bool(get_users()) or bool((os.getenv('ADMIN_API_KEY') or '').strip())


def _password_matches(plain: str, given: str) -> bool:
    """Comparação segura; nunca lança se os tamanhos forem diferentes."""
    if not plain or not given:
        return False
    a = plain.encode('utf-8')
    b = given.encode('utf-8')
    if len(a) != len(b):
        # evita ValueError do compare_digest e timing óbvio demais
        hmac.compare_digest(a, a)
        return False
    return hmac.compare_digest(a, b)


def verify_login(username: str, password: str) -> dict | None:
    """Retorna dict do usuário {user, role} ou None."""
    if not username or password is None:
        return None
    users = get_users()
    u = str(username).strip().lower()
    given = str(password)
    info = users.get(u)
    if not info:
        return None

    pwd_hash = (info.get('password_hash') or '').strip()
    if pwd_hash:
        try:
            if not check_password_hash(pwd_hash, given):
                return None
        except Exception:
            return None
    else:
        plain = info.get('password') or ''
        if not _password_matches(plain, given):
            return None

    return {'user': u, 'role': info.get('role') or 'admin'}


def login_user(username: str, role: str) -> None:
    # Regenera sessão (mitiga session fixation)
    session.clear()
    session['admin'] = True
    session['user'] = username.strip().lower()
    session['role'] = role
    session['csrf'] = secrets.token_urlsafe(32)
    # Permanente até logout explícito (prazo em PERMANENT_SESSION_LIFETIME)
    session.permanent = True
    session.modified = True


def touch_session() -> None:
    """Mantém a sessão viva enquanto o usuário navega (admin/dev)."""
    if session.get('admin') is True:
        session.permanent = True
        session.modified = True


# Rate limit de login (em memória)
_LOGIN_ATTEMPTS: dict[str, dict] = {}
_LOGIN_MAX = 10          # após 10 erros → timeout
_LOGIN_WINDOW = 120      # janela de contagem: 2 min
_LOGIN_LOCK = 120        # bloqueio: 2 min


def reset_login_rate_limits() -> None:
    _LOGIN_ATTEMPTS.clear()


def _client_ip() -> str:
    """IP do cliente. Só confia em X-Forwarded-For se TRUST_PROXY=true (Nginx/Oracle)."""
    remote = (request.remote_addr or 'unknown').strip()
    trust = os.getenv('TRUST_PROXY', 'false').lower().strip() in ('1', 'true', 'yes', 'on')
    if not trust:
        return remote or 'unknown'
    forwarded = (request.headers.get('X-Forwarded-For') or '').split(',')[0].strip()
    return forwarded or remote or 'unknown'


# ── Rate limit geral (anti-bruteforce / flood / scanners) ──────────────
_RATE_BUCKETS: dict[str, dict] = {}
_RATE_MAX_KEYS = 8000


def _rate_evict(now: float) -> None:
    if len(_RATE_BUCKETS) < _RATE_MAX_KEYS:
        return
    stale = [k for k, v in _RATE_BUCKETS.items() if now - float(v.get('start') or 0) > 120]
    for k in stale[: max(1, len(stale) // 2)]:
        _RATE_BUCKETS.pop(k, None)


def rate_limited(bucket: str, limit: int, window_sec: int) -> tuple[bool, int]:
    """Retorna (bloqueado?, retry_after_s)."""
    import time
    ip = _client_ip()
    now = time.time()
    _rate_evict(now)
    key = f'{bucket}:{ip}'
    row = _RATE_BUCKETS.get(key)
    if not row or now - float(row.get('start') or 0) > window_sec:
        _RATE_BUCKETS[key] = {'start': now, 'count': 1}
        return False, 0
    row['count'] = int(row.get('count') or 0) + 1
    if row['count'] > limit:
        wait = int(window_sec - (now - float(row['start']))) + 1
        return True, max(1, wait)
    return False, 0


def api_flood_limited() -> tuple[bool, int]:
    """Limite global por IP em /api/*."""
    path = (request.path or '')
    method = request.method.upper()
    if path.startswith('/api/auth/login') and method == 'POST':
        return False, 0  # login tem limite próprio
    if path.startswith('/api/search'):
        return rate_limited('search', int(os.getenv('RATE_SEARCH_PER_MIN', '60')), 60)
    if path.startswith('/api/auth/'):
        return rate_limited('auth', int(os.getenv('RATE_AUTH_PER_MIN', '40')), 60)
    # Warm: barato de chamar, mas não floodar
    if path.startswith('/api/thumbs/warm'):
        return rate_limited('thumbs_warm', int(os.getenv('RATE_THUMBS_WARM_PER_MIN', '6')), 60)
    # Prefetch plan: leve
    if path.startswith('/api/thumbs/prefetch-plan'):
        return rate_limited('thumbs_plan', int(os.getenv('RATE_THUMBS_PLAN_PER_MIN', '30')), 60)
    # Burst de thumbs no grid / pré-cache (HTTP/1.1 ~6 conexões × muitas imgs)
    if method == 'GET' and (
        re.search(r'/api/media/\d+/thumb(?:-small|-medium|-cover)?$', path)
        or path.startswith('/api/local/')
    ):
        return rate_limited('thumbs', int(os.getenv('RATE_THUMBS_PER_MIN', '600')), 60)
    # Originais/HD: limite mais baixo (enumeração + custo Drive/disco)
    if method == 'GET' and re.search(r'/api/media/\d+/download$', path):
        return rate_limited('download', int(os.getenv('RATE_DOWNLOAD_PER_MIN', '40')), 60)
    return rate_limited('api', int(os.getenv('RATE_API_PER_MIN', '120')), 60)


def require_csrf_for_mutation() -> tuple | None:
    """
    Exige CSRF em POST/PUT/PATCH/DELETE autenticados por sessão.
    API Key (scripts) dispensa CSRF.
    """
    method = request.method.upper()
    if method in ('GET', 'HEAD', 'OPTIONS'):
        return None
    if has_valid_api_key():
        return None
    # login já valida CSRF no handler
    path = (request.path or '').rstrip('/')
    if path in ('/api/auth/login', '/api/auth/csrf'):
        return None
    # Sem sessão: lockdown já bloqueia (exceto logout público)
    if not is_logged_in() and path == '/api/auth/logout':
        return None
    if not is_logged_in():
        return None
    token = (
        request.headers.get('X-CSRF-Token')
        or (request.get_json(silent=True) or {}).get('csrf')
        or request.form.get('csrf')
        or ''
    )
    if not verify_csrf_token(token):
        return jsonify({
            'status': 'error',
            'message': 'CSRF inválido. Recarregue a página.',
        }), 403
    return None


_SCANNER_PATH_RE = re.compile(
    r'(?i)('
    r'wp-admin|wp-login|xmlrpc\.php|phpmyadmin|\.php$|'
    r'\.asp$|\.aspx$|\.cgi$|/\.git|/vendor/|\.aws/|'
    r'actuator|env\.bak|\.DS_Store|cgi-bin'
    r')'
)


def is_scanner_probe(path: str) -> bool:
    p = (path or '').lower()
    if _SCANNER_PATH_RE.search(p):
        return True
    return False


def login_rate_limited() -> tuple[bool, int]:
    """Retorna (bloqueado?, segundos_restantes)."""
    import time
    ip = _client_ip()
    now = time.time()
    row = _LOGIN_ATTEMPTS.get(ip)
    if not row:
        return False, 0
    locked_until = float(row.get('locked_until') or 0)
    if locked_until > now:
        return True, int(locked_until - now)
    # Timeout acabou → zera contagem para novas 10 tentativas
    if locked_until and locked_until <= now:
        _LOGIN_ATTEMPTS.pop(ip, None)
        return False, 0
    if now - float(row.get('first') or 0) > _LOGIN_WINDOW:
        _LOGIN_ATTEMPTS.pop(ip, None)
        return False, 0
    return False, 0


def record_login_failure() -> None:
    import time
    ip = _client_ip()
    now = time.time()
    # Evict expired entries to prevent unbounded memory growth
    expired = [k for k, v in _LOGIN_ATTEMPTS.items()
               if now - float(v.get('first') or 0) > _LOGIN_WINDOW * 2
               and float(v.get('locked_until') or 0) < now]
    for k in expired:
        _LOGIN_ATTEMPTS.pop(k, None)
    row = _LOGIN_ATTEMPTS.get(ip) or {'count': 0, 'first': now, 'locked_until': 0}
    if now - float(row['first']) > _LOGIN_WINDOW:
        row = {'count': 0, 'first': now, 'locked_until': 0}
    row['count'] = int(row['count']) + 1
    if row['count'] >= _LOGIN_MAX:
        row['locked_until'] = now + _LOGIN_LOCK
    _LOGIN_ATTEMPTS[ip] = row


def clear_login_failures() -> None:
    _LOGIN_ATTEMPTS.pop(_client_ip(), None)


def issue_csrf_token() -> str:
    token = secrets.token_urlsafe(32)
    session['csrf'] = token
    # Não derruba login existente ao renovar CSRF
    if session.get('admin') is True:
        session.permanent = True
    session.modified = True
    return token


def verify_csrf_token(token: str | None) -> bool:
    expected = session.get('csrf')
    if not expected or not token:
        return False
    return hmac.compare_digest(str(expected), str(token))


def logout_user() -> None:
    session.clear()
    session.modified = True


def is_logged_in() -> bool:
    return bool(session.get('admin') is True)


def current_user() -> str | None:
    if is_logged_in():
        return session.get('user')
    return None


def current_role() -> str | None:
    if is_logged_in():
        return session.get('role') or 'admin'
    return None


def role_can(role: str | None, perm: str) -> bool:
    if not role:
        return False
    return perm in ROLE_PERMS.get(role, frozenset())


def current_can(perm: str) -> bool:
    return role_can(current_role(), perm)


def get_admin_api_key() -> str:
    return (os.getenv('ADMIN_API_KEY') or '').strip()


def extract_api_key() -> str | None:
    key = request.headers.get('X-API-Key', '').strip()
    if key:
        return key
    auth = request.headers.get('Authorization', '').strip()
    if auth.lower().startswith('bearer '):
        return auth[7:].strip()
    return None


def has_valid_api_key() -> bool:
    expected = get_admin_api_key()
    if not expected:
        return False
    provided = extract_api_key()
    if not provided:
        return False
    return hmac.compare_digest(provided, expected)


def is_admin_request() -> bool:
    """Sessão logada OU X-API-Key (scripts). API key = papel dev."""
    return is_logged_in() or has_valid_api_key()


def request_role() -> str | None:
    if is_logged_in():
        return current_role()
    if has_valid_api_key():
        return 'dev'
    return None


def _auth_error_response(perm: str | None = None):
    if not is_auth_configured():
        return jsonify({
            'status': 'error',
            'message': 'Auth não configurada no servidor.',
        }), 503

    if not is_admin_request():
        return jsonify({
            'status': 'error',
            'message': 'Não autorizado. Faça login em /loginsite.',
        }), 401

    if perm and not role_can(request_role(), perm):
        return jsonify({
            'status': 'error',
            'message': 'Sem permissão para esta ação.',
        }), 403
    return None


def require_admin(fn):
    """Exige login (qualquer papel admin/dev)."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        err = _auth_error_response()
        if err:
            return err
        return fn(*args, **kwargs)
    return wrapper


def require_perm(perm: str):
    """Exige login + permissão do papel."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            err = _auth_error_response(perm)
            if err:
                return err
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# Públicos: busca + status + auth
_ALWAYS_PUBLIC = {
    ('GET', '/api/search'),
    ('GET', '/api/search/autocomplete'),
    ('GET', '/api/tags'),
    ('GET', '/api/search/stats'),
    ('GET', '/api/drive/status'),
    ('GET', '/api/ai/clip/status'),
    ('GET', '/api/ai/face/status'),
    ('GET', '/api/ai/status'),
    ('GET', '/api/contato/reel'),
    ('GET', '/api/portfolio/slots'),
    ('GET', '/api/portfolio/home'),
    ('GET', '/api/thumbs/prefetch-plan'),
    # /thumbs/warm NÃO é público — DoS CPU/IO (só logado / boot)
    ('POST', '/api/auth/login'),
    ('POST', '/api/auth/logout'),
    ('GET', '/api/auth/me'),
    ('GET', '/api/auth/csrf'),
}

# GET /api/media (lista completa) e dashboard = admin
# GET /api/media/<id> = público (lightbox da busca)
_ALWAYS_PUBLIC_PREFIXES = (
    # single media get + download for public search UX
)


def lockdown_before_request():
    """
    API_LOCKDOWN=true (padrão):
      Públicos: busca, thumbs, GET mídia slim, auth, slots/home
      Originais HD (/download anexo, /local imagem): login ou PUBLIC_MEDIA_ORIGINALS
      Resto: login obrigatório
      + rate limit + CSRF em mutações autenticadas
    """
    if request.method.upper() == 'OPTIONS':
        return None

    # Renova cookie de sessão em qualquer hit autenticado
    if session.get('admin') is True:
        session.permanent = True

    blocked, wait = api_flood_limited()
    if blocked:
        return jsonify({
            'status': 'error',
            'message': f'Muitas requisições. Aguarde {wait}s.',
        }), 429

    csrf_err = require_csrf_for_mutation()
    if csrf_err:
        return csrf_err

    mode = (os.getenv('API_LOCKDOWN', 'true') or 'true').lower().strip()
    if mode in ('0', 'false', 'no', 'off'):
        env = (os.getenv('FLASK_ENV') or os.getenv('ENV') or '').lower().strip()
        # Produção: lockdown nunca desliga por engano no .env
        if env in ('production', 'prod'):
            print('[SECURITY] API_LOCKDOWN=false ignorado em produção')
        else:
            return None

    method = request.method.upper()
    path = (request.path or '').rstrip('/') or request.path

    if (method, path) in _ALWAYS_PUBLIC:
        return None

    # GET/HEAD público: thumbs + metadados leves. Originais — handler decide.
    if method in ('GET', 'HEAD'):
        if re.fullmatch(r'/api/media/\d+', path):
            return None
        if re.fullmatch(r'/api/media/\d+/thumb', path):
            return None
        if re.fullmatch(r'/api/media/\d+/thumb-small', path):
            return None
        if re.fullmatch(r'/api/media/\d+/thumb-medium', path):
            return None
        if re.fullmatch(r'/api/media/\d+/thumb-cover', path):
            return None
        if re.fullmatch(r'/api/media/\d+/download', path):
            return None
        if re.fullmatch(r'/api/local/[a-f0-9]+', path):
            return None

    # Lista /api/media (sem id) e dashboard exigem login
    return _auth_error_response()


def public_originals_allowed() -> bool:
    """Opt-in explícito — nunca default em produção."""
    raw = (os.getenv('PUBLIC_MEDIA_ORIGINALS') or 'false').lower().strip()
    if raw not in ('1', 'true', 'yes', 'on'):
        return False
    env = (os.getenv('FLASK_ENV') or os.getenv('ENV') or '').lower().strip()
    if env in ('production', 'prod'):
        # Em produção exige também flag de confirmação
        confirm = (os.getenv('PUBLIC_MEDIA_ORIGINALS_CONFIRM') or '').lower().strip()
        return confirm in ('1', 'true', 'yes', 'i-understand')
    return True


def can_access_media_original() -> bool:
    """Original HD: somente admin/dev (perm gallery) ou opt-in PUBLIC_MEDIA_ORIGINALS.

    Visitante/anônimo: False.
    Não confiar em query strings (?admin=true).
    """
    if public_originals_allowed():
        return True
    role = request_role()
    if role in ('admin', 'dev') and role_can(role, 'gallery'):
        return True
    return False


def require_media_original_access(*, media_id: int | None = None, mode: str = 'download'):
    """Centraliza autorização de original. Retorna Response de erro ou None se ok."""
    if can_access_media_original():
        return None
    log_media_original_denied(media_id=media_id, mode=mode)
    code = 401 if not is_logged_in() else 403
    return jsonify({
        'status': 'error',
        'message': 'Acesso ao arquivo original exige login de equipe (admin/dev).',
    }), code


def log_media_original_denied(*, media_id: int | None = None, mode: str = 'download') -> None:
    """Log curto de tentativa — sem PII extra."""
    try:
        from flask import request as flask_request
        ip = (flask_request.headers.get('X-Forwarded-For') or flask_request.remote_addr or '')
        ip = str(ip).split(',')[0].strip()[:64]
        role = request_role() or 'anonymous'
        user = current_user() or '-'
        print(
            f'[media-guard] deny original media_id={media_id} mode={mode} '
            f'role={role} user={user} ip={ip}'
        )
    except Exception:
        pass


# Alias legado (imports internos)
_public_originals_allowed = public_originals_allowed


def path_needs_login(path: str) -> bool:
    p = (path or '').lstrip('/').split('?')[0].lower()
    if not p:
        return False
    base = p.split('/')[-1]
    name = base[:-5] if base.endswith('.html') else base
    return base in PROTECTED_HTML or name in PROTECTED_HTML


def path_needs_dev(path: str) -> bool:
    """Código / Config: só role com system ou code (dev)."""
    p = (path or '').lstrip('/').split('?')[0].lower()
    if not p:
        return False
    base = p.split('/')[-1]
    name = base[:-5] if base.endswith('.html') else base
    return base in DEV_ONLY_HTML or name in DEV_ONLY_HTML


def path_dev_perm(path: str) -> str | None:
    """Permissão exigida para página DEV-only, ou None."""
    p = (path or '').lstrip('/').split('?')[0].lower()
    base = p.split('/')[-1] if p else ''
    name = base[:-5] if base.endswith('.html') else base
    if name in ('code',) or base in ('code.html', 'code'):
        return 'code'
    if name in ('settings',) or base in ('settings.html', 'settings'):
        return 'system'
    return None


def safe_int(value, default=1, min_v=1, max_v=10_000):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_v, min(max_v, n))


def escape_fts_term(term: str) -> str:
    term = (term or '').strip()
    term = term.replace('"', ' ')
    term = re.sub(r'[^\w\-áàâãéèêíïóôõöúüçñ]+', ' ', term, flags=re.UNICODE)
    term = re.sub(r'\s+', ' ', term).strip()
    return term[:64]


def build_fts_match(terms) -> str | None:
    cleaned = []
    if isinstance(terms, str):
        terms = terms.split()
    for t in terms:
        t = escape_fts_term(t)
        if len(t) >= 2:
            cleaned.append(f'"{t}"')
    return ' OR '.join(cleaned) if cleaned else None


_ALLOWED_URL_HOSTS = {
    'drive.google.com',
    'lh3.googleusercontent.com',
    'googleusercontent.com',
}


def is_safe_image_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    if len(url) > 2000:
        return False
    # Somente thumbs internos — NÃO /api/local (UID = original de vídeo/imagem)
    if re.fullmatch(r'/api/media/\d+/thumb(?:-small|-medium|-cover)?(?:\?.*)?', url):
        return True
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme != 'https':
        return False
    host = (parsed.hostname or '').lower()
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
        if (
            ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast
        ):
            return False
        return False
    except ValueError:
        pass

    allowed = host in _ALLOWED_URL_HOSTS or any(
        host.endswith('.' + h) for h in _ALLOWED_URL_HOSTS
    )
    if not allowed:
        return False
    if parsed.username or parsed.password:
        return False
    return True


def is_safe_thumb_url(url: str) -> bool:
    return is_safe_image_url(url)


def generate_api_key() -> str:
    return secrets.token_urlsafe(32)


def hash_password(password: str) -> str:
    return generate_password_hash(password)
