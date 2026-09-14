# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Account Connection
# File        : principal.py
#
# Description :
#     Deployment-configured identity of the CryoStack AWS principal that a
#     user's cross-account role must trust.
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
The CryoStack AWS principal ARN.

The user-created ``CryoStackExecutionRole`` trusts *this* ARN to
``sts:AssumeRole``. It is a per-deployment fact -- the AWS identity CryoStack
runs as -- and is **never** hardcoded in product code (a personal or root ARN
must not ship). It comes from deployment configuration:

    CRYOSTACK_AWS_PRINCIPAL_ARN=arn:aws:iam::<cryostack-account>:role/<name>

When it is not configured, onboarding fails loudly and early rather than
generating a broken CloudFormation link.
"""

from __future__ import annotations

import os
import re

#: deployment env var carrying the CryoStack principal ARN
PRINCIPAL_ENV = "CRYOSTACK_AWS_PRINCIPAL_ARN"

_PRINCIPAL_ARN_RE = re.compile(
    r"\Aarn:aws[a-z-]*:(iam|sts)::\d{12}:"
    r"(root|(user|role|assumed-role)/[\w+=,.@/-]+)\Z"
)


class PrincipalNotConfiguredError(RuntimeError):
    """The deployment has not set the CryoStack AWS principal ARN."""


def is_valid_principal_arn(arn: str) -> bool:
    return bool(_PRINCIPAL_ARN_RE.match((arn or "").strip()))


def cryostack_principal_arn(*, env: "dict[str, str] | None" = None) -> str:
    """Return the configured CryoStack principal ARN or raise clearly."""
    source = os.environ if env is None else env
    raw = (source.get(PRINCIPAL_ENV) or "").strip()
    if not raw:
        raise PrincipalNotConfiguredError(
            "CryoStack's AWS principal is not configured on this deployment. "
            f"Set {PRINCIPAL_ENV} to the CryoStack IAM role ARN "
            "(arn:aws:iam::<cryostack-account>:role/<name>) before connecting "
            "an AWS account."
        )
    if not is_valid_principal_arn(raw):
        raise PrincipalNotConfiguredError(
            f"{PRINCIPAL_ENV} is set but is not a valid IAM principal ARN: "
            f"{raw!r}"
        )
    return raw
