# Tomorrow's lab — learn the CryoStack agent architecture by driving it

For the project owner. Ten short exercises. After finishing them you should be
able to explain the whole boundary — permissions, identity, digest-bound
approval, dry-run execution, the submit-backend composition — from memory.

Run everything from the repo root with the project env active. Nothing here
submits a job, touches a cluster, or costs money.

Set an identity once (the agent layer fails closed without one):

```bash
export CRYOSTACK_WORKSPACE_USER=lab-me
export CRYOSTACK_WORKSPACE_ROOT=/tmp/agent-lab      # a throwaway workspace
export ICEPACK_ROOT=$HOME/icepack                   # so examples resolve (if present)
```

---

## Exercise 1 — inspect a `ToolSpec`

```bash
python -c "
from cryostack_src.agents import default_registry, Permission, Trace
from cryostack_src.agents.context import ToolContext
from cryostack_src.workspace.identity import resolve_workspace_user
ctx = ToolContext(user=resolve_workspace_user(require_authenticated=True),
                  application='icesheets', max_permission=Permission.PLAN, trace=Trace())
for s in default_registry().describe(ctx=ctx):
    print(f\"{s['permission']:<8} {s['name']:<32} read_only={s['read_only']} effect={s['scientific_effect']}\")
"
```

**Look at:** `cryostack_src/agents/tools.py` — `ToolSpec.__post_init__`. Notice
a `read_only` tool cannot need more than `PLAN`, and a mutating tool must
declare a `scientific_effect`. Every shipped tool is OBSERVE or PLAN.

**Explain:** why the registry hands the LLM *dicts*, never callables
(`llm_adapters.assert_declarative_tools`).

---

## Exercise 2 — add a harmless read-only tool

Edit `cryostack_src/agents/readonly_tools.py`, add at the end:

```python
@tool(name="agent_lab_ping",
      description="A no-op tool for the lab. Returns a fixed string.",
      permission=Permission.OBSERVE)
def agent_lab_ping(ctx) -> dict:
    return {"pong": True, "user": ctx.user_id}
```

Then:

```bash
python -c "
from cryostack_src.agents import default_registry, Permission, Trace
from cryostack_src.agents.context import ToolContext
from cryostack_src.workspace.identity import resolve_workspace_user
reg = default_registry()
ctx = ToolContext(user=resolve_workspace_user(require_authenticated=True),
                  application='icesheets', max_permission=Permission.OBSERVE, trace=Trace())
print(reg.invoke('agent_lab_ping', ctx).to_dict())
"
python -m pytest cryostack_src/agents/tests/test_r2_malicious_agent.py -q
```

**Explain:** the tool got no `user_id` argument — it read `ctx.user_id`. The
`test_r2` suite still passes because the new tool takes no identity arg.
**Revert the edit** when done (`git checkout cryostack_src/agents/readonly_tools.py`).

---

## Exercise 3 — identity is fail-closed

```bash
env -u CRYOSTACK_WORKSPACE_USER -u HTTP_X_CRYOSTACK_USER_ID python -c "
from cryostack_src.agents import build_tool_context
build_tool_context(application='icesheets')
"
```

It raises `WorkspaceIdentityError`. Now with the env var set it succeeds and
the context is capped at `PLAN`.

**Look at:** `cryostack_src/agents/context.py` — `_TRUSTED_SOURCES`,
`__post_init__`, `with_ceiling` (it only ever *lowers* the ceiling).

**Explain:** an agent has exactly the authenticated user's scope and cannot
widen it.

---

## Exercise 4 — construct a `RunPlan` by hand

```bash
python -c "
from cryostack_src.agents import RunPlan, SlurmRequest
p = RunPlan(application='icesheets', model='issm', example='SquareIceShelf',
            execution_mode='remote', compute_resource='pace', backend='spack',
            run_target='runme.m',
            parameter_overrides={'friction': 1.0},
            slurm=SlurmRequest(job_name='ISSM', wall_time='01:00:00', account='alloc'))
print(p.to_json())
"
```

Try `execution_mode='local'` — it raises. Try `model='foo'` — it raises.

**Look at:** `planning.py` — `_digest_material()`. Only scientific + resource
fields. Not findings, not timestamps.

---

## Exercise 5 — the digest

```bash
python -c "
from cryostack_src.agents import RunPlan, SlurmRequest
from dataclasses import replace
mk = lambda **k: RunPlan(application='icesheets', model='issm', example='X',
     execution_mode='remote', compute_resource='pace', backend='spack',
     run_target='runme.m', slurm=SlurmRequest(wall_time='01:00:00', account='a'), **k)
a = mk(parameter_overrides={'friction': 1.0})
b = mk(parameter_overrides={'friction': 1.0})
c = mk(parameter_overrides={'friction': 2.0})
print('same intent  ->', a.digest() == b.digest())
print('changed param->', a.digest() == c.digest())
print('advisory finding does not change it ->',
      a.digest() == a.with_findings([]).digest())
"
```

**Explain:** approval binds to this string. Change any scientific/resource
field and the approval no longer matches.

---

## Exercise 6 — approve a plan

```bash
python -c "
from cryostack_src.agents import AgentStore, RunPlan, SlurmRequest, PlanState
from cryostack_src.workspace.identity import resolve_workspace_user
u = resolve_workspace_user(require_authenticated=True)
store = AgentStore(user=u)
mp = store.plans.create(RunPlan(application='icesheets', model='issm', example='X',
     execution_mode='remote', compute_resource='pace', backend='spack',
     run_target='runme.m', slurm=SlurmRequest(wall_time='01:00:00', account='a')))
mp.mark_validated(mp.plan); mp.submit_for_approval(); mp.approve(u)
store.plans.save(mp)
print('state:', mp.state, ' plan_id:', mp.plan_id)
print('persisted at:', store.plans._path(mp.plan_id))
"
```

**Look at:** `approval.py` — `ManagedPlan.approve` (only the owner can),
`assert_approved_for_execution` (the single execution gate). Keep the printed
`plan_id`.

---

## Exercise 7 — mutate an approved plan, watch it break

```bash
python -c "
from cryostack_src.agents import AgentStore, PlanState
from cryostack_src.workspace.identity import resolve_workspace_user
from dataclasses import replace
u = resolve_workspace_user(require_authenticated=True)
store = AgentStore(user=u)
pid = store.plans.list_ids()[0]                 # the one from ex. 6
mp = store.plans.load(pid)
mp.plan = replace(mp.plan, parameter_overrides={'friction': 99.0})   # tamper
store.plans.save(mp)
reloaded = store.plans.load(pid)
print('after reload -> state:', reloaded.state, ' approval:', reloaded.approval)
"
```

The state came back `DRAFT`, approval `None` — `restore_managed_plan`
recomputed the digest, saw it no longer matched, and dropped the approval.

**Explain:** what the human approved ≠ what is on disk ⇒ not approved.

---

## Exercise 8 — run the dry-run coordinator

```bash
python -c "
from cryostack_src.agents import (RunPlan, SlurmRequest, PlanStore, Permission, Trace)
from cryostack_src.agents.context import ToolContext
from cryostack_src.agents.execution import DryRunExecutionCoordinator
from cryostack_src.workspace.identity import resolve_workspace_user
u = resolve_workspace_user(require_authenticated=True)
ctx = ToolContext(user=u, application='icesheets', max_permission=Permission.EXECUTE, trace=Trace())
store = PlanStore()
mp = store.create(owner=u, plan=RunPlan(application='icesheets', model='issm', example='X',
     execution_mode='remote', compute_resource='pace', backend='spack',
     run_target='runme.m', slurm=SlurmRequest(job_name='ISSM', wall_time='01:00:00', account='a')))
mp.mark_validated(mp.plan); mp.submit_for_approval(); mp.approve(u)
rep = DryRunExecutionCoordinator().execute(ctx, mp, dry_run=True)
for o in rep.outcomes: print(f\"{o.phase:<20} {o.status:<10} {o.detail[:70]}\")
print('submitted:', rep.submitted, ' would run:', rep.submission_command)
"
```

**Look at:** `execution.py` — the phase list, and where it stops. `dry_run` is
forced `True` when no backend is wired. Try `dry_run=False` with
`max_permission=Permission.PLAN` — it blocks with `blocked_reason='permission'`.

---

## Exercise 9 — inspect a trace

Run the Run Assistant once to produce a trace:

```bash
python -c "
from cryostack_src.agents import (RunAssistant, RuleBasedAdapter, Permission, Trace, AgentStore)
from cryostack_src.agents.context import ToolContext
from cryostack_src.workspace.identity import resolve_workspace_user
u = resolve_workspace_user(require_authenticated=True)
store = AgentStore(user=u)
tr = Trace(user_id=u.user_id); store.traces.attach(tr)
ctx = ToolContext(user=u, application='icesheets', max_permission=Permission.PLAN, trace=tr)
res = RunAssistant(llm=RuleBasedAdapter(default_example='SquareIceShelf')).handle(
    ctx, 'run SquareIceShelf on pace, account gts-lab')
print('trace id:', tr.trace_id, ' plan?', res.proposed_plan is not None)
"
```

Then inspect it (use the printed trace id):

```bash
python -m cryostack_src.agents.inspect <trace-id>
```

**Look at:** the `PERMISSION DECISIONS` block. Every tool call, the permission
it needed, granted or refused. **Explain:** why this is separate from the run
manifest (`trace_store.run_manifest_stamp` / `assert_no_agent_chatter`).

---

## Exercise 10 — follow the path toward a real submit

Read, in this order:

1. `overnight/AUDIT_agent_submit_backend.md` §3 — the exact call sequence.
2. `cryostack_src/agent_execution/remote_backend.py` — `RemoteSubmitBackend.submit`
   — match each numbered step to §3.
3. `cryostack_src/agent_execution/tests/test_remote_backend.py` — every
   invariant, tested with injected fakes (no HPC).
4. `cryostack_src/remote/access_state.py:enforce_remote_access` — the B3 gate
   the backend calls fresh.

Then run:

```bash
python -m pytest cryostack_src/agent_execution/ -q
python -m cryostack_src.acceptance --offline
```

**Explain:** why the backend lives *outside* `cryostack_src/agents/`, and what
the two `OWNER_CHECKPOINT`s are before it can be wired into the gateway
(direct-SSH agent policy; a live PACE validation run).

---

## After the lab

You should be able to answer, without looking:

* What are the five permission levels and what can each do?
* How does an agent get an identity, and what happens if it has none?
* What exactly does the plan digest cover, and why not more?
* Give the sequence: draft → … → completed. Where does the human act?
* How is "approve config A, run config B" made impossible — name the function.
* Where does the dry-run coordinator stop, and what does it print instead?
* Why can't a provider adapter be handed an SSH command?

If any of those is fuzzy, re-run the exercise that covers it.
