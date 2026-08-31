# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Frontend
# Component   : CryoLauncher Output Workspace
# File        : output_workspace.py
#
# Description :
#     Composes CryoLauncher logs and result preview widgets into a
#     unified output workspace while preserving gateway-owned state
#     and callbacks.
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

from __future__ import annotations

from dataclasses import dataclass

import ipywidgets as W


@dataclass
class OutputWorkspace:
    container: W.VBox

    tabs: W.Tab

    logs_panel: W.VBox
    results_panel: W.VBox


def build_output_workspace(
    *,
    log_output: W.Output,
    results_output: W.Output,
    download_controls: W.Widget,
    log_controls: W.Widget | None = None,
) -> OutputWorkspace:

    log_children = [
        log_output,
    ]

    if log_controls is not None:
        log_children.append(
            log_controls
        )

    heading = W.HTML(
        """
        <div style="margin-bottom:4px;">
          <div
            style="
              font-size:13px;
              font-weight:700;
              color:#172033;
            "
          >
            Output
          </div>

          <div
            style="
              margin-top:3px;
              font-size:11px;
              color:#66758d;
            "
          >
            Monitor the current run and inspect generated results.
          </div>
        </div>
        """
    )

    logs_panel = W.VBox(
        log_children,
        layout=W.Layout(
            width="100%",
            min_height="0",
            gap="8px",
            overflow="hidden",
        ),
    )

    results_panel = W.VBox(
        [
            results_output,
            download_controls,
        ],
        layout=W.Layout(
            width="100%",
            min_height="0",
            gap="8px",
            overflow="hidden",
        ),
    )

    tabs = W.Tab(
        children=[
            logs_panel,
            results_panel,
        ],
        layout=W.Layout(
            width="100%",
            min_height="0",
        ),
    )

    tabs.set_title(0, "Run log")
    tabs.set_title(1, "Results")

    container = W.VBox(
        [
            heading,
            tabs,
        ],
        layout=W.Layout(
            width="100%",
            min_height="0",
            gap="8px",
            overflow="hidden",
        ),
    )

    logs_panel.add_class(
    "cryostack-output-tab"
    )

    results_panel.add_class(
        "cryostack-output-tab"
    )

    tabs.add_class(
        "cryostack-output-tabs"
    )

    container.add_class(
        "cryostack-output-workspace"
    )

    return OutputWorkspace(
        container=container,
        tabs=tabs,
        logs_panel=logs_panel,
        results_panel=results_panel,
    )