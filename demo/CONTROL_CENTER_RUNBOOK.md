# October 15 Control Center allocations

Status: verified in isolated server staging at `/home/bkyanjo3/CryoLauncher-parallel/control-allocations-1015-e21qj4vi`. 421 focused tests passed plus the live kernel credential-isolation test (23.92 seconds). Production deployment approval is pending. No production source, database, service, or AWS resource was changed.

## Deployment prerequisites

Use `/home/bkyanjo3/CryoLauncher` and its existing launcher Python environment. Before applying the supplied `control-center-integration.patch`, compare its baseline against current files (`patch --dry-run -p1`). Stop if files changed concurrently or a hunk rejects; reconcile the exact hunk rather than replacing whole shared files. Save SHA256 checksums and copies of every changed file in a timestamped directory outside the checkout. Do not touch external/FrozenLegacies or application registries.

Inspect `/home/bkyanjo3/CryoLauncher-parallel/_changes/r7-byo.patch` against production. The local snapshot already contains that fix; the allocation patch does not carry it. Run `git apply --check` before applying it to a staging copy, and reconcile any existing changes. Ordinary users must never use server credentials, unverified or broken BYO connections must fail closed, and host-account roles must be rejected at verification and execution. Keep CRYOSTACK_CLOUD_OPERATOR_USER_IDS empty for this demo. Do not change AWS principals or issue any live AWS calls.

Completed on fresh staging databases with production paths protected by the repository audit hook (expanded suite also included CryoLauncher and ICESEE UI negative authorization tests):

```sh
python3 -m pytest control_center/tests/test_allocations.py control_center/tests/test_allocation_http.py control_center/tests/test_control_compute.py control_center/tests/test_control_ops_http.py cryostack_src/cloud/tests/test_cloud_connect_execution.py cryostack_src/cloud/tests/test_cloud_connect_isolation.py cryostack_src/cloud/tests/test_cloud_connect_onboarding.py cryostack_src/tests/test_kernel_credential_isolation.py -q
```

The prior intermittent live-kernel test passed on the server with the original credential assertions unchanged. It covers authenticated rendering, anonymous websocket denial, denial of arbitrary execution, per-user identity, clean kernel environments, and kernel restart. Logs: `staging-focused-tests.log` and `staging-kernel-test.log` in staging. A single successful run does not prove an intermittent issue can never recur.

## Approval-controlled deployment

Obtain explicit user approval before applying to production or restarting. The reviewed helper checks SHA256 baselines for all 26 files, refuses concurrent source changes, backs up source and the authentication database privately, sends SIGTERM only to the one gateway whose working directory is `/home/bkyanjo3/CryoLauncher`, and relaunches its exact command with its existing environment. Environment secrets stay in memory and are never logged or backed up. Its default invocation is read-only:

```sh
cd /home/bkyanjo3/CryoLauncher-parallel/control-allocations-1015-e21qj4vi
python3 deploy_control_allocations.py
```

Only after explicit deployment approval:

```sh
cd /home/bkyanjo3/CryoLauncher-parallel/control-allocations-1015-e21qj4vi
python3 deploy_control_allocations.py --deploy
```

Do not use `deployment/services.sh restart-gui`: inspection found global `pkill` patterns for all gateway/Voila processes. The scoped helper lets the selected gateway's cleanup stop only its own managed children. The connector relay remains running. All applications sharing this gateway may be briefly unavailable during the approved restart; Frozen Legacies source and data are untouched. Keep a maintenance window for active sessions.

Never use the all-services restart. Re-run the read-only helper immediately before deployment. The allocation service creates its tables and migrates two cohort columns at normal gateway startup. It updates the new-user trigger; do not share the production database with a standalone simulation process. No feature flag or port 18080 is needed. The running production operator allowlist was confirmed empty; the helper refuses deployment if it becomes nonempty. Automatic credits start disabled until an administrator creates/enables a policy. No live managed AWS mode exists in these allocation endpoints.

Verify the normal HTTPS URL, session login, role denial, and existing application health before declaring success.

## Normal-URL walkthrough

1. Sign in with an existing CryoStack admin/owner identity at https://cryostack.eas.gatech.edu/control/. Under COMPUTE select Resource Allocations, or open https://cryostack.eas.gatech.edu/control/allocations.
2. Create a Funding Pool: name `Oct 15 simulation`, budget $100. In Automatic Credits choose $10, enable the checkbox, and restrict the eligible email domain and/or institution as desired. Both restrictions must match when specified; blanks allow all. These are registration metadata filters, not verified institutional membership. Save. Table amounts are integer cents.
3. In User Allocations assign an existing researcher's real user ID +$10 with a reason. Copy IDs from the existing Users page. Existing users receive no retroactive automatic grants.
4. In the researcher's existing session open https://cryostack.eas.gatech.edu/compute/allocations. Reserve ICESEE or CryoLauncher, Small, 15 minutes. Observe a 150-cent reservation ($0.50 ceiling plus $1 overhead). Complete to record a 150-cent simulated charge. Reserve again and cancel to release the second reservation.
5. The administrator sees balances, reservations, simulated jobs, limits, and the latest 100 audit events. Ordinary researchers cannot administer pools or inspect another user's balance or finish another user's job.
6. Register an eligible new real account through the ordinary registration flow to show the one-time automatic credit. Disable the policy and register another account to show no new grant; re-enable with $5 to show the adjustable amount. Avoid unnecessary real registrations during rehearsal.
7. Show Cloud → Resource Allocations and the simulation warning. No scientific job or AWS resource is launched. Actual BYO cloud execution uses the user's verified account and incurs charges in that account; do not launch it during this demo. Credits do not authorize or pay for real AWS execution.

## Rollback

Stop only the GUI gateway during an approved maintenance window. Verify that no shared source file has changed since deployment. Restore backed-up versions of the changed files and the BYO files only if rollback of that security fix has been explicitly reviewed. Prefer preserving the BYO safeguards. Remove any newly added files only if their checksums still match the deployed versions.

Do not restore the whole authentication database after users have registered or other writes occurred: that would discard unrelated production data. Disable all introductory policies first. To reverse the allocation migration while preserving other data, with the gateway stopped and an online backup secured, drop only `allocation_new_user`; retain allocation tables and audit history for recovery. The prior gated code must not be re-enabled against retained policies until reviewed. Relaunch only the selected gateway using the preserved startup settings and verify normal login/application health. Avoid broad process-matching restart commands. A full database restore is permissible only when no intervening writes occurred and the operator has verified that condition.
