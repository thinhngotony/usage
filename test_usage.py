import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

from usage import _recent_cost, fetch


from pathlib import Path

from usage import _export, _keys, _parse_keys


def test_parse_json_array_preserves_names_and_order():
    assert _parse_keys('[{"name":"prod","key":"user_prod"},{"name":"dev","key":"user_dev"}]') == [("prod", "user_prod"), ("dev", "user_dev")]


def test_parse_json_object_preserves_names_and_order():
    assert _parse_keys('{"prod":"user_prod","dev":"user_dev"}') == [("prod", "user_prod"), ("dev", "user_dev")]


def test_parse_plain_keys_and_legacy_keys_helper():
    assert _parse_keys("first, second\nthird") == [(None, "first"), (None, "second"), (None, "third")]
    assert _keys("first, second\nthird") == ["first", "second", "third"]


def test_parse_malformed_json_is_rejected():
    try:
        _parse_keys('{"prod":')
    except ValueError as error:
        assert "valid JSON" in str(error)
    else:
        raise AssertionError("malformed JSON should fail")


def test_export_redacts_keys(tmp_path: Path):
    rows = [("prod", "user_secret", __import__("usage").Usage(total_tokens="1,234"))]
    json_path = tmp_path / "usage.json"
    csv_path = tmp_path / "usage.csv"
    _export(rows, json_path, "json")
    _export(rows, csv_path, "csv")
    assert "user_secret" not in json_path.read_text()
    assert "user_secret" not in csv_path.read_text()
    assert '"name": "prod"' in json_path.read_text()
    assert "prod" in csv_path.read_text()
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

def test_percent_boundaries_clamp_and_reject_invalid_caps():
    from usage import _percent

    assert _percent(0, 10) == 0
    assert _percent(5, 10) == 50
    assert _percent(15, 10) == 100
    assert _percent(-1, 10) == 0
    assert _percent(1, 0) is None
    assert _percent(None, 10) is None


def test_fetch_status_uses_provider_limited_flag(monkeypatch):
    from usage import SUMMARY_PATH, CREDITS_PATH

    payloads = {
        SUMMARY_PATH: {"totalTokens": 1, "totalCost": 2},
        CREDITS_PATH: {
            "credits": {"monthlyCredits": 10},
            "windowLimits": {
                "limited": False,
                "fiveHour": {"used": 1, "cap": 4, "resetAt": "2026-08-13T10:00:00Z"},
                "weekly": {"used": 3, "cap": 12, "resetAt": "2026-08-15T10:00:00Z"},
            },
        },
    }
    monkeypatch.setattr("usage._request", lambda _base, path, _key, _timeout: payloads[path])
    usage = fetch("key", 1)
    assert usage.status == "READY"
    assert usage.monthly_pct == 20
    assert usage.five_hour_pct == 25
    assert usage.weekly_pct == 25
    assert usage.five_hour_reset_at.endswith("Z")
    payloads[CREDITS_PATH]["windowLimits"]["limited"] = True
    assert fetch("key", 1).status == "NOT READY"

def test_render_table_aligns_bars_after_metric_values():
    from usage import Usage, _render_table
    output = _render_table([
        ("one", Usage(monthly="$3.03 / $6.97", monthly_pct=43)),
        ("two", Usage(monthly="$10.03 / $0.08", monthly_pct=100)),
    ], color=False)
    rows = [line for line in output.splitlines() if line.startswith("│ one") or line.startswith("│ two")]
    assert rows[0].index("▓") == rows[1].index("▓")

def test_render_table_right_aligns_monthly_values():
    from usage import Usage, _render_table
    output = _render_table([
        ("one", Usage(monthly="$3.03 / $6.97", monthly_pct=43)),
        ("two", Usage(monthly="$10.03 / $0.08", monthly_pct=100)),
    ], color=False)
    rows = [line for line in output.splitlines() if line.startswith("│ one") or line.startswith("│ two")]
    assert rows[0].index("/") == rows[1].index("/")
