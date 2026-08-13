# Security Policy

## Reporting a vulnerability

Do not open a public issue with API keys, tokens, or exploit details.

Report suspected vulnerabilities privately through the repository owner's GitHub security contact. Include reproduction steps, affected files, and impact without including live credentials.

## Credential handling

- Keep `keys.json` and `.usage.json` local with permissions `600`.
- Never commit API keys or exported credential material.
- Revoke and replace any key exposed in chat, shell history, logs, or source.
- This tool sends keys only as HTTPS Bearer headers to Command Code's API.
- Exported JSON and CSV reports omit API key values.
