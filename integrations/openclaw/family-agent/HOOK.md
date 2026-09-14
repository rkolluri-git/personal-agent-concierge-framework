---
name: family-agent
description: Forward allowed WhatsApp FA requests to the local Family Agent review inbox
metadata: {"openclaw":{"events":["message:received"],"requires":{"env":["FAMILY_MESSAGING_CONFIG"]}}}
---

Forward only FA-prefixed direct messages from the dedicated account and configured
opted-in recipients. Reads the private messaging configuration file. Sends matching
text, sender and stable message ID to the local gateway; does not log them. It does
not send replies or suppress OpenClaw's own agent processing. The gateway needs to
be reachable at http://127.0.0.1:8001 from this process. If the relay fails, a generic
error is logged; OpenClaw hooks do not provide a durable delivery queue. Resubmit
a request if it never appears in the dashboard.
