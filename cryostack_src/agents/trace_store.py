"""Append-only persistence for agent traces, and the boundary that keeps the
agent's operational record OUT of a run's scientific provenance (A7).

Two separate records, on purpose:

* **agent operational trace** — every request, tool call, validation, approval
  and execution decision for one agent turn. Verbose, may reference tool
  arguments and (redacted) context. Stored here, under the user's workspace in
  ``.cryostack/agent-traces/<trace-id>.jsonl``. Append-only: the store opens
  files ``"a"`` and never truncates or rewrites.

* **scientific run provenance** — the run manifest. It must record only the
  *facts a scientist needs to reproduce and trust the run*: that it was
  agent-assisted, the plan digest, who approved it and when, and a *pointer*
  to the operational trace. :func:`run_manifest_stamp` produces exactly that
  dict; :func:`assert_no_agent_chatter` rejects a manifest that has smuggled
  tool calls / prompt text / model output into the scientific record.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cryostack_src.workspace.identity import WorkspaceUser
from cryostack_src.workspace.roots import owner_root

from .trace import Trace, TraceEvent

_TRACE_DIRNAME = "agent-traces"
AGENT_PROVENANCE_KEY = "agent_assist"

#: keys that belong ONLY in the operational trace, never in a run manifest
_CHATTER_KEYS = frozenset({
    "prompt", "system_prompt", "messages", "completion", "model_output",
    "llm_response", "tool_call", "tool_calls", "args", "request_text",
    "assistant_text", "reasoning", "chain_of_thought",
})


class TraceStore:
    """Append-only JSONL store for agent traces, one directory per user."""

    def __init__(self, directory: str | Path) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def for_user(cls, user: WorkspaceUser, *,
                 workspace_root: str | Path | None = None) -> "TraceStore":
        return cls(owner_root(user, workspace_root=workspace_root)
                   / ".cryostack" / _TRACE_DIRNAME)

    def path_for(self, trace_id: str) -> Path:
        safe = "".join(c for c in str(trace_id) if c.isalnum() or c in "-_")
        if not safe:
            raise ValueError("invalid trace id")
        return self._dir / f"{safe}.jsonl"

    def attach(self, trace: Trace) -> Path:
        """Wire the trace so every future event is flushed to disk as it is
        appended. Returns the file path."""
        path = self.path_for(trace.trace_id)

        def _sink(ev: TraceEvent) -> None:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(ev.to_dict(), sort_keys=True) + "\n")

        # flush anything already recorded, then take over
        existing = trace.events
        trace._sink = _sink
        with path.open("a", encoding="utf-8") as fh:
            for ev in existing:
                fh.write(json.dumps(ev.to_dict(), sort_keys=True) + "\n")
        return path

    def persist(self, trace: Trace) -> Path:
        """Write the whole trace now (append). Use when you did not attach()."""
        path = self.path_for(trace.trace_id)
        with path.open("a", encoding="utf-8") as fh:
            for ev in trace.events:
                fh.write(json.dumps(ev.to_dict(), sort_keys=True) + "\n")
        return path

    def load(self, trace_id: str) -> list[dict]:
        path = self.path_for(trace_id)
        if not path.is_file():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out

    def verify_append_only(self, trace_id: str) -> None:
        """Structural check: sequence numbers are 0..n-1 in order and the
        timestamps never move backwards. A rewrite that reordered or dropped
        events fails this."""
        events = self.load(trace_id)
        for i, ev in enumerate(events):
            if ev.get("seq") != i:
                raise AssertionError(
                    f"trace {trace_id}: event {i} has seq {ev.get('seq')}")
        ats = [ev.get("at", "") for ev in events]
        if ats != sorted(ats):
            raise AssertionError(f"trace {trace_id}: timestamps out of order")


# ── the provenance boundary ──────────────────────────────────────────
def run_manifest_stamp(*, trace_id: str, plan_digest: str,
                       approver_user_id: str, approved_at: str) -> dict:
    """The ONLY thing an agent-assisted run writes into its scientific manifest.
    A pointer to the operational trace, not the trace itself."""
    return {
        AGENT_PROVENANCE_KEY: {
            "agent_assisted": True,
            "plan_digest": plan_digest,
            "approved_by": approver_user_id,
            "approved_at": approved_at,
            "agent_trace_ref": trace_id,
            "note": ("The agent's operational trace (requests, tool calls, "
                     "model output) is stored separately and is not part of "
                     "this scientific record."),
        }
    }


def assert_no_agent_chatter(manifest: dict) -> None:
    """Raise if a run manifest has smuggled operational-trace content into the
    scientific record."""
    def _walk(obj: Any, path: str = "") -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if str(k).lower() in _CHATTER_KEYS:
                    raise AssertionError(
                        f"run manifest carries agent chatter at {path}{k!r}; "
                        "operational trace content must not enter scientific "
                        "provenance")
                _walk(v, f"{path}{k}.")
        elif isinstance(obj, (list, tuple)):
            for i, v in enumerate(obj):
                _walk(v, f"{path}{i}.")

    stamp = manifest.get(AGENT_PROVENANCE_KEY)
    if stamp is not None:
        allowed = {"agent_assisted", "plan_digest", "approved_by",
                   "approved_at", "agent_trace_ref", "note"}
        extra = set(stamp) - allowed
        if extra:
            raise AssertionError(
                f"agent_assist stamp has unexpected keys: {sorted(extra)}")
    _walk({k: v for k, v in manifest.items() if k != AGENT_PROVENANCE_KEY})
