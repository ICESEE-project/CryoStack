# October 15, 2026 allocation demo

Production target: `gt-cryostack:/home/bkyanjo3/CryoLauncher`.
Development/testing: `/home/bkyanjo3/CryoLauncher-parallel/r7-byo`.

The allocation feature is off unless `CRYOSTACK_ALLOCATION_DEMO=1`. The standalone
demo enables it only in a private, fresh database and binds only to loopback.
It uses the existing CryoStack authentication, roles, and Control Center layouts.
The four application codebases and registry are unchanged. All jobs on this page
are simulated reservations; no scientific jobs, AWS calls, or cloud resources start.

## Start

On the server in a terminal:

```sh
cd /home/bkyanjo3/CryoLauncher
python3 scripts/allocation_demo.py --port 18080
```

Enter a demo-only password at the hidden prompt (at least eight characters).
Do not enter an AWS credential. Leave this terminal open. Each start creates
fresh private state in `/tmp/cryostack-allocation-demo-*`; production users and
databases are never copied. The process strips inherited AWS and CryoStack settings.
No production launcher or service manager is invoked.

On your laptop in another terminal:

```sh
ssh -N -L 18080:127.0.0.1:18080 gt-cryostack
```

Open `http://127.0.0.1:18080/control/allocations` and sign in as
`owner@example.test` with your chosen password. Use a private browser window
for `researcher@example.test` at `/compute/allocations` to keep sessions separate.

## Five-minute demonstration

1. Owner sees the seeded $100 pool, enabled introductory policy, and $10 default.
   Tables show cents: 10000 is $100; 1000 is $10. Copy pool/user IDs from the table.
2. Register a new demo account through `/auth/register`. Its account receives $10
   atomically on creation. Accounts created before policy activation do not receive
   retroactive credits. Intro grants stop if the pool lacks unallocated funds.
3. Owner saves the existing pool with introductory credits unchecked. Register
   another account: no grant. Re-enable and change the default to $5. Existing
   balances are unchanged; a newly registered account gets $5.
4. Adjust the researcher by +$5 with a reason. Observe the new balance and audit.
5. Researcher reserves ICESEE, Small, 15 minutes. $1.50 is reserved: $0.50 ceiling
   plus $1 overhead. Balance drops by the reserved amount. Complete the simulation:
   reserved becomes zero and the full $1.50 becomes a simulated charge.
6. Reserve another job and cancel: the simulation reservation is released.
   Repeat with another of the four application labels. These labels do not execute
   those applications.
7. Show an excessive runtime is rejected; two active jobs per user is enforced.
   Lower a user's unspent allowance to demonstrate insufficient funds. Adjustments
   cannot reclaim reserved or charged credit or overcommit the pool.
8. Owner reviews audit entries. Researcher cannot open administrator pages or read
   another user's allocations. Live managed mode is always rejected.

Stop both terminals with Ctrl-C. Restarting creates a fresh demonstration.

## Guardrails and limits

All values use integer cents. Pool commitments, credit changes, reservations,
finalization and their audit rows commit together under a SQLite write lock.
Retries with the same user/request key and identical parameters reuse the job.
Changed parameters with the same key are rejected. Per-user active limit: two;
platform active limit: ten. Small max runtime: 60 minutes; Medium: 30 minutes.
The displayed rates are fixed demo ceilings, **not AWS prices or billing enforcement**.
Completion charges the entire ceiling; cancellation releases only simulated jobs.
No automatic reservation expiry is used, so a crashed client cannot release a
reservation while an external workload might still run.

BYO jobs continue through the separate verified-account resolver. The r7-byo
patch rejects ordinary users without a connection, unverified connections, and
roles in the service's own AWS account. Operator access is empty by default.
Allocations confer no authority to use host credentials. The demo never invokes
this resolver, an AWS CLI, or a cloud submission backend.

## Live activation remains blocked

Do not restart production, change its environment, or enable live project-funded
execution for this demo. Source-copy authorization does not authorize those steps.
Live execution requires explicit owner approval, dedicated project role and account
review, account verification, instance allowlists, runtime/concurrency limits,
conservative ceilings covering compute/storage/network/service fees, watchdogs,
termination verification, and reconciliation that does not claim exact billing.
There is no live managed execution implementation in this MVP.

The earlier BYO validation report records the kernel credential test stalling on
both rc-1013 (5/24) and r7-byo (4/25), with shell-channel messages ignored while
control-channel replies still worked. A retry did not fix it and was reverted.
Treat this as an unresolved Jupyter transport issue; do not weaken the assertion
or claim credential isolation is proven from aggregate pass counts.

Frozen Legacies source, designs, dependencies and assets are outside this update.
Shared gateway and Control Center files should still be coordinated with anyone
editing those shared files. No commits or pushes are part of this procedure.

## Verified status, October 14

Eight allocation files copied into the production repository with checksums and backup. No Frozen Legacies source changed. No services restarted. The allocation feature remains off in the running gateway. The separate r7-byo patch has NOT been applied to the production checkout; its deployment is still pending. Do not describe current production cloud execution as secured by that patch.

Focused allocation/web/BYO tests: 103 passed. Broader Control Center/BYO/kernel selection: 221 passed, 1 failed. The unchanged kernel test failed at line 397 waiting 30 seconds for kernel_info_reply; no credential-leak assertion failed in this run. Full suite not rerun. Standalone demo assembly and seeded introductory credits verified in both development and destination checkouts.

Backup: /home/bkyanjo3/CryoLauncher-parallel/_changes/allocation-before-copy-1791998947.tar. Restore only its two existing Control Center files if rollback is approved; six added files can remain inert with the feature disabled. Coordinate rollback with concurrent shared-file edits.
