"""Append-only, secret-free agent operational trace (A7).

This is the **agent operational trace** — user request, plan creation, tool
calls, validation, approval, execution decision. It is deliberately SEPARATE
from scientific run provenance (the run manifest): LLM chatter and tool
arguments must never contaminate a run's scientific record. A run's manifest
records only *that* a plan was approved, by whom, and the plan digest.

Nothing here is ever persisted with a secret in it: :func:`redact` strips the
connector-relay secret fields plus password / private-key / AWS-credential /
token / MATLAB-license keys, recursively, before an event is stored.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

#: key names whose values are replaced with "***" anywhere in a trace payload
_SECRET_KEYS = frozenset({
    "password", "passwd", "pass", "secret", "session_secret", "control_secret",
    "pairing_code", "pairing_secret", "token", "deployment_token", "api_key",
    "apikey", "private_key", "privatekey", "priv_key", "id_ed25519", "id_rsa",
    "aws_access_key_id", "aws_secret_access_key", "aws_session_token",
    "access_key", "secret_key", "session_token", "credentials", "mlm_license",
    "mlm_license_file", "matlab_license", "authorization", "bearer",
})

#: substrings that, if they appear in a *string value*, get the value elided
_SECRET_MARKERS = (
    "-----BEGIN", "PRIVATE KEY", "aws_access_key", "AKIA", "ASIA",
    "1711@matlablic",
)


def redact(value: Any) -> Any:
    """Deep copy of ``value`` with known secret fields / markers replaced."""
    if isinstance(value, dict):
        return {
            k: ("***" if str(k).lower() in _SECRET_KEYS else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return type(value)(redact(v) for v in value)
    if isinstance(value, str):
        if any(m in value for m in _SECRET_MARKERS):
            return "***"
        return value
    return value


@dataclass(frozen=True)
class TraceEvent:
    seq: int
    at: str                       # ISO-8601 UTC
    kind: str                     # "request" | "plan" | "tool_call" | "validation"
    #                               | "scientific_change" | "approval"
    #                               | "execution_decision" | "run" | "failure" | "note"
    payload: dict

    def to_dict(self) -> dict:
        return {"seq": self.seq, "at": self.at, "kind": self.kind, "payload": self.payload}


class Trace:
    """An append-only list of :class:`TraceEvent`. Not thread-safe by design —
    one trace belongs to one agent turn / one session."""

    def __init__(self, *, trace_id: str | None = None, user_id: str | None = None) -> None:
        self.trace_id = trace_id or uuid.uuid4().hex
        self.user_id = user_id
        self._events: list[TraceEvent] = []

    def append(self, kind: str, payload: dict | None = None) -> TraceEvent:
        ev = TraceEvent(
            seq=len(self._events),
            at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            kind=str(kind),
            payload=redact(dict(payload or {})),
        )
        self._events.append(ev)
        return ev

    # -- convenience wrappers -----------------------------------------
    def request(self, text: str) -> TraceEvent:
        return self.append("request", {"text": text})

    def tool_call(self, name: str, *, args: dict, permission: str,
                  ok: bool, summary: str, duration_ms: float | None = None) -> TraceEvent:
        return self.append("tool_call", {
            "tool": name, "args": args, "permission": permission,
            "ok": ok, "summary": summary, "duration_ms": duration_ms,
        })

    def scientific_change(self, changes: dict) -> TraceEvent:
        return self.append("scientific_change", {"changes": changes})

    def approval(self, *, plan_digest: str, approver: str, approved: bool) -> TraceEvent:
        return self.append("approval", {
            "plan_digest": plan_digest, "approver": approver, "approved": approved,
        })

    def execution_decision(self, *, decision: str, reason: str,
                           dry_run: bool) -> TraceEvent:
        return self.append("execution_decision", {
            "decision": decision, "reason": reason, "dry_run": dry_run,
        })

    def failure(self, where: str, error: str) -> TraceEvent:
        return self.append("failure", {"where": where, "error": error})

    # -- read ------------------------------------------------------------
    @property
    def events(self) -> list[TraceEvent]:
        return list(self._events)

    def to_list(self) -> list[dict]:
        return [e.to_dict() for e in self._events]

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps({
            "trace_id": self.trace_id, "user_id": self.user_id,
            "events": self.to_list(),
        }, indent=indent)
