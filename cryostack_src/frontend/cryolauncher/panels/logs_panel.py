# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Frontend
# Component   : CryoLauncher Run Log
# File        : logs_panel.py
#
# Description :
#     Composes the CryoLauncher run-log panel around the existing
#     gateway-owned output widget.
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
CryoLauncher run-log presentation.
"""

from __future__ import annotations

import ipywidgets as W


def build_logs_panel(
    log_output: W.Output,
) -> W.VBox:

    heading = W.HTML(
        """
        <div class="icesee-h">
          Run log
        </div>
        """
    )

    return W.VBox(
        [
            heading,
            log_output,
        ],
        layout=W.Layout(
            width="100%",
            gap="8px",
        ),
    )