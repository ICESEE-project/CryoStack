# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Execution
# Component   : Execution Manager
# File        : manager.py
#
# Description :
#     Registers, resolves, and exposes CryoStack execution backends through
#     a common interface independent of frontend applications.
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
CryoStack execution manager.

The execution manager provides a shared backend registry used to resolve
execution environments such as remote HPC and cloud backends.

Frontend applications should eventually interact with execution
backends through this manager rather than importing backend-specific
runner implementations directly.
"""

from __future__ import annotations

from .backend import ExecutionBackend
from .cloud import CloudBackend
from .remote import RemoteBackend


class ExecutionManager:
    """
    Register and resolve CryoStack execution backends.
    """

    def __init__(
        self,
    ) -> None:

        self._backends: dict[
            str,
            ExecutionBackend,
        ] = {}

    def register(
        self,
        backend: ExecutionBackend,
    ) -> None:

        name = (
            backend.name
            .strip()
            .lower()
        )

        if not name:
            raise ValueError(
                "Execution backend requires a name."
            )

        self._backends[
            name
        ] = backend

    def get(
        self,
        name: str,
    ) -> ExecutionBackend:

        key = (
            name
            .strip()
            .lower()
        )

        backend = self._backends.get(
            key
        )

        if backend is None:
            raise ValueError(
                f"Unknown execution backend: {name}"
            )

        return backend

    def available(
        self,
    ) -> list[str]:

        return sorted(
            self._backends
        )


def create_execution_manager(
    *,
    remote_submitter=None,
    cloud_submitter=None,
) -> ExecutionManager:
    """
    Create the default CryoStack execution manager.

    Legacy execution functions are injected as submitters during the
    strangler migration so that tested implementations remain unchanged.
    """

    manager = ExecutionManager()

    manager.register(
        RemoteBackend(
            submitter=remote_submitter,
        )
    )

    manager.register(
        CloudBackend(
            submitter=cloud_submitter,
        )
    )

    return manager