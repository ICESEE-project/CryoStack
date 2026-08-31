# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : Shared Cloud Models
# File        : models.py
#
# Description :
#     Defines provider-independent cloud account and capability models used
#     across CryoStack cloud execution services.
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
Provider-independent cloud models used by CryoStack.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CloudAccount:
    """
    Cloud account connection state.
    """

    provider: str
    region: str

    account_id: str | None = None

    connected: bool = False
    authenticated: bool = False

    identity: str | None = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )


@dataclass
class CloudCapabilities:
    """
    Provider-independent cloud capability summary.
    """

    provider: str
    region: str

    account: CloudAccount

    storage_ready: bool = False
    compute_ready: bool = False
    registry_ready: bool = False

    messages: list[str] = field(
        default_factory=list
    )