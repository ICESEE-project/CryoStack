# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Account Connection
# File        : execution.py
#
# Description :
#     Resolve the credential context for one cloud operation: a fresh
#     cross-account AssumeRole for a connected BYO-AWS user, or ambient /
#     profile credentials for developer mode.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-09-03
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: MIT
#
# =============================================================================

"""
Per-operation credential resolution.

Two explicit, non-mixing paths:

* **BYO-AWS user mode** — the authenticated CryoStack user has a *connected*
  :class:`AWSConnection`. Every operation does a **fresh** ``sts:AssumeRole``
  (nothing from C7.2 is persisted), confirms the returned account matches the
  role ARN *and* the account recorded at connect time, and runs with those
  temporary credentials only. **No profile. No ambient-credential fallback.**
  A broken connection fails closed with :class:`CloudAccessError`.

* **Developer / operator mode** — no connection record exists *and* the
  authenticated user is listed in ``CRYOSTACK_CLOUD_OPERATOR_USER_IDS``
  (comma-separated CryoStack user ids; empty by default). Ambient AWS
  credentials, optionally selected by a named profile. Any other user without
  a connection is refused: the host's credentials are never lent to end users.

:func:`resolve_cloud_execution` returns a :class:`CloudExecution` the gateway
threads into ``CloudBridge`` / ``CloudManager`` via the ``credentials`` kwarg
added in C7.1.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from cryostack_src.workspace.identity import WorkspaceUser, resolve_workspace_user

from .assume_role import DEFAULT_SESSION_SECONDS, AssumeRoleError, assume_role
from .context import AWSExecutionContext
from .defaults import CloudDefaults, derive_cloud_defaults
from .models import AWSConnection, account_id_from_role_arn
from .principal import HOST_ACCOUNT_MESSAGE, is_host_account_role
from .store import AWSConnectionStore

MODE_BYO = "byo"
MODE_DEVELOPER = "developer"

#: CryoStack user ids allowed to run on the host's own AWS credentials.
OPERATOR_ENV = "CRYOSTACK_CLOUD_OPERATOR_USER_IDS"


class CloudAccessError(RuntimeError):
    """A connected BYO-AWS account cannot currently be used. Fail closed --
    never silently fall back to the CryoStack host's AWS credentials."""


def is_cloud_operator(user: WorkspaceUser | None, env=None) -> bool:
    """Whether ``user`` may use developer mode (the host's AWS credentials).

    Only users explicitly listed in :data:`OPERATOR_ENV` whose identity is
    trusted: the proxy-verified header or the server-side
    ``CRYOSTACK_WORKSPACE_USER`` override (single-user/dev servers). The list
    is empty unless the operator sets it; anonymous visitors never qualify.
    """
    if user is None or user.source not in {"cryostack-auth", "env-override"}:
        return False
    raw = (os.environ if env is None else env).get(OPERATOR_ENV, "")
    allowed = {item.strip() for item in raw.split(",") if item.strip()}
    return user.user_id in allowed


def _no_connection_error() -> CloudAccessError:
    return CloudAccessError(
        "No AWS account is connected. Open Cloud Environment → AWS ACCOUNT "
        "and connect your AWS account before using cloud execution."
    )


@dataclass
class CloudExecution:
    mode: str                       # "byo" | "developer"
    region: str
    #: {AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN} or None
    credentials: dict[str, str] | None = field(default=None, repr=False)
    profile: str | None = None
    account_id: str = ""            # "" in developer mode
    defaults: CloudDefaults | None = None
    connection: AWSConnection | None = None

    @property
    def is_byo(self) -> bool:
        return self.mode == MODE_BYO

    @property
    def matlab_license(self):
        """ISSM cloud-runtime MATLAB-license state for this connection
        (:class:`cryostack_src.cloud.matlab_license.CloudMatlabLicense`).
        Non-secret: only whether it is configured + the Secrets Manager ARN.
        ``NOT_CONFIGURED`` in developer mode / no connection."""
        from cryostack_src.cloud.matlab_license import (
            NOT_CONFIGURED,
            resolve_cloud_matlab_license,
        )

        if self.connection is None:
            return NOT_CONFIGURED
        return resolve_cloud_matlab_license(self.connection)

    def bucket(self, *, developer_fallback: str = "") -> str:
        """The S3 runs bucket for this operation.

        BYO mode always derives ``cryostack-runs-<account-id>``; developer mode
        uses whatever the Advanced field / caller supplied.
        """
        if self.is_byo and self.defaults is not None:
            return self.defaults.bucket
        return developer_fallback


def resolve_cloud_execution(
    *,
    user: WorkspaceUser | None = None,
    workspace_root=None,
    require_authenticated: bool = True,
    region_hint: str = "",
    profile_hint: str | None = None,
    model: str = "issm",
    duration_seconds: int = DEFAULT_SESSION_SECONDS,
    runner=None,
) -> CloudExecution:
    """Resolve the credential context for the calling CryoStack user."""
    user = user or resolve_workspace_user(require_authenticated=require_authenticated)
    store = AWSConnectionStore(
        user=user,
        workspace_root=workspace_root,
        require_authenticated=require_authenticated,
    )
    connection = store.load()

    # -- developer / operator mode: no connection record ---------------
    # Only for allow-listed operators; everyone else must connect an account.
    if connection is None:
        if not is_cloud_operator(user):
            raise _no_connection_error()
        return CloudExecution(
            mode=MODE_DEVELOPER,
            region=(region_hint or "").strip() or "us-east-2",
            credentials=None,
            profile=(profile_hint or None),
        )

    # -- BYO-AWS mode: a connection record exists ---------------------
    # From here on we NEVER fall back to ambient credentials.
    if not connection.is_connected:
        raise CloudAccessError(
            "Your AWS account connection is not verified. Open Cloud "
            "Environment → AWS ACCOUNT and click Verify connection (or "
            "Re-check) before preparing the cloud."
        )
    if not (connection.role_arn and connection.external_id):
        raise CloudAccessError(
            "Your AWS connection is missing its role ARN or ExternalId. "
            "Reconnect the AWS account."
        )
    # also catches connections verified before this check existed
    if is_host_account_role(connection.role_arn):
        raise CloudAccessError(HOST_ACCOUNT_MESSAGE)

    try:
        context = assume_role(
            role_arn=connection.role_arn,
            external_id=connection.external_id,
            region=connection.region,
            duration_seconds=duration_seconds,
            runner=runner,
        )
    except AssumeRoleError as err:
        raise CloudAccessError(
            f"CryoStack could not access your AWS account: {err} "
            "Re-check the connection in Cloud Environment → AWS ACCOUNT."
        ) from None

    # fail closed: the fresh session must match BOTH the role ARN account
    # (assume_role already checks this) and the account recorded at connect.
    if connection.account_id and context.account_id != connection.account_id:
        raise CloudAccessError(
            "The AWS account for this connection changed since it was "
            f"verified ({connection.account_id} → {context.account_id}). "
            "Reconnect the AWS account."
        )
    role_account = account_id_from_role_arn(connection.role_arn)
    if role_account and context.account_id != role_account:
        raise CloudAccessError(
            "Account mismatch between the assumed session and the role ARN. "
            "Connection not usable."
        )

    return CloudExecution(
        mode=MODE_BYO,
        region=connection.region,
        credentials=context.environment(),
        profile=None,
        account_id=context.account_id,
        defaults=derive_cloud_defaults(
            account_id=context.account_id, region=connection.region, model=model
        ),
        connection=connection,
    )
