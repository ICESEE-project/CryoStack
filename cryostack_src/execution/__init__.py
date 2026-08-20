# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Execution
# Component   : Public Execution API
# File        : __init__.py
#
# Description :
#     Exposes the public CryoStack execution interfaces, backend registry,
#     and currently supported execution backends.
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
Public API for CryoStack execution services.

Application frontends should prefer imports from this module rather
than depending directly on individual backend implementation files.
"""

from .backend import (
    ExecutionBackend,
    ExecutionResult,
    ExecutionStatus,
)

from .manager import (
    ExecutionManager,
    create_execution_manager,
)

from .remote import (
    RemoteBackend,
)

from .cloud import (
    CloudBackend,
)


__all__ = [
    "ExecutionBackend",
    "ExecutionResult",
    "ExecutionStatus",
    "ExecutionManager",
    "create_execution_manager",
    "RemoteBackend",
    "CloudBackend",
]