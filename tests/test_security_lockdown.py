"""Regressões de lockdown / superfície pública / hardening."""
import os

import pytest

from backend.utils import security as sec


def test_portfolio_home_is_public():
    assert ('GET', '/api/portfolio/home') in sec._ALWAYS_PUBLIC


def test_thumbs_warm_not_anonymous():
    assert ('GET', '/api/thumbs/warm') not in sec._ALWAYS_PUBLIC
    assert ('POST', '/api/thumbs/warm') not in sec._ALWAYS_PUBLIC


def test_get_all_embeddings_disabled():
    from backend.models import database as db
    try:
        db.get_all_embeddings()
        assert False, 'deveria falhar'
    except RuntimeError as e:
        assert 'get_embeddings_for_ids' in str(e)


def test_public_originals_default_off(monkeypatch):
    monkeypatch.delenv('PUBLIC_MEDIA_ORIGINALS', raising=False)
    monkeypatch.delenv('PUBLIC_MEDIA_ORIGINALS_CONFIRM', raising=False)
    assert sec._public_originals_allowed() is False


def test_public_originals_needs_confirm_in_prod(monkeypatch):
    monkeypatch.setenv('PUBLIC_MEDIA_ORIGINALS', 'true')
    monkeypatch.setenv('FLASK_ENV', 'production')
    monkeypatch.delenv('PUBLIC_MEDIA_ORIGINALS_CONFIRM', raising=False)
    assert sec._public_originals_allowed() is False
    monkeypatch.setenv('PUBLIC_MEDIA_ORIGINALS_CONFIRM', 'i-understand')
    assert sec._public_originals_allowed() is True


def test_is_safe_image_url_blocks_ssrf():
    assert sec.is_safe_image_url('http://127.0.0.1/secret') is False
    assert sec.is_safe_image_url('https://169.254.169.254/latest/meta-data/') is False
    assert sec.is_safe_image_url('https://evil.example.com/x.jpg') is False
    assert sec.is_safe_image_url('/api/media/12/thumb-medium') is True
    assert sec.is_safe_image_url(
        'https://drive.google.com/thumbnail?id=abc&sz=w280'
    ) is True


def test_to_search_card_strips_drive_secrets():
    from backend.models.database import to_search_card

    card = to_search_card({
        'id': 99,
        'nome': 'x.jpg',
        'tipo': 'foto',
        'categoria': 'ensaio',
        'pasta': 'Teste',
        'tags': 'a,b,c',
        'autor': 'Aleff',
        'drive_id': '1AbCdEfGhIjK',
        'drive_link': 'https://drive.google.com/file/d/1AbCdEfGhIjK/view',
        'thumb_url': '',
    })
    assert 'drive_id' not in card
    assert 'drive_link' not in card
    assert 'thumb_drive' not in card
    assert card.get('id') == 99
    assert card.get('thumb_small') == '/api/media/99/thumb-small'


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv('API_LOCKDOWN', 'true')
    monkeypatch.setenv('FLASK_ENV', 'development')
    monkeypatch.setenv('PUBLIC_MEDIA_ORIGINALS', 'false')
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key-for-security')
    monkeypatch.setenv('ADMIN_USER', 'admin')
    monkeypatch.setenv('ADMIN_PASSWORD', 'test-admin-pass-xyz')
    # Evita side-effects pesados de boot
    monkeypatch.setenv('THUMB_PREFETCH_ON_START', '0')
    monkeypatch.setenv('CLIP_WARMUP_ON_START', '0')
    monkeypatch.setenv('FACE_WARMUP_ON_START', '0')
    from backend.server import app
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


def test_health_public_is_minimal(client):
    r = client.get('/health')
    assert r.status_code == 200
    data = r.get_json()
    assert 'status' in data
    assert 'db' in data
    assert 'media_count' not in data
    assert 'drive' not in data
    assert 'ai' not in data


def test_can_access_media_original_roles(monkeypatch):
    monkeypatch.setenv('PUBLIC_MEDIA_ORIGINALS', 'false')
    monkeypatch.setattr(sec, 'request_role', lambda: None)
    assert sec.can_access_media_original() is False
    monkeypatch.setattr(sec, 'request_role', lambda: 'admin')
    assert sec.can_access_media_original() is True
    monkeypatch.setattr(sec, 'request_role', lambda: 'dev')
    assert sec.can_access_media_original() is True


def test_download_attachment_requires_auth(client):
    r = client.get('/api/media/1/download')
    # 401/403 (auth) ou 404 (mídia inexistente) — nunca 200 com original anônimo
    assert r.status_code in (401, 403, 404)
    if r.status_code in (401, 403):
        body = r.get_json() or {}
        assert body.get('status') == 'error'


def test_download_head_also_protected(client, monkeypatch):
    from backend.routes import api as api_mod

    monkeypatch.setattr(
        api_mod,
        'get_media',
        lambda mid: {
            'id': mid,
            'nome': 'foto.jpg',
            'tipo': 'foto',
            'drive_id': 'local:deadbeefdeadbeef',
            'mime_type': 'image/jpeg',
        },
    )
    r = client.head('/api/media/42/download')
    assert r.status_code in (401, 403)


def test_download_view_redirects_to_thumb_when_exists(client, monkeypatch):
    """dl=0 sem auth → redirect thumb-medium (não HD)."""
    from backend.routes import api as api_mod

    monkeypatch.setattr(
        api_mod,
        'get_media',
        lambda mid: {
            'id': mid,
            'nome': 'foto.jpg',
            'tipo': 'foto',
            'drive_id': 'local:deadbeefdeadbeef',
            'mime_type': 'image/jpeg',
        },
    )
    r = client.get('/api/media/42/download?dl=0', follow_redirects=False)
    assert r.status_code == 302
    assert '/thumb-medium' in (r.headers.get('Location') or '')


def test_admin_download_allowed(client, monkeypatch):
    from backend.routes import api as api_mod
    from flask import Response

    monkeypatch.setattr(
        api_mod,
        'get_media',
        lambda mid: {
            'id': mid,
            'nome': 'foto.jpg',
            'tipo': 'foto',
            'drive_id': 'local:aabbccddeeff0011',
            'mime_type': 'image/jpeg',
        },
    )
    monkeypatch.setattr(
        api_mod.drive_svc,
        'open_media_file',
        lambda did: (None, 'image/jpeg'),
    )
    monkeypatch.setattr(api_mod, 'increment_downloads', lambda mid: None)
    monkeypatch.setattr(
        api_mod,
        'send_file',
        lambda *a, **k: Response(b'\xff\xd8\xff\xd9', mimetype='image/jpeg'),
    )

    with client.session_transaction() as sess:
        sess['admin'] = True
        sess['role'] = 'admin'
        sess['user'] = 'admin'

    r = client.get('/api/media/7/download?dl=1')
    assert r.status_code == 200


def test_media_list_requires_auth(client):
    r = client.get('/api/media')
    assert r.status_code in (401, 403)


def test_portfolio_slot_rejects_evil_src():
    from backend.services import portfolio_slots as ps
    with pytest.raises(ValueError):
        ps.update_slot('01', {'src': 'javascript:alert(1)'})
    with pytest.raises(ValueError):
        ps.update_slot('01', {'src': 'https://evil.com/x.jpg'})
    with pytest.raises(ValueError):
        ps.update_slot('01', {'src': '../etc/passwd'})
