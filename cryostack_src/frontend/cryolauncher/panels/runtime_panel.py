# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Frontend
# Component   : CryoLauncher Runtime Panel
# File        : runtime_panel.py
#
# Description :
#     Composes CryoLauncher runtime state and job controls while
#     preserving gateway-owned widgets and callbacks.
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
class RuntimePanel:
    container: W.VBox

    primary_actions: W.HBox


def build_runtime_panel(
    *,
    status_widget: W.Widget,
    run_button: W.Button,

    remote_terminate_button: W.Button,
    cloud_terminate_button: W.Button,
) -> RuntimePanel:

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
            Execution
          </div>

          <div
            style="
              margin-top:3px;
              font-size:11px;
              color:#66758d;
            "
          >
            Launch, monitor, inspect, and stop the current run.
          </div>
        </div>
        """
    )

    state_row = W.HBox(
        [
            W.HTML(
                """
                <div
                  style="
                    width:90px;
                    color:#66758d;
                    font-size:12px;
                  "
                >
                  State
                </div>
                """
            ),
            status_widget,
        ],
        layout=W.Layout(
            align_items="center",
            gap="8px",
        ),
    )

    terminate_controls = W.HBox(
        [
            remote_terminate_button,
            cloud_terminate_button,
        ],
        layout=W.Layout(
            gap="8px",
        ),
    )

    primary_actions = W.HBox(
        [
            run_button,
            terminate_controls,
        ],
        layout=W.Layout(
            gap="8px",
            flex_wrap="wrap",
            align_items="center",
        ),
    )

    container = W.VBox(
        [
            heading,
            state_row,
            primary_actions,
        ],
        layout=W.Layout(
            width="100%",
            gap="8px",
            border="1px solid #dfe6ef",
            padding="12px",
            margin="0",
        ),
    )

    return RuntimePanel(
        container=container,
        primary_actions=primary_actions,
    )