# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Models
# File        : models.py
#
# Description :
#     Defines AWS-specific connection models used by CryoStack cloud
#     services.
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
AWS-specific cloud models for CryoStack.
"""

from __future__ import annotations

from dataclasses import dataclass, field

@dataclass
class AWSConfig:
    """
    AWS connection configuration.

    Two credential sources are supported, and exactly one is used per call:

    * **developer / operator mode** -- ambient AWS CLI credentials, optionally
      selected by a named ``profile``;
    * **end-user assumed-role mode** -- ``credentials`` carries the temporary
      ``AWS_ACCESS_KEY_ID`` / ``AWS_SECRET_ACCESS_KEY`` / ``AWS_SESSION_TOKEN``
      from an ``sts:AssumeRole`` call (see :mod:`cryostack_src.cloud.connect`).
      When present it wins and ``profile`` is ignored.

    ``credentials`` is ``repr``-suppressed and must never be persisted or
    logged -- it holds short-lived secret material for one operation only.
    """

    region: str = "us-east-2"
    profile: str | None = None
    credentials: dict[str, str] | None = field(default=None, repr=False)

@dataclass
class AWSCapabilities:
    """
    Combined AWS capability state discovered by CryoStack.
    """

    account_id: str | None
    region: str

    authenticated: bool

    storage_ready: bool
    network_ready: bool
    iam_ready: bool
    registry_ready: bool
    batch_ready: bool

    missing: list[str] = field(
        default_factory=list
    )

    messages: list[str] = field(
        default_factory=list
    )