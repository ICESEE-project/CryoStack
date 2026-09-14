# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Account Connection
# File        : store.py
#
# Description :
#     Per-user persistence of the non-secret AWS connection record.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-09-03
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""
Per-user AWS connection store.

The **active** record -- the one every AWS operation (execution resolution,
submit, poll, terminate, result sync) reads -- lives at::

    <workspace-root>/users/<safe-id>/.cryostack/cloud/aws-connection.json

exactly like the Workspace run history. The ``<safe-id>`` segment is derived
from the trusted ``HTTP_X_CRYOSTACK_USER_ID`` identity, so:

* user A physically cannot open user B's file -- the path is not constructible
  from anything A controls;
* two users never share a connection, an ExternalId, or a role ARN.

A **pending replacement** record -- staged by "Change AWS account" while the
active connection stays untouched -- lives alongside it at::

    <workspace-root>/users/<safe-id>/.cryostack/cloud/aws-connection.pending-replacement.json

Nothing outside :mod:`onboarding` ever reads the pending file: execution
resolution, submit/poll/terminate, and run history all keep reading ONLY the
active file, so a staged (unverified, possibly abandoned) replacement attempt
can never be mistaken for -- or accidentally used as -- the connection a run
is executing under. :meth:`promote_pending` is the ONLY method that writes
the active file from the pending one, and it is called ONLY after that
pending connection has itself passed AssumeRole + GetCallerIdentity.

Only non-secret metadata is written, to either file. :func:`assert_no_aws_secrets`
guards the write path so a future bug that stuffed a credential into a record
fails closed instead of persisting it.
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

from cryostack_src.workspace.identity import WorkspaceUser, resolve_workspace_user
from cryostack_src.workspace.roots import owner_root

from .external_id import generate_external_id
from .models import AWSConnection, utc_now_iso
from .redaction import assert_no_aws_secrets

_REL_PATH = Path(".cryostack") / "cloud" / "aws-connection.json"
_PENDING_REL_PATH = Path(".cryostack") / "cloud" / "aws-connection.pending-replacement.json"


class AWSConnectionStore:
    """Load / create / save / delete the calling user's AWS connection, plus
    the separate staged "pending replacement" slot Change AWS account uses."""

    def __init__(
        self,
        *,
        user: WorkspaceUser | None = None,
        workspace_root: str | Path | None = None,
        require_authenticated: bool = True,
    ) -> None:
        self.user = user or resolve_workspace_user(
            require_authenticated=require_authenticated
        )
        self._owner_root = owner_root(self.user, workspace_root=workspace_root)
        self._path = self._safe_path(_REL_PATH)
        self._pending_path = self._safe_path(_PENDING_REL_PATH)

    def _safe_path(self, rel: Path) -> Path:
        path = (self._owner_root / rel).resolve()
        if not path.is_relative_to(self._owner_root.resolve()):
            raise RuntimeError("AWS connection path escaped its user root.")
        return path

    # -- read: active ----------------------------------------------------
    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> AWSConnection | None:
        return self._read(self._path)

    # -- read: pending replacement ---------------------------------------
    @property
    def pending_path(self) -> Path:
        return self._pending_path

    def load_pending(self) -> AWSConnection | None:
        return self._read(self._pending_path)

    def _read(self, path: Path) -> AWSConnection | None:
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict) or not data.get("connection_id"):
            return None
        return AWSConnection.from_dict(data)

    # -- create: active ----------------------------------------------
    def create(self, *, region: str) -> AWSConnection:
        """Mint a fresh connection with a new ExternalId and persist it as
        the ACTIVE connection.

        Replaces any existing active record for this user immediately -- the
        old trust relationship stops working. Callers that must NOT destroy
        an existing, possibly-still-good active connection (e.g. "Change AWS
        account") use :meth:`create_pending` instead.
        """
        return self.save(self._mint(region=region))

    def get_or_create(self, *, region: str) -> AWSConnection:
        existing = self.load()
        if existing is not None:
            return existing
        return self.create(region=region)

    # -- create: pending replacement -----------------------------------
    def create_pending(self, *, region: str) -> AWSConnection:
        """Mint a fresh connection with a new ExternalId into the PENDING
        slot only. The active connection (if any) is not read or touched."""
        return self.save_pending(self._mint(region=region))

    def _mint(self, *, region: str) -> AWSConnection:
        return AWSConnection(
            connection_id=f"conn-{secrets.token_hex(8)}",
            external_id=generate_external_id(self.user),
            region=(region or "").strip(),
            created_at=utc_now_iso(),
        )

    # -- write: active -----------------------------------------------
    def save(self, connection: AWSConnection) -> AWSConnection:
        self._write(self._path, connection)
        return connection

    def delete(self) -> None:
        self._unlink(self._path)

    # -- write: pending replacement -------------------------------------
    def save_pending(self, connection: AWSConnection) -> AWSConnection:
        self._write(self._pending_path, connection)
        return connection

    def delete_pending(self) -> None:
        self._unlink(self._pending_path)

    def promote_pending(self) -> AWSConnection:
        """Atomically make the pending replacement the active connection.

        Order matters for crash-safety: the active file is written FIRST
        (an ``os.replace`` -- atomic on the same filesystem), and only THEN
        is the pending file removed. If the process dies in between, both
        files simply hold the same (already-verified) connection -- nothing
        is lost, and the next read of either one is correct; a stray pending
        file matching the active one is harmless and gets cleaned up the next
        time this runs. There is no window where the active file is missing
        or holds a half-written record.
        """
        pending = self.load_pending()
        if pending is None:
            raise RuntimeError("No pending AWS account replacement to promote.")
        self.save(pending)
        self.delete_pending()
        return pending

    # -- shared write/delete plumbing ------------------------------------
    def _write(self, path: Path, connection: AWSConnection) -> None:
        payload = connection.to_dict()
        # fail closed: a connection record never carries secret material
        assert_no_aws_secrets(payload, context="AWS connection record")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def _unlink(self, path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
