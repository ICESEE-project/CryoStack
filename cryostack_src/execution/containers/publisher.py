# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Execution
# Component   : Container Publisher
# File        : publisher.py
#
# Description :
#     Publishes container images to configured registries without coupling
#     container operations to a specific cloud provider.
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
Container image publishing services for CryoStack.
"""

from __future__ import annotations

from dataclasses import dataclass

from .docker import (
    inspect_image,
    push_image,
    tag_image,
)
from .models import (
    ContainerImage,
)


@dataclass
class PublishResult:
    """
    Result of publishing a container image.
    """

    success: bool

    source: str
    target: str

    tagged: bool
    pushed: bool

    messages: list[str]


def publish_image(
    image: ContainerImage,
) -> PublishResult:
    """
    Publish a local Docker image to its configured target registry.
    """

    target = image.publish_reference

    if not target:
        raise ValueError(
            "Container image has no target URI."
        )

    source = image.local_reference

    if not inspect_image(
        source
    ):
        raise RuntimeError(
            f"Local Docker image not found: {source}"
        )

    messages: list[str] = []

    if source != target:

        tag_image(
            source,
            target,
        )

        messages.append(
            f"Tagged {source} -> {target}"
        )

        tagged = True

    else:

        tagged = False

    push_image(
        target
    )

    messages.append(
        f"Pushed {target}"
    )

    return PublishResult(
        success=True,
        source=source,
        target=target,
        tagged=tagged,
        pushed=True,
        messages=messages,
    )