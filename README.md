<p align="center">
  <img src="https://img.shields.io/badge/platforms-macOS%20%7C%20Linux-blue" alt="Platforms">
  <img src="https://img.shields.io/badge/python-3.10%2B-green" alt="Python 3.10 or newer">
  <img src="https://img.shields.io/github/license/thinhngotony/usage" alt="License">
  <img src="https://img.shields.io/badge/dependencies-stdlib%20only-brightgreen" alt="Standard library only">
</p>

<h1 align="center">Command Code Usage</h1>

<p align="center">
  <strong>One command. Every Command Code account. Clear usage limits.</strong>
</p>

<p align="center">
  A local, dependency-free dashboard for monitoring multiple Command Code API keys,
  limits, reset times, and token usage without sending credentials to another service.
</p>

---

## Quick Start

Create a named key file. Keep it local and never commit it:

```json
[
  {"name": "production", "key": "user_REPLACE_ME"},
  {"name": "staging", "key": "user_REPLACE_ME"}
]
```

Run the first import:

```bash
./usage.py --keys-file keys.json
```

The imported configuration is saved locally as `.usage.json`. Future refreshes need no arguments:

```bash
./usage.py
```

The program reads only local files. It does not support API keys from environment variables.

## Dashboard

The dashboard uses an aligned table when every value fits. On narrower terminals it switches to an account view, keeping every reset date visible instead of truncating it.

| Column | Meaning |
| :--- | :--- |
| `KEY` | Name from the imported key file |
| `MONTHLY` | Current-period cost, fixed monthly quota, and progress |
| `5-HOUR` | Rolling five-hour cost, cap, and progress |
| `WEEKLY` | Rolling seven-day cost, cap, and progress |
| `STATUS` | `NOW`, `UNKNOWN`, an error, or the limiting reset and exact time when the account becomes usable |

All reset times include the full weekday and use the unambiguous format `Tuesday 15 Sep 2026, 05:00 UTC`. A missing metric or reset time is `UNKNOWN`; `NOW` appears only when every usage window is known and below its limit. If multiple limits are exhausted, an account becomes ready only after the latest applicable reset.

Monthly progress is calculated as current-period cost divided by the fixed `$10.00` monthly quota. Accounts are sorted with currently available accounts first, then by the time they become ready.

Use plain output in logs and CI:

```bash
./usage.py --no-color
```

## Import Formats

JSON object:

```json
{
  "production": "user_REPLACE_ME",
  "staging": "user_REPLACE_ME"
}
```

JSON array:

```json
[
  {"name": "production", "key": "user_REPLACE_ME"},
  {"name": "staging", "key": "user_REPLACE_ME"}
]
```

The array format is recommended for large accounts because it is easy to extend with metadata without changing the key contract.

Replace the saved configuration by importing another file:

```bash
./usage.py --keys-file new-keys.json
```

## Project Information

- [About](ABOUT.md) — scope, architecture, and design decisions
- [Contributing](CONTRIBUTING.md) — development and pull request workflow
- [Security](SECURITY.md) — credential handling and vulnerability reporting
- [Changelog](CHANGELOG.md) — user-facing release history
- [License](LICENSE) — MIT license

Continuous integration runs compilation, the test suite, and credential-pattern checks across supported Python versions for every push and pull request.


## Export

Write a redacted report for sharing or automation:

```bash
./usage.py --export usage.json
./usage.py --export usage.csv
```

Exports include names, token totals, usage percentages, caps, reset timestamps, availability, and the limiting window. API keys are never exported.

## How It Works

The CLI calls Command Code's authenticated API directly:

```text
GET https://api.commandcode.ai/alpha/usage/summary
GET https://api.commandcode.ai/alpha/billing/credits
GET https://api.commandcode.ai/alpha/billing/subscriptions
Authorization: Bearer <key>
```

Requests are made concurrently per account and across accounts, with a bounded five-account concurrency cap. No model request is made, so an exhausted account can still report its usage state.

## Security

```bash
chmod 600 keys.json .usage.json
```

`keys.json` and `.usage.json` are ignored by Git. Do not paste API keys into issues, chat, shell history, or source files. If a key is exposed, revoke it and create a replacement.

See [SECURITY.md](SECURITY.md) for reporting guidance.

## Development

```bash
python3 -m pytest -q
python3 -m py_compile usage.py test_usage.py
```

The project uses only the Python standard library at runtime.

## License

MIT. See [LICENSE](LICENSE).
