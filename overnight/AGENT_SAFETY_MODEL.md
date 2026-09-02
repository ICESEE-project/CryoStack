# The CryoStack agent safety model

Status: PASS 3 (agentic CryoStack). This document is the contract every agent
and tool in CryoStack obeys. It is **derived from existing CryoStack
boundaries** — B2 per-user isolation, B3 remote-identity verification, B4
pre-submit validation, the model/backend preflight, connector-v2 ownership, and
the secret-stripping already in the persistence layer — not invented on top of
them.

The machine-enforced half of this document lives in
`cryostack_src/agents/permissions.py`, `.../context.py`, `.../policy.py` and
their tests. Where this doc and the code disagree, the code wins and the doc is
a bug.

---

## 1. What an agent is (and is not) in CryoStack

- An **agent** is an orchestrator that turns a user request into a sequence of
  **tool** calls and a **RunPlan**, and asks the user for approval before
  anything with scientific or computational effect happens.
- A **tool** is a small, typed, permission-declaring wrapper around an API
  CryoStack already exposes to its own UI. A tool never contains business logic
  of its own — it calls `WorkspaceManager`, the model adapters, the execution
  backends, `RemoteBridge`, etc., exactly as the gateway does.
- An agent has **no capability the authenticated user does not already have**,
  and several the user *does* have are still withheld from agents (§4).
- The LLM is **advisory**. It proposes; the tool registry, the validation layer,
  and the human approve or reject. An LLM response never directly causes an
  sbatch, an S3 write, a file deletion, or an identity change.

---

## 2. Permission levels

Ordered, least → most privileged. A tool declares the **minimum** level it
needs; a `ToolContext` is granted a **maximum** level; a call is refused unless
`context.max_permission >= tool.permission`.

| Level | Meaning | Examples | Human approval |
|---|---|---|---|
| `OBSERVE` | Pure reads within the caller's scope. No mutation anywhere. | `list_models`, `inspect_example`, `list_runs`, `inspect_results` | never |
| `PLAN` | Construct / validate structured proposals. Still no mutation. | `prepare_run_plan`, `validate_run_plan`, `estimate_execution_requirements` | never |
| `PREPARE` | Mutations **confined to the authenticated user's own workspace tree** that do **not** change scientific intent and do **not** submit compute. | stage a working copy for a *plan already shown to the user*; create a user-owned scratch example | shown, not gated |
| `EXECUTE` | Compute submission (sbatch / AWS Batch) and remote-filesystem writes. | submit an **approved** RunPlan | **always** (a plan-digest-bound approval) |
| `DESTRUCTIVE` | Deletes or overwrites user data. | `delete_user_example`, clearing a run's outputs | **always**, explicit, per-operation |

Mapping to the operator's conceptual lifecycle:
`OBSERVE` ↔ observe · `PLAN` ↔ plan · `PREPARE` ↔ prepare · `EXECUTE` ↔ execute ·
`DESTRUCTIVE` ↔ destructive.

**PASS 3 ceiling:** the shipped Run Assistant is granted **`PLAN`**. `PREPARE`
is available to tools but only reached through an explicit user action.
`EXECUTE` and `DESTRUCTIVE` tools exist but are **not wired to a real backend in
PASS 3** — the dry-run coordinator stops before sbatch/submit (A6).

---

## 3. Identity — non-negotiable

- Every `ToolContext` is constructed from a **`WorkspaceUser`** obtained from
  `cryostack_src.workspace.identity.resolve_workspace_user(require_authenticated=True)`
  — the same fail-closed path B2 uses (`HTTP_X_CRYOSTACK_USER_ID`).
- A tool **never** receives a `user_id` / `owner` argument. It reads identity
  from its `ToolContext`. Any API that still takes a raw owner argument is
  called by the tool layer with the context's user, never with a value the LLM
  produced.
- There is **no** "act as", "impersonate", "admin", or developer-account
  fallback. `resolve_workspace_user` returning the anonymous sentinel ⇒ the
  agent layer refuses to construct a context at all.
- A `ToolContext` is immutable after construction and carries only: the
  `WorkspaceUser`, the application id (`"icesheets"` / `"icesee"`), the granted
  `max_permission`, an optional bound `WorkspaceManager` (already user-scoped),
  and a `Trace` sink.

---

## 4. Hard prohibitions (machine-enforced in `policy.py`)

An agent / tool **must not**:

1. become another identity or read another user's workspace, runs, datasets,
   examples, results, or figures;
2. fall back to a developer / service account;
3. expose or return a secret: **private SSH key material, raw HPC password,
   AWS access key / secret / session token, connector pairing code / session
   secret / control secret, deployment token, MATLAB license string**;
4. bypass **B3 remote-identity verification** (`enforce_remote_access`) before a
   remote run;
5. bypass **B4 Slurm validation** (`validate_slurm_resources`) or the
   model/backend **preflight** (`cloud_run_preflight`, MATLAB-license gate,
   Spack-readiness);
6. run an **arbitrary shell command** on any host — there is no
   `run_command` / `ssh` / `send_command(command=…)` tool, ever;
7. read or write an **arbitrary filesystem path** — there is no `read_file` /
   `write_file` / `list_dir` tool over absolute paths; file tools resolve only
   within `WorkspaceManager`'s containment (`_owns` / `_within`);
8. inject **arbitrary environment variables** into a job;
9. **modify a canonical example** — overrides only ever land in a per-run
   working copy (`stage_example_for_run`);
10. submit an **unapproved** plan, or a plan whose canonical digest differs from
    the approved one;
11. write LLM chatter, tool arguments, or model output into **scientific run
    provenance** (the run manifest). The agent operational trace is separate.

`policy.py` holds `PROHIBITED_SYMBOLS` — a literal allowlist-by-exclusion of the
importable functions a tool body may not call (`RemoteBridge.check_backend`,
`connector_ssh`, `send_command`, `ssh_run`, `run_ssh`, `bootstrap_passwordless_ssh`,
`deployment_token`, `current_binding`, …) and a test asserts no tool module
imports them.

---

## 5. Confirmation & approval

- `ToolSpec.requires_confirmation = True` ⇒ the orchestrator must surface the
  tool call (name + typed args + `scientific_effect`) and receive an explicit
  user acknowledgement before dispatch. `PREPARE`+ tools set this.
- **RunPlan approval** (A5) is stronger than a per-tool confirmation: a plan is
  hashed with a canonical, field-ordered digest
  (`RunPlan.digest()`); `Approval` binds `{plan_digest, approver_user_id,
  approved_at}`. The executor refuses any plan whose live digest ≠ the approved
  digest. Editing any scientific or resource field after approval changes the
  digest ⇒ the plan reverts to `AWAITING_APPROVAL`.
- Test (A5): `approve(plan)` → mutate `parameter_overrides` → `execute` ⇒
  `ApprovalError` (digest mismatch), no side effects.

---

## 6. Auditability

- Every agent turn appends to a `Trace` (A7): user request, plan creation, each
  tool call (name, redacted args, result summary, permission, duration),
  validation findings, scientific modifications, approval event, execution
  decision, resulting run id, results inspected, failures.
- The trace is **append-only** and **secret-free** (the same
  `connector_relay_auth.redact` field set plus AWS/MATLAB/password keys).
- `agent operational trace` (debugging, LLM chatter, tool args) and
  `scientific run provenance` (the run manifest: model, overrides, container,
  software) are **distinct stores**. A run's manifest records *that* a plan was
  approved and by whom and the plan digest — never the conversation.

---

## 7. Dry-run first

The execution coordinator (A6) consumes an approved plan and runs the **real**
staging + validation path as far as is safe, then **stops before**: `sbatch`,
`aws batch submit-job`, any `REMOTE_MUTATION`, any `DESTRUCTIVE` op. It returns a
structured trace: validation results, the staging actions that *would* run, the
identity requirements, the command/backend that *would* be used (with secret
values elided), the expected `outputs/` contract, and the blocked/approval
reason. Real submission is **not wired in PASS 3**.
