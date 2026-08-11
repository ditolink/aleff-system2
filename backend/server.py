import os
import sys
import secrets
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, abort, jsonify, redirect, request, send_from_directory
from flask_cors import CORS
from werkzeug.exceptions import NotFound, HTTPException

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env", override=True)

from backend.models.database import init_db, get_all_media
from backend.routes.api import api
from backend.utils.validators import MAX_FILE_SIZE
from backend.utils.security import (
    path_needs_login,
    path_needs_dev,
    path_dev_perm,
    is_logged_in,
    is_auth_configured,
    current_can,
    reset_login_rate_limits,
    is_scanner_probe,
)

# static_folder=None → NÃO serve arquivos automaticamente (evita furar o login)
app = Flask(__name__, static_folder=None)

try:
    from backend.utils.observability import init_observability
    init_observability(app)
except Exception as _obs_err:
    print(f"[OBS] skip: {_obs_err}")

app.config["MAX_CONTENT_LENGTH"] = int(
    os.getenv("MAX_CONTENT_LENGTH", MAX_FILE_SIZE)
)

# Sessão segura (cookie HttpOnly). Sem SECRET_KEY no .env, persiste em data/
# para admin/dev não perderem login a cada reinício do servidor.
_secret = (os.getenv("SECRET_KEY") or "").strip()
if not _secret:
    _secret_path = PROJECT_ROOT / "data" / ".flask_secret"
    try:
        if _secret_path.is_file():
            _secret = _secret_path.read_text(encoding="utf-8").strip()
        if not _secret:
            _secret_path.parent.mkdir(parents=True, exist_ok=True)
            _secret = secrets.token_hex(32)
            _secret_path.write_text(_secret, encoding="utf-8")
            print("[SECURITY] SECRET_KEY gerada em data/.flask_secret (defina SECRET_KEY no .env).")
    except OSError as _sk_err:
        _secret = secrets.token_hex(32)
        print(f"[SECURITY] Não gravou secret persistente ({_sk_err}) — sessões resetam ao reiniciar.")
app.config["SECRET_KEY"] = _secret
_flask_env = (os.getenv("FLASK_ENV") or os.getenv("ENV") or "").lower().strip()
_is_prod = _flask_env in ("production", "prod")
# Sessões mais curtas por padrão (antes 90d)
_session_days = max(1, int(os.getenv("SESSION_DAYS", "14" if _is_prod else "30")))
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=_session_days)
# Renova o cookie a cada request autenticado — fica logado até logout
app.config["SESSION_REFRESH_EACH_REQUEST"] = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# Fail-closed: em produção Secure=true mesmo se .env disser false
_secure_env = (os.getenv("SESSION_COOKIE_SECURE") or "").lower().strip()
if _is_prod or (os.getenv("HTTPS") or "").lower() in ("1", "true", "yes"):
    if _secure_env in ("0", "false", "no", "off"):
        print("[SECURITY] SESSION_COOKIE_SECURE=false ignorado em produção/HTTPS")
    app.config["SESSION_COOKIE_SECURE"] = True
else:
    app.config["SESSION_COOKIE_SECURE"] = _secure_env in ("1", "true", "yes")
app.config["SESSION_COOKIE_NAME"] = os.getenv("SESSION_COOKIE_NAME", "aleff_session")
app.config["REMEMBER_COOKIE_DURATION"] = timedelta(days=_session_days)
# Não vazar traceback em produção
app.config["PROPAGATE_EXCEPTIONS"] = False

_cors_raw = os.getenv(
    "CORS_ORIGINS",
    "http://127.0.0.1:3001,http://localhost:3001",
)
_cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip() and o.strip() != "*"]
if not _cors_origins:
    _cors_origins = ["http://127.0.0.1:3001", "http://localhost:3001"]
    print("[SECURITY] CORS_ORIGINS vazio/* — fallback localhost")
CORS(
    app,
    origins=_cors_origins,
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key", "Authorization", "X-CSRF-Token"],
    supports_credentials=True,
)

app.register_blueprint(api)

# Garante banco pronto também quando sobe via Waitress/Docker (não só __main__)
try:
    init_db()
except Exception as _db_boot_err:
    print(f"[DB] falha no boot: {_db_boot_err}")

# Pré-gera thumbs medium/small em background (Waitress também) — pesquisa lê do cache
try:
    if (os.getenv('THUMB_PREFETCH_ON_START', '1') or '').strip().lower() in ('1', 'true', 'yes', 'on'):
        from backend.services import thumb_pipeline as _tp

        def _boot_thumb_warm():
            import time
            time.sleep(2)
            _tp.start_background_warm(
                limit=int(os.getenv('THUMB_WARM_LIMIT', '240') or 240),
                workers=int(os.getenv('THUMB_WARM_WORKERS', '8') or 8),
            )

        import threading as _threading
        _threading.Thread(target=_boot_thumb_warm, daemon=True, name='thumb-warm-boot').start()
        print('[Thumbs] Pré-render agendado (home + categorias).')
except Exception as _tw_err:
    print(f'[Thumbs] warm boot skip: {_tw_err}')

# Só o que pode sair do frontend para o público
_ALLOWED_EXT = frozenset({
    ".html", ".css", ".js", ".map",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".ico",
    ".mp4", ".webm", ".mov",
    ".woff", ".woff2", ".ttf", ".otf",
})
_BLOCKED_EXT = frozenset({
    ".py", ".pyc", ".pyo", ".env", ".ini", ".cfg", ".toml",
    ".sqlite", ".db", ".sql", ".log",
    ".pem", ".key", ".p12", ".pfx", ".crt", ".cer",
    ".json", ".yaml", ".yml", ".xml",
    ".bat", ".ps1", ".sh", ".cmd",
    ".md", ".txt", ".example",
    ".zip", ".rar", ".7z", ".gz", ".tar",
})
_BLOCKED_NAMES = frozenset({
    ".env", ".env.local", ".env.production", ".env.development",
    ".git", ".gitignore", "dockerfile", "dockerfile.lite", "dockerfile.clip",
    "docker-compose.yml", "package.json", "package-lock.json", "requirements.txt",
    "requirements-clip.txt", "service-account.json", "credentials.json", "secrets.json",
    "procfile", "railway.toml", "hosting-aleffthiago.txt", "leia-me-demo.txt",
    "start.bat", ".dockerignore",
})

_SENSITIVE_PREFIXES = (
    "backend/", "data/", ".git/", ".venv/", "venv/", "node_modules/",
    "deploy/", "scripts/", ".cursor/", "agent-transcripts/",
)


def _is_blocked_request_path(path: str) -> bool:
    p = (path or "").replace("\\", "/").lstrip("/")
    low = p.lower()
    if not p or ".." in p.split("/"):
        return True
    # Exceções públicas seguras
    if low in ("robots.txt", "favicon.ico"):
        return False
    name = Path(low).name
    if name in _BLOCKED_NAMES or name.startswith(".env"):
        return True
    if any(x in low for x in (
        "service-account", "credentials", "private_key", "auth_users",
        "secret_key", "admin_api_key", "hf_api",
    )):
        return True
    suf = Path(low).suffix
    if suf in _BLOCKED_EXT:
        return True
    if low.startswith(_SENSITIVE_PREFIXES):
        return True
    return False


def _send_frontend(rel: str):
    """Envia arquivo SOMENTE de frontend/, com path traversal bloqueado."""
    from flask import send_file

    rel = (rel or "").replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/"):
        abort(404)
    target = (FRONTEND_DIR / rel).resolve()
    try:
        target.relative_to(FRONTEND_DIR.resolve())
    except ValueError:
        abort(404)
    if not target.is_file():
        raise NotFound()
    # Extensão precisa ser permitida
    suf = target.suffix.lower()
    if suf not in _ALLOWED_EXT and target.name not in ("robots.txt", "favicon.ico"):
        abort(404)
    # Nunca servir arquivos com nome sensível mesmo dentro de frontend/
    if target.name.lower().startswith(".env") or target.name.lower() in _BLOCKED_NAMES:
        abort(404)

    # Vídeos: send_file com conditional/etag pra Range (seek + stream completo)
    if suf in (".mp4", ".webm", ".mov"):
        mime = {
            ".mp4": "video/mp4",
            ".webm": "video/webm",
            ".mov": "video/quicktime",
        }.get(suf, "application/octet-stream")
        return send_file(
            target,
            mimetype=mime,
            conditional=True,
            etag=True,
            last_modified=True,
            max_age=86400,
        )

    return send_from_directory(FRONTEND_DIR, rel)


@app.before_request
def harden_request():
    # Bloqueia probes de scanners (WordPress, phpMyAdmin, .git, etc.)
    if is_scanner_probe(request.path or ""):
        return jsonify({"status": "error", "message": "Not found"}), 404
    # Host header simples (opcional): ALLOWED_HOSTS=aleffthiago.com.br,www.aleffthiago.com.br
    allowed = (os.getenv("ALLOWED_HOSTS") or "").strip()
    if allowed:
        host = (request.host or "").split(":")[0].lower()
        ok_hosts = {h.strip().lower() for h in allowed.split(",") if h.strip()}
        ok_hosts.update({"127.0.0.1", "localhost"})
        if host and host not in ok_hosts:
            return jsonify({"status": "error", "message": "Host inválido."}), 400
    return None


@app.after_request
def set_security_headers(response):
    path = (request.path or "").lower()
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    )
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-site"
    response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data: blob: https://drive.google.com https://*.googleusercontent.com; "
        "media-src 'self' blob: https://drive.google.com; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self' https://wa.me https://mail.google.com"
    )
    # Não revelar stack/framework
    response.headers.pop("Server", None)
    if os.getenv("FLASK_ENV") != "development":
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    if path.startswith("/api/auth/") or path in ("/loginsite", "/loginsite.html"):
        response.headers["Cache-Control"] = "no-store"
    elif path.startswith("/api/search/stats") or path.startswith("/api/tags"):
        response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=120"
    elif path.endswith((".mp4", ".webm", ".mov")):
        response.headers["Cache-Control"] = "public, max-age=604800, immutable"
        response.headers["Accept-Ranges"] = "bytes"
    elif path.endswith((".css", ".js")):
        # Produção: cache longo (deploy troca URL ou hard-refresh). Dev: revalida.
        if os.getenv("FLASK_ENV") == "production":
            response.headers["Cache-Control"] = (
                "public, max-age=86400, stale-while-revalidate=604800"
            )
        else:
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
    elif path.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".ico", ".woff2", ".woff")):
        response.headers["Cache-Control"] = "public, max-age=604800, immutable"
    elif path.startswith("/api/media/") and (
        "/thumb-small" in path or "/thumb-medium" in path or "/thumb-cover" in path
    ):
        # URLs estáveis WebP — não reescrever (view já manda immutable longo)
        if "Cache-Control" not in response.headers:
            response.headers["Cache-Control"] = (
                "public, max-age=31536000, immutable"
            )
    elif path.startswith("/api/media/") and "/thumb" in path:
        response.headers["Cache-Control"] = "public, max-age=86400, stale-while-revalidate=604800"
    elif path == "/" or path.endswith(".html"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.errorhandler(404)
def handle_404(error):
    if request.path.startswith("/api/"):
        return jsonify({"status": "error", "message": "Endpoint API não encontrado."}), 404
    # Nunca mascara vazamento: paths sensíveis / desconhecidos = 404 limpo
    if _is_blocked_request_path(request.path.lstrip("/")):
        return jsonify({"status": "error", "message": "Not found"}), 404
    return jsonify({"status": "error", "message": "Not found"}), 404


@app.errorhandler(413)
def handle_413(error):
    return jsonify({
        "status": "error",
        "message": "Arquivo ou requisição grande demais.",
    }), 413


@app.errorhandler(Exception)
def handle_exception(error):
    if request.path.startswith("/api/"):
        if isinstance(error, HTTPException):
            code = error.code or 500
            msg = error.description if code < 500 else "Erro interno do servidor."
            if code >= 500:
                print(f"[API ERROR {code}] {error}")
            return jsonify({"status": "error", "message": msg}), code
        print(f"[API ERROR] {type(error).__name__}: {error}")
        return jsonify({"status": "error", "message": "Erro interno do servidor."}), 500
    raise error


@app.route("/")
def index():
    return _send_frontend("index.html")


@app.route("/health")
def health():
    """Health público mínimo. Detalhes só com sessão gallery/system."""
    db_ok = False
    try:
        from backend.models.database import get_conn
        conn = get_conn()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        db_ok = True
    except Exception as e:
        print(f"[health] db: {e}")

    status = 'ok' if db_ok else 'degraded'
    payload = {'status': status, 'db': db_ok}

    # Detalhes internos só autenticado (evita recon / contagem do acervo)
    try:
        from backend.utils.security import current_can
        if current_can('gallery') or current_can('system'):
            media_count = None
            try:
                from backend.models.database import get_conn
                conn = get_conn()
                media_count = conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]
                conn.close()
            except Exception:
                pass
            drive_ok = None
            drive_err = None
            try:
                from backend.services import drive as drive_svc
                cached = getattr(drive_svc, '_ping_cache', {}).get('result')
                if cached is not None:
                    drive_ok, drive_err = cached
                else:
                    drive_ok, drive_err = drive_svc.drive_ping()
            except Exception as e:
                drive_ok = False
                drive_err = str(e)[:120]
            if drive_ok is False:
                payload['status'] = 'degraded'
            payload['media_count'] = media_count
            payload['drive'] = {
                'online': bool(drive_ok),
                'error': drive_err if not drive_ok else None,
            }
            try:
                from backend.services.ai_pipeline import get_public_ai_summary
                payload['ai'] = get_public_ai_summary()
            except Exception:
                payload['ai'] = None
    except Exception:
        pass
    return payload


def _safe_next(raw) -> str:
    nxt = raw or "/dashboard.html"
    if not str(nxt).startswith("/") or str(nxt).startswith("//"):
        return "/dashboard.html"
    bare = {
        "/dashboard": "/dashboard.html",
        "/upload": "/upload.html",
        "/admin": "/admin.html",
        "/search": "/search.html",
        "/slots": "/slots.html",
        "/code": "/code.html",
        "/settings": "/settings.html",
    }
    return bare.get(str(nxt), str(nxt))


@app.route("/loginsite")
@app.route("/loginsite.html")
def loginsite_page():
    return _send_frontend("loginsite.html")


@app.route("/login")
@app.route("/login.html")
def login_redirect():
    q = request.query_string.decode() if request.query_string else ""
    return redirect("/loginsite.html" + (f"?{q}" if q else ""), code=302)


@app.route("/<path:path>")
def serve_frontend(path):
    # Bloqueia qualquer tentativa de ler código/segredos/raiz do projeto
    if path.startswith("api/") or _is_blocked_request_path(path):
        abort(404)

    # Páginas protegidas: login obrigatório (HTML real, não API)
    if path_needs_login(path) and not is_logged_in():
        return redirect(f"/loginsite.html?next=/{path.lstrip('/')}")

    # code / settings: só DEV (perm code|system) — admin não abre a shell
    if path_needs_dev(path):
        need = path_dev_perm(path) or "system"
        if not current_can(need):
            return redirect("/dashboard.html")

    # code.html só existe se o viewer estiver ligado
    base = path.lower().split("/")[-1]
    if base in ("code.html", "code") and os.getenv("CODE_VIEWER_ENABLED", "false").lower() not in (
        "1", "true", "yes", "on",
    ):
        abort(404)

    try:
        return _send_frontend(path)
    except NotFound:
        pass

    # atalho /dashboard → /dashboard.html
    html_path = path + ".html"
    if path_needs_login(html_path) and not is_logged_in():
        return redirect(f"/loginsite.html?next=/{html_path}")
    if path_needs_dev(html_path):
        need = path_dev_perm(html_path) or "system"
        if not current_can(need):
            return redirect("/dashboard.html")
    try:
        return _send_frontend(html_path)
    except NotFound:
        abort(404)


if __name__ == "__main__":
    import threading

    init_db()
    reset_login_rate_limits()

    try:
        from backend.services import drive as drive_svc
        # Não bloqueia o boot — ping em background (status usa cache)
        drive_svc.drive_ping_async()
        email = drive_svc.get_service_account_email()
        print("[Drive] Ping em background…")
        if email:
            print(f"[Drive] Service account: {email}")
    except Exception as e:
        print(f"[Drive] falha na conexão inicial: {e}")

    def _env_on(name, default='0'):
        return os.getenv(name, default).strip().lower() in ('1', 'true', 'yes', 'on')

    # Por padrão NÃO força OpenCLIP/Faces no boot (come RAM/CPU e atrasa tudo).
    # Dashboard Dev → Warmup / Backfill quando quiser.
    def _warmup_clip_bg():
        try:
            import time
            time.sleep(8)  # deixa o HTTP responder primeiro
            from backend.services import clip_tagger
            if not getattr(clip_tagger, "is_enabled", lambda: True)():
                print("[CLIP] Desativado — busca rápida só com texto.")
                return
            if not _env_on('CLIP_WARMUP_ON_START', '0'):
                print("[CLIP] Warmup automático off — use o dashboard Dev.")
                return
            from backend.models.database import annotate_storage, embedding_stats
            samples = [annotate_storage(m) for m in get_all_media(limit=8)]
            thumb_urls = [m["thumb_url"] for m in samples if m.get("thumb_url")]
            clip_tagger.warmup(thumb_urls)
            print("[CLIP] Warmup em background concluído.")
            if _env_on('CLIP_BACKFILL_ON_START', '0'):
                stats = embedding_stats()
                if stats.get("missing", 0) > 0:
                    print(
                        f"[CLIP] Backfill: {stats['missing']} imagem(ns) sem índice — "
                        "indexando em background…"
                    )
                    clip_tagger.backfill_embeddings(batch_size=12, pause_sec=0.15)
                    print("[CLIP] Backfill concluído:", embedding_stats())
        except Exception as e:
            print(f"[CLIP Warmup] falhou na inicialização: {e}")

    threading.Thread(target=_warmup_clip_bg, daemon=True, name="clip-warmup").start()
    print("[CLIP] Disponível sob demanda (dashboard) — não força no boot.")

    def _warmup_face_bg():
        try:
            import time
            time.sleep(10)
            from backend.services import face_tagger
            from backend.models.database import face_stats

            if not face_tagger.is_enabled():
                print("[FACE] Desativado (FACE_ENABLED=false).")
                return
            if not _env_on('FACE_WARMUP_ON_START', '0'):
                print("[FACE] Warmup automático off — use o dashboard Dev.")
                return
            if not face_tagger.is_installed():
                print("[FACE] Pacotes ausentes — pip install -r requirements-face.txt")
                return
            face_tagger.warmup()
            if _env_on('FACE_BACKFILL_ON_START', '0'):
                stats = face_stats()
                if stats.get("missing", 0) > 0:
                    print(
                        f"[FACE] Backfill: {stats['missing']} imagem(ns) sem índice de rosto…"
                    )
                    face_tagger.backfill_faces(batch_size=10, pause_sec=0.12)
                    print("[FACE] Backfill concluído:", face_stats())
                else:
                    print("[FACE] Índice de rostos ok:", stats)
            else:
                print("[FACE] Warmup ok — backfill só sob demanda.")
        except Exception as e:
            print(f"[FACE Warmup] falhou: {e}")

    threading.Thread(target=_warmup_face_bg, daemon=True, name="face-warmup").start()

    def _face_focus_bg():
        """Preenche face_cx/cy e regenera thumbs com rosto no centro."""
        try:
            import time
            time.sleep(14)
            from backend.services import face_tagger
            if not face_tagger.is_enabled() or not face_tagger.is_installed():
                return
            if not _env_on('FACE_FOCUS_BACKFILL_ON_START', '1'):
                return
            print('[FACE] Backfill de enquadramento (centro do rosto)…')
            r = face_tagger.backfill_face_focus(batch_size=8, max_batches=50, pause_sec=0.1)
            print('[FACE] Focus backfill:', r)
        except Exception as e:
            print(f'[FACE Focus] falhou: {e}')

    threading.Thread(target=_face_focus_bg, daemon=True, name='face-focus-backfill').start()

    def _prefetch_thumbs_bg():
        try:
            import time
            time.sleep(2)
            if not _env_on('THUMB_PREFETCH_ON_START', '1'):
                return
            from backend.services import thumb_pipeline as tp
            # Já agendado no import do app; aqui só reforça se __main__
            tp.start_background_warm(
                limit=int(os.getenv('THUMB_WARM_LIMIT', '120') or 120),
                workers=int(os.getenv('THUMB_WARM_WORKERS', '6') or 6),
            )
        except Exception as e:
            print(f"[Thumbs] Prefetch falhou: {e}")

    threading.Thread(target=_prefetch_thumbs_bg, daemon=True, name="thumb-prefetch").start()

    port = int(os.getenv("PORT", 3001))
    default_host = (
        "127.0.0.1"
        if os.getenv("FLASK_ENV", "production") != "development"
        else "0.0.0.0"
    )
    host = os.getenv("HOST", default_host)
    debug = os.getenv("FLASK_ENV", "production") == "development"

    if not is_auth_configured():
        print(
            "[SECURITY] AVISO: defina AUTH_USERS no .env "
            "para liberar o login da equipe."
        )

    print(f"Aleff Media System rodando em http://{host}:{port}")
    print(f"Login equipe: http://{host}:{port}/loginsite.html")
    print(f"Portfólio:     http://{host}:{port}/")
    print(f"Busca:         http://{host}:{port}/search.html")

    # Waitress: vários workers — vídeos grandes não travam a página
    if debug:
        app.run(host=host, port=port, debug=True, use_reloader=False, threaded=True)
    else:
        try:
            from waitress import serve
            threads = int(os.getenv("WAITRESS_THREADS", "12"))
            print(f"[HTTP] Waitress · {threads} threads (stream de vídeo ok)")
            serve(
                app,
                host=host,
                port=port,
                threads=threads,
                channel_timeout=120,
                connection_limit=200,
            )
        except ImportError:
            print("[HTTP] Waitress ausente — Flask threaded (instale: pip install waitress)")
            app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)
