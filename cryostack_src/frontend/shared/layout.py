# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Frontend
# Component   : Shared Layout
# File        : layout.py
#
# Description :
#     Provides reusable layout primitives for CryoStack application
#     frontends built with ipywidgets.
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
Reusable CryoStack frontend layout primitives.
"""

from __future__ import annotations

import ipywidgets as W


def page(
    *children,
    gap: str = "16px",
) -> W.VBox:

    return W.VBox(
        list(children),
        layout=W.Layout(
            width="100%",
            gap=gap,
        ),
    )


def section(
    *children,
    gap: str = "10px",
) -> W.VBox:

    return W.VBox(
        list(children),
        layout=W.Layout(
            width="100%",
            gap=gap,
        ),
    )


def row(
    *children,
    gap: str = "10px",
    align_items: str = "center",
    justify_content: str = "flex-start",
    wrap: str = "wrap",
) -> W.HBox:

    return W.HBox(
        list(children),
        layout=W.Layout(
            width="100%",
            gap=gap,
            align_items=align_items,
            justify_content=justify_content,
            flex_flow=f"row {wrap}",
        ),
    )


def two_column(
    left,
    right,
    *,
    left_width: str = "50%",
    right_width: str = "50%",
    gap: str = "16px",
) -> W.HBox:

    left_box = W.VBox(
        [left],
        layout=W.Layout(
            width=left_width,
        ),
    )

    right_box = W.VBox(
        [right],
        layout=W.Layout(
            width=right_width,
        ),
    )

    return W.HBox(
        [
            left_box,
            right_box,
        ],
        layout=W.Layout(
            width="100%",
            gap=gap,
            align_items="stretch",
        ),
    )


def toolbar(
    *children,
    gap: str = "8px",
) -> W.HBox:

    return W.HBox(
        list(children),
        layout=W.Layout(
            width="100%",
            gap=gap,
            align_items="center",
            flex_flow="row wrap",
        ),
    )


def scroll_panel(
    child,
    *,
    height: str = "360px",
) -> W.Box:

    return W.Box(
        [child],
        layout=W.Layout(
            width="100%",
            height=height,
            overflow_y="auto",
        ),
    )