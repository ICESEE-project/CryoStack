# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Frontend
# Component   : CryoLauncher Execution Summary
# File        : execution_summary.py
#
# Description :
#     Composes the execution summary panel used by CryoLauncher while
#     preserving the existing gateway-owned summary widget.
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
CryoLauncher execution summary presentation.
"""

from __future__ import annotations

import ipywidgets as W


def build_execution_summary_panel(
    summary_widget: W.Widget,
) -> W.VBox:
    """
    Wrap the existing execution summary widget.

    The gateway continues to own and update ``summary_widget``.
    """

    heading = W.HTML(
        """
        <div
          class="icesee-subtle"
          style="margin-top:12px;"
        >
          Execution summary
        </div>
        """
    )

    return W.VBox(
        [
            heading,
            summary_widget,
        ],
        layout=W.Layout(
            width="100%",
            gap="6px",
        ),
    )