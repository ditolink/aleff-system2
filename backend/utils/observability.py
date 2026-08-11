"""
Observabilidade opcional: Sentry + OpenTelemetry.

Ativa só com env configurada — não quebra o boot se libs faltarem.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("aleff.observability")


def _truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def init_observability(app=None):
    """Chamar depois de criar o Flask app."""
    _init_sentry(app)
    _init_otel(app)


def _init_sentry(app=None):
    dsn = (os.getenv("SENTRY_DSN") or "").strip()
    if not dsn:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration

        sentry_sdk.init(
            dsn=dsn,
            integrations=[FlaskIntegration()],
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
            environment=os.getenv("SENTRY_ENVIRONMENT", os.getenv("FLASK_ENV", "production")),
            send_default_pii=False,
        )
        log.info("Sentry ativo")
    except Exception as e:
        log.warning("Sentry não inicializado: %s", e)


def _init_otel(app=None):
    if not _truthy("OTEL_ENABLED") and not (os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip():
        return
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.flask import FlaskInstrumentor

        resource = Resource.create({
            "service.name": os.getenv("OTEL_SERVICE_NAME", "aleff-system2"),
        })
        provider = TracerProvider(resource=resource)
        endpoint = (os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip()
        if endpoint:
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        trace.set_tracer_provider(provider)
        if app is not None:
            FlaskInstrumentor().instrument_app(app)
        log.info("OpenTelemetry ativo (OTLP)")
    except Exception as e:
        log.warning("OpenTelemetry não inicializado: %s", e)
