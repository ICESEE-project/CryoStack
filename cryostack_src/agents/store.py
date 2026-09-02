"""User-scoped persistence for agent plans and traces (PASS 4, task 2).

Layout, per authenticated user, inside the **existing** workspace — nothing new
is invented, this sits beside the run/working machinery::

    <workspace-root>/users/<safe-id>/.cryostack/agents/
        plans/<plan-id>.json       one ManagedPlan, atomically replaced
        traces/<trace-id>.jsonl    append-only (TraceStore)

`.cryostack/agents/` (not a visible `<workspace>/agents/`) keeps it consistent
with the sibling `.cryostack/{runs,working}` internals, which are likewise not
part of the user's browsable tree.

Guarantees (see ``cryostack_src/agents/tests/test_agent_store.py``):

* the owner is bound to the **storage path**, never read from the serialized
  blob — a tampered ``owner_user_id`` is ignored;
* atomic writes (`tmp` + ``os.replace``);
* plan digest survives the round trip; a plan edited while APPROVED reloads as
  DRAFT with the approval dropped (``restore_managed_plan``);
* traces stay append-only;
* a payload that still matches a structural secret pattern after redaction is
  **rejected** (plans) or **scrubbed** (traces) before it touches disk;
* user A's repository cannot see or load user B's plans/traces.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from cryostack_src.workspace.identity import WorkspaceIdentityError, WorkspaceUser
from cryostack_src.workspace.roots import owner_root

from .approval import ManagedPlan, restore_managed_plan
from .planning import RunPlan
from .trace import scan_for_secrets
from .trace_store import TraceStore

_AGENTS_DIRNAME = "agents"


class SecretInPayloadError(RuntimeError):
    """A payload still matched a secret pattern after redaction; refused."""

    def __init__(self, patterns: list[str]) -> None:
        super().__init__(
            "refusing to persist agent data containing secrets: "
            + ", ".join(patterns))
        self.patterns = patterns


class ConcurrentModificationError(RuntimeError):
    """The on-disk plan changed since it was loaded (another Voila kernel for
    the same user). The caller must reload and re-apply its change."""


def _safe_component(value: str) -> str:
    safe = "".join(c for c in str(value) if c.isalnum() or c in "-_")
    if not safe or safe in (".", ".."):
        raise ValueError(f"invalid id: {value!r}")
    return safe


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


class PlanRepository:
    """Persistent, owner-scoped store of :class:`ManagedPlan`."""

    def __init__(self, directory: str | Path, *, owner_user_id: str) -> None:
        if not owner_user_id or owner_user_id == "anonymous":
            raise WorkspaceIdentityError("PlanRepository needs an authenticated owner")
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._owner = owner_user_id
        #: mtime_ns seen at load() time, per plan id — for optimistic locking
        self._seen_mtime: dict[str, int] = {}

    def _path(self, plan_id: str) -> Path:
        return self._dir / f"{_safe_component(plan_id)}.json"

    # -- write -----------------------------------------------------------
    def create(self, plan: RunPlan) -> ManagedPlan:
        mp = ManagedPlan(plan_id=uuid.uuid4().hex, owner_user_id=self._owner,
                         plan=plan)
        mp._log("created", digest=plan.digest())
        self.save(mp)
        return mp

    def save(self, mp: ManagedPlan, *, force: bool = False) -> Path:
        if mp.owner_user_id != self._owner:
            raise WorkspaceIdentityError(
                f"plan {mp.plan_id} belongs to {mp.owner_user_id!r}, not this "
                f"repository's owner {self._owner!r}")
        payload = mp.to_dict()
        leaked = scan_for_secrets(payload)
        if leaked:
            raise SecretInPayloadError(leaked)
        path = self._path(mp.plan_id)
        key = _safe_component(mp.plan_id)
        # optimistic lock: if we loaded this plan and the on-disk copy has since
        # changed (another Voila kernel for the same user), refuse rather than
        # silently clobber. A fresh create() has no seen-mtime, so it is exempt.
        seen = self._seen_mtime.get(key)
        if seen is not None and not force and path.is_file():
            if path.stat().st_mtime_ns != seen:
                raise ConcurrentModificationError(
                    f"plan {mp.plan_id} changed on disk since it was loaded; "
                    "reload and re-apply your change (or save(force=True))")
        _atomic_write_json(path, payload)
        self._seen_mtime[key] = path.stat().st_mtime_ns
        return path

    # -- read ------------------------------------------------------------
    def exists(self, plan_id: str) -> bool:
        return self._path(plan_id).is_file()

    def load(self, plan_id: str) -> ManagedPlan:
        path = self._path(plan_id)
        if not path.is_file():
            raise KeyError(f"no plan {plan_id!r} for this user")
        d = json.loads(path.read_text(encoding="utf-8"))
        self._seen_mtime[_safe_component(str(plan_id))] = path.stat().st_mtime_ns
        return restore_managed_plan(d, owner_user_id=self._owner)

    def list_ids(self) -> list[str]:
        return sorted(p.stem for p in self._dir.glob("*.json"))

    def list(self) -> list[ManagedPlan]:
        return [self.load(i) for i in self.list_ids()]

    def delete(self, plan_id: str) -> None:
        self._path(plan_id).unlink(missing_ok=True)


class AgentStore:
    """The user-scoped facade the gateway holds. Built from a trusted
    :class:`WorkspaceUser`, never a caller-supplied id."""

    def __init__(self, *, user: WorkspaceUser,
                 workspace_root: str | Path | None = None) -> None:
        if not isinstance(user, WorkspaceUser) or not user.user_id \
                or user.user_id == "anonymous":
            raise WorkspaceIdentityError("AgentStore needs an authenticated user")
        self._user = user
        self._root = (owner_root(user, workspace_root=workspace_root)
                      / ".cryostack" / _AGENTS_DIRNAME)
        self.plans = PlanRepository(self._root / "plans",
                                    owner_user_id=user.user_id)
        self.traces = TraceStore(self._root / "traces")

    @classmethod
    def for_context(cls, ctx) -> "AgentStore":
        """From a :class:`~cryostack_src.agents.context.ToolContext`. The context
        already carries the trusted identity; a test may pin the workspace root
        via ``ctx.extras['workspace_root']``."""
        return cls(user=ctx.user,
                   workspace_root=(ctx.extras or {}).get("workspace_root"))

    @property
    def root(self) -> Path:
        return self._root

    @property
    def user_id(self) -> str:
        return self._user.user_id
