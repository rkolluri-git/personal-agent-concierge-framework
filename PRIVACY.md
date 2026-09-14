# Authentication and privacy boundaries

The dashboard and API now require authentication by default. Unauthenticated
requests cannot read family members, ages, contact details, calendars, tasks, or
configuration. `/health` remains a public liveness response with no household data.
The login page is public; API documentation and static dashboard assets require
administrator authentication.

## First sign-in and upgrades

On API startup, two independent random keys are created in the private config
mount, with mode `0600`:

- `config/api-auth.key`: household administrator access
- `config/worker-auth.key`: the macOS worker's scoped credential

Existing keys are preserved across restarts. Do not publish them. The first start
requires a writable config directory. After rebuilding, display the administrator
key **locally** with:

```sh
docker compose exec -T family-agent-api python auth_service.py --show-key
```

Open `http://localhost:8000/dashboard` and sign in. Do not paste the key into chat,
issue reports, URLs, or source files. The browser stores a signed, HttpOnly,
SameSite=Strict session cookie, not the access key. Sessions expire after twelve
hours. A same-origin check protects cookie-authenticated changes. HTTPS sessions
also receive the Secure cookie attribute. Responses are marked `no-store`.

Sign out clears the browser's session cookie. Rotating `api-auth.key` invalidates
all existing administrator keys and session cookies. To rotate deliberately, stop
the API, move the old file to a protected backup location outside the repository,
and restart; a new key will be created. Sign in again with the new key. A copied
session cookie remains valid until expiry or key rotation, even after browser
sign-out; this is a stateless session design.

## Worker authorization

The updated macOS worker reads `worker-auth.key` from its existing project config
directory. Update the worker code as well as the container during deployment.
It can claim/complete scheduled work, submit FA requests, and perform the limited
health/calendar/weather checks needed by its current features. It cannot list
contacts, family profiles, arbitrary tasks, or API documentation.

Twilio/OpenClaw workers keep using `bridge_token` from private messaging config.
It grants only the required messaging operations; it is not a dashboard login.
The narrow gateway still validates provider signatures or the OpenClaw token and
recipient allowlists. Expose only that ingress for external webhooks.

## Deployment limits

This is a single-household administrator model, not per-member role-based access.
Anyone holding the administrator key can read and modify all household data.
Separate family accounts, account recovery, per-user audit trails, and independent
session revocation are not implemented. The configured household member roles
are scheduling preferences, not API permission roles.

Keep the dashboard/API bound to loopback and use a trusted OS account. Authentication
does not protect against another process running as the same OS user, an OS
administrator, browser compromise, or someone who can read the private config
files. Do not publicly reverse-proxy the API or treat this change as a network
security or penetration-test certification. Broader deployments require their own
HTTPS, identity, authorization, and operational review.

Encryption at rest protects selected database fields; authorized API calls decrypt
them. Calendar, weather, mapping, and messaging providers receive relevant data
when integrations are used. This is not a claim that all runtime data stays local.

## Public Git history

This standardized publication starts with a single reviewed commit using a GitHub
no-reply author and committer identity. Runtime files and earlier commit objects
are not included in the publication checkout.

A rewritten origin cannot recall existing forks, clones, caches, or copied commit
URLs. No blanket “no personal data leakage” certification is made. Reviews should
include file content, commit metadata, all relevant refs, remote artifacts, and
runtime behavior appropriate to the intended deployment.

## Optional interpretation and discovery

The current LLM adapter permits only local Ollama endpoints and rejects redirects,
proxies and cloud-named models. It receives request text, member names and selected
draft context. Protect the local model service and its logs; hosted LLM adapters
are not included in this baseline. Event preferences and cached listings live in private config files and
are not encrypted; protect the config directory and its backups. Google Places and
calendar, weather, routing and messaging integrations send relevant requests externally.

## Current calendar and worker actions

The iCloud editor can explicitly create/update supported events after review. Google
calendar access remains read-only. Local archives encrypt event content; provider
readback verifies iCloud saves. Mac worker keys can claim/complete appointment traffic
and read bounded wake timestamps, but cannot edit calendars or recipient settings.
The optional privileged wake helper receives a copied worker key, not the admin key.
