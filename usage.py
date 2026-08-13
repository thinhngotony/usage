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


@dataclass
class Usage:
    total_tokens: str = "—"
    monthly: str = "—"
    five_hour: str = "—"
    weekly: str = "—"
    status: str = "NOT READY"
    monthly_pct: float | None = None
    five_hour_pct: float | None = None
    weekly_pct: float | None = None
    five_hour_reset_at: str | None = None
    weekly_reset_at: str | None = None


def _percent(used: float | None, cap: float | None) -> float | None:
    if used is None or cap is None or cap <= 0:
        return None
    return min(100.0, max(0.0, used / cap * 100.0))


def _reset(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    for name in ("resetAt", "reset_at", "resetTime", "reset_time", "resetsAt", "resets_at"):
        value = data.get(name)
        if value is not None and str(value).strip():
            return str(value)
    return None

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
    safe_rows = [{"name": name, **asdict(usage)} for name, _, usage in rows]
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
    return "—" if value is None else f"${value:.2f}"
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_BAR_FULL = "▓"
_BAR_EMPTY = "░"


def _visible_len(value: str) -> int:
    return len(_ANSI_RE.sub("", value))


def _truncate(value: str, width: int) -> str:
    """Trim a cell to width, preserving a useful ellipsis when needed."""
    if width <= 0:
        return ""
    plain = _ANSI_RE.sub("", str(value))
    return plain if len(plain) <= width else plain[: max(0, width - 1)] + "…"


def _progress_bar(percent: float | None, width: int = 10, color: bool = False) -> str:
    """Render a clamped percentage as a fixed-width progress bar."""
    width = max(1, width)
    if percent is None:
        return "—"
    bounded = max(0.0, min(100.0, float(percent)))
    filled = int(bounded * width / 100)
    bar = _BAR_FULL * filled + _BAR_EMPTY * (width - filled)
    text = f"{bar} {bounded:3.0f}%"
    if not color:
        return text
    shade = "\033[31m" if bounded >= 85 else "\033[33m" if bounded >= 65 else "\033[32m"
    return f"{shade}{bar}\033[0m {bounded:3.0f}%"


def _render_table(rows: list[tuple[str, Usage]], width: int | None = None, color: bool = False) -> str:
    """Return a width-aware usage table; output is deterministic when color is off."""
    headers = ("KEY", "STATUS", "MONTHLY", "5-HOUR", "WEEKLY")
    metric_rows = []
    for key, usage in rows:
        metric_rows.append([
            str(key), str(usage.status), str(usage.monthly),
            str(usage.five_hour), str(usage.weekly),
        ])
    metric_widths = [max(_visible_len(row[col]) for row in metric_rows) if metric_rows else 0 for col in range(5)]
    cells = []
    for values, (_, usage) in zip(metric_rows, rows):
        cells.append([
            values[0], values[1],
            f"{values[2].rjust(metric_widths[2])} {_progress_bar(usage.monthly_pct, 10, color)}",
            f"{values[3].rjust(metric_widths[3])} {_progress_bar(usage.five_hour_pct, 10, color)}",
            f"{values[4].rjust(metric_widths[4])} {_progress_bar(usage.weekly_pct, 10, color)}",
        ])
    data = [list(headers), *cells]
    widths = [max(_visible_len(row[col]) for row in data) for col in range(len(headers))]
    if width is not None:
        available = max(5, width - 18)
        while sum(widths) > available:
            index = max(range(len(widths)), key=lambda col: widths[col])
            if widths[index] <= 1:
                break
            widths[index] -= 1
    def row(values: list[str]) -> str:
        return "│ " + " │ ".join(_truncate(value, widths[i]).ljust(widths[i]) for i, value in enumerate(values)) + " │"
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
        _number(payload, "totalMonthlyCredits", "monthlyCredits", "monthly_credits"),
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
    except urllib.error.URLError as error:
        raise RuntimeError(f"network error: {error.reason}") from None
    except json.JSONDecodeError:
        raise RuntimeError(f"{path} returned non-JSON data") from None


def fetch(key: str, timeout: float, base_url: str = BASE_URL) -> Usage:
    with ThreadPoolExecutor(max_workers=2) as pool:
        summary_future = pool.submit(_request, base_url, SUMMARY_PATH, key, timeout)
        credits_future = pool.submit(_request, base_url, CREDITS_PATH, key, timeout)
        summary = summary_future.result()
        credits = credits_future.result()
    tokens, monthly_cost, _ = _summary(summary)
    window = credits.get("windowLimits", {}) if isinstance(credits, dict) else {}
    window = window if isinstance(window, dict) else {}
    five = window.get("fiveHour", {})
    five = five if isinstance(five, dict) else {}
    weekly = window.get("weekly", {})
    weekly = weekly if isinstance(weekly, dict) else {}
    credit_data = credits.get("credits", {}) if isinstance(credits, dict) else {}
    credit_data = credit_data if isinstance(credit_data, dict) else {}
    monthly_cap = _number(credit_data, "monthlyCredits")
    five_used, five_cap = _number(five, "used"), _number(five, "cap")
    weekly_used, weekly_cap = _number(weekly, "used"), _number(weekly, "cap")
    limited = window.get("limited")
    status = "READY" if limited is False else "NOT READY"
    return Usage(
        total_tokens="—" if tokens is None else f"{tokens:,.0f}",
        monthly=f"{_money(monthly_cost)} / {_money(monthly_cap)}",
        five_hour=f"{_money(five_used)} / {_money(five_cap)}",
        weekly=f"{_money(weekly_used)} / {_money(weekly_cap)}",
        status=status,
        monthly_pct=_percent(monthly_cost, monthly_cap),
        five_hour_pct=_percent(five_used, five_cap),
        weekly_pct=_percent(weekly_used, weekly_cap),
        five_hour_reset_at=_reset(five),
        weekly_reset_at=_reset(weekly),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show Command Code usage for multiple API keys")
    parser.add_argument("--keys", default=os.getenv("CMD_API_KEYS"), help="comma/newline keys or JSON array/object (or CMD_API_KEYS)")
    parser.add_argument("--keys-file", type=Path, help="read key input from a file")
    parser.add_argument("--base-url", default=os.getenv("CMD_API_BASE_URL", BASE_URL))
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--export", type=Path, help="write redacted usage rows as JSON or CSV")
    parser.add_argument("--export-format", choices=("json", "csv"), help="format for --export (otherwise inferred from extension)")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    args = parser.parse_args(argv)
    if args.keys_file:
        try:
            raw_keys = args.keys_file.read_text()
        except OSError as error:
            parser.error(f"cannot read --keys-file: {error}")
    else:
        raw_keys = args.keys
    if not raw_keys:
        parser.error("set CMD_API_KEYS, --keys, or --keys-file")
    try:
        named_keys = _parse_keys(raw_keys)
    except ValueError as error:
        parser.error(str(error))
    if not named_keys:
        parser.error("no API keys provided")
    failures = 0
    with ThreadPoolExecutor(max_workers=min(4, len(named_keys))) as pool:
        futures = {pool.submit(fetch, key, args.timeout, args.base_url): index for index, (_, key) in enumerate(named_keys, 1)}
        results = {}
        for future in as_completed(futures):
            index = futures[future]
            try:
                results[index] = future.result()
            except (RuntimeError, ValueError) as error:
                failures += 1
                results[index] = Usage(monthly=f"ERROR: {error}")
    rows = [(name or f"key-{index}", key, results[index]) for index, (name, key) in enumerate(named_keys, 1)]
    if args.export:
        format_name = args.export_format or ("csv" if args.export.suffix.lower() == ".csv" else "json")
        _export(rows, args.export, format_name)
    else:
        display_rows = [(name, usage) for name, _, usage in rows]
        print(_render_table(display_rows, width=shutil.get_terminal_size().columns, color=sys.stdout.isatty() and not args.no_color))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
