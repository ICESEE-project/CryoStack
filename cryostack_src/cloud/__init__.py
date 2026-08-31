# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : Public Cloud API
# File        : __init__.py
#
# Description :
#     Exposes provider-independent cloud services used across CryoStack.
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
Public CryoStack cloud API.
"""

from .manager import CloudManager
from .preflight import assert_cloud_run_allowed, cloud_run_preflight
from .runtime import (
    SUPPORTED_CLOUD_MODELS,
    CloudRuntimeError,
    build_cloud_runner,
    build_run_descriptor,
    is_supported_cloud_model,
)

from .drivers.aws import (
    AWSConfig,
    AWSDriver,
    CloudRunStaging,
    CloudStagingError,
    stage_run_inputs,
)

__all__ = [
    "CloudManager",
    "AWSDriver",
    "AWSConfig",
    "SUPPORTED_CLOUD_MODELS",
    "CloudRuntimeError",
    "build_cloud_runner",
    "build_run_descriptor",
    "is_supported_cloud_model",
    "cloud_run_preflight",
    "assert_cloud_run_allowed",
    "CloudRunStaging",
    "CloudStagingError",
    "stage_run_inputs",
]
