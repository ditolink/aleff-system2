"""Red team controlado — regressões de segurança (Issue #24)."""
from __future__ import annotations

import pytest


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv('API_LOCKDOWN', 'true')
    monkeypatch.setenv('FLASK_ENV', 'development')
    monkeypatch.setenv('PUBLIC_MEDIA_ORIGINALS', 'false')
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key-redteam-24')
    monkeypatch.setenv('ADMIN_USER', 'admin')
    monkeypatch.setenv('ADMIN_PASSWORD', 'test-admin-pass-xyz')
    monkeypatch.setenv('THUMB_PREFETCH_ON_START', '0')
    monkeypatch.setenv('CLIP_WARMUP_ON_START', '0')
    monkeypatch.setenv('FACE_WARMUP_ON_START', '0')
    from backend.server import app
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


def test_safe_next_blocks_open_redirect():
    from backend.server import _safe_next

    assert _safe_next('//evil.com') == '/dashboard.html'
    assert _safe_next('/\\evil.com') == '/dashboard.html'
    assert _safe_next('/%2f%2fevil.com') == '/dashboard.html'
    assert _safe_next('https://evil.com') == '/dashboard.html'
    assert _safe_next('/http://evil.com') == '/dashboard.html'
    assert _safe_next('javascript:alert(1)') == '/dashboard.html'
    assert _safe_next('/dashboard.html') == '/dashboard.html'
    assert _safe_next('/admin') == '/admin.html'
    assert _safe_next('/upload.html') == '/upload.html'


def test_upload_filename_path_traversal_rejected():
    from backend.utils.validators import validate_file, safe_upload_basename

    ok, _ = validate_file('../../etc/passwd.jpg', 'image/jpeg', 100)
    assert ok is False
    ok, _ = validate_file('..\\windows\\system32\\x.jpg', 'image/jpeg', 100)
    assert ok is False
    assert safe_upload_basename('../../a/b/foto.jpg') == 'foto.jpg'
    ok, _ = validate_file('foto.jpg', 'image/jpeg', 100)
    assert ok is True


def test_public_user_cannot_download_original(client, monkeypatch):
    from backend.routes import api as api_mod

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
    r = client.get('/api/media/55/download?dl=1')
    assert r.status_code in (401, 403)


def test_public_user_cannot_access_drive_id(client):
    r = client.get('/api/media/1')
    if r.status_code == 404:
        pytest.skip('mídia 1 ausente neste ambiente')
    assert r.status_code == 200
    item = (r.get_json() or {}).get('item') or {}
    assert 'drive_id' not in item
    assert 'drive_link' not in item
    assert 'thumb_drive' not in item


def test_invalid_media_id_is_rejected(client):
    r = client.get('/api/media/abc')
    assert r.status_code in (404, 405)


def test_path_traversal_local_uid_rejected(client):
    r = client.get('/api/local/../../etc/passwd')
    assert r.status_code in (400, 401, 404)
    r = client.get('/api/local/not-hex-!!')
    assert r.status_code in (400, 401, 404)


def test_unauthorized_admin_endpoint_is_blocked(client):
    for path in (
        '/api/media',
        '/api/dashboard',
        '/api/dev/system',
        '/api/dev/tree',
        '/api/dev/file?path=backend/server.py',
        '/api/dev/file?path=../../.env',
    ):
        r = client.get(path)
        assert r.status_code in (401, 403), path


def test_csrf_required_when_authenticated(client):
    with client.session_transaction() as sess:
        sess['admin'] = True
        sess['role'] = 'admin'
        sess['user'] = 'admin'
        sess['csrf'] = 'token-esperado'
    r = client.delete('/api/media/999999')
    assert r.status_code == 403


def test_sensitive_files_are_not_public(client):
    for path in (
        '/.env',
        '/service-account.json',
        '/backend/services/service-account.json',
        '/data/media.db',
        '/backend/server.py',
    ):
        r = client.get(path)
        assert r.status_code in (403, 404), path


def test_security_headers(client):
    r = client.get('/health')
    assert r.status_code == 200
    assert r.headers.get('X-Content-Type-Options') == 'nosniff'
    assert r.headers.get('X-Frame-Options') == 'DENY'
    csp = r.headers.get('Content-Security-Policy') or ''
    assert "frame-ancestors 'none'" in csp


def test_no_debug_in_app(client):
    from backend.server import app

    assert app.debug is False
    assert app.config.get('PROPAGATE_EXCEPTIONS') is False


def test_anon_video_stream_is_inline_not_attachment(client, monkeypatch):
    from backend.routes import api as api_mod
    from flask import Response

    monkeypatch.setattr(
        api_mod,
        'get_media',
        lambda mid: {
            'id': mid,
            'nome': 'clip.mp4',
            'tipo': 'video',
            'drive_id': 'local:aabbccddeeff0011',
            'mime_type': 'video/mp4',
        },
    )
    monkeypatch.setattr(
        api_mod.drive_svc,
        'open_media_file',
        lambda did: ('/tmp/fake.mp4', 'video/mp4'),
    )

    def fake_send_file(*a, **k):
        resp = Response(b'ftypmp4', mimetype='video/mp4')
        if k.get('as_attachment'):
            resp.headers['Content-Disposition'] = 'attachment; filename=clip.mp4'
        return resp

    monkeypatch.setattr(api_mod, 'send_file', fake_send_file)
    r = client.get('/api/media/88/download?dl=0')
    assert r.status_code == 200
    cd = (r.headers.get('Content-Disposition') or '').lower()
    assert 'attachment' not in cd
    assert 'noindex' in (r.headers.get('X-Robots-Tag') or '')


def test_to_search_card_strips_local_uid():
    from backend.models.database import to_search_card

    card = to_search_card({
        'id': 42,
        'nome': 'x.mp4',
        'tipo': 'video',
        'categoria': '',
        'pasta': 'Test',
        'tags': '',
        'autor': '',
        'drive_id': 'local:deadbeefdeadbeef',
        'drive_link': '/api/local/deadbeefdeadbeef',
        'thumb_url': '/api/local/deadbeefdeadbeef',
    })
    blob = str(card)
    assert '/api/local/' not in blob
    assert 'drive_id' not in card
    assert card.get('thumb_proxy') == '/api/media/42/download?dl=0'


def test_admin_role_cannot_access_dev_code(client):
    with client.session_transaction() as sess:
        sess['admin'] = True
        sess['role'] = 'admin'
        sess['user'] = 'admin'
        sess['csrf'] = 'x'
    r = client.get('/api/dev/tree')
    assert r.status_code in (401, 403)


def test_admin_can_download_original(client, monkeypatch):
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
        lambda did: ('/tmp/x.jpg', 'image/jpeg'),
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
        sess['csrf'] = 'x'
    r = client.get('/api/media/7/download?dl=1')
    assert r.status_code == 200


def test_head_download_protected_for_anon(client, monkeypatch):
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


def test_prefetch_plan_hides_ids_from_anonymous(client):
    r = client.get('/api/thumbs/prefetch-plan?limit=50')
    assert r.status_code == 200
    data = r.get_json() or {}
    assert 'urls' in data
    assert 'ids' not in data
    assert int(data.get('total') or 0) <= 120


def test_prefetch_plan_ids_for_staff(client):
    with client.session_transaction() as sess:
        sess['admin'] = True
        sess['role'] = 'admin'
        sess['user'] = 'admin'
        sess['csrf'] = 'x'
    r = client.get('/api/thumbs/prefetch-plan?limit=50')
    assert r.status_code == 200
    data = r.get_json() or {}
    assert 'urls' in data
    assert 'ids' in data


def test_prefetch_anon_cannot_raise_limit_above_120(client):
    r = client.get('/api/thumbs/prefetch-plan?limit=999')
    assert r.status_code == 200
    data = r.get_json() or {}
    assert int(data.get('total') or 0) <= 120
    assert 'ids' not in data
