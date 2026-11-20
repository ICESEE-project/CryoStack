# Troubleshooting the soft launch

| Symptom | Check and next action |
|---|---|
| AWS account connected but no project credits shown | Connection and funding are separate. Ask the organizer to confirm the participant allocation; do not assume a personal account is funded. |
| Prepare cloud waits | Open Run Log. Wait until Account shows Connected and Storage, Containers and Compute show Ready. Do not repeatedly click Prepare or create replacement infrastructure. |
| Cost unavailable | Stop participant launch and ask the organizer for a reviewed limit. Runtime estimates may fall back to the configured timeout. |
| Queued / Starting | Scheduling and image startup can exceed computation time. Keep one job active and watch status/logs. |
| MATLAB license error | Use the private license instructions and supported Connector path. Check reachability; do not embed license data in an example. |
| File selected but missing from Datasets | Click the second Upload button to persist selected files. Refresh the list. |
| Reference button disabled | Select a dataset and a user-owned example; clone or create an example first. |
| File not found during initialization | Check exact basename, case, and `data/` path. Leave the reference alias blank unless the script expects a different name. |
| Missing reference / conflicting alias | Re-upload the missing input or choose distinct relative names; do not rely on stale staged files. |
| Empty / malformed / wrong-model data | Use the correct model's small JSON, preserve metadata/units, and run the supplied validator. |
| Read-only canonical example | Clone to My Workspace. Save your working copy and select it as the run source. |
| Unsaved edits prevent switching | Save first, or deliberately discard the changes using the UI. |
| PC import succeeds but execution fails | Activate the full model environment, including its matching MPI compiler and libraries. Check the compile log. |
| Completed but no fields | Inspect export metadata; ensure Icepack fields remain in module globals and the mesh is supported. For the mesh/functions tutorial, inspect figures instead. |
| Logs unavailable but results present | A log-read permission error is distinct from a failed model run. Report it without discarding valid outputs. |
| Download fails | Keep the run ID, check results retrieval, and retry once. Do not re-run an expensive simulation merely to download it. |

## Report a bug

Reply to your invitation with model, mode, example, approximate local time/timezone, run ID, expected/observed outcome, browser, and a minimal sanitized reproduction. Include the last relevant error and a screenshot if safe. Never send AWS keys, session tokens, license information, passwords, or private research data.

To stop an active test, use the current run's **Terminate** control and verify a terminal state. Termination does not remove stored outputs or refund previous AWS usage.

## Expected outcome and evidence

A successful submission has a job ID. A successful model run finishes without a solver error. A complete tutorial also has retrievable logs, nonempty results, a readable figure, and a downloaded archive. Record all of these; a green job status alone is insufficient.

**Screenshot slot:** capture the selected model/example, completed run, and results panel using a participant test account. Exclude license fields, account identifiers, tokens, and private paths.

**Recording:** see the [recording matrix](recording_matrix.md) for the reviewed video and the evidence required for this workflow.

[All soft-launch tutorials](../soft_launch.md) · [Troubleshooting](troubleshooting.md)
