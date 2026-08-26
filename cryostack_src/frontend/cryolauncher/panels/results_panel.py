# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Frontend
# Component   : CryoLauncher Results
# File        : results_panel.py
#
# Description :
#     Composes CryoLauncher result preview and download controls around
#     widgets that remain owned by the legacy gateway during migration.
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
CryoLauncher result presentation.
"""

from __future__ import annotations

import ipywidgets as W


def build_results_panel(
    *,
    results_output: W.Output,
    download_controls: W.Widget,
) -> W.VBox:

    heading = W.HTML(
        """
        <div
          class="icesee-h"
          style="margin-top:16px;"
        >
          Results preview
        </div>
        """
    )

    return W.VBox(
        [
            heading,
            results_output,
            download_controls,
        ],
        layout=W.Layout(
            width="100%",
            gap="8px",
        ),
    )