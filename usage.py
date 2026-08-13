#!/usr/bin/env python3
"""Display Command Code usage for multiple API keys."""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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


def _keys(raw: str) -> list[str]:
    return [key.strip() for key in raw.replace(",", "\n").splitlines() if key.strip()]


def _number(data: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = data.get(name)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _money(value: float | None) -> str:
    return "—" if value is None else f"${value:.2f}"


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
    five = window.get("fiveHour", {}) if isinstance(window, dict) else {}
    weekly = window.get("weekly", {}) if isinstance(window, dict) else {}
    credit_data = credits.get("credits", {}) if isinstance(credits, dict) else {}
    return Usage(
        "—" if tokens is None else f"{tokens:,.0f}",
        f"{_money(monthly_cost)} / {_money(_number(credit_data, 'monthlyCredits'))}",
        f"{_money(_number(five, 'used'))} / {_money(_number(five, 'cap'))}",
        f"{_money(_number(weekly, 'used'))} / {_money(_number(weekly, 'cap'))}",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show Command Code usage for multiple API keys")
    parser.add_argument("--keys", default=os.getenv("CMD_API_KEYS"), help="comma/newline-separated keys (or CMD_API_KEYS)")
    parser.add_argument("--base-url", default=os.getenv("CMD_API_BASE_URL", BASE_URL))
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args(argv)
    if not args.keys:
        parser.error("set CMD_API_KEYS")
    print("KEY\tTOTAL TOKENS\tMONTHLY\t5-HOUR\tWEEKLY")
    failures = 0
    keys = _keys(args.keys)
    with ThreadPoolExecutor(max_workers=min(4, len(keys))) as pool:
        futures = {pool.submit(fetch, key, args.timeout, args.base_url): index for index, key in enumerate(keys, 1)}
        results = {}
        for future in as_completed(futures):
            index = futures[future]
            try:
                results[index] = future.result()
            except (RuntimeError, ValueError) as error:
                failures += 1
                results[index] = Usage(monthly=f"ERROR: {error}")
    for index in range(1, len(keys) + 1):
        usage = results[index]
        print(f"key-{index}\t{usage.total_tokens}\t{usage.monthly}\t{usage.five_hour}\t{usage.weekly}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
