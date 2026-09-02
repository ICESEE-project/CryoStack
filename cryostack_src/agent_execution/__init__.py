"""Agent execution backends (PASS 4, task 4).

This package sits **outside** ``cryostack_src/agents/`` on purpose: a real
``SubmitBackend`` composes ``submit_remote_icesheets`` (which imports
``ssh_run`` / ``connector_ssh`` — names in ``agents.policy.PROHIBITED_SYMBOLS``),
so it must never be importable from a tool module. The agent core stays clean.

A backend here is handed to
:class:`cryostack_src.agents.execution.DryRunExecutionCoordinator` by the
gateway, and is only ever reached **after** the coordinator has verified the
approval digest and the ``EXECUTE`` permission ceiling.

``RemoteSubmitBackend`` is implemented and unit-tested with injected seams, but
is **not wired into the gateway** — see ``overnight/AUDIT_agent_submit_backend.md``
§7-8 for the OWNER_CHECKPOINTs (direct-SSH agent policy; live-PACE validation).
"""
from __future__ import annotations

from .remote_backend import (
    ConnectionContext,
    DryRunSubmitBackend,
    RemoteSubmitBackend,
    SubmitBlocked,
)

__all__ = [
    "ConnectionContext",
    "DryRunSubmitBackend",
    "RemoteSubmitBackend",
    "SubmitBlocked",
]
