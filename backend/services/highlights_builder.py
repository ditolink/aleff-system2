"""
highlights_builder.py — Destaques estilo Instagram (JSON para /data/highlights.json).

Monta sequências a partir do acervo curado (pick_best + scores WOW quando existirem).
"""
from __future__ import annotations

import os
import time

_CACHE: dict = {'ts': 0.0, 'payload': None}
_TTL = float(os.getenv('HIGHLIGHTS_CACHE_SEC', '300') or 300)

# Temas do rail — ordem narrativa do portfólio
HIGHLIGHT_THEMES = (
    {'id': 'casamento', 'label': 'Casamentos', 'keys': ('casamento', 'noiva', 'cerimonia', 'igreja')},
    {'id': 'casais', 'label': 'Casais', 'keys': ('casal', 'casais', 'pre wedding', 'romantico')},
    {'id': 'retratos', 'label': 'Retratos', 'keys': ('retrato', 'retratos', 'ensaio', 'editorial')},
    {'id': 'shows', 'label': 'Shows', 'keys': ('show', 'shows', 'palco', 'banda', 'sonata')},
    {'id': 'familia', 'label': 'Família', 'keys': ('familia', 'infantil', 'batismo', 'evento')},
)


def _thumb_src(media_id: int, tier: str = 'medium') -> str:
    mid = int(media_id)
    if tier == 'small':
        return f'api/media/{mid}/thumb-small'
    if tier == 'story':
        # Stories / fullscreen — preview (não original HD)
        return f'api/media/{mid}/thumb?sz=1200'
    return f'api/media/{mid}/thumb-medium'


def _item_from_row(row: dict) -> dict:
    mid = int(row['id'])
    title = (row.get('pasta') or row.get('nome') or 'Trabalho').strip()
    return {
        'type': 'img',
        'src': _thumb_src(mid, 'story'),
        'preview': _thumb_src(mid, 'medium'),
        'title': title,
        'mediaId': mid,
    }


def build_highlights_config(*, per_theme: int = 8, force_refresh: bool = False) -> dict:
    """Retorna { title, items: [{ label, cover, subtitle?, items: [...] }] }."""
    global _CACHE
    now = time.time()
    if not force_refresh and _CACHE.get('payload') and (now - float(_CACHE.get('ts') or 0)) < _TTL:
        return _CACHE['payload']

    from backend.models.database import pick_best_for_keys

    per = max(3, min(int(per_theme or 8), 16))
    rings = []

    for theme in HIGHLIGHT_THEMES:
        keys = list(theme['keys'])
        try:
            pool = pick_best_for_keys(
                keys,
                limit=max(per * 3, 24),
                tipo='image',
                max_per_pasta=2,
                diversify_faces=True,
            )
        except Exception as e:
            print(f'[highlights] {theme["id"]}: {e}')
            pool = []

        if len(pool) < 3:
            continue

        slides = [_item_from_row(it) for it in pool[:per]]
        cover_id = int(pool[0]['id'])
        rings.append({
            'id': theme['id'],
            'label': theme['label'],
            'subtitle': theme['label'],
            'cover': _thumb_src(cover_id, 'small'),
            'items': slides,
        })

    payload = {
        'title': 'Destaques',
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'items': rings,
    }
    _CACHE['payload'] = payload
    _CACHE['ts'] = now
    return payload
