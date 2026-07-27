"""portfolio_slots.py — Espaços do portfólio (home) preenchíveis por admin/dev."""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
SLOTS_FILE = DATA_DIR / "portfolio_slots.json"
UPLOAD_DIR = PROJECT_ROOT / "frontend" / "fotos" / "slots"

_lock = threading.RLock()

DEFAULT_SLOTS = {
    "01": {
        "id": "01",
        "label": "Próximo ensaio",
        "shape": "p-tall",
        "placeholder": "Em breve",
        "filled": False,
    },
    "02": {
        "id": "02",
        "label": "Novo casal",
        "shape": "p-tall",
        "placeholder": "Em breve",
        "filled": False,
    },
    "03": {
        "id": "03",
        "label": "Novo vídeo",
        "shape": "p-tall",
        "placeholder": "Em breve",
        "filled": False,
    },
    "04": {
        "id": "04",
        "label": "Próximo destaque widescreen",
        "shape": "l-wide",
        "placeholder": "Reservado",
        "filled": False,
    },
}

_SAFE_NAME = re.compile(r"[^a-zA-Z0-9._\-]+")


def _ensure():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    if not SLOTS_FILE.exists():
        _write({"slots": DEFAULT_SLOTS, "version": 1})


def _write(payload: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SLOTS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SLOTS_FILE)


def load_slots() -> dict:
    _ensure()
    with _lock:
        try:
            raw = json.loads(SLOTS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {"slots": DEFAULT_SLOTS, "version": 1}
            _write(raw)
        slots = dict(DEFAULT_SLOTS)
        for sid, data in (raw.get("slots") or {}).items():
            if sid in slots and isinstance(data, dict):
                merged = {**slots[sid], **data, "id": sid}
                slots[sid] = merged
        return {"slots": slots, "version": int(raw.get("version") or 1)}


def get_slot(slot_id: str) -> dict | None:
    sid = str(slot_id).zfill(2)[-2:]
    data = load_slots()
    return data["slots"].get(sid)


def clear_slot(slot_id: str) -> dict | None:
    sid = str(slot_id).zfill(2)[-2:]
    if sid not in DEFAULT_SLOTS:
        return None
    with _lock:
        payload = load_slots()
        base = dict(DEFAULT_SLOTS[sid])
        old = payload["slots"].get(sid) or {}
        # remove arquivo local se for nosso upload
        src = (old.get("src") or "").replace("\\", "/")
        if src.startswith("fotos/slots/"):
            path = PROJECT_ROOT / "frontend" / src
            try:
                resolved = path.resolve()
                upload_root = UPLOAD_DIR.resolve()
                try:
                    resolved.relative_to(upload_root)
                    ok_path = True
                except ValueError:
                    ok_path = False
                if ok_path and resolved.is_file():
                    resolved.unlink(missing_ok=True)
            except OSError:
                pass
        payload["slots"][sid] = base
        payload["version"] = int(payload.get("version") or 1) + 1
        _write(payload)
        return base


def update_slot(slot_id: str, fields: dict) -> dict | None:
    sid = str(slot_id).zfill(2)[-2:]
    if sid not in DEFAULT_SLOTS:
        return None
    with _lock:
        payload = load_slots()
        cur = dict(payload["slots"].get(sid) or DEFAULT_SLOTS[sid])
        title = (fields.get("title") or cur.get("title") or "").strip()[:80]
        cat = (fields.get("cat") or fields.get("categoria") or cur.get("cat") or "").strip()[:80]
        src = (fields.get("src") or cur.get("src") or "").strip().replace("\\", "/")
        typ = (fields.get("type") or cur.get("type") or "img").strip().lower()
        if typ not in ("img", "video", "image"):
            typ = "img"
        if typ == "image":
            typ = "img"

        # só paths relativos seguros dentro de frontend
        if src:
            if src.startswith("/") or ".." in src or src.startswith("http"):
                # permite http(s) só de drive googleusercontent? melhor: só relativo
                if not (src.startswith("fotos/") or src.startswith("videos/")):
                    raise ValueError("Caminho de mídia inválido.")
            cur["src"] = src
            cur["filled"] = True
            cur["type"] = typ
            cur["title"] = title or "Sem título"
            cur["cat"] = cat or "Portfólio"
            cur["updated_at"] = datetime.now(timezone.utc).isoformat()
        if "label" in fields and fields["label"]:
            cur["label"] = str(fields["label"])[:60]
        if "placeholder" in fields and fields["placeholder"]:
            cur["placeholder"] = str(fields["placeholder"])[:40]

        payload["slots"][sid] = cur
        payload["version"] = int(payload.get("version") or 1) + 1
        _write(payload)
        return cur


def save_upload(slot_id: str, file_bytes: bytes, filename: str, mime: str, title: str = "", cat: str = "") -> dict:
    sid = str(slot_id).zfill(2)[-2:]
    if sid not in DEFAULT_SLOTS:
        raise ValueError("Slot inválido.")
    if not file_bytes:
        raise ValueError("Arquivo vazio.")
    if len(file_bytes) > 40 * 1024 * 1024:
        raise ValueError("Arquivo muito grande (máx 40MB).")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(filename or "").suffix.lower()
    if mime.startswith("image/"):
        typ = "img"
        if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            ext = ".jpg"
    elif mime.startswith("video/"):
        typ = "video"
        if ext not in (".mp4", ".webm", ".mov"):
            ext = ".mp4"
    else:
        raise ValueError("Envie foto ou vídeo.")

    safe = _SAFE_NAME.sub("-", Path(filename or f"slot-{sid}").stem)[:40] or f"slot-{sid}"
    out_name = f"{sid}-{safe}{ext}"
    out_path = UPLOAD_DIR / out_name
    out_path.write_bytes(file_bytes)
    rel = f"fotos/slots/{out_name}"

    return update_slot(sid, {
        "src": rel,
        "type": typ,
        "title": title or safe.replace("-", " ").title(),
        "cat": cat or "Portfólio",
    })
