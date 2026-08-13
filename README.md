# Command Code Usage

Small local CLI for displaying usage for multiple Command Code API keys.

## Setup

```sh
python3 -m venv .venv
.venv/bin/pip install pytest
```

Set keys as plain lines, a JSON object, or a JSON array. JSON keeps names
stable for large accounts:

```sh
cat > keys.json <<'JSON'
[{"name":"production","key":"user_REPLACE_ME"},{"name":"staging","key":"user_REPLACE_ME"}]
JSON
./usage.py --keys-file keys.json
```

The table shows `READY`/`NOT READY`, usage values, and progress bars. Use
`--no-color` for logs and `--export usage.json` or `--export usage.csv` for
redacted reports; exported rows never contain API keys.

```sh
./usage.py --keys-file keys.json --export usage.json
```

The CLI calls the same authenticated Studio API used by the website:

```text
GET https://api.commandcode.ai/alpha/usage/summary
GET https://api.commandcode.ai/alpha/billing/credits
Authorization: Bearer <key>
```

It reads the summary totals and computes rolling 5-hour and 7-day costs from
the usage entries. It does not make a model request, so exhausted credits do
not prevent dashboard reads. The documented website currently shows plan
limits as 30% of monthly credits for 5 hours and 60% for 7 days.

Keys are passed only in request headers, never printed or stored. The CLI
returns exit code 1 if any key fails.

```sh
python3 -m pytest -q
```

Revoke any API key pasted into chat, terminals, or logs. Use newly rotated keys only.

