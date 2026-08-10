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
