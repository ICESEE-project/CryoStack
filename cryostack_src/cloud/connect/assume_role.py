# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Account Connection
# File        : assume_role.py
#
# Description :
#     Cross-account STS AssumeRole + caller-identity verification, producing
#     a short-lived AWSExecutionContext.
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
STS ``AssumeRole`` for the end-user "bring your AWS account" path.

The CryoStack principal (ambient credentials in dev/operator mode; the
CryoStack service role in the deployed setup) assumes the user-created
cross-account role, presenting the connection's ``ExternalId``. AWS returns
*temporary* credentials, which we immediately use -- via
``sts:GetCallerIdentity`` -- to:

1. discover the connected account id,
2. confirm the session is valid,
3. confirm the returned account matches the account embedded in the role ARN
   (**fail closed on mismatch**).

Nothing here is persisted. The caller receives an
:class:`AWSExecutionContext` whose lifetime is the operation.
"""

from __future__ import annotations

import json
import secrets
import subprocess

from .context import AWSExecutionContext
from .models import account_id_from_role_arn, is_valid_role_arn
from .redaction import redact_aws_secrets

#: short-lived by design -- long enough for one prepare/verify, not a session
DEFAULT_SESSION_SECONDS = 900
_MIN_SESSION_SECONDS = 900
_MAX_SESSION_SECONDS = 3600


class AssumeRoleError(RuntimeError):
    """AssumeRole failed, returned an unusable payload, or failed a safety check."""


# ---------------------------------------------------------------------------
# default runner: the real `aws` CLI
# ---------------------------------------------------------------------------
def _default_runner(args: list[str], *, env: dict[str, str] | None = None) -> dict:
    """Run ``aws <args> --output json`` and return the parsed payload.

    ``env`` (when given) fully replaces the subprocess environment's AWS
    credential source -- used to call ``get-caller-identity`` as the freshly
    assumed role.
    """
    import os

    proc_env = None
    if env is not None:
        proc_env = {
            k: v
            for k, v in os.environ.items()
            if k
            not in (
                "AWS_PROFILE",
                "AWS_ACCESS_KEY_ID",
                "AWS_SECRET_ACCESS_KEY",
                "AWS_SESSION_TOKEN",
                "AWS_SECURITY_TOKEN",
            )
        }
        proc_env.update(env)

    completed = subprocess.run(
        ["aws", *args, "--output", "json"],
        capture_output=True,
        text=True,
        env=proc_env,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        # never echo an env dump / arg list that might carry a token
        raise AssumeRoleError(_sanitise_cli_error(detail))
    try:
        return json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as err:
        raise AssumeRoleError(f"Unparseable AWS response: {err}") from None


def _sanitise_cli_error(detail: str) -> str:
    if not detail:
        return "AWS STS call failed."
    lowered = detail.lower()
    if "accessdenied" in lowered or "not authorized to perform: sts:assumerole" in lowered:
        return (
            "AWS denied the role assumption. Check that the CryoStack access "
            "role exists and its trust policy allows this CryoStack principal "
            "with the matching ExternalId."
        )
    if "expired" in lowered:
        return "The temporary AWS session expired before the check completed."
    return detail.splitlines()[0][:300]


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------
def assume_role(
    *,
    role_arn: str,
    external_id: str,
    region: str,
    duration_seconds: int = DEFAULT_SESSION_SECONDS,
    session_name: str | None = None,
    runner=None,
) -> AWSExecutionContext:
    """Assume ``role_arn`` with ``external_id`` and return a live context.

    Raises :class:`AssumeRoleError` on any failure, including an account
    mismatch between the returned identity and the role ARN.
    """
    role_arn = (role_arn or "").strip()
    external_id = (external_id or "").strip()
    region = (region or "").strip()

    if not is_valid_role_arn(role_arn):
        raise AssumeRoleError(
            "Role ARN must look like "
            "arn:aws:iam::<account-id>:role/CryoStackExecutionRole"
        )
    if not external_id:
        raise AssumeRoleError("An ExternalId is required to assume the role.")
    if not region:
        raise AssumeRoleError("A region is required.")

    duration = max(_MIN_SESSION_SECONDS, min(_MAX_SESSION_SECONDS, int(duration_seconds)))
    session_name = session_name or f"cryostack-{secrets.token_hex(4)}"
    run = runner or _default_runner

    payload = run(
        [
            "sts",
            "assume-role",
            "--role-arn",
            role_arn,
            "--role-session-name",
            session_name,
            "--external-id",
            external_id,
            "--duration-seconds",
            str(duration),
            "--region",
            region,
        ]
    )

    creds = (payload or {}).get("Credentials") or {}
    env = {
        "AWS_ACCESS_KEY_ID": creds.get("AccessKeyId", ""),
        "AWS_SECRET_ACCESS_KEY": creds.get("SecretAccessKey", ""),
        "AWS_SESSION_TOKEN": creds.get("SessionToken", ""),
    }
    if not all(env.values()):
        raise AssumeRoleError(
            "AssumeRole did not return usable temporary credentials "
            f"(payload keys: {sorted(redact_aws_secrets(payload or {}))})"
        )

    identity = run(["sts", "get-caller-identity", "--region", region], env=env)
    account_id = str((identity or {}).get("Account") or "").strip()
    if not account_id:
        raise AssumeRoleError("Could not read the account id from the assumed session.")

    role_account = account_id_from_role_arn(role_arn)
    if role_account and account_id != role_account:
        # fail closed: the session is not for the account we were told about
        raise AssumeRoleError(
            "Account mismatch: the assumed session belongs to a different "
            "AWS account than the role ARN. Connection not verified."
        )

    return AWSExecutionContext(
        account_id=account_id,
        region=region,
        role_arn=role_arn,
        external_id=external_id,
        expiration=str(creds.get("Expiration") or ""),
        _credentials=env,
    )
