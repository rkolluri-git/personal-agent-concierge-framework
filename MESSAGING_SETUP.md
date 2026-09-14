# Windows, WhatsApp, and a dedicated household number

Messaging is optional. Existing installations default to `imessage`; enabling a
new provider is a deliberate configuration change. Select one outbound provider
per installation. Do not run the old macOS bridge after switching. The claim API
rejects a worker for a different provider, preventing two transports from claiming
the same alert. Family members keep their own contact numbers; the sender is a
separate household identity configured below.

## Choose a route

| Route | Runs on | Dedicated number | Incoming requests | Outgoing reminders |
| --- | --- | --- | --- | --- |
| iMessage | macOS bridge | Signed-in Apple identity | Local Messages access | Existing implementation |
| Twilio SMS | Docker on Windows/macOS/Linux | Provision an SMS-capable Twilio number | Signed provider webhook | SMS from configured number |
| Twilio WhatsApp | Docker on Windows/macOS/Linux | Register an approved WhatsApp sender | Signed provider webhook | Approved notification templates |
| OpenClaw WhatsApp | OpenClaw plus Python 3.10+ in WSL/Linux/macOS | Separate WhatsApp account linked to OpenClaw | Included OpenClaw hook | OpenClaw message CLI |

OpenClaw uses a linked WhatsApp Web session; Twilio is a separate Business Platform
integration. Neither integration is installed, signed in, or enabled automatically.
This package does not acquire a number, create a provider account, approve WhatsApp
templates, or send a test text during setup. OpenClaw is not required for Twilio.

The cross-platform worker queues due calendar and morning briefings and delivers
saved task/other alerts. Apple Maps traffic estimates, macOS wake scheduling,
Messages access, and macOS weekly maintenance remain macOS-only. Keep Docker and
any host worker running and the computer awake for scheduled delivery.

## Windows dashboard

Install Docker Desktop and enable Linux containers. Copy `.env.example` to `.env`,
set `POSTGRES_PASSWORD`, and choose the regional settings. From PowerShell in the
project directory:

```powershell
.\windows\preflight.ps1
.\windows\start.ps1
```

If Windows policy blocks the scripts, use an approved execution policy for your
machine or run the existing `./start.sh` in WSL with Docker integration. Do not
turn off machine-wide security policy merely to run these scripts. The native
preflight checks package files, Docker, Compose, and basic `.env` configuration;
the shell preflight also checks conflicting container ownership and config access.
Python and PostgreSQL for the dashboard run inside Docker.

## Dedicated sender configuration

Choose the matching example and copy it to **`config/messaging.json`**:

- `examples/messaging-twilio-sms.json`
- `examples/messaging-twilio-whatsapp.json`
- `examples/messaging-openclaw.json`

This file contains credentials and private phone numbers. It is ignored by Git
and Docker build context. Restrict file access to the account running the app;
on macOS/Linux use `chmod 600 config/messaging.json`. Never put real values in the
public examples or paste credentials into chat. Generate a random `bridge_token`
of at least 32 characters locally with a password manager (or Python's
`secrets.token_urlsafe(32)`). It authenticates the ingress and worker to the app.

Set `sender_number` to the independent household number, including `+` and the
country code. Add only consenting recipients to `opted_in_recipients`; removing a
number blocks future dispatch after the next config reload. In the dashboard, save
the same exact E.164 number as that member's messaging contact and enable alerts.
Email contacts work only for iMessage. The internal API/database field is still
named `imessage_handle` for compatibility; no database migration is required.

For SMS, obtain an SMS-capable number from Twilio and complete the registrations
required by the provider for your destination countries. For Twilio WhatsApp,
complete sender onboarding and any business verification the provider requests.
The Sandbox is for testing with a shared number; it is not an independent
production identity. With OpenClaw, obtain a separate number capable of WhatsApp's
registration verification, register it on a phone, then link that account. Number
availability, eligibility, fees, and sender approval are managed by the provider;
not every virtual/text number can be used for WhatsApp verification.

## Twilio SMS or WhatsApp

1. Fill the private file: provider, Account SID, Auth Token, dedicated sender,
   bridge token, opted-in recipients, and the exact public HTTPS webhook URL.
2. Set `.env` to `FAMILY_MESSAGING_PROVIDER=twilio-sms` or `twilio-whatsapp`, and
   add `COMPOSE_PROFILES=messaging`.
3. Build the image and run the no-send provider configuration check:

   ```sh
   docker compose build
   docker compose run --rm --no-deps messaging-worker python messaging_worker.py --check
   ```

4. Run `./start.sh` (WSL/macOS/Linux) or `.\windows\start.ps1` (PowerShell).
5. Route a trusted HTTPS reverse proxy/tunnel to **127.0.0.1:8001**, and register
   `https://YOUR-HOST/webhooks/twilio` as the number's incoming-message POST webhook.
   Use the identical URL in the private file: signatures include the exact URL.
   Expose only this ingress service. Do not publish port 8000, PostgreSQL, or the
   dashboard through the tunnel. No tunnel or public access is created by setup.

The ingress validates Twilio's signature using its SDK, checks the account and
destination sender, bounds request size, and filters recipients. Only FA-prefixed
text enters the existing encrypted Concierge review flow. The bridge token grants scoped messaging API access, not administrator access.
Stable provider IDs are
namespaced and deduplicated. Unknown senders and ordinary messages are ignored.
The iMessage intake can queue acknowledgments and clarification questions.
Incoming requests create reviewable drafts; they do not directly execute tasks.
The separate Twilio/OpenClaw intake currently uses the basic preview flow;
multi-turn iMessage dialog behavior is not guaranteed for those adapters.
Provider opt-out rules (including SMS STOP handling) still apply.

### WhatsApp scheduled notifications

WhatsApp free-form replies are limited to the customer-service window after an
incoming message. This worker uses approved **Content Templates** for all scheduled
WhatsApp sends, so reminders do not depend on a recently opened session. Set
`content_sid` and match `content_variables` to the slots in your approved template.
Only `{member_name}` and `{message}` are substituted. For example, slot 1 can contain
`{member_name}` and slot 2 `{message}` if that template design is approved. A fixed
notification with no variables is also supported, but it will not include the
alert's details. Example variables are illustrative and do not guarantee approval.
Templates, opt-in, sender approval, and provider restrictions must be satisfied
before activation. No free-form fallback is attempted on template failure.

## OpenClaw WhatsApp on Windows via WSL

Use OpenClaw's Windows/WSL setup guide, and install Python 3.10+ in the same WSL
environment. The adapter targets the WSL/Linux/macOS CLI, not a Windows `.cmd`
launcher. Ensure WSL can reach the Docker dashboard at `http://127.0.0.1:8000` and
ingress at `http://127.0.0.1:8001`; networking depends on Docker/WSL configuration.
If it cannot, run the Docker CLI and app in the integrated WSL environment before
continuing. The supplied hook intentionally only forwards to local loopback.

1. Set the private config provider to `openclaw` and account to `family`. The
   `sender_number` must match the WhatsApp account you link; verify this yourself
   in OpenClaw's channel status. The configuration checker cannot prove ownership.
2. Set `.env` to `FAMILY_MESSAGING_PROVIDER=openclaw` and
   `COMPOSE_PROFILES=messaging-ingress`, then start Personal Agent. This starts only
   the narrow ingress service; the outbound OpenClaw worker runs on the host.
3. Merge `examples/openclaw-whatsapp.json` into your existing OpenClaw configuration,
   replacing recipient examples. Preserve unrelated settings. It uses a dedicated
   `family` account, an explicit DM allowlist, and disables group intake.
4. Install/link the WhatsApp channel interactively in OpenClaw:

   ```sh
   openclaw channels add --channel whatsapp --account family
   openclaw channels login --channel whatsapp --account family
   openclaw channels status
   ```

   Complete the channel/plugin setup and scan the QR code with the dedicated
   account. Keep the gateway running. In multi-agent OpenClaw setups, configure a
   System Agent owner according to the official message CLI documentation.
5. In a WSL terminal in the project directory, set the host worker environment:

   ```sh
   export FAMILY_MESSAGING_PROVIDER=openclaw
   export FAMILY_MESSAGING_CONFIG="$PWD/config/messaging.json"
   python3 backend/messaging_worker.py --check
   python3 backend/messaging_worker.py
   ```

   The foreground worker polls every 30 seconds. Manage it with your normal user
   service manager for unattended use; this package does not install that service.
6. For incoming FA requests, copy `integrations/openclaw/family-agent/` into
   `~/.openclaw/hooks/family-agent/`. Set `FAMILY_MESSAGING_CONFIG` to the absolute
   private file path in the **OpenClaw Gateway process environment**, not only in
   an unrelated terminal. Then run `openclaw hooks enable family-agent`, ensure
   internal hooks are enabled/loaded, and restart/reload your gateway as needed.

The hook checks channel, account, sender allowlist, FA prefix, and stable message
ID before forwarding. It does not read unrelated files or send a reply. It is an
observer and does **not** suppress OpenClaw's normal agent response or actions;
configure that separate agent's behavior/tools for your intended household use.
A disconnected ingress can lose a hook event: there is no durable hook retry queue.
Check that the request appears in the Concierge Inbox; resubmit if necessary.

## Verification and delivery status

Run configuration checks without sending. Once the number is activated, perform
your own end-to-end test with one consenting recipient: send `FA add milk to the
shopping list`, confirm a review item appears, and schedule an alert. Provider
callbacks, real sender registration, live OpenClaw pairing, and delivery are not
verified by the automated tests. The PowerShell scripts also require a real Windows
smoke test; a syntax-check job is included in CI.

`Sent` means the provider/CLI accepted the handoff, **not** delivery or a read
receipt. Definite Twilio client rejections use the existing bounded retry flow.
Timeouts, server failures, and ambiguous OpenClaw exits become `uncertain` to avoid
blind duplicate sends. Provider delivery receipts and automatic number purchasing
are not implemented. Existing pending alerts use the newly selected provider when
claimed; review or clear them before switching a populated installation.

## Sources

- [Twilio WhatsApp overview and onboarding](https://www.twilio.com/docs/whatsapp/api)
- [Twilio Sandbox](https://www.twilio.com/docs/whatsapp/sandbox)
- [Twilio webhook signature validation](https://www.twilio.com/docs/usage/webhooks/webhooks-security)
- [Twilio Content Templates](https://www.twilio.com/docs/content/send-templates-created-with-the-content-template-builder)
- [OpenClaw Windows setup](https://docs.openclaw.ai/platforms/windows)
- [OpenClaw WhatsApp accounts](https://docs.openclaw.ai/channels/whatsapp)
- [OpenClaw message CLI](https://docs.openclaw.ai/cli/message)
- [OpenClaw hook contract](https://docs.openclaw.ai/automation/hooks/writing-hooks)
- [OpenClaw message event fields](https://docs.openclaw.ai/automation/hooks/event-types)

The dashboard now requires administrator sign-in; see [PRIVACY.md](PRIVACY.md).
