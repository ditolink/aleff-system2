"""code_viewer.py — Leitura segura de código (somente papel dev / system).

Nunca expõe .env, credenciais, bancos, chaves ou segredos.
Somente leitura. Sem escrita, sem shell, sem path traversal.
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Pastas que podem ser listadas/lidas
ALLOWED_ROOTS = (
    PROJECT_ROOT / "backend",
    PROJECT_ROOT / "frontend",
)

# Extensões legíveis
ALLOWED_EXT = frozenset({
    ".py", ".js", ".css", ".html", ".md", ".txt", ".toml",
    ".yml", ".yaml", ".example", ".gitignore", ".svg",
})

# Nomes/padrões bloqueados (case-insensitive)
BLOCKED_NAMES = frozenset({
    ".env", ".env.local", ".env.production", ".env.development",
    "credentials.json", "service-account.json", "service_account.json",
    "token.json", "client_secret.json", "secrets.json",
    "id_rsa", "id_ed25519", ".git-credentials",
})

BLOCKED_SUBSTRINGS = (
    "service-account",
    "service_account",
    "credentials",
    "client_secret",
    "private_key",
    "secret_key",
)

BLOCKED_DIRS = frozenset({
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".cursor", ".idea", ".vscode", "agent-transcripts",
    "terminals", "mcps",
})

MAX_BYTES = 180_000
MAX_TREE_ENTRIES = 800


def _is_blocked_name(name: str) -> bool:
    low = name.lower()
    if low in BLOCKED_NAMES:
        return True
    if low.startswith(".env"):
        return True
    if low.endswith((".sqlite", ".db", ".pem", ".key", ".p12", ".pfx", ".crt")):
        return True
    for frag in BLOCKED_SUBSTRINGS:
        if frag in low:
            return True
    return False


def _resolve_safe(rel: str) -> Path | None:
    """Resolve path relativo ao projeto; retorna None se inseguro."""
    raw = (rel or "").replace("\\", "/").strip().lstrip("/")
    if not raw or ".." in raw.split("/") or raw.startswith("~"):
        return None
    candidate = (PROJECT_ROOT / raw).resolve()
    try:
        candidate.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return None

    # deve estar sob uma raiz permitida
    under = False
    for root in ALLOWED_ROOTS:
        try:
            candidate.relative_to(root.resolve())
            under = True
            break
        except ValueError:
            continue
    if not under:
        return None

    # bloqueia dirs proibidos no caminho
    for part in candidate.parts:
        if part.lower() in BLOCKED_DIRS:
            return None
        if _is_blocked_name(part):
            return None

    return candidate


def list_tree(rel_dir: str = "") -> dict:
    base = _resolve_safe(rel_dir) if rel_dir else None
    if rel_dir and base is None:
        raise PermissionError("Caminho bloqueado.")
    if base is None:
        # raiz virtual: backend + frontend
        entries = []
        for root in ALLOWED_ROOTS:
            if root.is_dir():
                entries.append({
                    "name": root.name,
                    "path": root.name,
                    "type": "dir",
                })
        return {"path": "", "entries": entries}

    if not base.is_dir():
        raise FileNotFoundError("Pasta não encontrada.")

    entries = []
    try:
        children = sorted(base.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError as e:
        raise PermissionError(str(e)) from e

    for child in children:
        if len(entries) >= MAX_TREE_ENTRIES:
            break
        name = child.name
        if name.startswith(".") and name not in (".gitignore",):
            # permite .gitignore; bloqueia .env e similares
            if _is_blocked_name(name):
                continue
            if name not in (".gitignore",):
                continue
        if _is_blocked_name(name):
            continue
        if child.is_dir():
            if name.lower() in BLOCKED_DIRS:
                continue
            rel = str(child.relative_to(PROJECT_ROOT)).replace("\\", "/")
            entries.append({"name": name, "path": rel, "type": "dir"})
        elif child.is_file():
            if child.suffix.lower() not in ALLOWED_EXT and child.name != ".gitignore":
                # .example files
                if not name.endswith(".example"):
                    continue
            rel = str(child.relative_to(PROJECT_ROOT)).replace("\\", "/")
            entries.append({
                "name": name,
                "path": rel,
                "type": "file",
                "size": child.stat().st_size,
            })
    return {"path": str(base.relative_to(PROJECT_ROOT)).replace("\\", "/"), "entries": entries}


def read_file(rel: str) -> dict:
    path = _resolve_safe(rel)
    if path is None:
        raise PermissionError("Arquivo bloqueado ou caminho inválido.")
    if not path.is_file():
        raise FileNotFoundError("Arquivo não encontrado.")
    if _is_blocked_name(path.name):
        raise PermissionError("Arquivo sensível — acesso negado.")
    if path.suffix.lower() not in ALLOWED_EXT and path.name != ".gitignore" and not path.name.endswith(".example"):
        raise PermissionError("Tipo de arquivo não permitido.")

    size = path.stat().st_size
    if size > MAX_BYTES:
        raise PermissionError(f"Arquivo grande demais para visualizar (máx {MAX_BYTES // 1000}KB).")

    # leitura binária → texto; rejeita binário óbvio
    data = path.read_bytes()
    if b"\x00" in data[:4096]:
        raise PermissionError("Arquivo binário — não exibido.")

    # redacao defensiva de padrões de segredo em conteúdo
    text = data.decode("utf-8", errors="replace")
    text = _redact(text)

    return {
        "path": str(path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "name": path.name,
        "size": size,
        "content": text,
        "language": path.suffix.lstrip(".") or "text",
    }


def _redact(text: str) -> str:
    """Remove linhas que parecem secrets mesmo em arquivos permitidos."""
    import re
    lines = []
    secret_line = re.compile(
        r'(?i)(password|passwd|secret|api[_-]?key|token|private[_-]?key)\s*[:=]\s*\S+'
    )
    for line in text.splitlines(keepends=True):
        if secret_line.search(line):
            lines.append(re.sub(r'(=|:)\s*\S+', r'\1 ***REDACTED***', line, count=1))
        else:
            lines.append(line)
    out = ''.join(lines)
    out = re.sub(
        r'(?i)-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----',
        '***REDACTED PRIVATE KEY***',
        out,
    )
    out = re.sub(r'(?i)"private_key"\s*:\s*"[^"]+"', '"private_key":"***REDACTED***"', out)
    return out
