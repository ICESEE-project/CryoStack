# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Frontend
# Component   : CryoLauncher Run Settings
# File        : run_settings.py
#
# Description :
#     Composes the existing CryoLauncher configuration rows into the
#     Run Settings panel while preserving gateway-owned widget state.
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
CryoLauncher Run Settings panel.
"""

from __future__ import annotations

import ipywidgets as W


def build_run_settings_panel(
    *,
    configuration_rows: list[W.Widget],
    remote_panel: W.Widget,
    cloud_panel: W.Widget,
    run_plan: W.Widget,
    workspace_rows: list[W.Widget] | None = None,
) -> W.VBox:
    """Compose Run Settings top-to-bottom in execution-environment-first
    order: identity/mode rows -> Remote/Cloud connection -> FILE/WORKSPACE
    operations (editor, datasets) + model/run configuration
    (``workspace_rows``) -> Review/Launch (``run_plan``).

    The principle: establish the execution environment first, THEN expose
    operations against it -- a caller must never place file/editor/upload/
    download controls in ``configuration_rows`` (before ``remote_panel``/
    ``cloud_panel``); ``workspace_rows`` (optional -- a caller with no
    separate file/workspace section, e.g. ICESEE, omits it) is where those
    belong. Reuses whatever widget instances the caller passes -- pure
    layout/container composition, no widget creation here.
    """

    children: list[W.Widget] = [
        W.HTML(
            "<div class='icesee-h'>Run settings</div>"
        ),
    ]

    children.extend(
        configuration_rows
    )

    children.extend(
        [
            remote_panel,
            cloud_panel,
        ]
    )

    children.extend(
        workspace_rows or []
    )

    children.append(run_plan)

    return W.VBox(
        children,
        layout=W.Layout(
            width="100%",
            gap="10px",
        ),
    )