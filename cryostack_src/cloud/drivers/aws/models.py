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

    Named CLI profiles are supported during development. Future
    CryoStack account connections may use temporary credentials
    or assumed IAM roles without changing the higher-level cloud API.
    """

    region: str = "us-east-2"
    profile: str | None = None

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