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
from backend.services import clip_tagger
from backend.utils.validators import MAX_FILE_SIZE
from backend.utils.security import (
    path_needs_login,
    is_logged_in,
    is_auth_configured,
    reset_login_rate_limits,
    is_scanner_probe,
)

# static_folder=None → NÃO serve arquivos automaticamente (evita furar o login)
app = Flask(__name__, static_folder=None)

app.config["MAX_CONTENT_LENGTH"] = int(
    os.getenv("MAX_CONTENT_LENGTH", MAX_FILE_SIZE)
)

# Sessão segura (cookie HttpOnly)
_secret = (os.getenv("SECRET_KEY") or "").strip()
if not _secret:
    _secret = secrets.token_hex(32)
    print("[SECURITY] SECRET_KEY ausente no .env — usando chave temporária (sessões resetam ao reiniciar).")
app.config["SECRET_KEY"] = _secret
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(
    days=int(os.getenv("SESSION_DAYS", "7"))
)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.getenv("SESSION_COOKIE_SECURE", "false").lower() in (
    "1", "true", "yes",
)
app.config["SESSION_COOKIE_NAME"] = os.getenv("SESSION_COOKIE_NAME", "aleff_session")
# Não vazar traceback em produção
app.config["PROPAGATE_EXCEPTIONS"] = False

_cors_raw = os.getenv(
    "CORS_ORIGINS",
    "http://127.0.0.1:3001,http://localhost:3001",
)
_cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]
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
        response.headers["Cache-Control"] = "public, max-age=30, stale-while-revalidate=60"
    elif path.endswith((".css", ".js", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".mp4", ".webm")):
        response.headers["Cache-Control"] = "public, max-age=86400"
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
    return {"status": "ok"}


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
        online, err = drive_svc.drive_ping()
        email = drive_svc.get_service_account_email()
        if online:
            print("[Drive] Online — pasta acessível.")
        else:
            print(f"[Drive] Offline: {err}")
            if email:
                print(f"[Drive] Compartilhe a pasta com: {email}")
    except Exception as e:
        print(f"[Drive] falha na conexão inicial: {e}")

    def _warmup_clip_bg():
        try:
            if not getattr(clip_tagger, "is_enabled", lambda: True)():
                print("[CLIP] Desativado — busca rápida só com texto.")
                return
            thumb_urls = [
                m["thumb_url"] for m in get_all_media(limit=8) if m.get("thumb_url")
            ]
            clip_tagger.warmup(thumb_urls)
            print("[CLIP] Warmup em background concluído.")
        except Exception as e:
            print(f"[CLIP Warmup] falhou na inicialização: {e}")

    threading.Thread(target=_warmup_clip_bg, daemon=True, name="clip-warmup").start()
    if getattr(clip_tagger, "is_enabled", lambda: True)():
        print("[CLIP] Warmup em background — site já pode abrir (busca não espera o modelo).")
    else:
        print("[CLIP] Off — site leve, ideal pra hospedagem barata.")

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
    app.run(host=host, port=port, debug=debug, use_reloader=False)
