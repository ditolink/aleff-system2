"""
ai_pipeline.py — Indexação CLIP + Faces em background (upload, sync, backfill).

Centraliza threads e status AI para não duplicar lógica em api.py.

Por padrão NÃO carrega os modelos no sync/upload — isso trava CPU/RAM
e faz o site parecer “ligando as IAs” por minutos.
Use Warmup no dashboard, ou AI_INDEX_ON_SYNC=1 / AI_INDEX_ON_UPLOAD=1.
"""
from __future__ import annotations

import os
import threading
from typing import Iterable, Sequence


def _env_on(name: str, default: str = '0') -> bool:
    return (os.getenv(name, default) or '').strip().lower() in ('1', 'true', 'yes', 'on')


def _clip_ready() -> bool:
    try:
        from backend.services.clip_tagger import is_ready
        return bool(is_ready())
    except Exception:
        return False


def _face_ready() -> bool:
    try:
        from backend.services.face_tagger import is_ready
        return bool(is_ready())
    except Exception:
        return False


def _run_clip_batch(items: Sequence[tuple[int, str]]) -> None:
    try:
        from backend.services.clip_tagger import encode_image_embedding, is_enabled
        from backend.models.database import save_media_embedding, set_media_ai_status
    except Exception as e:
        print(f"[CLIP] Pipeline indisponível: {e}")
        return
    if not is_enabled():
        return
    for mid, url in items:
        try:
            set_media_ai_status(mid, clip_status='processing')
            emb = encode_image_embedding(url, media_id=mid)
            if emb:
                save_media_embedding(mid, emb)
            else:
                set_media_ai_status(mid, clip_status='failed')
        except Exception as e:
            try:
                set_media_ai_status(mid, clip_status='failed')
            except Exception:
                pass
            print(f"[CLIP] Pipeline item {mid}: {e}")


def _run_face_batch(items: Sequence[tuple[int, str]]) -> None:
    try:
        from backend.services.face_tagger import index_media_face, is_enabled
    except Exception as e:
        print(f"[FACE] Pipeline indisponível: {e}")
        return
    if not is_enabled():
        return
    for mid, url in items:
        try:
            index_media_face(mid, url)
        except Exception as e:
            print(f"[FACE] Pipeline item {mid}: {e}")


def enqueue_media_ai(
    media_id: int,
    thumb_url: str,
    *,
    clip: bool = True,
    face: bool = True,
    force: bool = False,
) -> None:
    """
    Dispara CLIP e/ou Face para um único item.
    Sem force: só roda se o modelo já estiver em memória OU AI_INDEX_ON_UPLOAD=1.
    """
    do_clip = clip and (
        force or _clip_ready() or _env_on('AI_INDEX_ON_UPLOAD', '0')
    )
    do_face = face and (
        force or _face_ready() or _env_on('AI_INDEX_ON_UPLOAD', '0')
    )
    if clip and not do_clip:
        print(
            f"[CLIP] Skip upload#{media_id} — modelo idle "
            "(Warmup no dashboard ou AI_INDEX_ON_UPLOAD=1)."
        )
    if face and not do_face:
        print(
            f"[FACE] Skip upload#{media_id} — modelo idle "
            "(Warmup no dashboard ou AI_INDEX_ON_UPLOAD=1)."
        )
    if do_clip:
        threading.Thread(
            target=_run_clip_batch,
            args=([(int(media_id), thumb_url)],),
            daemon=True,
            name=f'clip-one-{media_id}',
        ).start()
    if do_face:
        threading.Thread(
            target=_run_face_batch,
            args=([(int(media_id), thumb_url)],),
            daemon=True,
            name=f'face-one-{media_id}',
        ).start()


def enqueue_media_ai_batch(
    items: Iterable[tuple[int, str]],
    *,
    clip: bool = True,
    face: bool = True,
    thread_prefix: str = 'sync',
    force: bool = False,
) -> int:
    """
    Enfileira um lote inteiro em até 2 threads (CLIP + Face).
    Sync NÃO carrega modelo por padrão (AI_INDEX_ON_SYNC=0).
    """
    batch = [(int(mid), str(url or '')) for mid, url in items if mid and url]
    if not batch:
        return 0

    allow_auto = force or _env_on('AI_INDEX_ON_SYNC', '0')
    do_clip = clip and (allow_auto or _clip_ready())
    do_face = face and (allow_auto or _face_ready())

    if clip and not do_clip:
        print(
            f"[CLIP] Sync: {len(batch)} item(ns) pendente(s) — "
            "não carrega modelo agora. Use Warmup/Backfill no dashboard "
            "ou AI_INDEX_ON_SYNC=1."
        )
    if face and not do_face:
        print(
            f"[FACE] Sync: {len(batch)} item(ns) pendente(s) — "
            "não carrega modelo agora. Use Warmup/Backfill no dashboard "
            "ou AI_INDEX_ON_SYNC=1."
        )

    if do_clip:
        threading.Thread(
            target=_run_clip_batch,
            args=(batch,),
            daemon=True,
            name=f'clip-{thread_prefix}-batch',
        ).start()
    if do_face:
        threading.Thread(
            target=_run_face_batch,
            args=(batch,),
            daemon=True,
            name=f'face-{thread_prefix}-batch',
        ).start()
    return len(batch) if (do_clip or do_face) else 0


def get_public_ai_summary() -> dict:
    """Resumo leve e seguro — usado em /health e /api/ai/status."""
    clip = {'enabled': False, 'ready': False, 'loaded': False}
    face = {'enabled': False, 'ready': False, 'installed': False}
    try:
        from backend.services.clip_tagger import get_model_info
        info = get_model_info()
        clip = {
            'enabled': bool(info.get('enabled')),
            'ready': bool(info.get('loaded')),
            'loaded': bool(info.get('loaded')),
            'installed': bool(info.get('installed')),
            'missing_index': (info.get('index') or {}).get('missing'),
        }
    except Exception:
        pass
    try:
        from backend.services.face_tagger import get_status
        finfo = get_status()
        face = {
            'enabled': bool(finfo.get('enabled')),
            'ready': bool(finfo.get('ready')),
            'installed': bool(finfo.get('installed')),
            'clusters': (finfo.get('index') or {}).get('clusters', 0),
            'missing': (finfo.get('index') or {}).get('missing', 0),
        }
    except Exception:
        pass
    return {'clip': clip, 'face': face}
