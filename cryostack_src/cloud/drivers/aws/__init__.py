# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Driver
# File        : __init__.py
#
# Description :
#     Public AWS cloud driver API.
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
AWS cloud provider implementation.
"""

from .batch_config import FargateJobConfig
from .batch_provision import AWSBatchProvisionResult, ensure_batch_resources
from .driver import AWSDriver
from .models import AWSConfig, AWSCapabilities
from .registry_delivery import (
    ECRImageDelivery,
    RegistryDeliveryError,
    buildx_imagetools_copier,
    ensure_ecr_lifecycle_policy,
    mirror_tested_image,
)
from .staging import CloudRunStaging, CloudStagingError, stage_run_inputs
from .submit import (
    BatchSubmission,
    CloudSubmitError,
    build_container_overrides,
    build_submit_job_args,
    sanitize_job_name,
    submit_batch_job,
)

__all__ = [
    "AWSDriver",
    "AWSConfig",
    "AWSCapabilities",
    "AWSBatchProvisionResult",
    "FargateJobConfig",
    "ensure_batch_resources",
    "ECRImageDelivery",
    "RegistryDeliveryError",
    "mirror_tested_image",
    "ensure_ecr_lifecycle_policy",
    "buildx_imagetools_copier",
    "CloudRunStaging",
    "CloudStagingError",
    "stage_run_inputs",
    "BatchSubmission",
    "CloudSubmitError",
    "build_container_overrides",
    "build_submit_job_args",
    "sanitize_job_name",
    "submit_batch_job",
]