# Overnight autonomous session — PASS 3 morning report

**Objective: make CryoStack genuinely agentic, as a teaching implementation.**

From `ebee0c5` (PASS 2, accepted as checkpoint) on `gatech_vm_backend`.
**End HEAD: `49df948`** (before this report's own commit). All work in small
green commits. Prior passes: `overnight/MORNING_REPORT_pass1-2.md`.

Nothing that needed production access, Duo/MFA, a Connector publish, a paid
cloud call, a real HPC job, or a scientific decision was done — those are
marked **OWNER_CHECKPOINT** in §13.

---

## 1. What was built

A new `cryostack_src/agents/` package: a provider-agnostic layer that lets an
orchestrator (an LLM, a script, a test) drive CryoStack through **bounded,
typed, permission-declaring tools**, with human approval bound to a
deterministic digest and a dry-run execution boundary that stops before any
real submission.

* **A1–A10** — the agent layer: audit, safety model, tool registry + 11
  read-only tools, planning tools, approval boundary, dry-run executor, trace
  persistence + provenance split, the Run Assistant + LLM adapter, a prototype
  UI panel, the Developer Guide.
* **P1–P3** — platform generalizations: ModelCapabilities registry,
  model-neutral result contract, additive experiment/sweep abstraction.
* **R1–R3** — cross-model contract matrix, malicious-agent, and
  scientific-integrity test suites.
* Teaching doc: `overnight/LEARNING_AGENTIC_DEVELOPMENT.md`.

---

## 2. Commits in order

| hash | task | what |
|---|---|---|
| `cad59f8` | — | PASS 3 plan + A1 delegation in the trail |
| `1ac7cde` | A2 | `overnight/AGENT_SAFETY_MODEL.md` |
| `dc52568` | A2+A3 | `AUDIT_agent_capabilities.md`; permissions, trace, context, tools, registry, policy, readonly_tools; 18 core tests |
| `a1af2bb` | A4 | `planning.py` (RunPlan + digest) + `planning_tools.py` (prepare/validate/estimate); 13 tests |
| `6ef2823` | A5 | `approval.py` — lifecycle + digest-bound approval; 10 tests incl. approve-A / mutate / execute → rejected |
| `9289d36` | A6 | `execution.py` — dry-run coordinator stopping at the submit boundary; 8 tests |
| `646ce71` | A7 | `trace_store.py` — append-only JSONL + `run_manifest_stamp` / `assert_no_agent_chatter`; 8 tests |
| `c2b5609` | A8 | `llm.py` (adapter + ScriptedLLM mock) + `assistant.py` (RunAssistant, PLAN-capped); 4 tests |
| `9a9a9bf` | A9 | `icesee_jupyter_book/ui/shared_agent_panel.py` — prototype panel, Approve gated on human ack; 2 tests |
| `48a9776` | A10 | `icesee_jupyter_book/docs/building_agents.md` in the public Developer Guide |
| `53d266d` | P1 | `cryostack_src/models/capabilities.py` — ModelCapabilities registry; agent layer consumes it; 6 tests |
| `7a88ad3` | P2 | `results_common` — `ResultPackageProtocol` / `VisualizerProtocol` / `describe_package` / resolvers; manager delegates; 3 tests |
| `271252f` | P3 | `experiment.py` — ExperimentPlan / SweepAxis / ManagedExperiment; 8 tests |
| `49df948` | R1–3 | `test_r1_contract_matrix.py`, `test_r2_malicious_agent.py`, `test_r3_scientific_integrity.py` |

---

## 3. The agent architecture

```
orchestrator (LLM / script / test)
      │
   RunAssistant  ── deterministic loop, hard-capped at PLAN
      │
   ToolRegistry.invoke(name, ctx, **kwargs)     ← the one checkpoint
      │   enforces: permission ceiling · confirmation gate · identity · trace
      ▼
  OBSERVE tools        PLAN tools (prepare / validate / estimate)
      │                     │
      │                RunPlan ──digest──►  approval.ManagedPlan lifecycle
      │                                         │  human approves (digest-bound)
      │                                         ▼
      │                              DryRunExecutionCoordinator
      │                                  stops before sbatch / aws batch submit
      ▼
  append-only, redacted Trace  ──(pointer only)──►  scientific run manifest
```

Files: `permissions.py`, `context.py`, `trace.py`, `trace_store.py`,
`tools.py`, `registry.py`, `policy.py`, `readonly_tools.py`, `planning.py`,
`planning_tools.py`, `approval.py`, `execution.py`, `llm.py`, `assistant.py`,
`experiment.py`. **No LLM vendor SDK is imported anywhere.**

---

## 4. The permission model

`OBSERVE (10) < PLAN (20) < PREPARE (30) < EXECUTE (40) < DESTRUCTIVE (50)`.

Every tool declares its minimum level. `ToolContext` carries a
`max_permission` ceiling (only ever lowered, never raised — `with_ceiling`
takes a `min`). The registry refuses any call above the ceiling **and** traces
the refusal. Discovery is filtered: a context never sees a tool it could not
call. Everything shipped is OBSERVE or PLAN and read-only — no EXECUTE or
DESTRUCTIVE tool is wired to a real backend.

Derived from CryoStack's existing boundaries (B2 workspace isolation, B3
remote-identity verification, B4 pre-submit Slurm validation), not invented on
top of them.

---

## 5. Safety guarantees, and the test that proves each

| Guarantee | Test |
|---|---|
| No agent context without an authenticated identity | `test_r2::test_context_cannot_be_built_without_an_authenticated_identity` |
| A forged identity source is rejected | `test_r2::test_context_rejects_a_forged_identity_source` |
| No tool takes a `user_id` / `owner` argument | `test_r2::test_no_tool_accepts_a_user_id_argument` |
| An agent cannot read another user's run | `test_agent_core` + `test_r2::test_agent_cannot_read_another_users_run` |
| The permission ceiling cannot be raised | `test_r2::test_context_ceiling_cannot_be_raised` |
| A tool above the ceiling is refused | `test_r2::test_registry_refuses_a_tool_above_the_ceiling` |
| The assistant stays at PLAN even given an EXECUTE context | `test_r2::test_assistant_stays_at_plan_even_with_an_execute_context` |
| **Approve config A, mutate, execute config B → rejected, no side effects** | `test_agent_approval` + `test_r2::test_approve_A_execute_B_is_rejected_with_no_side_effects` |
| A fabricated approval object is caught by the live digest check | `test_r2::test_fabricated_approval_object_is_caught` |
| A user cannot approve another user's plan | `test_r2::test_a_user_cannot_approve_another_users_plan` |
| A live execute without an EXECUTE ceiling never calls the backend | `test_r2::test_live_execute_without_execute_ceiling_never_calls_the_backend` |
| Secrets passed to a tool are redacted in the trace / on disk | `test_r2` + `test_agent_trace_store::test_secrets_never_hit_disk` |
| Tool modules reference no prohibited symbol (AST scan) | `test_agent_core` + `test_r2::test_tool_modules_reference_no_prohibited_symbol` |
| A scientific change shows in digest + `scientific_changes` + `approvals_required` and forces re-approval | `test_r3` (2 tests) |
| Out-of-range Basic-mode values block validation | `test_r3::test_out_of_range_basic_mode_value_is_a_validation_error` |
| No shipped tool mutates or invents science | `test_r3` (2 tests) |
| Agent chatter never enters a run manifest | `test_agent_trace_store` + `test_r3::test_agent_assisted_run_manifest_carries_only_a_pointer` |

96 agent tests total.

---

## 6. Identity & isolation

`ToolContext` is built from
`resolve_workspace_user(require_authenticated=True)` and raises
`WorkspaceIdentityError` if there is no trusted identity — no anonymous, no
developer fallback. Trusted sources: `cryostack-auth`, `env-override` (the CLI
single-user pin). Scope is always `ctx.user`; no tool signature contains
`user_id`. Filesystem helpers go through `policy.assert_within_workspace`.
`AUDIT_agent_capabilities.md` enumerates the exact "never expose" functions and
the identity-spoof surface (anything taking `host=` / `user=` / `session_id=` /
`owner=`).

---

## 7. Approval & the digest

`RunPlan.digest()` = SHA-256 over **only** the scientific + resource fields
(model, example, execution mode, compute resource, backend, run target,
parameter overrides, datasets, Slurm request) — not findings, not timestamps.

`Approval{plan_digest, approver_user_id, approved_at}`. Only the plan's owner
can approve. `assert_approved_for_execution` recomputes the live digest and
refuses on mismatch. Revising any scientific/resource field drops the approval
and returns the plan to DRAFT. This is the load-bearing property: an agent
cannot get approval for one configuration and run another.

---

## 8. Dry-run execution boundary

`DryRunExecutionCoordinator` walks revalidate → check-approval →
resolve-identity → stage → precheck-scheduler → **SUBMIT (stop)**. In dry-run
mode the SUBMIT phase returns a redacted description of the command a backend
would issue (`sbatch …` / `aws batch submit-job …`) and returns — nothing
reaches a scheduler or AWS. A real `SubmitBackend` is a Protocol with **no
implementation in the tree**; wiring one is a human step gated on B3. With no
backend, a live request is downgraded to dry-run. The coordinator never
imports the remote/cloud submission modules (AST-scanned).

---

## 9. Trace vs scientific provenance

Two separate records. The **operational trace** (`.cryostack/agent-traces/
<id>.jsonl`, append-only, redacted) holds every request, tool call, validation,
approval, and execution decision. The **run manifest** gets only
`run_manifest_stamp(...)`: agent-assisted flag, plan digest, approver, time,
and a *pointer* to the trace. `assert_no_agent_chatter` rejects a manifest that
smuggled tool calls / prompt text / model output into the scientific record.

---

## 10. The Run Assistant + LLM adapter

`llm.LLMClient` is a `Protocol`; `llm.ScriptedLLM` is a deterministic mock used
by every test. `assistant.RunAssistant.handle(ctx, message)` hard-caps the
context at PLAN, runs a deterministic loop over `complete()`, runs read/plan
tools **through the registry**, and returns an `AssistantResult` whose
`submitted` field is always `False`. A validated plan is surfaced as a
*proposal*. `shared_agent_panel` is a prototype Voila panel over it with an
Approve control gated behind an explicit human acknowledgement.

---

## 11. Platform generalizations (P1–P3)

* **P1 `ModelCapabilities`** (`models/capabilities.py`) — one authoritative
  statement per model of Basic-mode config, structured results + contract,
  offline reader, visualization, MATLAB requirement, execution modes/backends,
  cloud support. Import-time asserts keep it consistent with the adapters and
  `cloud.runtime.SUPPORTED_CLOUD_MODELS`. The agent layer now consumes it
  instead of hard-coding `_MODELS` and per-model contracts.
* **P2 result contract** — `results_common` now declares
  `ResultPackageProtocol` / `VisualizerProtocol` (both models already satisfy
  them), `describe_package()`, and `resolve_result_reader` /
  `resolve_visualizer`. `WorkspaceManager` delegates its dispatch here.
  Behaviour unchanged (existing suites pass).
* **P3 experiment abstraction** — `experiment.py`: `ExperimentPlan` = base
  `RunPlan` + one `SweepAxis`; `expand()` yields ordinary `RunPlan`s;
  `ManagedExperiment` gives each child its own digest-bound `ManagedPlan`; one
  `approve()` binds the experiment digest **and** every child digest. Purely
  additive — no change to `RunPlan`, `approval.py`, `execution.py`, the
  manifest, or the gateway. Sweeps capped at 32 runs.

---

## 12. Tests and builds

* Python (`cryostack_src` + `icesee_jupyter_book` + `bin` +
  `icesee_hpc_connector` + `deployment`): **1140 passed, 1 skipped**
  (+~118 this pass; 96 in `cryostack_src/agents/`). Green before every commit.
* `node --test deployment/tests/connect_page.test.mjs`: **18/18**.
* `jupyter-book build icesee_jupyter_book/`: **clean** (new `building_agents`
  page renders).
* `bin/build_application_docs.sh` (CryoLauncher / ICESEE / Frozen Legacies):
  **all build succeeded**.
* Firedrake / icepack still not importable on this box — Icepack exporter
  remains mock-tested (unchanged from PASS 2).

---

## 13. OWNER_CHECKPOINT — decisions and work left for you

**Carried from PASS 2 (still open):**
* **PACE password-bootstrap / institutional auth (Duo/MFA)** — untouched, per
  instruction. Manual acceptance checkpoint.
* **Icepack structured exporter** needs a real Firedrake/HPC validation before
  any further scientific expansion — no scientific Icepack work was done this
  pass.
* Stale deployed relay + `icesee_app.py`; Connector rebuild — not done.
* ICESEE `cryostack.icesee.results` schema + `results_directory` semantics;
  ICESEE cloud compute primitive (Batch/Fargate can't run the MPI ensemble).

**New — decisions this pass surfaces:**
1. **Wiring a real `SubmitBackend`.** The dry-run boundary is complete and
   tested. A live submitter must reuse `enforce_remote_access` / the B3
   verification and must not change `approval.py` or the digest scope. This is
   the intended next integration step and needs your review of the interface
   in `execution.py`.
2. **Granting the Run Assistant more than PLAN.** Today it is hard-capped. If a
   future "prepare my working copy" step (PREPARE) is wanted, it needs its own
   confirmation gate and an "does nothing without approval" test — decide the
   UX first.
3. **Persisting `PlanStore` / `TraceStore` in the real workspace.** Both are
   in-memory / file-local prototypes with the right interface. Backing them
   with the workspace is safe but is a schema touch — deferred for your call.
4. **An agent panel in the live gateway.** `shared_agent_panel` is a prototype;
   mounting it in `icesheets_gateway` / `icesee_gateway` and choosing the
   `on_approve` target (the approval queue UI) is a gateway change.
5. **Real LLM adapter.** `LLMClient` is ready; a concrete implementation
   (Anthropic or otherwise) belongs in a separate integration package, not in
   `cryostack_src/agents/`.

**Nothing in this pass changed** authentication, B2/B3/B4, connector-v2
ownership, credential handling, Slurm validation, tested-container gates, or a
scientific-result contract. No personal identifiers or developer defaults were
added.

---

## Manual acceptance for the agent layer

1. `python -m pytest cryostack_src/agents -q` → 96 passed.
2. Read `overnight/LEARNING_AGENTIC_DEVELOPMENT.md` end to end — it is the
   design rationale.
3. Read `icesee_jupyter_book/docs/building_agents.md` (renders under Developer
   Guide) — the public narrative + add-a-tool checklist.
4. Skim `overnight/AGENT_SAFETY_MODEL.md` §2 (permission table), §4
   (prohibitions), §5 (approval contract).
5. In a Python shell: `build_tool_context(application="icesheets")` with no
   identity env set → `WorkspaceIdentityError`. With
   `CRYOSTACK_WORKSPACE_USER=you` → a context capped at PLAN.
