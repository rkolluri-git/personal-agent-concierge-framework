# Standardized baseline validation — September 14, 2026

The publication combines the current local implementation with the previously
reviewed authentication and privacy fixes. It starts with one new public commit.
Only reviewed source categories and synthetic templates were copied; runtime
configuration, data, logs, private keys and old Git objects were excluded.

## Completed checks

- Python 3.14 host: 233 tests and eight subtests passed.
- Python 3.12 Linux container: 233 tests and eight subtests passed with container
  networking disabled and publication source mounted read-only.
- Six OpenClaw hook filtering scenarios passed; no messages were sent.
- Dashboard/login JavaScript, Python source and shell syntax checks passed.
- Docker Compose configuration validated with a synthetic password.
- Production Docker image built successfully using the legacy builder.
- Production API started against a disposable PostgreSQL 16 database on an isolated
  Docker network. Public liveness, protected database health, anonymous denial,
  authenticated synthetic member creation, and empty event/traffic, archive, iCloud calendar selection and appointment wake routes passed.
  Disposable containers, their anonymous volumes and the network were removed.
- New regressions cover protected current API routes, narrow traffic-worker scope,
  calendar-write/archive access, restricted appointment-worker scope, host validation,
  no default school calendar, no default venues, configured currency, credential-free
  HTTPS source URLs and non-US event timezones.
- Targeted identity/credential scans passed after replacing household names and
  historical location fixtures. Public commit metadata uses a no-reply identity.

The test stack emits one upstream Starlette/AnyIO deprecation warning.
The builder initially failed to write BuildKit activity metadata in the restricted
host context; the supported legacy builder completed the production image.

## Limits

No live household data, provider credentials, Safari/Messages session, or running
household containers were used. No live calendar synchronization, message delivery,
LLM invocation, venue scraping, native traffic routing, native Windows execution or
wake registration was tested. Remote CI results are separate from these local checks.
Dependency vulnerability auditing and exhaustive security certification were not
performed. Targeted privacy scans cannot recall old clones, forks or remote caches.

## Current implementation refresh

Includes the unified concierge workspace, schedule queries, explicit iCloud editor,
encrypted local calendar archive, appointment traffic reconciliation and optional
Mac wake helper. Existing public administrator/scoped-worker authentication remains
the access boundary. The optional LLM adapter now follows the current implementation's
local-only Ollama restrictions. Calendar provider writes were tested with mocks only.
A prior baseline Git bundle is kept outside the publication checkout for rollback.
