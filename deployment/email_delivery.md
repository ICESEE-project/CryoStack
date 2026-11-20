# Account email delivery

`CRYOSTACK_MAIL_MODE` selects `smtp`, `resend`, `postmark`, `file`, or
`disabled`. Select exactly one transport. There is no automatic cross-provider
retry because a timeout can occur after a provider has already accepted mail.
Registration, one-time email confirmation, owner approval, and account access
checks are independent of the selected transport. Keep owner-only approval on.

## Georgia Tech relay (OIT configuration, November 2026)

The selected GT profile uses `outbound.mail.gatech.edu:25`, STARTTLS, and
`CryoStack <cryostack@eas.gatech.edu>`, the sender authorized by OIT. OIT
confirmed the host allowlist/rDNS repair and documented that certificate
validation fails on its supported relay hostname. The owner selected this
route to avoid an additional email service charge. GT sending limits remain
pending OIT confirmation.

`CRYOSTACK_SMTP_TLS_POLICY=gt-relay-exception` explicitly permits this one
institutional configuration: STARTTLS remains mandatory, but the relay's
certificate chain/hostname is not verified. This encrypts the connection
without authenticating the relay. There is no plaintext fallback. The exception
is rejected unless the host is exactly `outbound.mail.gatech.edu`, port is 25,
security is `starttls`, and both SMTP credential fields are empty. No SMTP2GO
credential is used for GT. Mail JSON cannot change user verification/approval.

The default policy is `verified`; SMTP2GO and HTTPS API transports retain
certificate/hostname verification. The TLS policy is included in SMTP delivery
events and public mail diagnostics. Invalid policy values block delivery and
new registration rather than silently relaxing checks.

Copy `mail.gt-smtp.example.json` into a private provider profile to select GT.
Keep the pre-switch SMTP2GO JSON and password privately for rollback. To
restore SMTP2GO, restore its JSON with `CRYOSTACK_SMTP_TLS_POLICY=verified`
explicitly set and restart the gateway with the retained runtime environment.
An explicit policy reset matters when retaining an existing process environment.

## Retained fallback: SMTP2GO

The temporary production route is `smtp` through `mail.smtp2go.com:587`, with
STARTTLS and ordinary certificate/hostname validation. The sender is
`CryoStack <brian.kyanjo@aims.ac.rw>`, confirmed as a Single Sender in the
SMTP2GO account. Open and click tracking are disabled for the dedicated
`CryoStack` SMTP user. No OIT DNS change was needed. Its password is stored
only in the private server credential file referenced by the active JSON.

The free plan has 1,000 messages/month and 200/day; single-sender sending
without domain verification is limited to 25/hour. Every confirmation,
applicant notice, reviewer notice, decision, and password reset counts.
Additional reviewers increase messages per registration. Provider rate limits
leave notices in the retry queue; monitor Control Center and provider reports.

The live Gmail test received the confirmation, pending, and approval messages
in Spam; the owner confirmed receipt of the review notification. Authentication
results showed SPF/DKIM passing for SMTP2GO's domain, with DMARC unaligned to
the AIMS From address. Single Sender is a temporary delivery route and does
not establish aligned domain authentication. Tell users to check spam/junk;
use a verified sending domain or the repaired GT relay to improve this.

`mail.example.json` is the SMTP2GO template. Keep a separate private GT
profile using `mail.gt-smtp.example.json`; select it with
`CRYOSTACK_MAIL_CONFIG_FILE` when restoring GT SMTP. Both use the existing
SMTP transport; switching profiles changes the provider without code edits.
The GT example contains the OIT-authorized sender and explicit institutional
TLS policy, but no secret. Test delivery before switching production profiles.

## Activate a provider

The production service manager loads `$HOME/.config/cryostack/mail.json` if
present (override the path with `CRYOSTACK_MAIL_CONFIG_FILE`). The file must be
owned by the service user and inaccessible to group/other users (mode 0600).
Only whitelisted mail settings are accepted. Values in this JSON override the
service manager's defaults and inherited mail settings. It cannot configure
approval or verification policy. Use a private directory (mode 0700).

1. Obtain a production-authorized sender and provider credential. For SMTP2GO,
   confirm a Single Sender on a domain whose DMARC policy permits it and create
   a dedicated SMTP user. The retained fallback account uses this route.
   Postmark can
   confirm one private-domain Sender Signature through email without DNS;
   its account must also be approved for sending to arbitrary recipients.
   Resend needs an already verified sending domain; `resend.dev` only permits
   the account owner's recipient address and cannot serve public signup.
2. Store the credential in a separate, service-owned regular file, mode 0600.
   Do not put a credential in the repository, JSON settings, shell command,
   process environment, or logs.
3. Copy `deployment/mail.example.json` to the private path and replace the
   sender, SMTP username, and credential path for SMTP2GO. For Resend, select `resend` and use
   `CRYOSTACK_RESEND_API_KEY_FILE`. For Postmark, select `postmark` and use
   `CRYOSTACK_POSTMARK_SERVER_TOKEN_FILE`. Preserve GT SMTP settings in the
   separate private GT profile for later restoration. Its example SMTP port is
   25, matching the inspected relay; confirm OIT's intended port when restoring it.
4. Disable authentication-email click tracking for the Resend sending domain.
   The Postmark adapter explicitly disables link and open tracking.
5. Restart only the GUI gateway with its existing environment and interpreter:
   `bash deployment/services.sh restart-gui`. Do not lose unrelated runtime
   settings when launching it from a new shell. Connector restart is unnecessary.
6. Register a controlled working inbox through `/auth/register`, receive the
   confirmation email, open the link and explicitly submit confirmation.
   Confirm the account is still pending; verify the owner's review notice;
   have the owner approve in Control Center; receive the approval email;
   sign in and check protected application access. Confirm an unapproved
   account stays blocked. Provider acceptance alone is not this validation.

`file` is an isolated testing mode and is never a production email fallback.
Disabled/invalid configuration returns HTTP 503 for password registration and
verification resend, before creating an account or replacing a valid token.
For a configured provider that subsequently fails, mail stays in the durable
outbox and retries with backoff. The registration page says queued, not sent.
Ten unsuccessful attempts mark the row failed; Control Center supports retry.
Previously queued expired, used, and superseded confirmation/reset links are
cancelled before submission. Existing unverified users should sign in and use
"Send the link again" after delivery is restored.

## Delivery evidence and failures

The gateway log (`icesee.log`) contains `cryostack_mail` JSON events:
`queued`, `attempt`, `accepted`, `retry`, `blocked`, `cancelled`. Entries contain
the provider, outbox ID, template, attempt and sanitized protocol error. API
acceptance includes the provider receipt ID. Addresses, bodies, links, tokens,
and provider credentials are excluded. Errors with response content are never
copied into the database or logs. `blocked` is emitted once per configuration
state to avoid a repeated warning every worker tick.

The legacy outbox `sent` state means transport acceptance, not delivery or
inbox receipt. Match the logged receipt with the provider dashboard to check
delivery/bounces. This change does not install provider webhooks or poll for
bounces. A bounce after acceptance therefore requires provider monitoring.
Resend retries use the same payload and idempotency key within its 24-hour
retention window. Postmark and SMTP cannot guarantee exactly-once delivery
after an ambiguous network timeout.

## Restore Georgia Tech SMTP

After OIT confirms relay authorization and reverse DNS, test delivery to a
controlled inbox using the explicitly approved TLS policy. Select the private GT profile with
`CRYOSTACK_MAIL_CONFIG_FILE`, or restore its host, port, security, credentials,
and authorized sender in the active JSON. Both routes use `CRYOSTACK_MAIL_MODE=smtp`.
Restart the GUI with its retained environment and repeat the email smoke test.
Certificate/hostname verification is the default; only the explicitly selected
GT relay policy above permits an exception. Switching back to
`disabled` pauses delivery and returns an explicit registration outage; it
does not bypass confirmation or approve any account.

To roll back source, use the task's exact pre-change backups for `mailer.py`,
`manager.py` and `services.sh` after checking for later changes, remove only
the newly added files, and restart the gateway with its retained environment.
No database migration is needed. Pending accounts, tokens and outbox rows
are compatible with the previous source. Retain the protected backups locally;
do not publish auth data or a complete process environment.

Provider requirements: [Resend sender restrictions](https://resend.com/docs/knowledge-base/403-error-resend-dev-domain),
[Postmark Sender Signatures](https://postmarkapp.com/developer/user-guide/managing-your-account/managing-sender-signatures),
[Postmark account approval](https://postmarkapp.com/support/article/1084-how-does-the-account-approval-process-work).

## Backup registration approvers

An owner can add or remove approved, email-confirmed accounts in Control Center
→ Registrations → Registration approvers. Enter their existing account email.
Delegates get registration review notices and can approve/reject pending ordinary
accounts through the authenticated review page. They cannot approve themselves,
manage approvers, change roles, or reach other Control Center pages unless they
already held a separate platform role. Grant/revoke changes are audited, bound
to the exact account/email, and rechecked at decision time. Suspending an account,
changing its email, or removing its delegation makes the permission inactive.
No additional approver is granted automatically by installing this feature.
