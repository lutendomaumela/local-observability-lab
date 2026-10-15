import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


logging.basicConfig(level=logging.INFO, format="%(message)s")
alerts_lock = threading.Lock()
latest_alerts = []


class Handler(BaseHTTPRequestHandler):
    def _write_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._write_json(200, {"status": "ok"})
            return
        if self.path == "/alerts":
            with alerts_lock:
                alerts = list(latest_alerts)
            self._write_json(200, {"alerts": alerts})
            return
        self._write_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/alerts":
            self._write_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1_000_000:
                raise ValueError("request body size must be between 1 and 1000000 bytes")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict) or not isinstance(payload.get("alerts"), list):
                raise ValueError("expected an Alertmanager JSON object with an alerts array")
        except (ValueError, json.JSONDecodeError) as error:
            self._write_json(400, {"error": str(error)})
            return

        with alerts_lock:
            latest_alerts[:] = payload["alerts"]
        logging.info(json.dumps({
            "event": "alertmanager_webhook_received",
            "status": payload.get("status"),
            "alert_count": len(payload["alerts"]),
            "alert_names": [
                alert.get("labels", {}).get("alertname", "unknown")
                for alert in payload["alerts"]
            ],
        }))
        self._write_json(200, {"status": "received", "alert_count": len(payload["alerts"])})

    def log_message(self, format_string, *args):
        logging.info(json.dumps({"http": format_string % args}))


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
