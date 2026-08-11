"""
thumb_pipeline.py — Pré-cache small/medium (WebP) para a busca.

Pipeline:
  media_cache / Drive thumb → PIL → data/thumbs/{small|medium}/{id}.webp

Não roda CLIP. Não baixa HD na pesquisa — gera a partir de fonte leve quando possível.
"""
from __future__ import annotations

import io
import json
import os
import threading
import time
from pathlib import Path

from backend.services import drive as drive_svc

# Tiers
TIER_SMALL = 'small'
TIER_MEDIUM = 'medium'
TIER_COVER = 'cover'  # capa larga dos botões de categoria (rosto no centro)
TIER_SIZES = {
    TIER_SMALL: int(os.getenv('THUMB_SMALL_PX', '320')),
    TIER_MEDIUM: int(os.getenv('THUMB_MEDIUM_PX', '800')),
    TIER_COVER: int(os.getenv('THUMB_COVER_PX', '800')),
}
TIER_QUALITY = {
    TIER_SMALL: int(os.getenv('THUMB_SMALL_Q', '62')),
    TIER_MEDIUM: int(os.getenv('THUMB_MEDIUM_Q', '78')),
    TIER_COVER: int(os.getenv('THUMB_COVER_Q', '76')),
}
# Proporção ≈ botão Explorar (largo/baixo ~2.9:1) — evita CSS cover cortar o rosto
COVER_ASPECT = float(os.getenv('THUMB_COVER_ASPECT', '2.85'))
# Bump só invalida capas panorâmicas (não small/medium)
COVER_FOCUS_VERSION = 4

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
_inflight: dict[str, threading.Event] = {}

_stats = {
    'hit': 0,
    'miss': 0,
    'generated': 0,
    'errors': 0,
    'dedupe_wait': 0,
    'gen_ms_small': 0.0,
    'gen_ms_medium': 0.0,
    'gen_n_small': 0,
    'gen_n_medium': 0,
}
_stats_lock = threading.Lock()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def thumbs_root() -> Path:
    d = _project_root() / 'data' / 'thumbs'
    d.mkdir(parents=True, exist_ok=True)
    return d


def tier_dir(tier: str) -> Path:
    if tier == TIER_COVER:
        t = TIER_COVER
    elif tier == TIER_SMALL:
        t = TIER_SMALL
    else:
        t = TIER_MEDIUM
    d = thumbs_root() / t
    d.mkdir(parents=True, exist_ok=True)
    return d


def thumb_path(media_id: int, tier: str = TIER_SMALL) -> Path:
    return tier_dir(tier) / f'{int(media_id)}.webp'


def meta_path(media_id: int, tier: str = TIER_SMALL) -> Path:
    return tier_dir(tier) / f'{int(media_id)}.json'


def thumb_version(media_id: int, tier: str = TIER_SMALL) -> str:
    p = thumb_path(media_id, tier)
    if p.is_file():
        try:
            return str(int(p.stat().st_mtime))
        except OSError:
            pass
    return '0'


def is_ready(media_id: int, tier: str = TIER_SMALL) -> bool:
    p = thumb_path(media_id, tier)
    return p.is_file() and p.stat().st_size > 80


def read_meta(media_id: int, tier: str = TIER_SMALL) -> dict:
    mp = meta_path(media_id, tier)
    if not mp.is_file():
        return {}
    try:
        return json.loads(mp.read_text(encoding='utf-8'))
    except Exception:
        return {}


def get_stats() -> dict:
    with _stats_lock:
        return dict(_stats)


def _bump(key: str, n: float | int = 1):
    with _stats_lock:
        _stats[key] = _stats.get(key, 0) + n


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        # Evita crescimento ilimitado após milhares de mídias
        if len(_locks) > 4000:
            # remove chaves sem dono aparente (locks não acquired) — best-effort
            stale = [k for k, lk in _locks.items() if k not in _inflight and not lk.locked()]
            for k in stale[:2000]:
                _locks.pop(k, None)
        lk = _locks.get(key)
        if lk is None:
            lk = threading.Lock()
            _locks[key] = lk
        return lk


# Bump quando o algoritmo de crop mudar — força regenerar thumbs focus=face
FACE_FOCUS_VERSION = 4


def _crop_landscape_face(img, cx: float, cy: float, aspect: float = COVER_ASPECT):
    """
    Recorte panorâmico com o rosto no centro — feito sob medida pros
    botões largos/baixos da grade Explorar (background-size: cover).
    """
    w, h = img.size
    if w < 32 or h < 32:
        return img
    try:
        cx = max(0.0, min(1.0, float(cx)))
        cy = max(0.0, min(1.0, float(cy)))
        aspect = max(1.2, float(aspect))
    except (TypeError, ValueError):
        return img
    # Maior janela possível na proporção da capa
    ch = min(h, int(round(w / aspect)))
    cw = int(round(ch * aspect))
    if cw > w:
        cw = w
        ch = max(16, int(round(cw / aspect)))
    fx, fy = cx * w, cy * h
    left = int(round(fx - cw * 0.5))
    # Rosto no meio vertical do retângulo da capa
    top = int(round(fy - ch * 0.50))
    left = max(0, min(left, w - cw))
    top = max(0, min(top, h - ch))
    return img.crop((left, top, left + cw, top + ch))


def ensure_cover_thumb(item: dict) -> Path:
    """
    Gera WebP panorâmico com rosto no centro pra capa do botão de categoria.
    """
    from PIL import Image

    mid = int(item['id'])
    path = thumb_path(mid, TIER_COVER)
    meta = read_meta(mid, TIER_COVER) or {}
    if (
        path.is_file()
        and path.stat().st_size > 80
        and int(meta.get('cover_v') or 0) == COVER_FOCUS_VERSION
        and meta.get('kind') == 'cover'
    ):
        return path

    key = f'{mid}:cover'
    lk = _lock_for(key)
    with lk:
        meta = read_meta(mid, TIER_COVER) or {}
        if (
            path.is_file()
            and path.stat().st_size > 80
            and int(meta.get('cover_v') or 0) == COVER_FOCUS_VERSION
            and meta.get('kind') == 'cover'
        ):
            return path

        prefer_w = max(TIER_SIZES[TIER_COVER], 900)
        raw = _source_bytes(item, prefer_w)
        if not raw:
            raise RuntimeError(f'Cover source unavailable for media {mid}')

        img = Image.open(io.BytesIO(raw))
        if img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')
        elif img.mode == 'L':
            img = img.convert('RGB')

        # Detecta no bitmap que vamos cortar (coords do DB podem ser de outra fonte)
        cx = cy = None
        try:
            from backend.services import face_tagger
            if face_tagger.is_enabled() and face_tagger.is_installed():
                detected_ai = face_tagger.detect_face_center_pil(img)
                if detected_ai:
                    cx, cy = detected_ai
        except Exception:
            pass
        if cx is None:
            detected = _detect_face_center_haar(img)
            if detected:
                cx, cy = detected
        if cx is None:
            cx, cy = _resolve_face_focus(mid, img)
        if cx is None or cy is None:
            # Sem rosto: terço superior (retratos típicos)
            cx, cy = 0.5, 0.32
        img = _crop_landscape_face(img, cx, cy, COVER_ASPECT)

        max_w = TIER_SIZES[TIER_COVER]
        w, h = img.size
        if w > max_w and w > 0:
            nh = max(1, int(round(h * (max_w / float(w)))))
            img = img.resize((max_w, nh), Image.Resampling.LANCZOS)
            w, h = img.size

        out = io.BytesIO()
        img.save(out, format='WEBP', quality=TIER_QUALITY[TIER_COVER], method=4)
        tmp = path.with_suffix('.webp.part')
        try:
            tmp.write_bytes(out.getvalue())
            os.replace(tmp, path)
        finally:
            if tmp.is_file():
                try:
                    tmp.unlink()
                except OSError:
                    pass
        try:
            meta_path(mid, TIER_COVER).write_text(
                json.dumps({
                    'w': w, 'h': h, 'tier': TIER_COVER, 'kind': 'cover',
                    'ts': int(time.time()),
                    'focus': 'face' if cx is not None else 'none',
                    'focus_v': FACE_FOCUS_VERSION,
                    'cover_v': COVER_FOCUS_VERSION,
                    'face_cx': cx, 'face_cy': cy,
                    'aspect': COVER_ASPECT,
                }),
                encoding='utf-8',
            )
        except OSError:
            pass
        return path


def _crop_face_focus(img, cx: float, cy: float):
    """
    Recorte leve no rosto (mantém aspect ratio).
    Zoom moderado + um pouco de espaço acima (cabelo/testa) pra não
    cortar a cabeça e deixar só o queixo na capa/grid.
    """
    w, h = img.size
    if w < 32 or h < 32:
        return img
    try:
        cx = max(0.0, min(1.0, float(cx)))
        cy = max(0.0, min(1.0, float(cy)))
    except (TypeError, ValueError):
        return img
    # Zoom leve + rosto quase no centro (sobe um pouco a testa, sem cortar o queixo)
    s = 0.90
    cw = max(16, int(round(w * s)))
    ch = max(16, int(round(h * s)))
    fx = cx * w
    fy = cy * h
    left = int(round(fx - cw * 0.5))
    # 46% do quadro: um pouco abaixo do 40% anterior (desce o enquadramento)
    top = int(round(fy - ch * 0.46))
    left = max(0, min(left, w - cw))
    top = max(0, min(top, h - ch))
    if left == 0 and top == 0 and cw == w and ch == h:
        return img
    return img.crop((left, top, left + cw, top + ch))


_haar_cascade = None


def _detect_face_center_haar(img):
    """Fallback leve (OpenCV Haar) quando InsightFace não gravou face_cx/cy."""
    global _haar_cascade
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None
    try:
        if _haar_cascade is None:
            path = getattr(cv2.data, 'haarcascades', '') + 'haarcascade_frontalface_default.xml'
            _haar_cascade = cv2.CascadeClassifier(path)
        if _haar_cascade is None or _haar_cascade.empty():
            return None
        rgb = np.asarray(img.convert('RGB'))
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        h, w = gray.shape[:2]
        if w < 40 or h < 40:
            return None
        min_side = max(20, min(w, h) // 25)
        faces = _haar_cascade.detectMultiScale(
            gray,
            scaleFactor=1.05,
            minNeighbors=3,
            flags=cv2.CASCADE_SCALE_IMAGE,
            minSize=(min_side, min_side),
        )
        if faces is None or len(faces) == 0:
            # 2ª tentativa com cascade alt2
            alt = cv2.CascadeClassifier(
                getattr(cv2.data, 'haarcascades', '') + 'haarcascade_frontalface_alt2.xml'
            )
            if not alt.empty():
                faces = alt.detectMultiScale(
                    gray, scaleFactor=1.05, minNeighbors=3,
                    flags=cv2.CASCADE_SCALE_IMAGE, minSize=(min_side, min_side),
                )
        if faces is None or len(faces) == 0:
            return None
        x, y, fw, fh = max(faces, key=lambda f: int(f[2]) * int(f[3]))
        cx = (float(x) + float(fw) * 0.5) / float(w)
        cy = (float(y) + float(fh) * 0.5) / float(h)
        return max(0.0, min(1.0, cx)), max(0.0, min(1.0, cy))
    except Exception:
        return None


def _resolve_face_focus(media_id: int, img):
    """DB → InsightFace (IA) → Haar; persiste o centro quando achar."""
    try:
        from backend.models.database import get_face_focus, update_face_focus
        foc = get_face_focus(media_id)
        if foc:
            return foc['cx'], foc['cy']

        # IA de rostos (InsightFace) — preferida quando instalada
        try:
            from backend.services import face_tagger
            if face_tagger.is_enabled() and face_tagger.is_installed():
                result = face_tagger.extract_primary_face(media_id=int(media_id))
                if result and int(result.get('face_count') or 0) >= 1:
                    cx, cy = result.get('face_cx'), result.get('face_cy')
                    if cx is not None and cy is not None:
                        try:
                            # Atualiza só o centro; se ainda não há linha, update_face_focus cria stub
                            update_face_focus(media_id, cx, cy)
                        except Exception:
                            pass
                        return float(cx), float(cy)
        except Exception:
            pass

        detected = _detect_face_center_haar(img)
        if detected:
            cx, cy = detected
            try:
                update_face_focus(media_id, cx, cy)
            except Exception:
                pass
            return cx, cy
    except Exception:
        pass
    return None, None


def _resize_to_webp(
    raw: bytes,
    max_w: int,
    quality: int,
    *,
    face_cx=None,
    face_cy=None,
) -> tuple[bytes, int, int]:
    from PIL import Image

    img = Image.open(io.BytesIO(raw))
    if img.mode not in ('RGB', 'L'):
        img = img.convert('RGB')
    elif img.mode == 'L':
        img = img.convert('RGB')
    if face_cx is not None and face_cy is not None:
        img = _crop_face_focus(img, face_cx, face_cy)
    w, h = img.size
    if w > max_w and w > 0:
        nh = max(1, int(round(h * (max_w / float(w)))))
        img = img.resize((max_w, nh), Image.Resampling.LANCZOS)
        w, h = img.size
    out = io.BytesIO()
    img.save(out, format='WEBP', quality=quality, method=4)
    return out.getvalue(), w, h


def _source_bytes(item: dict, prefer_w: int) -> bytes | None:
    """Origem leve preferencial — não baixa HD se puder evitar."""
    did = (item.get('drive_id') or '').strip()
    if not did:
        return None

    # 1) arquivo local (upload)
    local = drive_svc.resolve_local_path(did)
    if local and local.is_file():
        try:
            return local.read_bytes()
        except OSError:
            pass

    # 2) media_cache em disco
    try:
        cache = drive_svc.media_cache_path(did)
        if cache.is_file() and cache.stat().st_size > 200:
            return cache.read_bytes()
    except Exception:
        pass

    # 3) thumb JPEG já cacheada (qualquer size em data/thumbs/{hash}.jpg)
    try:
        legacy = drive_svc.find_cached_thumb_bytes(did, prefer_w=prefer_w)
        if legacy:
            return legacy
    except Exception:
        pass

    # 4) Drive public thumbnail (leve)
    try:
        public = drive_svc._try_public_thumb(did, size=prefer_w)
        if public:
            raw, _mime = public
            # também grava no cache legado pra reuso
            try:
                legacy_path = drive_svc.thumb_cache_path(did, size=prefer_w)
                legacy_path.write_bytes(raw)
            except OSError:
                pass
            return raw
    except Exception:
        pass

    # 5) fetch_thumbnail_bytes (API SA / cache — sem full download)
    try:
        raw, _mime = drive_svc.fetch_thumbnail_bytes(did, size=prefer_w, use_cache=True)
        if raw:
            return raw
    except Exception:
        pass

    return None


def ensure_thumb(item: dict, tier: str = TIER_SMALL) -> Path:
    """
    Garante WebP em disco. Thread-safe: requests concorrentes aguardam a 1ª geração.
    """
    tier = TIER_SMALL if tier == TIER_SMALL else TIER_MEDIUM
    mid = int(item['id'])
    path = thumb_path(mid, tier)

    def _thumb_is_fresh() -> bool:
        if not (path.is_file() and path.stat().st_size > 80):
            return False
        try:
            meta = read_meta(mid, tier) or {}
            # Thumbs novas marcam focus=face|none + versão do algoritmo
            if meta.get('focus') not in ('face', 'none'):
                return False
            return int(meta.get('focus_v') or 0) == FACE_FOCUS_VERSION
        except Exception:
            return True

    if _thumb_is_fresh():
        _bump('hit')
        return path

    key = f'{mid}:{tier}'
    lk = _lock_for(key)
    with lk:
        if _thumb_is_fresh():
            _bump('hit')
            return path

        # Sinaliza inflight pra telemetria
        with _locks_guard:
            if key in _inflight:
                _bump('dedupe_wait')
            ev = _inflight.setdefault(key, threading.Event())

        t0 = time.perf_counter()
        try:
            _bump('miss')
            prefer_w = TIER_SIZES[tier]
            raw = _source_bytes(item, prefer_w)
            if not raw:
                _bump('errors')
                raise RuntimeError(f'Thumb source unavailable for media {mid}')

            from PIL import Image as _Image
            _probe = _Image.open(io.BytesIO(raw))
            if _probe.mode not in ('RGB', 'L'):
                _probe = _probe.convert('RGB')
            elif _probe.mode == 'L':
                _probe = _probe.convert('RGB')
            face_cx, face_cy = _resolve_face_focus(mid, _probe)

            webp, w, h = _resize_to_webp(
                raw,
                prefer_w,
                TIER_QUALITY[tier],
                face_cx=face_cx,
                face_cy=face_cy,
            )
            tmp = path.with_suffix('.webp.part')
            try:
                tmp.write_bytes(webp)
                os.replace(tmp, path)
            finally:
                if tmp.is_file():
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
            try:
                meta_path(mid, tier).write_text(
                    json.dumps({
                        'w': w, 'h': h, 'tier': tier, 'ts': int(time.time()),
                        'focus': 'face' if (face_cx is not None and face_cy is not None) else 'none',
                        'focus_v': FACE_FOCUS_VERSION,
                        'face_cx': face_cx, 'face_cy': face_cy,
                    }),
                    encoding='utf-8',
                )
            except OSError:
                pass
            ms = (time.perf_counter() - t0) * 1000
            _bump('generated')
            if tier == TIER_SMALL:
                _bump('gen_ms_small', ms)
                _bump('gen_n_small')
            else:
                _bump('gen_ms_medium', ms)
                _bump('gen_n_medium')
            return path
        finally:
            ev.set()
            with _locks_guard:
                _inflight.pop(key, None)


def urls_for_card(media_id: int, *, check_ready: bool = False) -> dict:
    """
    URLs estáveis (sem ?v=0→mtime) pra o browser/prefetch baterem no mesmo cache.
    Invalidação via ETag/Last-Modified no send_file.
    check_ready=False na busca (evita 2×stat por card).
    """
    mid = int(media_id)
    out = {
        'thumb_small': f'/api/media/{mid}/thumb-small',
        'thumb_medium': f'/api/media/{mid}/thumb-medium',
    }
    if check_ready:
        out['thumb_small_ready'] = is_ready(mid, TIER_SMALL)
        out['thumb_medium_ready'] = is_ready(mid, TIER_MEDIUM)
    return out


def dims_for_card(media_id: int) -> tuple[int | None, int | None]:
    meta = read_meta(media_id, TIER_MEDIUM) or read_meta(media_id, TIER_SMALL)
    try:
        w = int(meta.get('w') or 0) or None
        h = int(meta.get('h') or 0) or None
        return w, h
    except (TypeError, ValueError):
        return None, None


def _ensure_small_from_medium(mid: int) -> bool:
    """Se medium existe, deriva small sem ir ao Drive."""
    if is_ready(mid, TIER_SMALL):
        return True
    med = thumb_path(mid, TIER_MEDIUM)
    if not (med.is_file() and med.stat().st_size > 80):
        return False
    try:
        raw = med.read_bytes()
        # Medium já veio com focus=face se aplicável — não recorta de novo
        webp, w, h = _resize_to_webp(raw, TIER_SIZES[TIER_SMALL], TIER_QUALITY[TIER_SMALL])
        path = thumb_path(mid, TIER_SMALL)
        tmp = path.with_suffix('.webp.part')
        try:
            tmp.write_bytes(webp)
            os.replace(tmp, path)
        finally:
            if tmp.is_file():
                try:
                    tmp.unlink()
                except OSError:
                    pass
        try:
            med_meta = read_meta(mid, TIER_MEDIUM) or {}
            meta_path(mid, TIER_SMALL).write_text(
                json.dumps({
                    'w': w, 'h': h, 'tier': TIER_SMALL, 'ts': int(time.time()),
                    'from': 'medium',
                    'focus': med_meta.get('focus') or 'none',
                    'focus_v': med_meta.get('focus_v') or FACE_FOCUS_VERSION,
                    'face_cx': med_meta.get('face_cx'),
                    'face_cy': med_meta.get('face_cy'),
                }),
                encoding='utf-8',
            )
        except OSError:
            pass
        _bump('generated')
        return True
    except Exception:
        return False


def warm_media_ids(
    ids: list[int],
    *,
    tiers: tuple[str, ...] = (TIER_SMALL, TIER_MEDIUM),
    workers: int = 6,
) -> dict:
    """
    Pré-gera WebPs em paralelo no disco.
    Batch-load SQLite; medium primeiro; small derivado do medium quando possível.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from backend.models.database import get_media_many

    id_list = []
    seen = set()
    for raw in ids or []:
        try:
            mid = int(raw)
        except Exception:
            continue
        if mid in seen:
            continue
        seen.add(mid)
        id_list.append(mid)

    want_medium = TIER_MEDIUM in tiers or not tiers
    want_small = TIER_SMALL in tiers
    if not want_medium and not want_small:
        want_medium = True

    rows = get_media_many(id_list)
    ok = 0
    fail = 0
    skip = 0

    def _one(mid: int):
        item = rows.get(mid)
        if not item or (item.get('tipo') or '') == 'video':
            return 'skip'
        did_work = False
        if want_medium and not is_ready(mid, TIER_MEDIUM):
            ensure_thumb(item, tier=TIER_MEDIUM)
            did_work = True
        if want_small and not is_ready(mid, TIER_SMALL):
            if not _ensure_small_from_medium(mid):
                ensure_thumb(item, tier=TIER_SMALL)
            did_work = True
        return 'ok' if did_work else 'skip'

    workers = max(1, min(int(workers or 6), 12))
    if not id_list:
        return {'ok': 0, 'fail': 0, 'skip': 0, 'total': 0}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_one, mid): mid for mid in id_list}
        for fut in as_completed(futs):
            try:
                r = fut.result()
                if r == 'ok':
                    ok += 1
                else:
                    skip += 1
            except Exception as e:
                fail += 1
                mid = futs[fut]
                print(f'[thumb_pipeline] warm {mid}: {e}')

    return {'ok': ok, 'fail': fail, 'skip': skip, 'total': len(id_list)}


_warm_lock = threading.Lock()
_warm_running = False

_plan_cache: dict = {'ids': [], 'ts': 0.0, 'limit': 0}
_plan_cache_lock = threading.Lock()
_PLAN_TTL = float(os.getenv('THUMB_PLAN_CACHE_TTL', '45') or 45)


def get_prefetch_plan_cached(limit: int = 120) -> list[int]:
    """Plano home+categorias com cache curto (warm + prefetch-plan)."""
    lim = max(8, min(int(limit or 120), 400))
    now = time.time()
    with _plan_cache_lock:
        if (
            _plan_cache['ids']
            and _plan_cache['limit'] == lim
            and (now - float(_plan_cache['ts'])) < _PLAN_TTL
        ):
            return list(_plan_cache['ids'])
    ids = build_prefetch_plan(limit=lim)
    with _plan_cache_lock:
        _plan_cache['ids'] = list(ids)
        _plan_cache['ts'] = now
        _plan_cache['limit'] = lim
    return ids


def start_background_warm(limit: int = 120, workers: int = 6) -> bool:
    """Dispara warm do plano home+categorias uma vez (não bloqueia)."""
    global _warm_running
    with _warm_lock:
        if _warm_running:
            return False
        _warm_running = True

    def _run():
        global _warm_running
        try:
            ids = get_prefetch_plan_cached(limit=limit)
            # medium primeiro (é o que o grid usa)
            print(f'[Thumbs] Pré-render: {len(ids)} mídia(s)…')
            stats = warm_media_ids(ids, tiers=(TIER_MEDIUM, TIER_SMALL), workers=workers)
            print(f'[Thumbs] Pré-render ok={stats["ok"]} skip={stats["skip"]} fail={stats["fail"]}')
        except Exception as e:
            print(f'[Thumbs] Pré-render falhou: {e}')
        finally:
            with _warm_lock:
                _warm_running = False

    threading.Thread(target=_run, daemon=True, name='thumb-warm-plan').start()
    return True


def build_prefetch_plan(limit: int = 80) -> list[int]:
    """
    IDs prioritários: home pool → categorias explore → tagged.
    Não varre o acervo inteiro.
    """
    from backend.models import database as db

    lim = max(8, min(int(limit or 80), 400))
    seen: set[int] = set()
    out: list[int] = []

    def _add(items):
        for it in items or []:
            try:
                mid = int(it['id'])
            except Exception:
                continue
            if mid in seen:
                continue
            if (it.get('tipo') or '') == 'video':
                continue
            seen.add(mid)
            out.append(mid)
            if len(out) >= lim:
                return True
        return False

    try:
        home = db.pick_best_home_items(limit=min(160, lim), tipo='image', max_per_pasta=2)
        if _add(home):
            return out
    except Exception as e:
        print(f'[thumb_pipeline] home plan: {e}')

    try:
        from backend.services.search_engine import EXPLORE_THEME_KEYS

        for cat, keys in list(EXPLORE_THEME_KEYS.items())[:8]:
            if cat in ('show', 'retrato', 'casal', 'noiva', 'moto', 'pre wedding'):
                continue
            pool = db.pick_best_for_keys(
                list(keys)[:4],
                limit=16,
                tipo='image',
                max_per_pasta=3,
                diversify_faces=False,
            )
            if _add(pool):
                return out
    except Exception as e:
        print(f'[thumb_pipeline] theme plan: {e}')

    # Completa com recentes (têm JPEG legado com frequência)
    try:
        recent = db.get_all_media(limit=lim)
        _add(recent)
    except Exception as e:
        print(f'[thumb_pipeline] recent plan: {e}')

    return out
