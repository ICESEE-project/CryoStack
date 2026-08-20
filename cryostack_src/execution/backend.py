# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Execution
# Component   : Backend Interface
# File        : backend.py
#
# Description :
#     Defines backend-independent execution result, status, and backend
#     interfaces shared across CryoStack execution environments.
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
CryoStack execution backend interfaces.

This module defines the common execution contract used by CryoStack
execution backends. Local, remote HPC, cloud, and container execution
implementations should expose their operations through these shared
interfaces so that frontend applications do not depend directly on
backend-specific execution details.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExecutionResult:
    """
    Backend-independent result returned after a job is submitted.
    """

    success: bool
    backend: str

    job_id: str | None = None

    working_directory: str | None = None
    output_directory: str | None = None
    log_path: str | None = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    messages: list[str] = field(
        default_factory=list
    )


@dataclass
class ExecutionStatus:
    """
    Backend-independent execution status.
    """

    state: str

    raw_state: str | None = None
    reason: str = ""

    exit_code: str | int | None = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )


class ExecutionBackend(ABC):
    """
    Common interface implemented by CryoStack execution backends.

    Existing execution implementations may initially be wrapped rather
    than rewritten as part of the CryoStack strangler migration.
    """

    name: str = "unknown"

    @abstractmethod
    def submit(
        self,
        **kwargs,
    ) -> ExecutionResult:
        raise NotImplementedError

    @abstractmethod
    def status(
        self,
        *,
        job_id: str,
        **kwargs,
    ) -> ExecutionStatus:
        raise NotImplementedError

    @abstractmethod
    def logs(
        self,
        *,
        job_id: str,
        **kwargs,
    ) -> str:
        raise NotImplementedError

    @abstractmethod
    def terminate(
        self,
        *,
        job_id: str,
        **kwargs,
    ) -> dict:
        raise NotImplementedError