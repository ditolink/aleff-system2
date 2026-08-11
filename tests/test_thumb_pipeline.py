"""Testes do pipeline small/medium de thumbnails."""
from __future__ import annotations

import io
from pathlib import Path

import pytest


@pytest.fixture()
def tiny_jpeg_bytes():
    from PIL import Image

    img = Image.new('RGB', (640, 480), color=(40, 80, 120))
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=85)
    return buf.getvalue()


def test_thumb_pipeline_paths(tmp_path, monkeypatch):
    from backend.services import thumb_pipeline as tp

    monkeypatch.setattr(tp, '_project_root', lambda: tmp_path)
    p = tp.thumb_path(42, 'small')
    assert p.name == '42.webp'
    assert 'small' in str(p)
    assert not tp.is_ready(42, 'small')


def test_ensure_thumb_creates_webp(tmp_path, monkeypatch, tiny_jpeg_bytes):
    from backend.services import thumb_pipeline as tp

    monkeypatch.setattr(tp, '_project_root', lambda: tmp_path)

    item = {'id': 7, 'drive_id': 'local:abc', 'tipo': 'image'}

    def fake_source(_item, prefer_w):
        return tiny_jpeg_bytes

    monkeypatch.setattr(tp, '_source_bytes', fake_source)
    path = tp.ensure_thumb(item, tier='small')
    assert path.is_file()
    assert path.suffix == '.webp'
    assert path.stat().st_size > 80
    assert tp.is_ready(7, 'small')
    # segunda chamada = hit
    path2 = tp.ensure_thumb(item, tier='small')
    assert path2 == path
    stats = tp.get_stats()
    assert stats['hit'] >= 1
    assert stats['generated'] >= 1


def test_ensure_thumb_dedupe_concurrent(tmp_path, monkeypatch, tiny_jpeg_bytes):
    import threading
    from backend.services import thumb_pipeline as tp

    monkeypatch.setattr(tp, '_project_root', lambda: tmp_path)
    item = {'id': 99, 'drive_id': 'x', 'tipo': 'image'}
    calls = {'n': 0}

    def slow_source(_item, prefer_w):
        calls['n'] += 1
        import time
        time.sleep(0.05)
        return tiny_jpeg_bytes

    monkeypatch.setattr(tp, '_source_bytes', slow_source)
    errs = []

    def worker():
        try:
            tp.ensure_thumb(item, tier='medium')
        except Exception as e:
            errs.append(e)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errs
    assert tp.is_ready(99, 'medium')
    # geração efetiva uma vez (fonte pode ser chamada sob lock serializado = 1)
    assert calls['n'] == 1


def test_ensure_cover_thumb_landscape(tmp_path, monkeypatch, tiny_jpeg_bytes):
    from PIL import Image
    from backend.services import thumb_pipeline as tp

    monkeypatch.setattr(tp, '_project_root', lambda: tmp_path)
    # Retrato alto — capa deve sair mais larga que alta
    from PIL import Image as _I
    import io as _io
    tall = _I.new('RGB', (600, 900), color=(90, 40, 40))
    buf = _io.BytesIO()
    tall.save(buf, format='JPEG', quality=85)
    portrait_jpeg = buf.getvalue()

    item = {'id': 55, 'drive_id': 'local:cover', 'tipo': 'image'}
    monkeypatch.setattr(tp, '_source_bytes', lambda *_a, **_k: portrait_jpeg)
    monkeypatch.setattr(tp, '_resolve_face_focus', lambda *_a, **_k: (0.5, 0.28))
    monkeypatch.setattr(tp, '_detect_face_center_haar', lambda *_a, **_k: None)

    path = tp.ensure_cover_thumb(item)
    assert path.is_file()
    assert 'cover' in str(path)
    img = Image.open(path)
    assert img.size[0] > img.size[1]
    # hit na 2ª chamada
    assert tp.ensure_cover_thumb(item) == path


def test_urls_for_card_stable(tmp_path, monkeypatch):
    from backend.services import thumb_pipeline as tp

    monkeypatch.setattr(tp, '_project_root', lambda: tmp_path)
    urls = tp.urls_for_card(15)
    assert urls['thumb_small'] == '/api/media/15/thumb-small'
    assert urls['thumb_medium'] == '/api/media/15/thumb-medium'
    assert 'v=' not in urls['thumb_small']
    assert 'thumb_small_ready' not in urls  # light path
    urls2 = tp.urls_for_card(15, check_ready=True)
    assert 'thumb_small_ready' in urls2


def test_annotate_storage_includes_tiers(monkeypatch):
    from backend.models.database import annotate_storage

    out = annotate_storage({'id': 3, 'drive_id': 'driveABC', 'tipo': 'image'}, thumb_size=560)
    assert 'thumb_small' in out
    assert 'thumb_medium' in out
    assert '/thumb-small' in out['thumb_small']
    assert out['thumb_url']  # compat
    assert 'thumb_small_ready' not in out  # light=True default


def test_small_derived_from_medium(tmp_path, monkeypatch, tiny_jpeg_bytes):
    from backend.services import thumb_pipeline as tp

    monkeypatch.setattr(tp, '_project_root', lambda: tmp_path)
    item = {'id': 21, 'drive_id': 'x', 'tipo': 'image'}
    monkeypatch.setattr(tp, '_source_bytes', lambda *_a, **_k: tiny_jpeg_bytes)
    tp.ensure_thumb(item, tier='medium')
    assert tp.is_ready(21, 'medium')
    assert tp._ensure_small_from_medium(21)
    assert tp.is_ready(21, 'small')


def test_find_cached_thumb_any_size(tmp_path, monkeypatch, tiny_jpeg_bytes):
    from backend.services import drive as drive_svc
    from backend.services import thumb_pipeline as tp

    monkeypatch.setattr(drive_svc, '_thumbs_dir', lambda: tmp_path)
    # só tem size 560 — não o 800 que o medium pede
    p560 = drive_svc.thumb_cache_path('driveXYZ', 560)
    p560.write_bytes(tiny_jpeg_bytes)
    assert drive_svc.find_cached_thumb_bytes('driveXYZ', prefer_w=800) == tiny_jpeg_bytes

    # WebP sai em outro root
    monkeypatch.setattr(tp, '_project_root', lambda: tmp_path)
    item = {'id': 77, 'drive_id': 'driveXYZ', 'tipo': 'image'}
    path = tp.ensure_thumb(item, tier='medium')
    assert path.is_file()
