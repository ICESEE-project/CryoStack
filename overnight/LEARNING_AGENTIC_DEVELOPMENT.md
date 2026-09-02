# Learning: how an agentic scientific-software system was designed

This is the teaching companion to PASS 3. It is written for the project owner:
the goal is to understand *why the agent layer looks the way it does*, so the
next person extending it keeps the safety properties instead of accidentally
removing them.

The code is in `cryostack_src/agents/`. The formal contract is
`overnight/AGENT_SAFETY_MODEL.md`. The public narrative is
`icesee_jupyter_book/docs/building_agents.md`. This document is the reasoning.

---

## 1. The one sentence everything follows from

> An agent assists a scientific workflow. It never silently changes scientific
> intent, and it never gets unrestricted shell, HPC, or cloud access.

Every decision below is a consequence of that sentence. When you are unsure
whether a change is safe, check it against that sentence, not against "does it
make the demo cooler".

---

## 2. Why not just give an LLM a shell?

The fast way to build "agentic CryoStack" is: expose `ssh_run`, `sbatch`, and
`aws batch submit-job` as tools, write a good system prompt, and let the model
go. That was rejected on day one, for concrete reasons:

1. **A prompt is not an enforcement boundary.** "Please don't delete anything"
   is a wish. `Permission.DESTRUCTIVE` that the registry refuses is a rule.
2. **Scientific intent is silent.** If the model can edit a parameter file and
   then submit, nobody ever sees that it changed the basal friction
   coefficient. The run just produces different physics.
3. **Secrets leak through tool arguments and logs.** An LLM that can read a
   file can read `~/.ssh/id_ed25519` and then "helpfully" paste it into a
   summary.
4. **Blast radius.** One confused tool call on an HPC login node with real
   credentials is not a bug you can `git revert`.

So the design is the opposite: **many small typed tools, each declaring the
least privilege it needs, dispatched through one checkpoint.**

---

## 3. The layers, and what each one is responsible for

| Layer | File | Responsibility | Key property |
|---|---|---|---|
| Permissions | `permissions.py` | the OBSERVE→PLAN→PREPARE→EXECUTE→DESTRUCTIVE ladder | ordered; `covers()` |
| Identity | `context.py` | bind every call to one authenticated user | fail closed; no `user_id` arg |
| Trace | `trace.py` / `trace_store.py` | append-only, redacted operational record | secrets never stored; separate from science |
| Tools | `tools.py` | typed, permission-declaring units of capability | invariants enforced at definition time |
| Registry | `registry.py` | the single dispatch checkpoint | ceiling + confirmation + trace |
| Policy | `policy.py` | machine-enforced prohibitions | AST scan of tool modules |
| Read tools | `readonly_tools.py` | OBSERVE over existing read APIs | no absolute paths out |
| Planning | `planning.py` / `planning_tools.py` | build + validate an inert `RunPlan` | canonical digest |
| Approval | `approval.py` | human approval bound to the digest | approve-A / execute-B impossible |
| Execution | `execution.py` | walk the run phases, stop before submit | dry-run first; no backend shipped |
| Assistant | `assistant.py` / `llm.py` | the bounded reference agent | hard-capped at PLAN |
| Experiment | `experiment.py` | additive parameter-sweep grouping | one approval binds every child digest |

The important thing about this table: **each row can be tested in isolation**,
and each row fails closed if the row above it is bypassed. Approval checks the
digest even if planning produced a bad plan; execution checks approval even if
someone hand-built a `ManagedPlan`; the registry checks the ceiling even if a
tool forgot to.

---

## 4. The digest is the load-bearing idea

`RunPlan.digest()` is a SHA-256 over **only** the scientific and resource
fields — model, example, execution mode, compute resource, backend, run
target, parameter overrides, datasets, Slurm request. Not the findings, not
the timestamps, not the advisory text.

Why this exact scope:

* If the digest covered advisory findings, attaching a warning would invalidate
  an approval — annoying and it trains people to ignore re-approval.
* If the digest covered *less* than the scientific fields, an agent could
  change physics without breaking the approval. That is the whole attack we
  are preventing.

`Approval` stores `{plan_digest, approver_user_id, approved_at}`.
`assert_approved_for_execution` recomputes the live digest and compares. The
mandated test mutates a parameter after approval and asserts the executor
refuses with no side effects (`test_agent_approval.py`,
`test_r2_malicious_agent.py`).

This is the same trick a code-signing system uses: sign the artifact, verify
the signature against the artifact you are about to run, not the one you were
shown.

---

## 5. Identity: why there is no `user_id` argument anywhere

An agent acts *as* a user. It has exactly that user's scope. The temptation is
to let a tool take `user_id="..."` "for flexibility". That is an
identity-spoofing surface: a compromised LLM would just pass a different id.

So:

* `ToolContext` is built from `resolve_workspace_user(require_authenticated=True)`
  and raises if there is no trusted identity. There is no anonymous or
  developer fallback — that was removed in an earlier pass and must not come
  back.
* No tool signature contains `user_id` or `owner`. `test_r2` asserts this
  across the whole registry, so a future tool that adds one fails CI.
* Filesystem helpers go through `assert_within_workspace`, which only resolves
  paths inside the user's own root.

The audit in `AUDIT_agent_capabilities.md` lists the exact functions that form
the "identity-spoof surface" (anything taking `host=`, `user=`, `session_id=`,
`owner=`). None of them is a tool.

---

## 6. Machine enforcement beats code review

`policy.PROHIBITED_SYMBOLS` is a set of names — `ssh_run`, `connector_ssh`,
`send_command`, `deployment_token`, `os.environ`, `getpass`, … —
that must never appear in a tool module. `assert_tool_modules_are_clean()`
parses the AST of every module in `policy.TOOL_MODULES` and fails if any
appears. A test runs it.

This matters because the safe design erodes silently otherwise. Six months
from now someone adds "just a small helper" that imports `ssh_run` to check if
a host is up. Code review might miss it. The AST scan does not.

When you add a tool module, add its name to `TOOL_MODULES`.

---

## 7. Dry-run first, and why no backend ships

`DryRunExecutionCoordinator` walks the real phases — revalidate, check
approval, resolve identity, stage, precheck scheduler — and **stops at the
submit boundary**. In dry-run mode it returns a *description* of the command a
backend would issue (`sbatch …`, `aws batch submit-job …`).

A real submitter is the `SubmitBackend` protocol. **None is in the tree.**
That is deliberate for a teaching implementation: the boundary is complete and
tested, but wiring it to a live scheduler is a human integration step that
must reuse the existing B3 remote-identity verification. Shipping a working
autonomous-submit path would contradict section 1.

Even with a backend injected, a live submit also needs an `EXECUTE` context
*and* an approved digest-matching plan; with no backend a live request is
silently downgraded to a dry run (`test_agent_execution.py`).

---

## 8. Two records, never one

An agent turn produces a lot of operational detail: the user's request, every
tool call and its arguments, validation output, the approval, the execution
decision. That belongs in the **operational trace**
(`.cryostack/agent-traces/<id>.jsonl`, append-only, redacted).

It must **not** end up in the run manifest. A run's scientific provenance
records only: that it was agent-assisted, the plan digest, who approved it and
when, and a *pointer* to the trace (`run_manifest_stamp`).
`assert_no_agent_chatter` rejects a manifest that smuggled tool calls or model
output into the scientific record.

Reason: a scientist reading a run's history five years from now needs a stable,
minimal, trustworthy record — not a transcript of an LLM conversation that may
not even reproduce.

---

## 9. How the work was decomposed

PASS 3 was run as ten capability tasks (A1–A10) plus three platform
generalizations (P1–P3) plus three test suites (R1–R3):

* **A1 was delegated** to a read-only subagent — a broad inventory of ~15
  subsystems, classified by agent-safety. The coordinator needed the
  classified "never expose" and "identity-spoof surface" lists to design
  A2/A3, but should not spend its context reading every module. Everything
  else was done in-process because each task built directly on the last.
* **A2 (safety model) came before any code.** The permission table, the
  prohibitions, and the approval contract were written as a document first, so
  the code had a spec to satisfy.
* **Commits are one-capability-each and green.** `git log --grep "agents ("`
  shows the sequence. Each is independently revertible.
* **P1–P3 were gated on backward-compat.** P1 and P2 are refactors that change
  no behaviour (asserted by the existing suites still passing). P3 is purely
  additive — a new file, no change to `RunPlan` / `approval.py` / the manifest.

---

## 10. If you extend this

* Adding a **read** tool: OBSERVE, `read_only=True`, no `user_id`, no absolute
  paths out, add to the module `default_registry()` drains, add a
  ceiling-refusal + identity-scoping test.
* Adding a **planning** tool: PLAN, still `read_only=True` (a plan is inert),
  reuse the gateway's validators — do not re-implement them.
* Adding a **mutating** tool: it must declare a non-empty `scientific_effect`
  and (almost always) `requires_confirmation=True`; it must not be reachable
  from the assistant (which is capped at PLAN); it needs an "does nothing
  without approval" test.
* Wiring a **real backend**: implement `SubmitBackend`, reuse
  `enforce_remote_access` / the B3 verification, and do not change
  `approval.py` or the digest scope to make it fit.
* Adding a **model**: `ModelCapabilities` entry + adapter + result package that
  satisfies `ResultPackageProtocol`. `test_r1_contract_matrix` will tell you
  what you missed.

---

## 11. What this implementation is honest about not doing

* No autonomous submission to a real scheduler or to AWS.
* No autonomous scientific-parameter optimisation — an agent proposes a
  digest, a human approves that exact digest.
* No modification of canonical examples through an agent.
* No LLM vendor SDK dependency anywhere in `cryostack_src/agents/`.
* The Icepack structured exporter still needs a real Firedrake/HPC validation
  before any further scientific expansion (carried over from PASS 2).
