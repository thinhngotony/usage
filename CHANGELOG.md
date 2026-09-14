# Changelog

## [Unreleased]

### Fixed

- Kept unavailable accounts unavailable when an exhausted limit has no reset time.
- Waited for the last exhausted limit to reset before marking an account ready.
- Preserved reset dates and the limiting window in narrow terminal output.
- Rejected empty key files with a clear CLI error.
- Replaced missing usage and reset values with `UNKNOWN`.
- Added full reset weekdays and concise `NOW`/`UNKNOWN` statuses.

### Improved

- Increased the bounded account refresh fan-out from four to five accounts.
- Replaced multi-line metric rows with compact usage and reset columns.


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
