# Capability and skill catalog

These are application modules, not installable Codex skills.

| Module | Responsibility | Boundary |
| --- | --- | --- |
| `concierge_chain.py` | Resumable request processing | Drafts and reviewed actions |
| `concierge_workflow.py` | Local classification, extraction, validation | English parser; ISO dates recommended |
| `concierge_llm.py` | Optional structured interpretation | Configured provider; local fallback |
| `concierge_dialog.py` | Follow-up questions and confirmed details | Encrypted inbox state |
| `concierge_ack.py` | Explicit receipt tests | Acknowledgment only |
| `concierge_events.py` | Concert-search intent | Configured venue coverage |
| `events_service.py` | Listings, shortlists and preferences | No booking; no default venues |
| `calendar_service.py` | Calendar connections and views | Google read-only; iCloud writes through reviewed editor |
| `concierge_schedule.py` | Today/tomorrow schedule queries | Verified sender and calendar assignments |
| `icloud_editor.py` | Explicit create/update and provider readback | Conditional writes; unsupported events rejected |
| `calendar_archive.py` | Encrypted local event history | Up to 90 days; no provider deletion |
| `appointment_traffic.py` | Calendar-based departure checks and wake plan | Scoped native worker; enabled recipients |
| `briefing_service.py` | Daily summaries and recovery | Enabled recipients only |
| `traffic_checks.py` | One-time traffic requests and claim lifecycle | Native Mac routing worker |
| `messaging_worker.py` | Optional SMS/WhatsApp/OpenClaw delivery | Opted-in configured recipients |
| `auth_service.py` | Administrator sessions and scoped workers | Single-household authorization |
| `regional_settings.py` | Locale, country, timezone and units | Interface remains English |

Docker dashboard/API can run on macOS, Windows, and Linux. Native iMessage, Apple
Maps traffic, and wake scheduling require macOS. OpenClaw on Windows follows its
WSL setup. Provider accounts, phone numbers, model downloads and paid service
access are not supplied by this repository. No DeepSeek Harness dependency is installed.
