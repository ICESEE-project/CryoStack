# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Frontend
# Component   : Shared Widgets
# File        : widgets.py
#
# Description :
#     Provides standardized interactive widgets used across CryoStack
#     application frontends.
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
Reusable CryoStack ipywidget components.
"""

from __future__ import annotations

import ipywidgets as W


def primary_button(
    description: str,
    *,
    icon: str = "",
) -> W.Button:

    return W.Button(
        description=description,
        icon=icon,
        button_style="primary",
        layout=W.Layout(
            width="auto",
        ),
    )


def secondary_button(
    description: str,
    *,
    icon: str = "",
) -> W.Button:

    return W.Button(
        description=description,
        icon=icon,
        button_style="",
        layout=W.Layout(
            width="auto",
        ),
    )


def danger_button(
    description: str,
    *,
    icon: str = "stop",
) -> W.Button:

    return W.Button(
        description=description,
        icon=icon,
        button_style="danger",
        layout=W.Layout(
            width="auto",
        ),
    )


def success_button(
    description: str,
    *,
    icon: str = "check",
) -> W.Button:

    return W.Button(
        description=description,
        icon=icon,
        button_style="success",
        layout=W.Layout(
            width="auto",
        ),
    )


def output_panel(
    *,
    height: str = "320px",
) -> W.Output:

    out = W.Output(
        layout=W.Layout(
            width="100%",
            height=height,
            overflow_y="auto",
            border="1px solid #dfe6ef",
            padding="8px",
        ),
    )

    return out


def text_input(
    *,
    description: str,
    value: str = "",
    placeholder: str = "",
) -> W.Text:

    return W.Text(
        description=description,
        value=value,
        placeholder=placeholder,
        layout=W.Layout(
            width="100%",
        ),
        style={
            "description_width": "120px",
        },
    )


def dropdown(
    *,
    description: str,
    options,
    value=None,
) -> W.Dropdown:

    return W.Dropdown(
        description=description,
        options=options,
        value=value,
        layout=W.Layout(
            width="100%",
        ),
        style={
            "description_width": "120px",
        },
    )