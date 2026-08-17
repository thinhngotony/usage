import json
import threading

from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

from usage import _availability, _recent_cost, fetch


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
            elif self.path == "/alpha/billing/credits":
                payload = {"credits": {"monthlyCredits": 0.08}, "windowLimits": {"fiveHour": {"used": 0, "cap": 3}, "weekly": {"used": 0, "cap": 6}}}
            else:
                payload = {"currentPeriodEnd": "2026-09-01T00:00:00Z"}
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
    assert usage.monthly_pct == 100
    assert usage.five_hour == "$0.00 / $3.00"
    assert usage.weekly == "$0.00 / $6.00"
    assert usage.available == "00:00 01/09/2026"
    assert len(seen) == 3
    assert all(auth == "Bearer test-key" for _, auth in seen)

def test_fetch_uses_fixed_monthly_quota_not_remaining_credits(monkeypatch):
    payloads = {
        "/alpha/usage/summary": {"totalTokens": 1, "totalCost": 5.05},
        "/alpha/billing/credits": {
            "credits": {"monthlyCredits": 4.95},
            "windowLimits": {
                "fiveHour": {"used": 0, "cap": 3},
                "weekly": {"used": 5.05, "cap": 6},
            },
        },
        "/alpha/billing/subscriptions": {"currentPeriodEnd": "2026-09-01T00:00:00Z"},
    }
    monkeypatch.setattr("usage._request", lambda _base, path, _key, _timeout: payloads[path])

    usage = fetch("key", 1)

    assert usage.monthly == "$5.05 / $10.00"
    assert usage.monthly_pct == 50.5
    assert usage.available == "NOW"


def test_percent_boundaries_clamp_and_reject_invalid_caps():
    from usage import _percent

    assert _percent(0, 10) == 0
    assert _percent(5, 10) == 50
    assert _percent(15, 10) == 100
    assert _percent(-1, 10) == 0
    assert _percent(1, 0) is None
    assert _percent(None, 10) is None



    from usage import Usage, _availability_sort_key, _reset
    assert _reset({"resetAt": 1786639187997}) == "16:39 13/08/2026"
    assert _availability_sort_key(Usage(available="NOW"))[0] == 0
    assert _availability_sort_key(Usage(available="21:01 13/08/2026"))[0] == 1


def test_availability_uses_exhausted_window_precedence():
    assert _availability("MONTH", "FIVE", "WEEK", 100, 50, 50) == "MONTH"
    assert _availability("MONTH", "FIVE", "WEEK", 90, 100, 50) == "FIVE"
    assert _availability("MONTH", "FIVE", "WEEK", 90, 50, 100) == "WEEK"
    assert _availability("MONTH", "FIVE", "WEEK", 90, 50, 50) == "NOW"
