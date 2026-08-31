# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Execution
# Component   : Execution Package
# File        : __init__.py
#
# Description :
#     Defines the CryoStack execution namespace while keeping individual
#     execution backends and runtimes independently importable.
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
CryoStack execution services.

Execution backends and runtimes are intentionally imported explicitly
from their respective modules. This avoids loading remote, cloud, or
container dependencies when they are not required.
"""

__all__ = [
    "backend",
    "manager",
    "remote",
    "cloud",
    "containers",
]