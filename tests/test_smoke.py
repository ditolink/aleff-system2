"""Smoke: app boot + observabilidade (sem depender de ranking novo)."""


def test_import_app():
    from backend.server import app
    assert app is not None


def test_observability_noop_without_env(monkeypatch):
    monkeypatch.delenv('SENTRY_DSN', raising=False)
    monkeypatch.delenv('OTEL_ENABLED', raising=False)
    monkeypatch.delenv('OTEL_EXPORTER_OTLP_ENDPOINT', raising=False)
    from backend.utils.observability import init_observability

    init_observability(None)


def test_agents_md_exists():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    assert (root / 'AGENTS.md').is_file()
    text = (root / 'AGENTS.md').read_text(encoding='utf-8')
    assert 'Fixes #' in text or 'Fixes #<N>' in text or 'Fixes #' in text.replace('<N>', '1')
    assert 'Issue' in text


def test_database_path_can_be_overridden_by_env(monkeypatch):
    import importlib
    from pathlib import Path

    monkeypatch.setenv('DATABASE_PATH', 'custom_data/prod_media.db')
    import backend.models.database as database_module
    importlib.reload(database_module)

    expected = (Path(__file__).resolve().parents[1] / 'custom_data' / 'prod_media.db').resolve()
    assert Path(database_module.DB_PATH).resolve() == expected


def test_get_conn_creates_missing_database_directory(monkeypatch, tmp_path):
    import importlib
    import backend.models.database as database_module

    missing_dir = tmp_path / 'missing' / 'nested'
    target_db = missing_dir / 'media.db'
    monkeypatch.setenv('DATABASE_PATH', str(target_db))
    importlib.reload(database_module)

    conn = database_module.get_conn()
    conn.execute('SELECT 1').fetchone()
    conn.close()

    assert target_db.parent.exists()
    assert target_db.exists()
