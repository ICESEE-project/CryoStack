# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Frontend
# Component   : Shared Status
# File        : status.py
#
# Description :
#     Provides shared visual status indicators for CryoStack frontends.
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
Shared frontend status helpers.

These functions translate application state into presentation markup.
They intentionally contain no backend behavior.
"""

from __future__ import annotations

from html import escape


_STATUS_ALIASES = {
    "done": "success",
    "complete": "success",
    "completed": "success",

    "pending": "warning",
    "submitted": "running",

    "fail": "error",
    "failure": "error",
}


_STATUS_LABELS = {
    "idle": "Idle",
    "running": "Running",
    "ready": "Ready",
    "success": "Ready",
    "warning": "Attention",
    "error": "Error",
    "failed": "Failed",
}


def normalize_status(
    state: str | None,
) -> str:
    """
    Normalize a runtime state for frontend presentation.
    """

    value = (
        state
        or "idle"
    ).strip().lower()

    return _STATUS_ALIASES.get(
        value,
        value,
    )


def status_badge(
    state: str | None,
    *,
    label: str | None = None,
) -> str:
    """
    Return CryoStack status badge HTML.
    """

    normalized = normalize_status(
        state
    )

    display_label = (
        label
        or _STATUS_LABELS.get(
            normalized,
            normalized.replace(
                "_",
                " ",
            ).title(),
        )
    )

    return f"""
    <span
      class="
        cryostack-status
        cryostack-status-{escape(normalized)}
      "
    >
      {escape(display_label)}
    </span>
    """