# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Frontend
# Component   : CryoLauncher Run Plan
# File        : run_plan.py
#
# Description :
#     Composes the execution summary and command preview into a single
#     CryoLauncher run-planning panel while preserving gateway-owned
#     widgets and update logic.
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
class RunPlanPanel:
    container: W.VBox
    summary_section: W.VBox
    command_section: W.VBox
    command_accordion: W.Accordion


def build_run_plan_panel(
    *,
    summary_widget: W.Widget,
    command_widget: W.Widget,
) -> RunPlanPanel:

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
            Run Plan
          </div>

          <div
            style="
              margin-top:3px;
              font-size:11px;
              color:#66758d;
            "
          >
            Review the selected workflow and generated execution command
            before launching the experiment.
          </div>
        </div>
        """
    )

    summary_section = W.VBox(
        [
            W.HTML(
                """
                <div
                  style="
                    font-size:11px;
                    font-weight:700;
                    color:#66758d;
                    margin-bottom:4px;
                  "
                >
                  Execution summary
                </div>
                """
            ),
            summary_widget,
        ],
        layout=W.Layout(
            width="100%",
            gap="4px",
        ),
    )

    command_section = W.VBox(
        [
            command_widget,
        ],
        layout=W.Layout(
            width="100%",
        ),
    )

    command_accordion = W.Accordion(
        children=[
            command_section,
        ],
        selected_index=None,
        layout=W.Layout(
            width="100%",
        ),
    )

    command_accordion.set_title(
        0,
        "Command preview",
    )

    container = W.VBox(
        [
            heading,
            summary_section,
            command_accordion,
        ],
        layout=W.Layout(
            width="100%",
            gap="8px",
            border="1px solid #dfe6ef",
            padding="12px",
        ),
    )

    return RunPlanPanel(
        container=container,
        summary_section=summary_section,
        command_section=command_section,
        command_accordion=command_accordion,
    )