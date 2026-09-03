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

The record lives at::

    <workspace-root>/users/<safe-id>/.cryostack/cloud/aws-connection.json

exactly like the Workspace run history. The ``<safe-id>`` segment is derived
from the trusted ``HTTP_X_CRYOSTACK_USER_ID`` identity, so:

* user A physically cannot open user B's file -- the path is not constructible
  from anything A controls;
* two users never share a connection, an ExternalId, or a role ARN.

Only non-secret metadata is written. :func:`assert_no_aws_secrets` guards the
write path so a future bug that stuffed a credential into the record fails
closed instead of persisting it.
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


class AWSConnectionStore:
    """Load / create / save / delete the calling user's AWS connection."""

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
        self._path = (self._owner_root / _REL_PATH).resolve()
        if not self._path.is_relative_to(self._owner_root.resolve()):
            raise RuntimeError("AWS connection path escaped its user root.")

    # -- read ----------------------------------------------------------
    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> AWSConnection | None:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict) or not data.get("connection_id"):
            return None
        return AWSConnection.from_dict(data)

    # -- create ------------------------------------------------------
    def create(self, *, region: str) -> AWSConnection:
        """Mint a fresh pending connection with a new ExternalId and persist it.

        Replaces any existing record for this user (reconnecting rotates the
        ExternalId -- the old trust relationship stops working, which is the
        safe default).
        """
        connection = AWSConnection(
            connection_id=f"conn-{secrets.token_hex(8)}",
            external_id=generate_external_id(self.user),
            region=(region or "").strip(),
            created_at=utc_now_iso(),
        )
        return self.save(connection)

    def get_or_create(self, *, region: str) -> AWSConnection:
        existing = self.load()
        if existing is not None:
            return existing
        return self.create(region=region)

    # -- write -----------------------------------------------------
    def save(self, connection: AWSConnection) -> AWSConnection:
        payload = connection.to_dict()
        # fail closed: a connection record never carries secret material
        assert_no_aws_secrets(payload, context="AWS connection record")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self._path)
        try:
            os.chmod(self._path, 0o600)
        except OSError:
            pass
        return connection

    def delete(self) -> None:
        try:
            self._path.unlink()
        except FileNotFoundError:
            pass
