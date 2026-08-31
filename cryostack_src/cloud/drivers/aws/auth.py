# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Authentication
# File        : auth.py
#
# Description :
#     Provides AWS credential detection and account identity discovery for
#     CryoStack cloud connections.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-08-24
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""
AWS authentication services for CryoStack.

This module isolates AWS identity and credential handling from storage,
networking, Batch execution, and frontend logic.
"""

from __future__ import annotations

import json
import subprocess

from ...models import CloudAccount
from .models import AWSConfig


class AWSCredentialsError(
    RuntimeError
):
    """
    Raised when CryoStack cannot find usable AWS credentials.
    """


def aws_command(
    config: AWSConfig,
) -> list[str]:

    command = ["aws"]

    if config.profile:
        command.extend([
            "--profile",
            config.profile,
        ])

    if config.region:
        command.extend([
            "--region",
            config.region,
        ])

    return command


def run_aws(
    config: AWSConfig,
    arguments: list[str],
) -> tuple[int, str, str]:

    process = subprocess.run(
        aws_command(config) + arguments,
        capture_output=True,
        text=True,
    )

    return (
        process.returncode,
        process.stdout,
        process.stderr,
    )


def get_account_identity(
    config: AWSConfig,
) -> dict:

    code, stdout, stderr = run_aws(
        config,
        [
            "sts",
            "get-caller-identity",
        ],
    )

    if code != 0:

        error_text = (
            stderr
            or stdout
            or ""
        )

        if (
            "NoCredentials"
            in error_text
            or "Unable to locate credentials"
            in error_text
        ):
            raise AWSCredentialsError(
                "AWS credentials are not configured."
            )

        raise RuntimeError(
            error_text.strip()
            or "AWS identity lookup failed."
        )

    return json.loads(
        stdout or "{}"
    )


def discover_account(
    config: AWSConfig,
) -> CloudAccount:
    """
    Return the current AWS connection state without crashing when the
    account has not yet been connected.
    """

    try:
        identity = get_account_identity(
            config
        )

    except AWSCredentialsError:

        return CloudAccount(
            provider="aws",
            region=config.region,
            connected=False,
            authenticated=False,
        )

    account_id = identity.get(
        "Account"
    )

    arn = identity.get(
        "Arn"
    )

    return CloudAccount(
        provider="aws",
        region=config.region,
        account_id=account_id,
        connected=True,
        authenticated=True,
        identity=arn,
        metadata={
            "user_id": identity.get(
                "UserId"
            ),
        },
    )