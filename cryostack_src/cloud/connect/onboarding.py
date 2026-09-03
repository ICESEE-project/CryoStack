# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Account Connection
# File        : onboarding.py
#
# Description :
#     UI-neutral orchestration of the "Connect AWS Account" flow: mint /
#     reuse the connection, build the Quick Create URL, verify, disconnect.
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
:class:`AWSOnboarding` -- the single object a frontend talks to.

It owns no widgets and no AWS semantics of its own; it composes the connection
store, the deployment principal, the CloudFormation template URL, and
:func:`verify_connection`. Every method returns plain data safe to render.

Key behaviours the UI relies on:

* ``begin()`` **reuses** the existing connection record -- the ExternalId is
  *not* regenerated on a page refresh. Only an explicit :meth:`disconnect`
  (or :meth:`reconnect`) rotates it.
* :meth:`verify` always persists a record that is safe to store (no STS
  credentials); it returns the live context for immediate use only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from cryostack_src.workspace.identity import WorkspaceUser

from .cloudformation import DEFAULT_STACK_NAME, quick_create_url
from .defaults import derive_cloud_defaults
from .models import AWSConnection
from .principal import cryostack_principal_arn
from .store import AWSConnectionStore
from .verify import VerificationResult, verify_connection

#: deployment env var: public URL the CryoStackExecutionRole template is hosted at
TEMPLATE_URL_ENV = "CRYOSTACK_CF_TEMPLATE_URL"
DEFAULT_REGION = "us-east-2"


class OnboardingConfigError(RuntimeError):
    """A required deployment setting for onboarding is missing."""


@dataclass
class ConnectStep:
    """What the UI needs to render the 3-step Connect card."""

    connection: AWSConnection
    setup_url: str
    stack_name: str
    principal_arn: str
    external_id: str


class AWSOnboarding:
    def __init__(
        self,
        *,
        user: WorkspaceUser | None = None,
        workspace_root=None,
        require_authenticated: bool = True,
        template_url: str | None = None,
        region: str = DEFAULT_REGION,
        principal_arn: str | None = None,
        runner=None,
    ) -> None:
        self.store = AWSConnectionStore(
            user=user,
            workspace_root=workspace_root,
            require_authenticated=require_authenticated,
        )
        self.region = (region or DEFAULT_REGION).strip()
        self._template_url = template_url
        self._principal_arn = principal_arn
        self._runner = runner

    # -- config (fail clearly) --------------------------------------
    def principal_arn(self) -> str:
        return self._principal_arn or cryostack_principal_arn()

    def template_url(self) -> str:
        url = self._template_url or (os.environ.get(TEMPLATE_URL_ENV) or "").strip()
        if not url:
            raise OnboardingConfigError(
                "The CryoStack access-role template URL is not configured on "
                f"this deployment. Set {TEMPLATE_URL_ENV}."
            )
        return url

    # -- read ------------------------------------------------------
    def current(self) -> AWSConnection | None:
        return self.store.load()

    def summary(self) -> dict:
        """A render-ready snapshot for the Cloud panel (no secrets)."""
        conn = self.store.load()
        if conn is None:
            return {"status": "disconnected", "region": self.region}
        out = conn.to_public_dict(own=True)
        out["status"] = "connected" if conn.is_connected else conn.status
        if conn.is_connected:
            out["defaults"] = derive_cloud_defaults(
                account_id=conn.account_id, region=conn.region
            ).as_dict()
            out["access"] = "Temporary role"
        return out

    # -- connect flow --------------------------------------------
    def begin(self, *, region: str | None = None) -> ConnectStep:
        """Load or mint this user's connection and build the Quick Create URL.

        Reuses an existing record (stable ExternalId). A region is only applied
        to a *new* record.
        """
        principal = self.principal_arn()          # raise early if unset
        template_url = self.template_url()

        conn = self.store.load()
        if conn is None:
            conn = self.store.create(region=(region or self.region).strip())

        url = quick_create_url(
            template_url=template_url,
            external_id=conn.external_id,
            region=conn.region,
            principal_arn=principal,
            stack_name=DEFAULT_STACK_NAME,
        )
        return ConnectStep(
            connection=conn,
            setup_url=url,
            stack_name=DEFAULT_STACK_NAME,
            principal_arn=principal,
            external_id=conn.external_id,
        )

    def reconnect(self, *, region: str | None = None) -> ConnectStep:
        """Explicitly rotate: new connection record + new ExternalId."""
        self.store.delete()
        self.store.create(region=(region or self.region).strip())
        return self.begin(region=region)

    def verify(self, *, role_arn: str) -> VerificationResult:
        """Assume the role, confirm identity, persist the (non-secret) result."""
        conn = self.store.load()
        if conn is None:
            conn = self.store.create(region=self.region)
        result = verify_connection(conn, role_arn=role_arn, runner=self._runner)
        self.store.save(result.connection)
        return result

    def recheck(self) -> VerificationResult:
        """Re-verify an already-connected account with its stored role ARN."""
        conn = self.store.load()
        if conn is None or not conn.role_arn:
            raise OnboardingConfigError("No AWS connection to re-check.")
        result = verify_connection(conn, runner=self._runner)
        self.store.save(result.connection)
        return result

    def disconnect(self) -> None:
        """Remove this user's connection metadata. Nothing to revoke -- STS
        credentials are short-lived and were never stored."""
        self.store.delete()
