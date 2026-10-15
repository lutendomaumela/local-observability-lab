import hmac
import json
import logging
import os
import random
import threading
import time
from datetime import datetime, timezone

import psycopg
from flask import Flask, g, jsonify, request
from prometheus_client import Counter, Histogram, generate_latest
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


REQUESTS = Counter(
    "http_requests_total",
    "HTTP requests handled by the lab application.",
    ["method", "route", "status"],
)
REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ["method", "route"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

CHAOS = {"latency_ms": 0, "db_delay_ms": 0, "error_rate": 0.0}
CHAOS_LOCK = threading.Lock()


class JsonFormatter(logging.Formatter):
    def format(self, record):
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "message": record.getMessage(),
        }
        if hasattr(record, "fields"):
            event.update(record.fields)
        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            event["trace_id"] = f"{span_context.trace_id:032x}"
            event["span_id"] = f"{span_context.span_id:016x}"
        return json.dumps(event, separators=(",", ":"))


logger = logging.getLogger("lab")
handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False


def configure_tracing():
    resource = Resource.create(
        {"service.name": os.environ.get("OTEL_SERVICE_NAME", "app")}
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    PsycopgInstrumentor().instrument()
    return provider


TRACER_PROVIDER = configure_tracing()


def connect_db():
    return psycopg.connect(
        host=os.environ.get("POSTGRES_HOST", "postgres"),
        port=os.environ.get("POSTGRES_PORT", "5432"),
        dbname=os.environ.get("POSTGRES_DB", "observability"),
        user=os.environ.get("POSTGRES_USER", "labuser"),
        password=os.environ.get("POSTGRES_PASSWORD", ""),
        connect_timeout=3,
    )


def create_app():
    app = Flask(__name__)
    FlaskInstrumentor().instrument_app(app)

    with connect_db() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS page_hits (
                id BIGSERIAL PRIMARY KEY,
                visited_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )

    @app.before_request
    def start_request():
        g.started_at = time.perf_counter()
        if request.path in ("/health", "/metrics", "/chaos"):
            return None

        with CHAOS_LOCK:
            latency_ms = CHAOS["latency_ms"]
            error_rate = CHAOS["error_rate"]

        if latency_ms:
            time.sleep(latency_ms / 1000)
        if error_rate and random.random() < error_rate:
            return jsonify(error="chaos-injected"), 500
        return None

    @app.after_request
    def record_request(response):
        elapsed = time.perf_counter() - getattr(g, "started_at", time.perf_counter())
        route = request.url_rule.rule if request.url_rule else "unmatched"
        REQUESTS.labels(request.method, route, str(response.status_code)).inc()
        REQUEST_DURATION.labels(request.method, route).observe(elapsed)
        logger.info(
            "http_request",
            extra={
                "fields": {
                    "method": request.method,
                    "route": route,
                    "status": response.status_code,
                    "duration_ms": round(elapsed * 1000, 2),
                }
            },
        )
        return response

    @app.get("/")
    def index():
        with CHAOS_LOCK:
            db_delay_ms = CHAOS["db_delay_ms"]
        with connect_db() as connection:
            if db_delay_ms:
                connection.execute("SELECT pg_sleep(%s)", (db_delay_ms / 1000,))
            connection.execute("INSERT INTO page_hits DEFAULT VALUES")
            visits = connection.execute("SELECT count(*) FROM page_hits").fetchone()[0]
        return jsonify(service="observability-lab", visits=visits)

    @app.get("/health")
    def health():
        try:
            with connect_db() as connection:
                connection.execute("SELECT 1")
        except psycopg.Error as error:
            logger.error(
                "database_health_check_failed",
                extra={"fields": {"error": str(error)}},
            )
            return jsonify(status="unhealthy", dependency="postgres"), 503
        return jsonify(status="ok", dependency="postgres")

    @app.get("/metrics")
    def metrics():
        from flask import Response

        return Response(generate_latest(), mimetype="text/plain; version=0.0.4")

    @app.route("/chaos", methods=["GET", "POST", "DELETE"])
    def chaos():
        expected = os.environ.get("CHAOS_ADMIN_TOKEN", "")
        supplied = request.headers.get("X-Admin-Token", "")
        if not expected or not hmac.compare_digest(supplied, expected):
            return jsonify(error="unauthorized"), 401

        if request.method == "DELETE":
            with CHAOS_LOCK:
                CHAOS.update(latency_ms=0, db_delay_ms=0, error_rate=0.0)
            return jsonify(status="cleared", **CHAOS)

        if request.method == "POST":
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                return jsonify(error="expected a JSON object"), 400

            latency_ms = payload.get("latency_ms", CHAOS["latency_ms"])
            db_delay_ms = payload.get("db_delay_ms", CHAOS["db_delay_ms"])
            error_rate = payload.get("error_rate", CHAOS["error_rate"])
            if (
                isinstance(latency_ms, bool)
                or not isinstance(latency_ms, int)
                or not 0 <= latency_ms <= 10000
            ):
                return jsonify(error="latency_ms must be an integer from 0 to 10000"), 400
            if (
                isinstance(db_delay_ms, bool)
                or not isinstance(db_delay_ms, int)
                or not 0 <= db_delay_ms <= 10000
            ):
                return jsonify(error="db_delay_ms must be an integer from 0 to 10000"), 400
            if (
                isinstance(error_rate, bool)
                or not isinstance(error_rate, (int, float))
                or not 0 <= error_rate <= 1
            ):
                return jsonify(error="error_rate must be a number from 0 to 1"), 400

            with CHAOS_LOCK:
                CHAOS.update(
                    latency_ms=latency_ms,
                    db_delay_ms=db_delay_ms,
                    error_rate=float(error_rate),
                )

        with CHAOS_LOCK:
            current = dict(CHAOS)
        return jsonify(status="configured", **current)

    @app.errorhandler(psycopg.Error)
    def database_error(error):
        logger.error(
            "database_request_failed",
            extra={"fields": {"error": str(error)}},
        )
        return jsonify(error="database unavailable"), 503

    return app


app = create_app()
