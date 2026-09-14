# Lessons learned

1. Publish from a source allowlist. Ignore rules alone cannot remove secrets
   already present in files, history, author metadata, or build artifacts.
2. Protect loopback services too. Administrator sessions and scoped worker keys
   prevent ordinary unauthenticated API reads; household roles are not API roles.
3. Keep interpretation separate from execution. Validate model output and retain
   the review step. Follow-up messages should preserve previously confirmed fields.
4. Treat source text as private. Inbox plans and requests need protected storage;
   optional hosted models necessarily receive the context submitted to them.
5. Make local assumptions configurable. Country, timezone, school calendars,
   venue sources, budget currency, contacts, and transport accounts belong in config.
6. Record uncertain outcomes. Retry boundaries and idempotency matter for message
   delivery, traffic claims, and scheduled summaries. Acceptance is not proof of delivery.
7. Test failure paths with synthetic data. Block unmocked network access and keep
   test databases and encryption keys separate from installed household resources.
8. Preserve working implementations during publication. A clean public baseline
   should not reset a running installation or copy its runtime state.
9. Document limitations alongside features. Locale formatting is not language
   translation, explicit reviewed saves must be distinguished from draft creation, and native Mac tools are not portable.

10. Validate changes after provider writes. Conditional versions and readback checks
    reduce conflicts and prevent claiming a save whose content differs from the draft.
11. Keep routine reconciliation idempotent. Unchanged calendar context should not
    be encrypted or written again every minute, and missing contacts must not be
    reported as successful notifications.
