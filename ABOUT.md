# About Command Code Usage

Command Code Usage is a local terminal dashboard for people who use multiple Command Code accounts or API keys.

## Problem

Command Code exposes useful usage information in its authenticated Studio interface, but checking several accounts repeatedly is slow and difficult to compare. This tool turns those account reads into one repeatable command.

## What it does

- Imports named accounts from one local JSON file.
- Reads token totals, monthly usage, five-hour usage, and weekly usage.
- Shows human-readable reset times and the earliest applicable availability time.
- Sorts accounts with currently available accounts first.
- Exports redacted JSON or CSV reports.
- Uses concurrent read-only API requests without making model calls.

## What it does not do

- It does not send prompts or consume model credits.
- It does not upload credentials to a third-party dashboard.
- It does not store API keys in exported reports.
- It does not manage billing, purchases, upgrades, or key rotation.

## Design choices

The runtime uses only Python's standard library. The CLI talks directly to Command Code's authenticated API, keeps the local configuration in `.usage.json`, and leaves provider-specific authentication to HTTPS Bearer headers.

The project favors a small executable over a hosted service: fewer moving parts, no account database, no web server, and no new credential trust boundary.

## Intended audience

- Developers with multiple Command Code accounts.
- Teams that need a quick local usage snapshot.
- Automation that needs a redacted JSON or CSV report.

See [README.md](README.md) for usage and [SECURITY.md](SECURITY.md) for credential handling.
