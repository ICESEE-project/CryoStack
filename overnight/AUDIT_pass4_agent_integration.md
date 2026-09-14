# AUDIT — PASS 3 agent layer, read for PASS 4 integration

Read-only review of `cryostack_src/agents/` at HEAD `beda9f3`, plus
`ModelCapabilities` (`cryostack_src/models/capabilities.py`), the result-contract
protocols (`cryostack_src/models/results_common.py`), the experiment abstraction,
`RunAssistant`, the agent UI prototype (`icesee_jupyter_book/ui/shared_agent_panel.py`),
and the agent Developer Guide (`icesee_jupyter_book/docs/building_agents.md`).

**Verdict:** the architecture is sound and the safety invariants hold. Do not
redesign it. There are a handful of concrete integration hazards and small
debts, none of which require an architecture change. They are catalogued below
with severity and a PASS-4 action.

Severity: **P0** blocks safe integration · **P1** fix this pass if independently
safe · **P2** owner decision / deferred.

---

## 1. Duplicated abstractions

| # | Finding | Sev | Action |
|---|---|---|---|
| 1a | Canonical digest logic is written twice: `RunPlan.digest` (`planning.py:111`) and `ExperimentPlan.digest` (`experiment.py:93`) — same `sha256(json.dumps(material, sort_keys=True, separators=(",",":")))`. | P2 | Extract `_canonical_digest(material) -> str` in `planning.py`, call from both. Low risk. |
| 1b | Argument-scrubbing helper duplicated: `registry._safe_args` (`registry.py:92`) and `assistant._safe` (`assistant.py:142`) are byte-identical in intent. | P2 | Move one to a shared `_util`. |
| 1c | `ManagedPlan` and `ManagedExperiment` re-implement the lifecycle (`state`, `approval`, `validate/submit_for_approval/approve`) in parallel (`approval.py:60`, `experiment.py:146`). Not identical (experiment fans out to children) but the state machine is copied. | P2 | Acceptable for now; if a third lifecycle appears, factor a `_Lifecycle` mixin. |
| 1d | Three separate "sensitive string" lists: `trace._SECRET_KEYS` / `trace._SECRET_MARKERS` (`trace.py:22,32`), `trace_store._CHATTER_KEYS` (`trace_store.py:34`), `policy.PROHIBITED_SYMBOLS` (`policy.py:22`). Different purposes, correctly separate — but they must not drift. | P1 | Add a doc cross-reference and a test that asserts every `_SECRET_KEYS` entry is also rejected by the persistence guard (task 2). |

---

## 2. Hidden model-specific assumptions

| # | Finding | Sev | Action |
|---|---|---|---|
| 2a | `RunPlan.__post_init__` (`planning.py:78`) validates `model ∈ SUPPORTED_MODELS`, `execution_mode ∈ ("remote","cloud")`, `backend ∈ ("spack","container")` — but **does not check the plan's model against `ModelCapabilities.execution_modes` / `.backends`**. `RunPlan(model="icepack", execution_mode="cloud")` constructs fine; the mismatch is only caught later as a `validate_run_plan` finding. | P1 | Have `RunPlan.__post_init__` consult `get_model_capabilities(model)` and raise on an unsupported mode/backend, so an impossible plan cannot be built at all. Keep the finding too (defense in depth). |
| 2b | `assistant.py:122-125` captures the proposed plan by **string-matching tool names** `"validate_run_plan"` / `"prepare_run_plan"`. Rename either tool and the assistant silently stops surfacing plans. | P1 | Add a `ToolSpec` flag (`produces_plan: bool`, or a `result_kind` string) and match on that. Backward compatible. |
| 2c | `planning_tools.validate_run_plan` step 4 (`planning_tools.py:132`) hardcodes `if p.model == "issm" and p.backend == "container"` for the MATLAB check and `_detect_issm_solvers`. These are **genuine scientific differences**, but they are not driven by `ModelCapabilities`. | P2 | `ModelCapabilities.requires_matlab` already exists — key the MATLAB check off `get_model_capabilities(p.model).requires_matlab and p.backend == "container"`. Solver detection stays ISSM-specific (correct). |
| 2d | `execution._describe_submission` (`execution.py:96`) branches on `execution_mode == "cloud"` to build the fake `sbatch` / `aws batch submit-job` string. This is display-only and correct, but it is the one place a new execution mode needs a hand edit. | P2 | Fine. Note it in the SubmitBackend audit. |
| 2e | `readonly_tools._slim_example` (`readonly_tools.py:66`) depends on the attribute shape of `merged_examples_for_model`'s objects (`ex.kind`, `ex.path`, `ex.entrypoint`, `ex.label`, `ex.to_dict()`). | P2 | Acceptable — it's the one adapter point. Keep it in one function (it is). |

---

## 3. UI / business-logic coupling — **the main integration hazard**

| # | Finding | Sev | Action |
|---|---|---|---|
| 3a | **Layering inversion.** `cryostack_src/agents/` imports `icesee_jupyter_book`: `planning_tools.py:96` (`from icesee_jupyter_book.ui.shared_validation import validate_slurm_resources`), `planning_tools.py:190` and `readonly_tools.py:56` (`from icesee_jupyter_book.core.icesheet_examples import merged_examples_for_model`). The imports are lazy (inside functions), so `import cryostack_src.agents` still works, but `prepare_run_plan` / `validate_run_plan` / `list_examples` cannot run without `icesee_jupyter_book` importable. | P1 | Accept for this pass (both packages ship together), but **document it** in the Developer Guide and the integration audit, and add a test that imports `cryostack_src.agents` with `icesee_jupyter_book` absent from a fresh interpreter to prove the *core* (permissions/context/approval/execution/trace) has no hard dependency. Longer term: move `validate_slurm_resources` and the example registry into `cryostack_src` and have the gateway import *up*. |
| 3b | `shared_agent_panel.py` — clean. Presentation + wiring only; all policy is in the agents package; `on_approve` is a host callback; no submit path. Good to mount (task 3). | — | — |
| 3c | `ToolContext._ALLOWED_APPS = ("icesheets", "icesee")` (`context.py:26`) is a hardcoded allow-list. Fine, but a mounted panel must pass the right one. | P2 | — |

---

## 4. Unsafe execution escape hatches

| # | Finding | Sev | Action |
|---|---|---|---|
| 4a | `DryRunExecutionCoordinator(submit_backend=…)` (`execution.py:113`) is the only escape hatch. It is correctly gated: a live submit needs `dry_run=False` **and** `ctx.can(EXECUTE)` **and** `assert_approved_for_execution` (digest match) — verified by `test_agent_execution.py` and `test_r2_malicious_agent.py`. With no backend, `report()` forces `dry_run=True` (`execution.py:125`). | — | Sound. No change. |
| 4b | `execution.py:27` imports `PermissionError` but never uses it. Dead import. | P2 | Remove. |
| 4c | The injected `SubmitBackend` is fully trusted to perform B3 and to not accept LLM-chosen commands. There is **no in-tree backend** and no contract test that a backend *must* re-verify B3. | P1 | Task 4 deliverable: `AUDIT_agent_submit_backend.md` + (only if safe) a backend that composes existing APIs, plus a contract test that a backend which skips B3 is rejected. |

---

## 5. User scoping

| # | Finding | Sev | Action |
|---|---|---|---|
| 5a | `PlanStore` (`approval.py:178`) is process-memory only; `PlanStore.get(plan_id, owner=)` enforces `owner_user_id` match — correct. But there is **no persistence**, so approval state is lost on restart, and `ManagedExperiment` has no store at all. | P1 | Task 2: user-scoped persistence through the workspace. |
| 5b | `TraceStore.__init__(directory)` (`trace_store.py:44`) accepts an arbitrary directory. `TraceStore.for_user(user)` is the safe constructor (scopes to `owner_root/.cryostack/agent-traces`). A caller could bypass `for_user`. | P1 | Task 2: make the workspace-scoped path the only public constructor for the integrated store; keep a raw-dir escape only for tests. |
| 5c | `ManagedPlan.owner_user_id` is a plain mutable string; the whole dataclass is mutable. In-process forging (`mp.state = APPROVED; mp.approval = Approval(mp.plan.digest(), …)`) is possible — but this is the same trust boundary as the running process, and the digest binding still protects the *scientific config*. | P2 | On **reload from disk** (task 2), never trust the serialized `owner_user_id` — bind owner to the storage path, and re-verify `approval.plan_digest == reloaded_plan.digest()` before honouring APPROVED state. |
| 5d | `context.build_tool_context` fails closed with no identity (`context.py:100`, `resolve_workspace_user(require_authenticated=True)`). `_TRUSTED_SOURCES = ("cryostack-auth", "env-override")` (`context.py:56`). Verified by `test_r2`. | — | Sound. |

---

## 6. Mutable approval state

| # | Finding | Sev | Action |
|---|---|---|---|
| 6a | `ManagedPlan` / `ManagedExperiment` are mutable dataclasses. `revise()` (`approval.py:119`) correctly drops approval on digest change, but a direct `mp.plan = replace(...)` bypasses `revise()`. **Mitigation that already exists:** `assert_approved_for_execution` (`approval.py:162`) recomputes the live digest, so a bypassed revision is still caught at the execution gate (`test_r2_malicious_agent.py::test_approve_A_execute_B_is_rejected_with_no_side_effects`). | P2 | Keep the runtime gate as the source of truth. Task 2: the persisted record stores `approval.plan_digest`; on load, recompute and compare. Consider making `.plan` a property with a setter that calls `revise()`. |
| 6b | `mark_validated` (`approval.py:80`): if validation returned a plan with a different digest it calls `revise()` and returns early — good — but a caller could pass any `RunPlan` as "the validated plan". The digest guard means a swapped plan just reverts to DRAFT. | P2 | Acceptable. |

---

## 7. Digest gaps (feeds task 5 — TOCTOU)

`RunPlan._digest_material()` (`planning.py:96`) covers: application, model, example
(a **string id**), execution_mode, compute_resource, backend, run_target (a
**string**), parameter_overrides (values only), datasets (**names/refs only**),
slurm. It does **not** cover:

| Gap | Risk | Task-5 candidate |
|---|---|---|
| Content of the canonical example / working copy that `example` + `run_target` resolve to | A canonical example file changes between approval and staging → different physics runs than approved | Fingerprint the resolved run-target file(s) at validate time; re-check at stage time |
| Content of referenced `datasets` | An uploaded dataset is replaced after approval | Use the existing dataset metadata / content-addressing if present (don't re-hash GB); audit in task 5 |
| `detected_solvers` is derived from run-target content and **not** in the digest | Solver set at validate time ≠ at stage time if the file changed | Covered by fingerprinting the run-target file |
| `run_target` is not checked to exist in the example at `prepare_run_plan` time (`planning_tools.py:54`) | A plan can name a non-existent or out-of-tree target | Validate `run_target` is a basename that exists in the resolved example |
| `slurm.job_name` / `slurm.account` are free strings, never sanitized (`shared_validation.validate_slurm_resources` doesn't take `job_name`) | Shell-metacharacter injection **if** they ever reach `sbatch` unquoted | Task 4: a SubmitBackend must sanitize; add a basename/allowed-charset check in planning |

---

## 8. Secrets entering traces

`Trace.append` → `redact()` (`trace.py:38`). Redaction is **deny-by-known-pattern**:

- Redacts dict values whose **key** is in `_SECRET_KEYS`, and string values containing a `_SECRET_MARKER` (`-----BEGIN`, `AKIA`, `ASIA`, `1711@matlablic`, …).
- **Does not** redact a secret that appears as a *value under an innocuous key with no marker* — e.g. `{"note": "token is abc123def..."}`. A generic 40-char API token with no recognisable prefix passes through.
- `ToolResult.to_dict` redacts `self.value` (`tools.py:74`) — good, tool outputs are covered.
- Tool `args` in the trace are pre-scrubbed to scalars (`registry._safe_args`) then redacted.

**Assessment:** acceptable residual risk *because no tool accepts a free-form
secret argument* (all tool params are typed enums/ids/dicts-of-known-keys). But
task 2 says "secrets rejected/redacted before persistence" — the persistence
layer should add a **stricter, structural** check: reject a trace event whose
JSON, after redaction, still matches a high-entropy-secret regex
(AWS keys, PEM blocks, `xox[baprs]-` Slack, long hex/base64 runs), rather than
relying only on key names.

---

## 9. Arbitrary path / command / env injection

| Surface | Status |
|---|---|
| Any tool taking a raw path | **None.** |
| Any tool taking a shell command | **None.** |
| Any tool taking an env dict | **None.** |
| `run_target` (string) | Flows to `_describe_submission` (display) + digest today. **Not validated as a basename / existence-checked.** Task 5 + task 4. |
| `parameter_overrides` (dict) | **Schema-validated** for issm (`validate_md_config`) and icepack (`validate_icepack_config`) — unknown keys and out-of-range values rejected. |
| `slurm` dict | Fields typed (int/str) via `SlurmRequest`. `job_name`/`account` not sanitized (see 7). |
| `datasets` (list[str]) | Not resolved/validated in `prepare_run_plan`; future staging resolves via the user-scoped `WorkspaceManager`. |
| `policy.PROHIBITED_SYMBOLS` AST scan | Covers `readonly_tools, planning_tools, planning, approval, assistant, execution, trace, trace_store, experiment` (`policy.py:35`). Green. |

---

## 10. APIs that will be awkward to integrate tomorrow

1. **`cryostack_src.agents` → `icesee_jupyter_book` import** (§3a) — the single
   biggest friction. Mitigate with a "core has no UI dep" test now; plan the
   move later.
2. **`RunAssistant` string-matches tool names** (§2b) — brittle join point.
3. **`default_registry()` global singleton** draining a module-global `_PENDING`
   (`tools.py:113`, `registry.py:103`). Fine for one long-lived gateway process;
   fragile under test import ordering (already worked around in PASS 3 tests).
   Consider an explicit `build_default_registry()` the gateway calls once and
   holds.
4. **No store for `ManagedExperiment`** — task 2 should cover experiments too or
   explicitly defer them.
5. **`ToolContext` is frozen and carries `workspace_manager`** — good, but the
   gateway must build a fresh context per agent turn (the panel already does,
   `shared_agent_panel.py:135`).
6. **Approval lives only in `ManagedPlan`, not addressable by id across a
   restart** — task 2.

---

## 11. What is already right (do not touch)

- Permission ceiling enforced centrally in `registry.invoke` (`registry.py:51`),
  with the refusal traced.
- Identity fail-closed; no `user_id` argument anywhere (asserted by
  `test_r2::test_no_tool_accepts_a_user_id_argument`).
- Digest binds only scientific+resource fields; advisory findings excluded
  (`planning.py:96`, `test_agent_planning.py`).
- `assert_approved_for_execution` recomputes the live digest — the real
  protection against approve-A/execute-B.
- Dry-run is the default and the only wired mode; no `SubmitBackend` in tree.
- Trace is append-only with a sink; `run_manifest_stamp` /
  `assert_no_agent_chatter` keep the operational trace out of scientific
  provenance.
- `RunAssistant` hard-caps its context at PLAN (`assistant.py:89`).
- Machine-enforced `PROHIBITED_SYMBOLS` AST scan.

---

## 12. PASS-4 action summary

| Task | Driven by this audit |
|---|---|
| 2 (persist) | §5a, §5b, §6a, §8 (structural secret check), §10.4 |
| 3 (mount panel) | §3b — clean to mount; **no Submit button** until task 4 |
| 4 (SubmitBackend audit) | §4c, §7 (run_target/job_name), §2d |
| 5 (approval integrity) | §7 in full |
| 2b/2b | §2b (tool-name matching) — fix opportunistically |
| 10 (model conditionals) | §2a, §2c |
| core-no-UI-dep test | §3a |
