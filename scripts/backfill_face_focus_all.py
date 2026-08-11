"""Enquadra todos os rostos com InsightFace e regenera thumbs das categorias."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.models.database import get_conn, pick_best_for_keys, pick_best_home_items, pick_category_covers
from backend.services import face_tagger
from backend.services import thumb_pipeline as tp
from backend.services.search_engine import EXPLORE_THEME_KEYS, clear_search_result_cache


def main():
    print('[1/3] InsightFace…', face_tagger.is_installed())
    if not face_tagger.is_installed():
        print('Instale: pip install -r requirements-face.txt')
        return 1
    face_tagger.warmup()

    c = get_conn()
    missing = c.execute(
        """
        SELECT COUNT(*) FROM media_faces
        WHERE COALESCE(face_count,0)>=1 AND (face_cx IS NULL OR face_cy IS NULL)
        """
    ).fetchone()[0]
    c.close()
    print(f'[2/3] Backfill foco IA — faltam {missing} rostos…')
    # max_batches=0 → sem limite
    r = face_tagger.backfill_face_focus(batch_size=10, max_batches=0, pause_sec=0.02)
    print('backfill', r)

    print('[3/3] Regenerando thumbs das categorias / home…')
    explore = {
        k: v for k, v in EXPLORE_THEME_KEYS.items()
        if k in ('shows', 'casamento', 'retratos', 'casais', 'familia', 'infantil', 'ensaios', 'editorial')
    }
    ids = set()
    covers = pick_category_covers(explore, 560)
    for cov in covers.values():
        if cov.get('id'):
            ids.add(int(cov['id']))
    for cat, keys in explore.items():
        for it in pick_best_for_keys(list(keys), limit=60, tipo='image', max_per_pasta=4):
            ids.add(int(it['id']))
    for it in pick_best_home_items(limit=100, tipo='image', max_per_pasta=3):
        ids.add(int(it['id']))

    conn = get_conn()
    ok = face_n = 0
    for mid in sorted(ids):
        row = conn.execute('SELECT * FROM media WHERE id=?', (mid,)).fetchone()
        if not row:
            continue
        it = dict(row)
        for tier in (tp.TIER_MEDIUM, tp.TIER_SMALL):
            meta = tp.read_meta(mid, tier) or {}
            if int(meta.get('focus_v') or 0) != tp.FACE_FOCUS_VERSION or meta.get('focus') != 'face':
                p = tp.thumb_path(mid, tier)
                m = tp.meta_path(mid, tier)
                if p.is_file():
                    p.unlink()
                if m.is_file():
                    m.unlink()
        try:
            tp.ensure_thumb(it, tier=tp.TIER_MEDIUM)
            meta = tp.read_meta(mid, tp.TIER_MEDIUM) or {}
            ok += 1
            if meta.get('focus') == 'face':
                face_n += 1
        except Exception as e:
            print('thumb err', mid, e)
    conn.close()
    clear_search_result_cache()
    print(f'done thumbs={ok} with_face_focus={face_n} covers={ {k: v.get("id") for k,v in covers.items()} }')
    c2 = get_conn()
    print('db with_focus', c2.execute(
        'SELECT COUNT(*) FROM media_faces WHERE face_cx IS NOT NULL'
    ).fetchone()[0])
    print('db missing_focus', c2.execute(
        'SELECT COUNT(*) FROM media_faces WHERE face_count>=1 AND face_cx IS NULL'
    ).fetchone()[0])
    c2.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
