# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Execution
# Component   : Remote Backend
# File        : remote.py
#
# Description :
#     Provides the CryoStack remote execution abstraction while preserving
#     the existing and tested remote HPC implementation during migration.
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
CryoStack remote execution backend.

This module provides the shared CryoStack execution interface for remote
HPC environments. During the strangler migration, it acts as a thin
compatibility layer around the existing remote execution implementation
in ``icesee_jupyter_book.core.remote_runner``.

The legacy remote execution path remains unchanged while CryoStack
gradually moves shared execution behavior into ``cryostack_src``.
"""

from __future__ import annotations

from .backend import (
    ExecutionBackend,
    ExecutionResult,
    ExecutionStatus,
)

from icesee_jupyter_book.core.remote_runner import (
    remote_cancel_job,
    remote_job_status,
)


class RemoteBackend(
    ExecutionBackend
):
    """
    CryoStack remote HPC execution backend.

    The backend currently wraps the existing remote execution
    implementation rather than replacing it.
    """

    name = "remote"

    def __init__(
        self,
        *,
        submitter=None,
    ) -> None:

        self._submitter = submitter

    def submit(
        self,
        **kwargs,
    ) -> ExecutionResult:

        if self._submitter is None:
            raise RuntimeError(
                "Remote submitter has not been "
                "configured."
            )

        result = self._submitter(
            **kwargs
        )

        if isinstance(
            result,
            dict,
        ):

            job_id = (
                result.get("jobid")
                or result.get("job_id")
            )

            remote_dir = result.get(
                "remote_dir"
            )

            messages = result.get(
                "messages",
                [],
            )

            log_path = result.get(
                "log_file"
            )

        else:

            job_id = (
                getattr(
                    result,
                    "jobid",
                    None,
                )
                or getattr(
                    result,
                    "job_id",
                    None,
                )
            )

            remote_dir = getattr(
                result,
                "remote_dir",
                None,
            )

            messages = getattr(
                result,
                "messages",
                [],
            )

            log_path = getattr(
                result,
                "log_file",
                None,
            )

        return ExecutionResult(
            success=True,
            backend=self.name,
            job_id=(
                str(job_id)
                if job_id is not None
                else None
            ),
            working_directory=remote_dir,
            output_directory=(
                f"{remote_dir}/outputs"
                if remote_dir
                else None
            ),
            log_path=log_path,
            messages=list(
                messages or []
            ),
        )

    def status(
        self,
        *,
        job_id: str,
        host: str,
        user: str,
        port: int,
        **kwargs,
    ) -> ExecutionStatus:

        result = remote_job_status(
            host,
            user,
            port,
            job_id,
        )

        raw_state = (
            result.get("state")
            or ""
        ).strip()

        return ExecutionStatus(
            state=self._normalize_state(
                raw_state
            ),
            raw_state=raw_state,
            exit_code=result.get(
                "exit_code"
            ),
            metadata={
                "source": result.get(
                    "source"
                ),
                "stdout": result.get(
                    "stdout",
                    "",
                ),
                "stderr": result.get(
                    "stderr",
                    "",
                ),
                "returncode": result.get(
                    "returncode"
                ),
            },
        )

    def logs(
        self,
        *,
        job_id: str,
        **kwargs,
    ) -> str:

        # The existing SSH/connector tail implementation
        # remains in the legacy gateway for now.
        raise NotImplementedError(
            "Remote logs still use the "
            "legacy gateway implementation."
        )

    def terminate(
        self,
        *,
        job_id: str,
        host: str,
        user: str,
        port: int,
        **kwargs,
    ) -> dict:

        return remote_cancel_job(
            host,
            user,
            port,
            job_id,
        )

    @staticmethod
    def _normalize_state(
        state: str,
    ) -> str:

        value = (
            state
            .strip()
            .upper()
        )

        if value in {
            "PENDING",
            "PD",
            "CONFIGURING",
            "CF",
        }:
            return "queued"

        if value in {
            "RUNNING",
            "R",
            "COMPLETING",
            "CG",
        }:
            return "running"

        if value in {
            "COMPLETED",
            "CD",
        }:
            return "completed"

        if value in {
            "FAILED",
            "F",
            "TIMEOUT",
            "TO",
            "NODE_FAIL",
            "NF",
            "OUT_OF_MEMORY",
            "OOM",
        }:
            return "failed"

        if value in {
            "CANCELLED",
            "CA",
        }:
            return "cancelled"

        return "unknown"