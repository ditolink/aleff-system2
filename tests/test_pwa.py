import json


def test_pwa_manifest_and_icons_are_served():
    from backend.server import app

    client = app.test_client()
    response = client.get('/manifest.webmanifest')

    assert response.status_code == 200
    assert response.mimetype == 'application/manifest+json'
    assert response.headers['Cache-Control'] == 'no-cache, must-revalidate'

    manifest = json.loads(response.get_data(as_text=True))
    icon_sizes = {icon['sizes'] for icon in manifest['icons']}
    assert {'192x192', '512x512'} <= icon_sizes

    for size in (192, 512):
        icon = client.get(f'/assets/pwa-icon-{size}.png')
        assert icon.status_code == 200
        assert icon.mimetype == 'image/png'


def test_pwa_service_worker_does_not_cache_api_routes():
    from backend.server import app

    response = app.test_client().get('/sw.js')

    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-cache, must-revalidate'
    assert b"url.pathname.startsWith('/api/')" in response.data