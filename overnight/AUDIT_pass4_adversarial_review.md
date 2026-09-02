# PASS 4 task 16 — adversarial review + coordinator reconciliation

Three independent read-only subagents reviewed the final HEAD
(`971531c`, before the fixes below). None edited. The coordinator reconciled
their findings, fixed the independently-safe P0/P1 items backed by repository
evidence, and recorded the rest as OWNER_CHECKPOINT. **The coordinator did not
accept a recommendation without deciding on it** — decisions are below.

**Headline: no P0 from any reviewer.** Security: "no agent/LLM-reachable bypass
of the identity, approval, or submission boundary." Scientific integrity: "the
intent digest + digest-bound approval machinery is solid." Architecture: "sound
and safe to mount as a Beta."

---

## What the reviewers ran against vs. what shipped

Reviewers saw HEAD `971531c`. Two of their findings were **already fixed** in a
commit they hadn't seen (`df4c402`, core-no-UI-dep test). Everything else below
was reconciled after their reports.

---

## Fixed this pass (commits `8bddbcd` → `165b420`)

| Reviewer | Finding | Coordinator decision | Commit |
|---|---|---|---|
| SEC #1,#2 | `policy.py` `"os.environ"` rule could never fire; no stdlib exec primitives in the denylist | **Fix.** The machine-enforced half of the safety model was a no-op for env access. Rebuilt `_referenced_names` to reconstruct dotted tails / `ImportFrom` paths / bare-name calls; added `subprocess/Popen/os.system/os.popen/os.exec*/socket/pty/ctypes/importlib/runpy/os.getenv/getuser`; `eval/exec/compile/__import__` matched only as bare calls (so `re.compile` stays clean). 24 adversarial + false-positive tests. | `8bddbcd` |
| SEC #3 / ARCH #5 | `TOOL_MODULES` hand-maintained; `assert_tool_modules_are_clean` skips missing files; no completeness check | **Fix.** Now fails on any `agents/*.py` not in `TOOL_MODULES` (or `_UNSCANNED_OK`) and on a listed-but-missing module. `eval.py` + core modules added. | `8bddbcd` |
| SEC #12 / ARCH #9 | `acceptance._agent_no_backend` was a `"def submit(" + "job id"` string heuristic; `--offline` parsed and ignored | **Fix.** Now an AST check (no `agents` module imports `agent_execution`; no `agents` class has a `submit(plan,*,ctx)` method). `--offline` is `required=True`. | `8bddbcd` |
| ARCH #3 | `DryRunSubmitBackend.submit` missing `approval=` → `TypeError` if wired; `SubmitBlocked`/exceptions escape the coordinator raw | **Fix.** New `SubmitError` base in `agents/execution.py`; `agent_execution.SubmitBlocked` subclasses it; the coordinator catches `SubmitError` → `blocked_reason="submit-backend"` and any other exception → `"submit-backend-error"`. `DryRunSubmitBackend.submit` signature fixed; 3 coordinator tests. Removed dead `PermissionError`/`PlanState` imports. | `f3e745d` |
| ARCH #4 / #10.2 (PASS-3 §2b) | assistant string-matched tool names; rename → silent `proposed_plan=None` | **Fix.** `ToolSpec.result_kind`; `prepare_run_plan`→`"run_plan"`, `validate_run_plan`→`"validated_run_plan"`; assistant matches on that. Test: a fully-renamed planning tool still yields a plan. | `1f4759a` |
| ARCH #1 (PASS-3 §1) | `registry.py` `try/except ImportError` around `planning_tools` hides real breakage | **Fix.** Extracted `build_default_registry()` (fatal on a failed tool import); `default_registry()` delegates. | `1f4759a` |
| SCI #2 / SEC #6 | NaN/Inf override passes `<`/`>` bound checks — `md.x = nan;` is valid MATLAB, a silent NaN run | **Fix.** `validate_icepack_config` + `validate_md_config._as_number` reject non-finite values. | `114d36c` |
| SCI #5 (P1) | Fingerprint blind to `.msh`/`.exp`/`.mat`/`.nc`; skips `data/`; truncation binds silently | **Fix.** `_BINARY_SCI_SUFFIXES` hashed to a 16 MiB cap; `data` removed from `_SKIP_DIRS`; `truncated` surfaced in `fingerprint_run_inputs` output + a trace note in the backend. The **opt-in** nature stays (see OWNER_CHECKPOINT). | `114d36c` |
| SCI #7 (P2) | `assert_no_agent_chatter` never wired; `_CHATTER_KEYS` missing `arguments`; `ctx._approval` never set → `approved_at=""` | **Fix.** `_CHATTER_KEYS` extended (`arguments`, `steps`, `transcript`, `user_message`, `llm_output`, …); `RemoteSubmitBackend._register_run` now calls `assert_no_agent_chatter(metadata)` and uses the threaded `approval` param. | `114d36c` |
| SCI #3 / SEC #6 | `_staging_glue` passes raw (not normalised) overrides; backend does no independent re-validation | **Fix.** `RemoteSubmitBackend._revalidate_overrides` re-runs the model validator and stages the **normalised** dict. | `114d36c` |
| SEC #4 | Panel Approve enabled without `plan_is_valid` (only `not _has_errors`) | **Fix.** `_refresh_controls` gates on `plan.get("validated")`; an adapter that skips `validate_run_plan` can no longer get a plan approved. Panel test added. | `114d36c` |
| SEC #11 / SCI #5 | Gateway `_on_approve` never binds a `RunInputFingerprint` | **Fix.** `_on_approve` computes `fingerprint_run_inputs` and passes `input_fingerprint=`. (Still degrades to intent-only if the example can't be resolved.) | `114d36c` |
| SEC #7 | `redact`/`scan_for_secrets` miss Basic-auth headers, URL credentials | **Fix.** Added `auth-header` (Basic + Bearer) and `url-credentials` patterns. | `114d36c` |
| ARCH #2 (PASS-3 §1a) | canonical-digest idiom copied 4×; a change silently breaks approval matching | **Fix.** `planning.canonical_digest(material)` is the single home; `RunPlan`, `ExperimentPlan`, `RunInputFingerprint` all call it. | `165b420` |
| ARCH PASS-3 §2a | `RunPlan.__post_init__` doesn't check `ModelCapabilities` modes/backends — impossible plans constructible | **Fix.** Now rejects an unsupported mode/backend at construction. `validate_run_plan` keeps the cloud finding defensively. | `165b420` |
| ARCH #6 | No concurrent-writer handling (two Voila kernels, same user) → clobbered approval | **Fix.** `PlanRepository` optimistic lock: `save()` raises `ConcurrentModificationError` if the on-disk file changed since `load()`; `save(force=True)` overrides; `create()` exempt. | `165b420` |

---

## OWNER_CHECKPOINT — recorded, not fixed autonomously

| Reviewer | Finding | Why deferred |
|---|---|---|
| SCI #5 (P1) | The input fingerprint is **opt-in** — a plain approval binds intent only. A valid-but-different physics edit to a canonical example between approve and execute is not caught unless the UI passed a fingerprint. | The gateway `_on_approve` now *does* pass one, but making it **mandatory** (approval refused without a fingerprint) is a UX + policy decision — a maintainer editing a canonical example legitimately would then invalidate every pending approval. Owner call. |
| SCI #5 (P2) | Datasets > 8 MiB are `(name, size, mtime)` only; a `touch -d` equal-size overwrite is invisible. | Judgement call on the threshold; content-addressed dataset storage would be the real fix (a workspace change). |
| SEC #5 | A hand-written `plans/<id>.json` with a **self-consistent** approval (right digest, right approver) survives `restore_managed_plan` — no HMAC/signature proves a human clicked Approve. | The forger is necessarily the same authenticated user who could click Approve, and no agent has a filesystem-write tool. Signing approvals is a real hardening step but needs a key-management design; out of scope tonight. |
| SEC #8 | `inspect.py --store DIR` / a path arg has no containment check — a shell user could point it at another user's workspace dir. | A shell user already has `cat`. `inspect` without `--store` is correctly scoped. Documented as a dev/debug tool. |
| SEC #9 | `policy.assert_same_user` / `assert_within_workspace` are defined and documented as guards but have **zero call sites**. | Latent safety net for a future tool author. Decision: keep them (cheap), and a future mutating tool MUST call them (noted in the Developer Guide checklist). |
| ARCH #3 | `ConnectionContext` is a 25-field grab-bag that will need more fields once wired. | Part of the "wire `RemoteSubmitBackend` into the gateway" checkpoint. |
| ARCH #6 (SCI #8) | `ManagedExperiment` has **no persistence** and no `restore_managed_experiment`. | Decision: **document experiments as in-memory-only for this pass** (done — Developer Guide §11, `experiment.py` docstring). Adding `ExperimentRepository` is a clean follow-up, not a review fix. |
| ARCH #10 | `agents/inspect.py` shadows stdlib `inspect`; `agents` vs `agent_execution` names too similar. | Cosmetic; a rename touches the `python -m …` entry point and every import. Owner call whether it's worth it. |
| ARCH #1 (P2) | Long-term: move `validate_slurm_resources` + the example registry into `cryostack_src` so the gateway imports *up*. | A package-split project, not a review fix. The new `test_agent_core_no_ui_dep` guards against regression in the meantime. |

---

## Decisions where the coordinator did NOT follow a recommendation

* **ARCH #10 (rename `agent_execution`/`inspect.py`):** declined for now. The
  split is correctly motivated and documented; a rename is churn with no safety
  gain, and the `python -m cryostack_src.agents.inspect` entry point is
  published in `TOMORROW_AGENT_LAB.md`. Left as an owner cosmetic call.
* **SEC #5 (sign approvals):** declined tonight. The threat (a user forging
  their own approval) is bounded by "that user could click Approve anyway",
  and no submit backend is wired. A signing scheme needs a key-management
  design that is out of scope for an overnight pass.
* **SCI #5 (make the fingerprint mandatory):** declined as an autonomous
  change — it would break the legitimate maintainer-edits-a-canonical-example
  workflow. The gateway now binds one by default; making it *required* is an
  owner policy decision.

---

## Test delta

Agent + agent_execution suites: **171 → 208** (+37 review tests). Full project
suite green throughout. `python -m cryostack_src.acceptance --offline`:
15 PASS / 0 FAIL / 2 MANUAL.
