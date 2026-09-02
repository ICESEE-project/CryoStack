# AUDIT — approval integrity across approval → staging → execution (PASS 4, task 5)

Read-only review + design. Evidence `file:line` at HEAD `a35c5e9`.

Objective: **what the human approved == what CryoStack executes.**

The `RunPlan` digest (`planning.py:96-114`, `sha256` of
application/model/example/execution_mode/compute_resource/backend/run_target/
parameter_overrides/datasets/slurm) already binds the **intent**. Approval is
digest-bound and re-checked at the execution gate (`approval.py:162-175`,
`execution.py:152-162`). This audit asks: between approval and the job
actually running, can a **mutable input the digest only *names*** change?

---

## 1. The window

```
 approve(plan)                 [digest D recorded]
    │  human walks away; hours pass (HPC queue, review, next day)
 stage_example_for_run(...)     [copies canonical example -> working copy NOW]
    │
 submit_remote_icesheets(...)   [rsyncs the working copy, sbatch]
    │
 job runs on the cluster        [reads the working copy]
```

The digest is recomputed at the execution gate, so a change to a
**digest-covered field** (backend, slurm, parameter_overrides values, …) is
caught — verified by `test_r2::test_approve_A_execute_B_is_rejected_with_no_side_effects`.
The exposure is entirely in inputs the digest references **by name / id**:

| Input | In the digest? | Mutable in the window? | Consequence if changed |
|---|---|---|---|
| execution mode / backend | value | no (frozen `RunPlan`) | — |
| Slurm settings | values | no | — |
| parameter_overrides | values | no | — |
| dataset **selection** (which datasets) | names (sorted) | no | — |
| **canonical example source files** | `example` = a string id only | **YES** — a maintainer can edit/replace a canonical example; a user example is under the user's own workspace and editable any time | different `runme.m` / notebook ⇒ different physics than approved; different solver set ⇒ B4/solver findings stale |
| **the resolved `run_target` file content** | `run_target` = a basename only | **YES** (same as above) | the script that actually runs is not the one the findings were computed against |
| **referenced dataset file content** | names only | **YES** — `MAX_DATASET_UPLOAD_BYTES = 50 MB` per file (`manager.py:612`); a user can overwrite `foo.nc` after approving | the job reads different data than approved |
| staged working copy | not referenced | created *after* approval | this is downstream of the above; fingerprint the source, not the copy |

No content-addressing exists for examples or datasets: `list_datasets` returns
`{name, path, size}` (`manager.py:658-663`); `_resolve_dataset` is a name
lookup (`manager.py:641-647`); there is no sha/manifest anywhere in
`WorkspaceManager` (grep: `sha`/`hashlib`/`checksum` — none in `manager.py`).

`detected_solvers` (`planning.py:72`) is derived from the `run_target` file at
validate time and is **not** in the digest (correct — it's derived) — but that
makes it a silent staleness carrier if the file changes.

---

## 2. What to fingerprint (and what not to)

| Input | Fingerprint | Rationale |
|---|---|---|
| resolved `run_target` file | **full sha256** | always a small text file (`.m` / `.py` / `.ipynb`); the exact script that runs |
| other source files in the example dir | **tree digest**: sorted `(relpath, size, sha256)` for text/source files under a per-file cap (256 KB) and a file-count cap (200); larger/binary files recorded as `(relpath, size)` only | ISSM `runme.m` often `include`s sibling `.m`; a notebook may import a local `.py`. Cheap. |
| referenced datasets | **metadata fingerprint**: `(name, size, mtime_ns)`; plus `sha256` **only if `size ≤ 8 MB`** | the brief: "Do not hash enormous scientific datasets unnecessarily." 50 MB cap means a `.nc` is plausibly large; size+mtime catches an overwrite; small dataded files get a real hash |
| execution mode / backend / slurm / overrides | **nothing new** | already digest-covered |

The whole thing collapses to one `sha256` — `RunInputFingerprint.digest()` —
over the canonical JSON of the above. That single string is what an approval
binds to.

---

## 3. Design — a second binding on the approval

Keep the **intent digest** exactly as is (stable, human-reviewable). Add a
**separate** inputs binding:

* `RunInputFingerprint` + `fingerprint_run_inputs(ctx, *, plan)` — a PLAN-level,
  read-only tool. Resolves the canonical example read-only, walks it, hashes.
* `Approval.input_fingerprint: str = ""` — recorded at `approve()` time **iff
  the caller passes one** (the UI computes it and shows the human "you are
  approving these exact files"; an approval with no fingerprint keeps today's
  intent-only binding, so nothing regresses).
* `verify_run_input_fingerprint(ctx, *, plan, expected)` — recompute + return
  `{ok, drift: [human-readable changes]}`.
* `RemoteSubmitBackend` (which already resolves the canonical example and
  stages, `remote_backend.py:132-155`) gains a check: if
  `approval.input_fingerprint` is set and the freshly-computed fingerprint
  differs → `SubmitBlocked("inputs", drift)` **before staging**.
* `DryRunExecutionCoordinator` gains a `fingerprint_resolver` seam; when set and
  the approval carries a fingerprint, a `VERIFY_INPUTS` phase reports drift in
  the dry-run report (so the human sees it before the real run).

Why a second field rather than folding into the plan digest: the plan digest is
what the human *reads and approves* — model, resource, parameters. Folding a
2 KB tree-hash into it makes the approvable artifact opaque and means every
trivial whitespace edit to an unrelated sibling file silently invalidates a
approval with no explanation. The separate binding lets `verify_*` say
*exactly* which file changed.

---

## 4. Invariant after this change

| Claim | Mechanism |
|---|---|
| the approved scientific parameters run | intent digest (existing) |
| the approved **script** runs | `run_target` sha in the fingerprint; `SubmitBlocked` on drift |
| approved **sibling source** runs | example tree digest |
| approved **data** is read | dataset size+mtime(+sha if small); `SubmitBlocked` on drift |
| a stale approval is visible, not silent | `verify_run_input_fingerprint` names the changed file; dry-run `VERIFY_INPUTS` phase |
| nothing regresses for today's callers | `input_fingerprint` is optional; absent ⇒ intent-only, as before |

---

## 5. Not covered / OWNER_CHECKPOINT

- **Remote-side drift** — once the working copy is `rsync`ed to the cluster, a
  third party with write access to the remote run dir could edit it before
  `sbatch` picks it up. Out of scope for the agent layer (this is remote FS
  trust, same as the human path). The fingerprint binds the *local source*.
- **Container image drift** — `resolve_stack` already resolves to an exact
  digest at submit (`gateway:1996`, container provenance recorded). No change
  needed.
- **Dataset hashing threshold (8 MB)** — a judgement call; revisit if real
  datasets cluster just above it.
- **Full example tarball hash vs per-file tree digest** — chose per-file so
  `verify_*` can name the culprit; a tarball hash would be simpler but opaque.
