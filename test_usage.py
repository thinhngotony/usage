import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

from usage import _recent_cost, fetch


def test_recent_cost_uses_window():
    now = datetime.now(timezone.utc)
    payload = {"usages": [
        {"createdAt": (now - timedelta(hours=1)).isoformat(), "totalCost": 2.5},
        {"createdAt": (now - timedelta(hours=6)).isoformat(), "totalCost": 9},
    ]}
    assert _recent_cost(payload, now - timedelta(hours=5)) == 2.5


def test_fetch_reads_summary_and_usage_with_bearer():
    seen = []
    now = datetime.now(timezone.utc)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path, self.headers["Authorization"]))
            if self.path == "/alpha/usage/summary":
                payload = {"totalTokens": 573169426, "totalCost": 10.0266}
            else:
                payload = {"credits": {"monthlyCredits": 10}, "windowLimits": {"fiveHour": {"used": 1.5, "cap": 3}, "weekly": {"used": 1.5, "cap": 6}}}
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        usage = fetch("test-key", 2, f"http://127.0.0.1:{server.server_port}")
    finally:
        server.shutdown()
        thread.join()
    assert usage.total_tokens == "573,169,426"
    assert usage.monthly == "$10.03 / $10.00"
    assert usage.five_hour == "$1.50 / $3.00"
    assert usage.weekly == "$1.50 / $6.00"
    assert len(seen) == 2
    assert all(auth == "Bearer test-key" for _, auth in seen)
