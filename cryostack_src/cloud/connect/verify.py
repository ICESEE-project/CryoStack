# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Account Connection
# File        : verify.py
#
# Description :
#     Verify an AWS connection by assuming its role and reading the caller
#     identity, then fold the result back into the connection record.
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
Connection verification.

:func:`verify_connection` is the single call the UI makes after the user
reports "I created the role". It never raises for an ordinary failure -- it
returns the connection in ``error`` status with a short, user-facing reason --
so the caller only has to persist whatever comes back.
"""

from __future__ import annotations

from dataclasses import dataclass

from .assume_role import DEFAULT_SESSION_SECONDS, AssumeRoleError, assume_role
from .context import AWSExecutionContext
from .models import AWSConnection, is_valid_role_arn


@dataclass
class VerificationResult:
    connection: AWSConnection
    #: present only on success; never persisted
    context: AWSExecutionContext | None = None

    @property
    def ok(self) -> bool:
        return self.connection.is_connected


def verify_connection(
    connection: AWSConnection,
    *,
    role_arn: str | None = None,
    duration_seconds: int = DEFAULT_SESSION_SECONDS,
    runner=None,
) -> VerificationResult:
    """Assume the connection's role and confirm the session.

    ``role_arn`` may be supplied here (the user pasting it in the verify step)
    -- it is folded into the record. Returns a :class:`VerificationResult`
    whose ``connection`` is always safe to persist.
    """
    if role_arn is not None:
        connection = connection.with_role(role_arn)

    if not is_valid_role_arn(connection.role_arn):
        return VerificationResult(
            connection.mark_error(
                "Enter the CryoStack access role ARN, e.g. "
                "arn:aws:iam::<account-id>:role/CryoStackExecutionRole"
            )
        )
    if not connection.external_id:
        return VerificationResult(
            connection.mark_error("This connection has no ExternalId; reconnect.")
        )

    try:
        context = assume_role(
            role_arn=connection.role_arn,
            external_id=connection.external_id,
            region=connection.region,
            duration_seconds=duration_seconds,
            runner=runner,
        )
    except AssumeRoleError as err:
        return VerificationResult(connection.mark_error(str(err)))

    return VerificationResult(
        connection.mark_connected(account_id=context.account_id),
        context=context,
    )
