# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Frontend
# Component   : CryoLauncher Runtime State
# File        : runtime_state.py
#
# Description :
#     Stores transient CryoLauncher execution, connector-session, and
#     automatic log-tail state during the frontend migration.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-08-25
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""
CryoLauncher runtime state.

This module owns transient frontend runtime state while preserving the
dictionary interfaces currently used by the legacy gateway.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RuntimeState:
    status: dict = field(
        default_factory=lambda: {
            "mode": "idle",
            "remote_dir": None,
            "jobid": None,
            "batch_job_id": None,
            "cloud_run": None,
            "selected_example_path": None,
        }
    )

    session: dict = field(
        default_factory=lambda: {
            "id": None,
            "ws_url": None,
        }
    )

    auto_tail: dict = field(
        default_factory=lambda: {
            "task": None,
            "running": False,
        }
    )


def build_runtime_state() -> RuntimeState:
    return RuntimeState()


def status_html(
    state: str,
) -> str:

    cls = {
        "idle": "icesee-idle",
        "running": "icesee-running",
        "done": "icesee-done",
        "fail": "icesee-fail",
    }[state]

    label = {
        "idle": "Idle",
        "running": "Running…",
        "done": "Done",
        "fail": "Failed",
    }[state]

    return (
        f"<span class='icesee-status {cls}'>"
        f"{label}</span>"
    )