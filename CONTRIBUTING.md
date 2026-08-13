# Contributing

## Development

```sh
python3 -m venv .venv
.venv/bin/pip install pytest
python3 -m pytest -q
python3 -m py_compile usage.py test_usage.py
```

Runtime code must remain standard-library only unless a dependency is necessary and documented.

## Pull requests

- Keep changes focused.
- Add or update behavior tests.
- Never include API keys, `.usage.json`, `keys.json`, or exported reports.
- Describe security and compatibility impact.
- Wait for GitHub Actions to pass before merging.

## Commit messages

Use imperative conventional subjects such as `feat: add ...`, `fix: correct ...`, or `docs: update ...`.
