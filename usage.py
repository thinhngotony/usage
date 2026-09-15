#!/usr/bin/env python3
"""Display Command Code usage for multiple API keys."""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sys
import textwrap
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

BASE_URL = "https://api.commandcode.ai"
SUMMARY_PATH = "/alpha/usage/summary"
CREDITS_PATH = "/alpha/billing/credits"
SUBSCRIPTION_PATH = "/alpha/billing/subscriptions"
STATE_PATH = Path(".usage.json")
MONTHLY_QUOTA = 10.0


@dataclass
class Usage:
    total_tokens: str = "UNKNOWN"
    monthly: str = "UNKNOWN"
    five_hour: str = "UNKNOWN"
    weekly: str = "UNKNOWN"
    monthly_pct: float | None = None
    five_hour_pct: float | None = None
    weekly_pct: float | None = None
    monthly_reset_at: str | None = None
    five_hour_reset_at: str | None = None
    weekly_reset_at: str | None = None
    available: str = "UNKNOWN"
    availability_at: str | None = None
    limiting_windows: tuple[str, ...] = ()
    error: str | None = None
def _datetime(value: Any) -> datetime | None:
    if value is None or not str(value).strip():
        return None
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return datetime.fromtimestamp(value / 1000, timezone.utc)
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (OSError, OverflowError, TypeError, ValueError):
        return None
    return (result if result.tzinfo else result.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _format_datetime(value: Any) -> str | None:
    value = _datetime(value)
    return value.strftime("%A %d %b %Y, %H:%M UTC") if value else None


def _reset_at(data: Any) -> datetime | None:
    if not isinstance(data, dict):
        return None
    for name in ("resetAt", "reset_at", "resetTime", "reset_time", "resetsAt", "resets_at"):
        if name in data:
            return _datetime(data[name])
    return None


def _reset(data: Any) -> str | None:
    return _format_datetime(_reset_at(data))


def _availability(
    monthly_reset: datetime | None,
    five_reset: datetime | None,
    weekly_reset: datetime | None,
    monthly_pct: float | None,
    five_pct: float | None,
    weekly_pct: float | None,
) -> tuple[str, str | None, tuple[str, ...]]:
    windows = (
        ("Monthly", monthly_reset, monthly_pct),
        ("5-hour", five_reset, five_pct),
        ("Weekly", weekly_reset, weekly_pct),
    )
    missing_value = tuple(label for label, _, percent in windows if percent is None)
    if missing_value:
        return "UNKNOWN", None, missing_value
    exhausted = [(label, reset) for label, reset, percent in windows if percent >= 100]
    if not exhausted:
        return "NOW", None, ()
    missing_reset = tuple(label for label, reset in exhausted if reset is None)
    if missing_reset:
        return "UNKNOWN", None, missing_reset
    available_at = max(reset for _, reset in exhausted if reset is not None)
    limited_by = tuple(label for label, reset in exhausted if reset == available_at)
    return _format_datetime(available_at) or "UNKNOWN", available_at.isoformat(), limited_by


def _availability_sort_key(usage: Usage) -> tuple[int, datetime]:
    if usage.error:
        return (3, datetime.max.replace(tzinfo=timezone.utc))
    if usage.available == "NOW":
        return (0, datetime.min.replace(tzinfo=timezone.utc))
    if usage.availability_at:
        available_at = _datetime(usage.availability_at)
        if available_at:
            return (1, available_at)
    return (2, datetime.max.replace(tzinfo=timezone.utc))


def _percent(used: float | None, cap: float | None) -> float | None:
    if used is None or cap is None or cap <= 0:
        return None
    return min(100.0, max(0.0, used / cap * 100.0))




def _parse_keys(raw: str) -> list[tuple[str | None, str]]:
    text = raw.strip()
    if not text:
        return []
    if text[0] in "[{":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise ValueError("API key input is not valid JSON") from error
        if isinstance(payload, list):
            result = []
            for item in payload:
                if not isinstance(item, dict) or not isinstance(item.get("key"), str) or not item["key"].strip():
                    raise ValueError('JSON key arrays require objects with a non-empty "key"')
                name = item.get("name")
                if name is not None and not isinstance(name, str):
                    raise ValueError('JSON key "name" values must be strings')
                result.append((name.strip() if name else None, item["key"].strip()))
            return result
        if isinstance(payload, dict):
            if not all(isinstance(name, str) and isinstance(key, str) and key.strip() for name, key in payload.items()):
                raise ValueError("JSON key maps require non-empty string names and keys")
            return [(name.strip(), key.strip()) for name, key in payload.items()]
        raise ValueError("JSON key input must be an array or object")
    values = []
    for item in text.replace(",", "\n").splitlines():
        item = item.strip()
        if item:
            values.append((None, item))
    return values


def _keys(raw: str) -> list[str]:
    return [key for _, key in _parse_keys(raw)]


def _export(rows: list[tuple[str | None, str, Usage]], destination: Path, format_name: str) -> None:
    safe_rows = []
    for name, _, usage in rows:
        row = asdict(usage)
        row["limiting_windows"] = " & ".join(usage.limiting_windows)
        safe_rows.append({"name": name, **row})
    if format_name == "json":
        destination.write_text(json.dumps(safe_rows, indent=2) + "\n")
        return
    with destination.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=["name", *asdict(rows[0][2]).keys()])
        writer.writeheader()
        writer.writerows(safe_rows)


def _number(data: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = data.get(name)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _money(value: float | None) -> str:
    return "UNKNOWN" if value is None else f"${value:.2f}"
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_BAR_FULL = "#"
_BAR_EMPTY = "-"


def _visible_len(value: str) -> int:
    return len(_ANSI_RE.sub("", value))




def _progress_bar(percent: float | None, width: int = 10, color: bool = False) -> str:
    """Render a clamped percentage as a fixed-width progress bar."""
    width = max(1, width)
    if percent is None:
        return "UNKNOWN"
    bounded = max(0.0, min(100.0, float(percent)))
    filled = min(width, max(1 if bounded > 0 else 0, int(bounded * width / 100)))
    full = _BAR_FULL * filled
    empty = _BAR_EMPTY * (width - filled)
    text = f"[{full}{empty}] {bounded:3.0f}%"
    if not color or not full:
        return text
    shade = "\033[31m" if bounded >= 85 else "\033[33m" if bounded >= 65 else "\033[32m"
    return f"[{shade}{full}\033[0m{empty}] {bounded:3.0f}%"

def _metric(value: str, percent: float | None, width: int = 0, color: bool = False) -> str:
    value = value.ljust(width)
    return value if percent is None else f"{value} {_progress_bar(percent, color=color)}"


def _status(usage: Usage) -> str:
    if usage.error:
        return f"ERROR: {usage.error}"
    if usage.available == "NOW":
        return "NOW"
    labels = " & ".join(usage.limiting_windows)
    if usage.available == "UNKNOWN":
        return f"UNKNOWN ({labels})" if labels else "UNKNOWN"
    return f"{labels or 'RESET'}: {usage.available}"


def _table_reset(value: str | None) -> str:
    if not value:
        return "Reset: UNKNOWN"
    date, separator, time = value.rpartition(", ")
    if separator:
        date, _, year = date.rpartition(" ")
        if year.isdigit():
            return f"Reset: {date} {time}"
    return f"Reset: {value}"


def _wrap(value: str, width: int) -> list[str]:
    if _visible_len(value) <= width:
        return [value]
    return textwrap.wrap(
        _ANSI_RE.sub("", value),
        width=max(20, width),
        subsequent_indent="    ",
        break_on_hyphens=False,
    ) or [""]


def _render_compact(rows: list[tuple[str, Usage]], width: int, color: bool) -> str:
    output = []
    for key, usage in rows:
        output.extend(_wrap(str(key), width))
        output.extend(_wrap(f"  Status: {_status(usage)}", width))
        if not usage.error:
            for label, value, percent, reset_at in (
                ("Monthly", usage.monthly, usage.monthly_pct, usage.monthly_reset_at),
                ("5-Hour", usage.five_hour, usage.five_hour_pct, usage.five_hour_reset_at),
                ("Weekly", usage.weekly, usage.weekly_pct, usage.weekly_reset_at),
            ):
                output.extend(_wrap(f"  {label}: {_metric(value, percent, color=color)}", width))
                output.extend(_wrap(f"    Reset: {reset_at or 'UNKNOWN'}", width))
        output.append("")
    return "\n".join(output).rstrip()


def _render_table(rows: list[tuple[str, Usage]], width: int | None = None, color: bool = False) -> str:
    """Return a complete table or a readable account view on narrow terminals."""
    headers = ("KEY", "MONTHLY", "5-HOUR", "WEEKLY", "STATUS")
    metric_rows = [[str(key), str(usage.monthly), str(usage.five_hour), str(usage.weekly), _status(usage)] for key, usage in rows]
    metric_widths = (
        max((_visible_len(values[1]) for values, (_, usage) in zip(metric_rows, rows) if usage.monthly_pct is not None), default=0),
        max((_visible_len(values[2]) for values, (_, usage) in zip(metric_rows, rows) if usage.five_hour_pct is not None), default=0),
        max((_visible_len(values[3]) for values, (_, usage) in zip(metric_rows, rows) if usage.weekly_pct is not None), default=0),
    )
    cells = []
    for values, (_, usage) in zip(metric_rows, rows):
        cells.append([
            values[0],
            _metric(values[1], usage.monthly_pct, metric_widths[0], color),
            _metric(values[2], usage.five_hour_pct, metric_widths[1], color),
            _metric(values[3], usage.weekly_pct, metric_widths[2], color),
            values[4],
        ])
        if not usage.error:
            cells.append([
                "",
                _table_reset(usage.monthly_reset_at),
                _table_reset(usage.five_hour_reset_at),
                _table_reset(usage.weekly_reset_at),
                "",
            ])
    data = [list(headers), *cells]
    widths = [max(_visible_len(row[col]) for row in data) for col in range(len(headers))]
    if width is not None and sum(widths) + 3 * len(headers) + 1 > width:
        return _render_compact(rows, width, color)

    def pad(value: str, cell_width: int) -> str:
        return value + " " * max(0, cell_width - _visible_len(value))

    def row(values: list[str]) -> str:
        return "│ " + " │ ".join(pad(value, widths[i]) for i, value in enumerate(values)) + " │"

    top = "╭" + "┬".join("─" * (item + 2) for item in widths) + "╮"
    divider = "├" + "┼".join("─" * (item + 2) for item in widths) + "┤"
    bottom = "╰" + "┴".join("─" * (item + 2) for item in widths) + "╯"
    output = [top, row(list(headers)), divider, *(row(values) for values in cells), bottom]
    if color:
        output[1] = "\033[1;36m" + output[1] + "\033[0m"
    return "\n".join(output)


def _summary(payload: Any) -> tuple[float | None, float | None, float | None]:
    if not isinstance(payload, dict):
        raise ValueError("usage response must be a JSON object")
    return (
        _number(payload, "totalTokens", "total_tokens"),
        _number(payload, "totalCost", "total_cost"),
        _number(payload, "totalMonthlyCredits", "total_monthly_credits"),
    )


def _recent_cost(payload: Any, since: datetime) -> float:
    entries = payload.get("usages", []) if isinstance(payload, dict) else []
    total = 0.0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        timestamp = entry.get("createdAt") or entry.get("created_at") or entry.get("timestamp")
        try:
            when = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if when >= since:
            total += _number(entry, "totalCost", "total_cost", "cost") or 0.0
    return total


def _request(base_url: str, path: str, key: str, timeout: float) -> Any:
    request = urllib.request.Request(
        f"{base_url}{path}",
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "User-Agent": "usage-dashboard/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"HTTP {error.code} from {path}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise RuntimeError(f"network error: {error}") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise RuntimeError(f"{path} returned non-JSON data") from None
def fetch(key: str, timeout: float, base_url: str = BASE_URL) -> Usage:
    with ThreadPoolExecutor(max_workers=3) as pool:
        summary_future = pool.submit(_request, base_url, SUMMARY_PATH, key, timeout)
        credits_future = pool.submit(_request, base_url, CREDITS_PATH, key, timeout)
        subscription_future = pool.submit(_request, base_url, SUBSCRIPTION_PATH, key, timeout)
        summary = summary_future.result()
        credits = credits_future.result()
        subscription = subscription_future.result()
    tokens, monthly_cost, _ = _summary(summary)
    monthly_quota = MONTHLY_QUOTA
    window = credits.get("windowLimits", {}) if isinstance(credits, dict) else {}
    window = window if isinstance(window, dict) else {}
    five = window.get("fiveHour", {})
    five = five if isinstance(five, dict) else {}
    weekly = window.get("weekly", {})
    weekly = weekly if isinstance(weekly, dict) else {}
    five_used, five_cap = _number(five, "used"), _number(five, "cap")
    weekly_used, weekly_cap = _number(weekly, "used"), _number(weekly, "cap")
    subscription_data = subscription.get("data", subscription) if isinstance(subscription, dict) else {}
    monthly_reset = _datetime(subscription_data.get("currentPeriodEnd") if isinstance(subscription_data, dict) else None)
    five_reset, weekly_reset = _reset_at(five), _reset_at(weekly)
    monthly_pct = _percent(monthly_cost, monthly_quota)
    five_hour_pct = _percent(five_used, five_cap)
    weekly_pct = _percent(weekly_used, weekly_cap)
    available, availability_at, limiting_windows = _availability(
        monthly_reset, five_reset, weekly_reset, monthly_pct, five_hour_pct, weekly_pct
    )
    return Usage(
        total_tokens="UNKNOWN" if tokens is None else f"{tokens:,.0f}",
        monthly=f"{_money(monthly_cost)} / {_money(monthly_quota)}",
        five_hour=f"{_money(five_used)} / {_money(five_cap)}",
        weekly=f"{_money(weekly_used)} / {_money(weekly_cap)}",
        monthly_pct=monthly_pct,
        five_hour_pct=five_hour_pct,
        weekly_pct=weekly_pct,
        monthly_reset_at=_format_datetime(monthly_reset),
        five_hour_reset_at=_format_datetime(five_reset),
        weekly_reset_at=_format_datetime(weekly_reset),
        available=available,
        availability_at=availability_at,
        limiting_windows=limiting_windows,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show Command Code usage for multiple API keys")
    parser.add_argument("--keys-file", type=Path, help="import JSON key file on first run")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--export", type=Path, help="write redacted usage rows as JSON or CSV")
    parser.add_argument("--export-format", choices=("json", "csv"))
    parser.add_argument("--no-color", action="store_true")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    source = args.keys_file or STATE_PATH
    if not source.exists():
        parser.error("first run requires --keys-file keys.json")
    try:
        named_keys = _parse_keys(source.read_text())
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if not named_keys:
        parser.error("key file contains no API keys")
    failures = 0
    keys = [(name or f"key-{index}", key) for index, (name, key) in enumerate(named_keys, 1)]
    with ThreadPoolExecutor(max_workers=min(5, len(keys))) as pool:
        futures = {pool.submit(fetch, key, args.timeout, args.base_url): index for index, (_, key) in enumerate(keys)}
        results = {}
        for future in as_completed(futures):
            index = futures[future]
            try:
                results[index] = future.result()
            except (RuntimeError, ValueError) as error:
                failures += 1
                results[index] = Usage(error=str(error))
    STATE_PATH.write_text(json.dumps([{"name": name, "key": key} for name, key in keys], indent=2) + "\n")
    rows = [(name, key, results[index]) for index, (name, key) in enumerate(keys)]
    rows.sort(key=lambda row: _availability_sort_key(row[2]))
    if args.export:
        _export(rows, args.export, args.export_format or ("csv" if args.export.suffix.lower() == ".csv" else "json"))
    else:
        print(_render_table([(name, usage) for name, _, usage in rows], width=shutil.get_terminal_size().columns, color=sys.stdout.isatty() and not args.no_color))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
