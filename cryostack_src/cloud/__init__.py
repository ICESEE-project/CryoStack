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
#     Exposes cloud-provider services used by the CryoStack execution
#     architecture.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-08-20
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""
Public API for CryoStack cloud services.
"""

from .aws_batch import (
    AWSConfig,
    batch_logs,
    batch_status,
    describe_job,
    terminate_batch_job,
)

from .bootstrap import (
    AWSBootstrapResult,
    get_account_identity,
    inspect_aws_environment,
)

__all__ = [
    "AWSConfig",
    "batch_logs",
    "batch_status",
    "describe_job",
    "terminate_batch_job",
    "AWSBootstrapResult",
    "get_account_identity",
    "inspect_aws_environment",
]