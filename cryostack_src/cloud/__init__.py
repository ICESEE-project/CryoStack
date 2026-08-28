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

from .drivers.aws import (
    AWSDriver,
    AWSConfig,
)

__all__ = [
    "CloudManager",
    "AWSDriver",
    "AWSConfig",
]
