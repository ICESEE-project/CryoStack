# Building Agents in CryoStack

CryoStack has a small **agent layer** (`cryostack_src/agents/`) that lets an
orchestrator — an LLM, a script, a test — drive the platform through
**bounded, typed, permission-declaring tools**. This page explains how it is
built and *why it is built that way*, so you can extend it without weakening
the safety properties.

The guiding rule: **an agent assists a scientific workflow; it never silently
changes scientific intent, and it never gets unrestricted shell, HPC, or cloud
access.** Every design decision below follows from that.

The authoritative contract is `overnight/AGENT_SAFETY_MODEL.md` in the
repository. This page is the narrative version.

---

## 1. The shape of the layer

```text
  orchestrator (LLM / script / test)
        │  natural language / a plan
        ▼
  RunAssistant  ── deterministic loop, capped at PLAN ──┐
        │                                               │
        ▼                                               │
  ToolRegistry.invoke(name, ctx, **kwargs)              │  every call is
        │   enforces: permission ceiling                │  appended to an
        │              confirmation gate                │  append-only Trace
        │              identity (ctx.user)              │
        ▼                                               │
  read-only tools   planning tools                      │
  (OBSERVE)         (PLAN: prepare / validate / estimate)│
        │                                               │
        ▼                                               │
  RunPlan  ──digest──►  approval.ManagedPlan lifecycle ◄─┘
                              │  human approves (digest-bound)
                              ▼
                     DryRunExecutionCoordinator
                              │  stops before sbatch / aws batch submit-job
                              ▼
                        (a real SubmitBackend — not shipped)
```

Nothing in `cryostack_src/agents/` imports an LLM vendor SDK. `llm.LLMClient`
is a `Protocol`; `llm.ScriptedLLM` is a deterministic mock that every test
uses.

---

## 2. Permissions

`permissions.Permission` is an ordered ladder:

| Level | Value | Means | Example |
|---|---|---|---|
| `OBSERVE` | 10 | read existing state | list examples, inspect a run |
| `PLAN` | 20 | build an inert proposal | `prepare_run_plan`, `validate_run_plan` |
| `PREPARE` | 30 | stage without submitting | write a working copy, render scripts |
| `EXECUTE` | 40 | submit / run | `sbatch`, `aws batch submit-job` |
| `DESTRUCTIVE` | 50 | delete / overwrite | remove a run, prune a workspace |

Every tool declares the **minimum** level it needs. A `ToolContext` carries a
`max_permission` ceiling. `ToolRegistry.invoke` refuses any call whose tool
needs more than the ceiling, *and* records the refusal in the trace. Discovery
is filtered too: `registry.describe(ctx=ctx)` never lists a tool the context
could not call, so an LLM is not even tempted.

The ladder is derived from CryoStack's existing boundaries (per-user workspace
isolation, remote-identity verification, pre-submit Slurm validation), not
invented on top of them.

---

## 3. Identity — fail closed

An agent has **no capability the authenticated user does not have**. It
inherits the user's scope and cannot widen it.

* `ToolContext` is built from `resolve_workspace_user(require_authenticated=True)`.
  There is no anonymous or "developer" fallback — construction raises
  `WorkspaceIdentityError` if there is no trusted identity.
* **No tool takes a `user_id` / `owner` argument.** Scope is always
  `ctx.user`. `policy.assert_same_user` is a call-site guard that makes an
  accidental mismatch loud.
* Filesystem-touching helpers go through `policy.assert_within_workspace`,
  which resolves a path only if it is inside the user's own workspace root.

---

## 4. What agents may never touch

`policy.PROHIBITED_SYMBOLS` is a set of importable names that must never appear
in a tool module — arbitrary remote command execution
(`ssh_run`, `connector_ssh`, `send_command`, `check_backend`, the
password-bootstrap functions), secret retrieval (`deployment_token`,
`current_binding`, `matlab_license_config`), and identity spoofing
(`os.environ`, `getpass`).

`policy.assert_tool_modules_are_clean()` parses the AST of every module in
`policy.TOOL_MODULES` and fails the build if any prohibited name is
referenced. This is a machine check, not a code-review convention. A test in
`tests/test_agent_core.py` runs it.

Secrets never reach a trace either: `trace.redact` strips a frozenset of
secret-bearing key names and known markers (`-----BEGIN`, `AKIA`, …)
recursively before any event is stored.

---

## 5. Plans and the digest

`planning.RunPlan` is an **inert, frozen** description of a run: model,
example, execution mode, compute resource, backend, run target, parameter
overrides, datasets, Slurm request. Building or validating one submits
nothing.

The critical method is `RunPlan.digest()` — a SHA-256 over **only the
scientific and resource fields** (not advisory findings). Two plans with the
same intent have the same digest regardless of dict ordering; changing any
parameter override, the backend, or the node count changes it; attaching a
warning does not.

`validate_run_plan` reuses the *same* validation the gateway uses — B4 Slurm
rules, the model's Basic-mode parameter spec with solver detection, the
MATLAB-licence and cloud-support preflight facts — and returns findings plus
the list of approvals the plan will require. It never mutates intent, so the
digest is unchanged.

---

## 6. Approval is digest-bound

`approval.ManagedPlan` walks a lifecycle:

```text
DRAFT → VALIDATED → AWAITING_APPROVAL → APPROVED → EXECUTING → COMPLETED / FAILED
```

`approve()` records an `Approval{plan_digest, approver_user_id, approved_at}`.
Only the user the plan belongs to can approve it. There is **no agent tool
that approves a plan** — approval is a human action.

`assert_approved_for_execution(mp)` is the single gate the executor calls. It
raises `ApprovalError` unless the plan is `APPROVED` **and its live digest
still equals the approved digest**. Revising any scientific or resource field
recomputes the digest, drops the approval, and returns the plan to `DRAFT`.

The property this buys: *an agent cannot get approval for configuration A and
then execute configuration B.* The mandated test
(`test_approve_A_then_mutate_then_execute_is_rejected`) does exactly that and
asserts nothing runs.

---

## 7. Execution is dry-run first

`execution.DryRunExecutionCoordinator` walks the phases a real run goes
through — revalidate, check approval, resolve identity, stage, precheck
scheduler — and **stops at the submit boundary**. In dry-run mode (the only
mode wired today) the `SUBMIT` phase returns a redacted *description* of the
command a backend would issue (`sbatch …`, `aws batch submit-job …`) and
returns. Nothing reaches a scheduler or AWS.

A real submitter is the `SubmitBackend` protocol. None ships in the tree —
wiring one is a human integration step, gated on the same remote-identity
verification the gateway uses. Even with a backend injected, a live submit
also requires an `EXECUTE` context and an approved, digest-matching plan; with
no backend a live request is silently downgraded to a dry run.

The coordinator never imports the remote or cloud submission modules, so it
stays clean under `assert_tool_modules_are_clean`.

---

## 8. Two separate records

* **Agent operational trace** — `trace.Trace` + `trace_store.TraceStore`.
  Every request, tool call, validation, approval and execution decision for
  one agent turn, redacted, written append-only to
  `.cryostack/agent-traces/<id>.jsonl` (files opened `"a"`, never truncated).
* **Scientific run provenance** — the run manifest. It records only
  `trace_store.run_manifest_stamp(...)`: that the run was agent-assisted, the
  plan digest, who approved it and when, and a *pointer* to the operational
  trace.

`trace_store.assert_no_agent_chatter(manifest)` rejects a manifest that has
smuggled tool calls, prompt text, or model output into the scientific record.
LLM chatter must never contaminate a run's scientific history.

---

## 9. The Run Assistant

`assistant.RunAssistant` is the reference bounded agent. `handle(ctx, message)`:

1. hard-caps the context at `Permission.PLAN` (`ctx.with_ceiling`), so even if
   handed an `EXECUTE` context it can neither see nor call a mutating tool;
2. runs a deterministic loop over `LLMClient.complete` — the model asks for
   read/plan tools, they run **through the registry**, results feed back;
3. returns an `AssistantResult`. If a valid plan was produced it is surfaced
   as a *proposal*. `AssistantResult.submitted` is always `False`.

`shared_agent_panel.build_agent_panel` is a prototype Voila panel over it: it
shows the transcript and every tool call, renders the proposed plan, and gates
an **Approve** button behind an explicit human acknowledgement. Approving only
hands the plan to the host's `on_approve` callback.

---

## 10. Adding a tool — checklist

1. Decide the **minimum** `Permission`. If it only reads, it is `OBSERVE` and
   `read_only=True`.
2. If it mutates, it must declare a non-empty `scientific_effect` and
   (usually) `requires_confirmation=True`. `ToolSpec.__post_init__` enforces
   this.
3. It takes **no `user_id`**. Use `ctx.user` / `ctx.workspace_manager`.
4. It must not reference anything in `PROHIBITED_SYMBOLS`. Run
   `assert_tool_modules_are_clean()`.
5. It returns plain JSON-ish data — names and ids, **no absolute local
   paths** (see `_slim_example` / `_slim_run` for the pattern).
6. Add it to the module drained by `default_registry()`.
7. Add a test: permission-ceiling refusal, identity scoping, and — if it
   mutates — that it does nothing without approval.

---

## 11. What is deliberately *not* here

* No autonomous submit. No agent tool at `EXECUTE` or `DESTRUCTIVE` is wired
  to a real backend.
* No autonomous scientific-parameter optimisation. An agent proposes; a human
  approves the exact digest.
* No modification of canonical examples through an agent.
* No LLM vendor SDK dependency anywhere in the package.
