# Changelog

## [1.0.0] - 2026-08-13

### Added

- Named JSON key imports for multiple Command Code accounts.
- Persistent local configuration after the first import.
- Token, monthly, five-hour, and weekly usage reporting.
- Human-readable reset dates and availability ordering.
- Progress bars and aligned terminal dashboard output.
- Redacted JSON and CSV exports.
- Concurrent API reads with a conservative account concurrency cap.

### Security

- API keys remain local and are never included in exports.
- Credential files are ignored by Git and documented for restrictive permissions.
