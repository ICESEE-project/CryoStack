# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Execution
# Component   : Container Runtime API
# File        : __init__.py
#
# Description :
#     Exposes shared container image and runtime services used by
#     CryoStack execution backends.
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
Public CryoStack container execution API.
"""

from .builder import (
    build,
)

from .docker import (
    DockerUnavailableError,
    docker_available,
)

from .images import (
    icepack_image,
    issm_image,
)

from .models import (
    ContainerImage,
)

from .publisher import (
    PublishResult,
    publish_image,
)


__all__ = [
    "ContainerImage",
    "PublishResult",
    "DockerUnavailableError",
    "build",
    "docker_available",
    "publish_image",
    "issm_image",
    "icepack_image",
]