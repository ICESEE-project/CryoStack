"""Read-only inspector for a saved agent session (PASS 4, task 6).

    python -m cryostack_src.agents.inspect <path-or-id> [--json] [--store DIR]

``<path-or-id>`` is either:

* a path to a persisted trace (``<id>.jsonl``) or managed plan (``<id>.json``);
* a bare trace-id or plan-id, resolved against the authenticated user's
  ``AgentStore`` (``.cryostack/agents/{plans,traces}``).

It prints, in order: the plan + its digest, every permission decision, the
validation findings, the approval (and whether its digest still binds), every
tool call, the execution decision, and any associated run id.

**It never replays a side effect.** There is no ``--run`` flag. This is a
learning / debugging aid, nothing more.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


# ── rendering ────────────────────────────────────────────────────────
def _line(label: str, value: Any) -> str:
    return f"  {label:<22} {value}"


def render_plan(plan: dict) -> list[str]:
    out = ["PLAN"]
    for k in ("application", "model", "example", "execution_mode",
              "compute_resource", "backend", "run_target"):
        out.append(_line(k, plan.get(k, "-")))
    over = plan.get("parameter_overrides") or {}
    out.append(_line("parameter_overrides",
                     ", ".join(f"{k}={v}" for k, v in over.items()) or "(none)"))
    out.append(_line("datasets", ", ".join(plan.get("datasets") or []) or "(none)"))
    s = plan.get("slurm") or {}
    out.append(_line("slurm", f"nodes={s.get('nodes')} tasks={s.get('tasks')} "
                              f"tpn={s.get('tasks_per_node')} "
                              f"time={s.get('wall_time') or '(default)'} "
                              f"account={s.get('account') or '(none)'}"))
    out.append(_line("expected_result", plan.get("expected_result_contract", "-")))
    out.append(_line("digest", plan.get("digest", "-")))
    findings = plan.get("findings") or []
    if findings:
        out.append("  findings")
        for f in findings:
            out.append(f"    [{f['level']}] {f['where']}: {f['message']}")
    if plan.get("approvals_required"):
        out.append(_line("approvals_required", ", ".join(plan["approvals_required"])))
    return out


def render_managed_plan(mp: dict) -> list[str]:
    out = [f"MANAGED PLAN  {mp.get('plan_id', '?')}",
           _line("owner", mp.get("owner_user_id", "?")),
           _line("state", mp.get("state", "?")),
           _line("run_id", mp.get("run_id") or "(none)")]
    if mp.get("failure_reason"):
        out.append(_line("failure_reason", mp["failure_reason"]))
    out.append("")
    out += render_plan(mp.get("plan") or {})
    appr = mp.get("approval")
    out.append("")
    if appr:
        out.append("APPROVAL")
        out.append(_line("approver", appr.get("approver_user_id")))
        out.append(_line("approved_at", appr.get("approved_at")))
        out.append(_line("plan_digest", appr.get("plan_digest")))
        out.append(_line("input_fingerprint", appr.get("input_fingerprint") or "(none)"))
        matches = mp.get("digest_matches_approval")
        out.append(_line("digest still binds",
                         "yes" if matches else "NO — plan changed after approval"))
        if appr.get("note"):
            out.append(_line("note", appr["note"]))
    else:
        out.append("APPROVAL   (none)")
    if mp.get("history"):
        out.append("")
        out.append("HISTORY")
        for h in mp["history"]:
            extra = " ".join(f"{k}={v}" for k, v in h.items()
                             if k not in ("at", "event", "state"))
            out.append(f"  {h.get('at','')}  {h.get('event',''):<24} "
                       f"[{h.get('state','')}] {extra}")
    return out


_KIND_LABEL = {
    "request": "REQUEST", "plan": "PLAN", "tool_call": "TOOL",
    "validation": "VALIDATION", "scientific_change": "SCIENTIFIC CHANGE",
    "approval": "APPROVAL", "execution_decision": "EXECUTION",
    "fingerprint": "FINGERPRINT", "failure": "FAILURE", "note": "NOTE",
}


def render_trace(events: list[dict]) -> list[str]:
    out = [f"TRACE  ({len(events)} events)"]
    perms: list[str] = []
    for ev in events:
        kind = ev.get("kind", "?")
        payload = ev.get("payload", {})
        label = _KIND_LABEL.get(kind, kind.upper())
        head = f"  #{ev.get('seq'):<3} {ev.get('at','')}  {label}"
        if kind == "request":
            out.append(head + f"  {payload.get('text','')!r}")
        elif kind == "tool_call":
            ok = "ok" if payload.get("ok") else f"REFUSED: {payload.get('summary','')}"
            out.append(head + f"  {payload.get('tool','?')} "
                              f"[{payload.get('permission','?')}] -> {ok}")
            perms.append(f"{payload.get('tool','?')}: "
                         f"{payload.get('permission','?')} "
                         f"({'granted' if payload.get('ok') else 'refused'})")
        elif kind == "validation":
            errs = payload.get("errors") or []
            out.append(head + f"  {len(errs)} error(s); "
                              f"approvals={payload.get('approvals_required')}")
        elif kind == "execution_decision":
            out.append(head + f"  submitted={payload.get('submitted')} "
                              f"dry_run={payload.get('dry_run')} "
                              f"{payload.get('reason') or payload.get('job_id') or ''}")
        elif kind == "failure":
            out.append(head + f"  {payload.get('where')}: {payload.get('error')}")
        else:
            out.append(head + f"  {json.dumps(payload, sort_keys=True)[:140]}")
    if perms:
        out.append("")
        out.append("PERMISSION DECISIONS")
        for p in perms:
            out.append("  " + p)
    return out


# ── loading ──────────────────────────────────────────────────────────
def _load_by_path(path: Path) -> tuple[str, Any]:
    if path.suffix == ".jsonl":
        events = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        return "trace", events
    data = json.loads(path.read_text())
    if isinstance(data, dict) and "plan_id" in data:
        return "managed_plan", data
    if isinstance(data, dict) and "digest" in data and "model" in data:
        return "plan", data
    raise SystemExit(f"unrecognised agent file: {path}")


def _load_by_id(ident: str, store_dir: str | None) -> tuple[str, Any]:
    from cryostack_src.workspace.identity import resolve_workspace_user
    from .store import AgentStore

    if store_dir:
        base = Path(store_dir)
        for cand, kind in ((base / "traces" / f"{ident}.jsonl", "trace"),
                           (base / "plans" / f"{ident}.json", "managed_plan")):
            if cand.is_file():
                return _load_by_path(cand)
        raise SystemExit(f"no trace or plan {ident!r} under {base}")

    user = resolve_workspace_user(require_authenticated=True)
    store = AgentStore(user=user)
    if store.traces.path_for(ident).is_file():
        return "trace", store.traces.load(ident)
    if store.plans.exists(ident):
        return "managed_plan", store.plans.load(ident).to_dict()
    raise SystemExit(f"no trace or plan {ident!r} for {user.user_id}")


def inspect(target: str, *, store_dir: str | None = None) -> tuple[str, Any]:
    p = Path(target)
    if p.exists():
        return _load_by_path(p)
    return _load_by_id(target, store_dir)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m cryostack_src.agents.inspect",
                                 description=__doc__)
    ap.add_argument("target", help="path to a <id>.jsonl / <id>.json, or a bare id")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--store", metavar="DIR",
                    help="an .cryostack/agents directory (else the current user's)")
    args = ap.parse_args(argv)

    kind, data = inspect(args.target, store_dir=args.store)

    if args.json:
        print(json.dumps({"kind": kind, "data": data}, indent=2, sort_keys=True))
        return 0

    if kind == "trace":
        lines = render_trace(data)
    elif kind == "managed_plan":
        lines = render_managed_plan(data)
    else:
        lines = render_plan(data)
    print("\n".join(lines))
    print("\n(read-only — no side effect was replayed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
