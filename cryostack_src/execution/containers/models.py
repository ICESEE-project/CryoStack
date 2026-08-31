# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Execution
# Component   : Container Models
# File        : models.py
#
# Description :
#     Defines provider-independent container image metadata used by
#     CryoStack execution backends and container runtimes.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-08-25
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""
Container image models used by CryoStack execution services.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ContainerImage:
    """
    Description of a container image managed by CryoStack.
    """

    name: str
    tag: str = "latest"

    dockerfile: Path | None = None
    context: Path | None = None

    source_uri: str | None = None
    target_uri: str | None = None

    runtime: str = "docker"

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def local_reference(
        self,
    ) -> str:
        """
        Return the local image reference.
        """

        return (
            f"{self.name}:{self.tag}"
        )

    @property
    def publish_reference(
        self,
    ) -> str | None:
        """
        Return the destination image reference.
        """

        if not self.target_uri:
            return None

        if ":" in self.target_uri.rsplit(
            "/",
            1,
        )[-1]:
            return self.target_uri

        return (
            f"{self.target_uri}:{self.tag}"
        )