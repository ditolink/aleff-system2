"""Converte JPEG legado → WebP medium/small para IDs recentes (local, one-shot)."""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

from backend.models.database import get_all_media
from backend.services import thumb_pipeline as tp


def main():
    limit = int(os.getenv('BACKFILL_LIMIT', '400') or 400)
    workers = int(os.getenv('BACKFILL_WORKERS', '10') or 10)
    items = get_all_media(limit=limit)
    ids = [int(it['id']) for it in items]
    print(f'Backfill {len(ids)} ids, workers={workers}')
    stats = tp.warm_media_ids(ids, tiers=(tp.TIER_MEDIUM, tp.TIER_SMALL), workers=workers)
    print('done', stats)


if __name__ == '__main__':
    main()
