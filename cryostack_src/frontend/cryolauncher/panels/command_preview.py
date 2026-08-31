# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Frontend
# Component   : CryoLauncher Command Preview
# File        : command_preview.py
#
# Description :
#     Composes the command preview area used by CryoLauncher while
#     preserving the gateway-owned preview widget.
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
CryoLauncher command preview presentation.
"""

from __future__ import annotations

import ipywidgets as W


def build_command_preview_panel(
    command_widget: W.Widget,
) -> W.VBox:

    heading = W.HTML(
        """
        <div
          class="icesee-subtle"
          style="margin-top:12px;"
        >
          Command preview
        </div>
        """
    )

    return W.VBox(
        [
            heading,
            command_widget,
        ],
        layout=W.Layout(
            width="100%",
            gap="6px",
        ),
    )