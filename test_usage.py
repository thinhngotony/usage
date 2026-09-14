import json
import threading

from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

from usage import _availability, _recent_cost, fetch


from pathlib import Path

from usage import _export, _keys, _parse_keys
from usage import Usage, _availability_sort_key, _render_table, main


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
    rows = [("prod", "user_secret", __import__("usage").Usage(total_tokens="1,234", limiting_windows=("Weekly",)))]
    json_path = tmp_path / "usage.json"
    csv_path = tmp_path / "usage.csv"
    _export(rows, json_path, "json")
    _export(rows, csv_path, "csv")
    assert "user_secret" not in json_path.read_text()
    assert "user_secret" not in csv_path.read_text()
    assert '"name": "prod"' in json_path.read_text()
    assert json.loads(json_path.read_text())[0]["limiting_windows"] == "Weekly"
    assert "Weekly" in csv_path.read_text()
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
    assert usage.available == "Tuesday 01 Sep 2026, 00:00 UTC"
    assert usage.availability_at == "2026-09-01T00:00:00+00:00"
    assert usage.limiting_windows == ("Monthly",)
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

def test_wide_dashboard_uses_compact_metric_and_reset_columns():
    usage = Usage(
        monthly="$5.00 / $10.00",
        five_hour="$1.00 / $3.00",
        weekly="$2.00 / $6.00",
        monthly_pct=50,
        five_hour_pct=33,
        weekly_pct=33,
        monthly_reset_at="Thursday 01 Oct 2026, 00:00 UTC",
        five_hour_reset_at="Tuesday 15 Sep 2026, 05:00 UTC",
        weekly_reset_at="Tuesday 15 Sep 2026, 23:00 UTC",
        available="NOW",
    )

    dashboard = _render_table([("account", usage)], width=200)
    account_line = next(line for line in dashboard.splitlines() if line.startswith("│ account "))

    assert dashboard.count("│ account ") == 1
    assert "M RESET UTC" in dashboard
    assert "50% $5.00" in account_line
    assert "33% $1.00" in account_line
    assert "Thu 01 Oct 00:00 UTC" in account_line
    assert "Tue 15 Sep 05:00 UTC" in account_line
    assert "[----------]" not in dashboard


def test_wide_dashboard_marks_missing_metric_and_reset_unknown():
    dashboard = _render_table([("unknown", Usage())], width=200)

    assert "UNKNOWN / UNKNOWN" not in dashboard
    assert dashboard.count("UNKNOWN") >= 7

def test_availability_waits_for_last_exhausted_reset():
    five_reset = datetime(2026, 9, 15, 5, tzinfo=timezone.utc)
    weekly_reset = datetime(2026, 9, 15, 23, tzinfo=timezone.utc)

    available, available_at, limiting_windows = _availability(None, five_reset, weekly_reset, 90, 100, 100)

    assert available == "Tuesday 15 Sep 2026, 23:00 UTC"
    assert available_at == "2026-09-15T23:00:00+00:00"
    assert limiting_windows == ("Weekly",)


def test_availability_marks_missing_exhausted_reset_unknown():
    available, available_at, limiting_windows = _availability(None, None, None, 100, 50, 50)

    assert available == "UNKNOWN"
    assert available_at is None
    assert limiting_windows == ("Monthly",)

def test_availability_marks_missing_usage_unknown():
    available, available_at, limiting_windows = _availability(None, None, None, None, 50, 50)

    assert available == "UNKNOWN"
    assert available_at is None
    assert limiting_windows == ("Monthly",)


def test_dates_are_utc_and_failed_usage_sorts_last():
    from usage import _reset

    assert _reset({"resetAt": 1786639187997}) == "Thursday 13 Aug 2026, 16:39 UTC"
    assert _availability_sort_key(Usage(available="NOW"))[0] == 0
    assert _availability_sort_key(Usage())[0] == 2
    assert _availability_sort_key(Usage(error="network error"))[0] == 3


def test_narrow_dashboard_preserves_ready_reason_and_reset_dates():
    usage = Usage(
        monthly="$9.50 / $10.00",
        five_hour="$3.00 / $3.00",
        weekly="$5.80 / $6.00",
        monthly_pct=95,
        five_hour_pct=100,
        weekly_pct=97,
        monthly_reset_at="Thursday 01 Oct 2026, 00:00 UTC",
        five_hour_reset_at="Tuesday 15 Sep 2026, 05:00 UTC",
        weekly_reset_at="Tuesday 15 Sep 2026, 23:00 UTC",
        available="Tuesday 15 Sep 2026, 05:00 UTC",
        availability_at="2026-09-15T05:00:00+00:00",
        limiting_windows=("5-hour",),
    )

    dashboard = _render_table([("a-long-account-name", usage)], width=80)

    assert "Status: WAIT 5H" in dashboard
    assert "Monthly: 95% $9.50" in dashboard
    assert "Reset: Thursday 01 Oct 2026, 00:00 UTC" in dashboard
    assert "Reset: Tuesday 15 Sep 2026, 05:00 UTC" in dashboard
    assert "…" not in dashboard


def test_dashboard_shows_errors_without_false_usage_values():
    dashboard = _render_table([("offline-account", Usage(error="network unavailable"))], width=80)

    assert "Status: ERROR" in dashboard
    assert "Error: network unavailable" in dashboard


def test_empty_key_file_is_rejected(tmp_path: Path, monkeypatch, capsys):
    key_file = tmp_path / "keys.json"
    key_file.write_text("[]")
    monkeypatch.chdir(tmp_path)

    try:
        main(["--keys-file", str(key_file)])
    except SystemExit as error:
        assert error.code == 2
    else:
        raise AssertionError("empty key file should fail")

    assert "contains no API keys" in capsys.readouterr().err
