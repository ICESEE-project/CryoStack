# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Frontend
# Component   : CryoLauncher Runtime Controls
# File        : status_panel.py
#
# Description :
#     Composes CryoLauncher submission, status, remote, and cloud runtime
#     controls without owning execution callbacks.
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
CryoLauncher runtime-control presentation.

Buttons remain owned and wired by the gateway during the strangler
migration.
"""

from __future__ import annotations

from dataclasses import dataclass

import ipywidgets as W


@dataclass
class StatusPanel:
    container: W.VBox
    remote_actions: W.HBox
    cloud_actions: W.HBox


def build_status_panel(
    *,
    run_button: W.Button,
    clear_button: W.Button,
    status_widget: W.Widget,

    remote_connect_button: W.Button,
    remote_status_button: W.Button,
    remote_logs_button: W.Widget,
    remote_terminate_button: W.Button,

    cloud_status_button: W.Button,
    cloud_logs_button: W.Button,
    cloud_terminate_button: W.Button,
) -> StatusPanel:

    primary_actions = W.HBox(
        [
            run_button,
            clear_button,
            status_widget,
        ],
        layout=W.Layout(
            gap="12px",
            align_items="center",
            flex_wrap="wrap",
        ),
    )

    primary_actions.add_class(
        "icesee-actions"
    )

    remote_actions = W.HBox(
        [
            remote_connect_button,
            remote_status_button,
            remote_logs_button,
            remote_terminate_button,
        ],
        layout=W.Layout(
            gap="10px",
            flex_wrap="wrap",
        ),
    )

    cloud_actions = W.HBox(
        [
            cloud_status_button,
            cloud_logs_button,
            cloud_terminate_button,
        ],
        layout=W.Layout(
            gap="10px",
            flex_wrap="wrap",
        ),
    )

    container = W.VBox(
        [
            W.HTML(
                "<div class='icesee-h'>Status</div>"
            ),

            primary_actions,

            W.HTML(
                """
                <div
                  class="icesee-subtle"
                  style="margin-top:10px;"
                >
                  Remote job controls
                </div>
                """
            ),

            remote_actions,

            W.HTML(
                """
                <div
                  class="icesee-subtle"
                  style="margin-top:10px;"
                >
                  Cloud job controls
                </div>
                """
            ),

            cloud_actions,
        ],
        layout=W.Layout(
            width="100%",
            gap="4px",
        ),
    )

    container.add_class(
        "icesee-card"
    )

    return StatusPanel(
        container=container,
        remote_actions=remote_actions,
        cloud_actions=cloud_actions,
    )