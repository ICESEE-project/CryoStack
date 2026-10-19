# Owner continuity and 10 November delivery program

This owner-only handbook is the continuity entry point for CryoStack. It must
contain procedures and references, never secret values. Credential locations,
custodians, and rotation procedures may be named; tokens, passwords, private
keys, recovery codes, and service-account JSON must not be copied here.

## Delivery objective

Complete the planned Frozen Legacies functionality by **10 November 2026** or
earlier. After feature completion, prioritize scientific validation, regression
testing, performance, usability, documentation, and safe updates rather than
new major features.

The completion gate includes RIGGS scientific context; embedded radar-image,
radargram, digitized-data, and picker-output previews; scalable dataset
ingestion; durable CEDAR-backed storage; quota and disk guards; provenance;
authorization; backup/restore; and desktop/mobile validation.

## Daily autonomous work program

Run three persistent, isolated workstreams every night in `America/New_York`,
starting at 21:00 and ending at 03:00. Stop new edits at 02:30, finish
verification and documentation, and leave a consolidated morning report for
the owner to review before any deployment or production decision.

### Workstream 1 — Frozen Legacies product and science workflow

Own RIGGS layers, right-panel previews, dataset manifests and ingestion,
LYRA guidance/calibration/echo workflow, browser/mobile behavior, scientific
labels, and Frozen Legacies documentation. It must not modify shared storage,
authentication, or deployment contracts without an interface review.

### Workstream 2 — storage, CEDAR, and resilience

Own CEDAR mount readiness, durable roots, quotas, local-disk guards, atomic and
resumable ingestion, checksums, backup/restore, and outage runbooks. It must not
migrate production data without an approved backup, migration, verification,
rollback, and recovery plan.

### Workstream 3 — integration, validation, and continuity

Own full regression and browser suites, authorization and workspace isolation,
cross-service compatibility, large-TIFF performance tests, release evidence,
and platform-wide developer/operations documentation. It independently reviews
high-risk work from the other streams.

Use isolated worktrees and branches (`codex/frozen-product`,
`codex/storage-cedar`, and `codex/integration-docs`). Maintain a shared work
ledger with task, owner, reserved components, dependencies, tests, status, and
commit. Cross-owned schema, API, navigation, authentication, deployment, or
storage changes require an interface note and review. Production deployment is
serialized through one release operator.

Each daily report records outcomes, documentation, test/browser/performance
evidence, current work, blockers, risks, approval requests, prioritized
improvements, tomorrow's reservations, completion estimate, and deployment
recommendation. Notify the owner for the daily summary, a failure, a material
blocker, or an approval—not for unchanged status.

## Accelerated delivery gates

- **By 23 October:** requirements, provenance decisions, CEDAR inventory,
  service inventory, owner-only documentation boundary, and baseline tests.
- **By 31 October:** previews, RIGGS layer, scalable ingestion, development
  CEDAR configuration, quotas/guards, and continuously updated guides.
- **By 6 November:** development cutover, restart/rollback/restore/outage
  testing, representative TIFF load test, and resolution of critical findings.
- **7–10 November:** feature freeze, complete validation, evidence package,
  rollback rehearsal, known limitations, and readiness decision.

## Mandatory release gates

1. Acceptance criteria, provenance, permissions, and rollback are documented.
2. Focused tests pass without weakening tests or inventing scientific data.
3. Full regression, authorization, isolation, and browser tests pass.
4. Backup is verified, restore tested, checksums recorded, rollback rehearsed.
5. Unapproved picker results remain scientifically unvalidated and ineligible
   for publication.
6. Private results and owner documentation pass positive and negative access
   tests.
7. Production migration/deployment receives owner approval and post-deployment
   durable-state checks.
8. Architecture, configuration, runbooks, recovery, and limitations are updated.

### Canonical first-party regression

Run CryoStack's maintained Python suites explicitly so pytest does not recurse
into vendored research projects with separate environments. Clear host state
that can select a production-like data root or cloud principal:

```bash
env -u CRYOSTACK_DATA_ROOT \
    -u CRYOSTACK_AWS_PRINCIPAL_ARN \
    -u CRYOSTACK_CF_TEMPLATE_URL \
    python -m pytest -q \
    cryostack_src icesee_jupyter_book icesee_hpc_connector deployment control_center
```

Record the revision, command, pass/skip/fail totals, duration, and warning
count in the release evidence. This is the first-party Python regression, not
a substitute for the real browser/device, representative large-TIFF,
non-production restore, or external cloud/HPC checks required by a change.

## Owner deployment-review checklist

Before authorizing production deployment, the owner must:

1. Review the complete diff and release evidence, including the canonical
   regression above, focused authorization/workspace-isolation tests, real
   desktop and narrow/mobile browser checks, and representative large-TIFF
   timings against an agreed threshold.
2. Confirm scientific provenance and validation status. Keep unapproved picker
   output marked unvalidated and ineligible for publication.
3. Confirm the production release identifier, service inventory and boot
   order, configuration changes, secret references (never values), dependency
   changes, known limitations, and named release/rollback operators.
4. Verify CEDAR mount type, path, device, ACLs, capacity, inode headroom,
   snapshots, retention, monitoring, off-host encrypted backup custody, and
   recovery ownership/RTO from administrator evidence.
5. Review a verified backup manifest and checksums plus successful restore,
   cutover, outage, and rollback rehearsals in an empty non-production target.
6. Approve the exact migration/deployment/restart window and rollback trigger.
   Approval for review or rehearsal is not approval for production action.
7. After the authorized deployment, require health, authentication,
   authorization, workspace isolation, durable-store location/capacity, backup,
   audit-log, and representative application smoke checks before declaring the
   release complete.

## Delegating documentation access

Developer and operator documentation is owner-controlled. Owners always have
access. A maintainer or admin has access only while the separate, audited
`developer_docs` capability is present; neither role receives it implicitly.

1. Open **Control Center → Users** and select the maintainer or admin.
2. Under **Platform Access**, select **Allow access to owner documentation and
   Developer Guides**, enter a meaningful reason, and save.
3. Verify that the recipient can open `/docs/developer_guide.html` and
   `/docs/maintainer/`, while an otherwise equivalent account without the
   grant receives `403`.
4. Clear the checkbox when coverage ends. Demotion to developer or user also
   revokes the capability in the same database transaction.
5. Confirm the `developer_docs_access_changed` event in the audit log.

Do not grant the capability merely to share a user manual. Never place secret
values in these guides: role protection limits readership but does not turn a
documentation page into a secret store.

## Seven-month absence documentation backlog

P0 material must be completed first: production service topology and boot
sequence; one deployment/rollback checklist; CEDAR mount and recovery; every
authoritative store and backup/restore order; OAuth and owner recovery; a
secret-reference and rotation inventory; monitoring, logs, alerts, and incident
playbooks; and a “first day back” system-verification checklist.

P1 application runbooks cover Frozen Legacies, LIVIST, CryoLauncher/ICESEE,
Control Center, Connector/Relay, BYO-AWS/CloudFormation, and PACE/HPC. Each must
state startup, dependencies, authoritative data, routine operation, health
checks, common failures, recovery, tests, deployment, rollback, ownership, and
known limitations.

P2 material covers autonomous-agent boundaries and shutdown, release evidence,
dependency/security maintenance, data governance, licensing, retention,
scientific approval, correction, and succession contacts.

## First day back

1. Read this page, the current roadmap, the latest daily/release report, and
   unresolved risks before changing production.
2. Confirm the production release/commit and review changes made during leave.
3. Run storage, service, authentication, connector, backup, and restore-health
   checks; confirm capacity and CEDAR mount state.
4. Review audit events, dependency/security notices, failed jobs, scientific
   validation status, and pending owner decisions.
5. Rehearse recovery in a non-production target before rotating credentials or
   performing a migration.

## Installed daily coordinator

The user-session units `cryostack-autonomy-night.service` and
`cryostack-autonomy-night.timer` start the coordinator at 21:00. A persistent
timer catches a missed start after laptop resume. The runner accepts delayed
starts until 03:00, assigns post-midnight work to the preceding evening, runs
at most once per night, and uses a file lock to prevent overlap. A failed run
preserves its Codex session and retries after 15 minutes while the window
remains open, including temporary credit/rate-limit failures.

Source configuration lives in `deployment/autonomy/`. Runtime reports and logs
live under `$CRYOSTACK_DATA_ROOT/autonomy` (normally
`~/cryostack-data/autonomy`), outside the source tree. The Codex process uses
the workspace-write sandbox and automatic approval review; its prompt forbids
production deployment, restart, destructive migration, secrets changes,
scientific approval, commits, and pushes without the owner's explicit approval.

Inspect with `systemctl --user list-timers 'cryostack-autonomy*'`; disable with
`systemctl --user disable --now cryostack-autonomy.timer
cryostack-autonomy-night.timer cryostack-autonomy.service`; reinstall after unit changes with
`bash deployment/autonomy/install_user_service.sh`.
