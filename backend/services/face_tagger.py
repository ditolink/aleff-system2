"""
face_tagger.py — Detecta rostos e agrupa a mesma pessoa (InsightFace / ArcFace).

Uso no reel de Contato: no máximo 1 foto por cluster de rosto.

Instalar (open source / grátis):
  pip install -r requirements-face.txt

Env:
  FACE_ENABLED=true   # padrão: false (servidor leve)
  FACE_SIM_THRESHOLD=0.42   # quanto maior, mais rigoroso (menos “mesmo rosto”)
"""
from __future__ import annotations

import os
import threading
from typing import Optional

try:  # numpy só existe quando os extras de IA estão instalados
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

FACE_ENABLED = os.getenv('FACE_ENABLED', 'false').lower().strip() in ('1', 'true', 'yes', 'on')
# ArcFace (buffalo_l): mesma pessoa costuma ficar acima de ~0.35–0.45
FACE_SIM_THRESHOLD = float(os.getenv('FACE_SIM_THRESHOLD', '0.42'))
FACE_MODEL = os.getenv('FACE_MODEL', 'buffalo_l')
FACE_DET_SIZE = int(os.getenv('FACE_DET_SIZE', '640'))

_app = None
_loading = False
_unavailable_reason = ''
_backfill_running = False
_lock = threading.Lock()


def is_enabled() -> bool:
    return FACE_ENABLED


_installed_cache = None


def is_installed() -> bool:
    """Checagem leve — não importa insightface/onnx (pesado)."""
    global _installed_cache
    if _installed_cache is not None:
        return _installed_cache
    import importlib.util
    _installed_cache = np is not None and all(
        importlib.util.find_spec(mod) is not None
        for mod in ('insightface', 'onnxruntime')
    )
    return _installed_cache


def is_ready() -> bool:
    return FACE_ENABLED and _app is not None


def get_status() -> dict:
    from backend.models.database import face_stats

    return {
        'enabled': FACE_ENABLED,
        'installed': is_installed(),
        'ready': is_ready(),
        'loaded': _app is not None,
        'model': FACE_MODEL,
        'threshold': FACE_SIM_THRESHOLD,
        'unavailable': _unavailable_reason or None,
        'backfill_running': _backfill_running,
        'index': face_stats(),
    }


def _load_app():
    global _app, _loading, _unavailable_reason
    if not FACE_ENABLED:
        raise RuntimeError('FACE_ENABLED=false')
    if _app is not None:
        return _app
    with _lock:
        if _app is not None:
            return _app
        if _loading:
            raise RuntimeError('InsightFace ainda carregando')
        _loading = True
        try:
            from insightface.app import FaceAnalysis

            providers = ['CPUExecutionProvider']
            try:
                import onnxruntime as ort
                avail = set(ort.get_available_providers())
                if 'CUDAExecutionProvider' in avail:
                    providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
            except Exception:
                pass

            print(f'[FACE] Carregando InsightFace ({FACE_MODEL}) — 1ª vez baixa o modelo…')
            app = FaceAnalysis(name=FACE_MODEL, providers=providers)
            # ctx_id=-1 = CPU; 0 = GPU
            ctx = 0 if providers[0].startswith('CUDA') else -1
            app.prepare(ctx_id=ctx, det_size=(FACE_DET_SIZE, FACE_DET_SIZE))
            _app = app
            _unavailable_reason = ''
            print(f'[FACE] Pronto ({providers[0]}).')
            return _app
        except Exception as e:
            _unavailable_reason = str(e)
            print(f'[FACE] Falha ao carregar: {e}')
            raise
        finally:
            _loading = False


def _pil_to_bgr(image):
    import cv2

    rgb = np.asarray(image.convert('RGB'))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na < 1e-9 or nb < 1e-9:
        return -1.0
    return float(np.dot(a, b) / (na * nb))


def _fetch_pil(media_id: Optional[int] = None, image_url: str = ''):
    from backend.services.clip_tagger import _fetch_image, _fetch_image_for_media_id

    image = None
    if media_id is not None:
        image = _fetch_image_for_media_id(int(media_id))
    if image is None and image_url:
        image = _fetch_image(image_url)
    return image


def detect_face_center_pil(image) -> Optional[tuple]:
    """Centro (cx, cy) 0–1 do maior rosto no PIL Image, ou None."""
    if image is None:
        return None
    try:
        app = _load_app()
        w, h = image.size
        max_side = max(w, h)
        work = image
        if max_side > 1280:
            scale = 1280 / max_side
            work = image.resize((max(1, int(w * scale)), max(1, int(h * scale))))
        bgr = _pil_to_bgr(work)
        faces = app.get(bgr) or []
        if not faces:
            return None

        def area(f):
            x1, y1, x2, y2 = f.bbox
            return max(0.0, float(x2 - x1)) * max(0.0, float(y2 - y1))

        best = max(faces, key=area)
        iw, ih = work.size
        x1, y1, x2, y2 = [float(v) for v in best.bbox]
        if iw <= 0 or ih <= 0:
            return None
        cx = max(0.0, min(1.0, ((x1 + x2) * 0.5) / float(iw)))
        cy = max(0.0, min(1.0, ((y1 + y2) * 0.5) / float(ih)))
        return cx, cy
    except Exception as e:
        print(f'[FACE] detect_face_center_pil: {e}')
        return None


def extract_primary_face(media_id=None, image_url=''):
    """
    Retorna dict {embedding: np.float32[512], score, face_count} ou None se sem rosto / falha.
    """
    try:
        app = _load_app()
        image = _fetch_pil(media_id, image_url)
        if image is None:
            return None
        # InsightFace trabalha melhor com resolução razoável
        w, h = image.size
        max_side = max(w, h)
        if max_side > 1280:
            scale = 1280 / max_side
            image = image.resize((max(1, int(w * scale)), max(1, int(h * scale))))
        bgr = _pil_to_bgr(image)
        faces = app.get(bgr) or []
        if not faces:
            return {'embedding': None, 'score': 0.0, 'face_count': 0}
        # Rosto principal = maior área (bbox)
        def area(f):
            x1, y1, x2, y2 = f.bbox
            return max(0.0, float(x2 - x1)) * max(0.0, float(y2 - y1))

        best = max(faces, key=area)
        emb = np.asarray(best.embedding, dtype=np.float32)
        # L2 normalize
        n = float(np.linalg.norm(emb))
        if n > 1e-9:
            emb = emb / n
        score = float(getattr(best, 'det_score', 0.0) or 0.0)
        # Centro do bbox no frame (0–1) — enquadramento de thumb/capa
        iw, ih = image.size
        cx = cy = None
        try:
            x1, y1, x2, y2 = [float(v) for v in best.bbox]
            if iw > 0 and ih > 0:
                cx = max(0.0, min(1.0, ((x1 + x2) * 0.5) / float(iw)))
                cy = max(0.0, min(1.0, ((y1 + y2) * 0.5) / float(ih)))
        except Exception:
            cx = cy = None
        return {
            'embedding': emb,
            'score': score,
            'face_count': len(faces),
            'face_cx': cx,
            'face_cy': cy,
        }
    except Exception as e:
        print(f'[FACE] extract falhou (media={media_id}): {e}')
        return None


def assign_cluster(emb: np.ndarray) -> int:
    """Casa com cluster existente (cosine) ou cria novo."""
    from backend.models.database import list_face_cluster_samples, next_face_cluster_id

    samples = list_face_cluster_samples(limit_per_cluster=3)
    best_cid = None
    best_sim = -1.0
    for cid, vecs in samples.items():
        for v in vecs:
            sim = _cosine(emb, v)
            if sim > best_sim:
                best_sim = sim
                best_cid = cid
    if best_cid is not None and best_sim >= FACE_SIM_THRESHOLD:
        return int(best_cid)
    return int(next_face_cluster_id())


def index_media_face(media_id: int, image_url: str = '') -> dict:
    """Detecta, agrupa e grava em media_faces. Sem rosto: face_count=0."""
    from backend.models.database import save_media_face, set_media_ai_status

    if not FACE_ENABLED:
        return {'ok': False, 'reason': 'disabled'}

    result = extract_primary_face(media_id=media_id, image_url=image_url)
    if result is None:
        set_media_ai_status(media_id, face_status='failed')
        return {'ok': False, 'reason': 'extract_failed'}

    face_count = int(result.get('face_count') or 0)
    emb = result.get('embedding')
    score = float(result.get('score') or 0.0)

    if face_count < 1 or emb is None:
        save_media_face(media_id, None, None, face_count=0, det_score=0.0)
        return {'ok': True, 'media_id': media_id, 'face_count': 0, 'cluster_id': None}

    cluster_id = assign_cluster(emb)
    save_media_face(
        media_id,
        emb.astype(np.float32).tobytes(),
        cluster_id,
        face_count=face_count,
        det_score=score,
        face_cx=result.get('face_cx'),
        face_cy=result.get('face_cy'),
    )
    return {
        'ok': True,
        'media_id': media_id,
        'face_count': face_count,
        'cluster_id': cluster_id,
        'score': score,
        'face_cx': result.get('face_cx'),
        'face_cy': result.get('face_cy'),
    }


def backfill_face_focus(batch_size=12, max_batches=40, pause_sec=0.1) -> dict:
    """
    Re-detecta rostos que já existem no índice mas sem face_cx/face_cy
    (necessário pro enquadramento centrado).
    """
    import time
    from backend.models.database import get_conn

    if not FACE_ENABLED:
        return {'ok': False, 'reason': 'disabled'}
    if not is_installed():
        return {'ok': False, 'reason': 'not_installed'}

    processed = 0
    ok_n = 0
    batches = 0
    try:
        _load_app()
        while True:
            if max_batches and batches >= max_batches:
                break
            conn = get_conn()
            rows = conn.execute(
                """
                SELECT m.id, m.thumb_url
                FROM media m
                JOIN media_faces f ON f.media_id = m.id
                WHERE m.tipo='image'
                  AND COALESCE(f.face_count,0)>=1
                  AND (f.face_cx IS NULL OR f.face_cy IS NULL)
                ORDER BY m.id DESC
                LIMIT ?
                """,
                (int(batch_size),),
            ).fetchall()
            conn.close()
            if not rows:
                break
            batches += 1
            for r in rows:
                mid = int(r['id'])
                processed += 1
                try:
                    res = index_media_face(mid, r['thumb_url'] or '')
                    if res.get('ok') and res.get('face_cx') is not None:
                        ok_n += 1
                        # Invalida thumbs antigas sem focus=face
                        try:
                            from backend.services import thumb_pipeline as tp
                            for tier in (tp.TIER_SMALL, tp.TIER_MEDIUM):
                                p = tp.thumb_path(mid, tier)
                                meta = tp.meta_path(mid, tier)
                                if p.is_file():
                                    p.unlink(missing_ok=True)
                                if meta.is_file():
                                    meta.unlink(missing_ok=True)
                        except Exception:
                            pass
                except Exception as e:
                    print(f'[FACE] focus backfill {mid}: {e}')
                if pause_sec:
                    time.sleep(pause_sec)
        return {'ok': True, 'processed': processed, 'with_focus': ok_n, 'batches': batches}
    except Exception as e:
        return {'ok': False, 'reason': str(e), 'processed': processed, 'with_focus': ok_n}


def backfill_faces(batch_size=16, max_batches=0, pause_sec=0.08) -> dict:
    global _backfill_running
    import time
    from backend.models.database import get_media_missing_faces, face_stats

    if not FACE_ENABLED:
        return {'ok': False, 'reason': 'disabled'}
    if _backfill_running:
        return {'ok': False, 'reason': 'already_running'}

    _backfill_running = True
    processed = 0
    ok_n = 0
    batches = 0
    try:
        _load_app()
        while True:
            if max_batches and batches >= max_batches:
                break
            items = get_media_missing_faces(limit=batch_size)
            if not items:
                break
            batches += 1
            for it in items:
                mid = int(it['id'])
                processed += 1
                try:
                    r = index_media_face(mid, it.get('thumb_url') or '')
                    if r.get('ok'):
                        ok_n += 1
                except Exception as e:
                    print(f'[FACE] backfill {mid}: {e}')
                if pause_sec:
                    time.sleep(pause_sec)
        return {'ok': True, 'processed': processed, 'indexed': ok_n, 'index': face_stats()}
    except Exception as e:
        return {'ok': False, 'reason': str(e), 'processed': processed, 'indexed': ok_n}
    finally:
        _backfill_running = False


def warmup():
    if not FACE_ENABLED or not is_installed():
        return False
    try:
        _load_app()
        return True
    except Exception:
        return False
