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

from .config import (
    CloudRunConfig,
    DEFAULT_CLOUD_REGION,
    resolve_cloud_config,
    validate_cloud_config,
)
from .manager import CloudManager
from .preflight import assert_cloud_run_allowed, cloud_run_preflight
from .smoke import SmokeReport, run_infrastructure_smoke_test
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
    BatchSubmission,
    CloudRunStaging,
    CloudStagingError,
    CloudSubmitError,
    stage_run_inputs,
    submit_batch_job,
)

__all__ = [
    "CloudManager",
    "AWSDriver",
    "AWSConfig",
    "CloudRunConfig",
    "DEFAULT_CLOUD_REGION",
    "resolve_cloud_config",
    "validate_cloud_config",
    "SUPPORTED_CLOUD_MODELS",
    "CloudRuntimeError",
    "build_cloud_runner",
    "build_run_descriptor",
    "is_supported_cloud_model",
    "cloud_run_preflight",
    "assert_cloud_run_allowed",
    "SmokeReport",
    "run_infrastructure_smoke_test",
    "CloudRunStaging",
    "CloudStagingError",
    "stage_run_inputs",
    "BatchSubmission",
    "CloudSubmitError",
    "submit_batch_job",
]
