# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Frontend
# Component   : Shared Forms
# File        : forms.py
#
# Description :
#     Provides reusable frontend forms for execution and infrastructure
#     configuration without containing backend logic.
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
Reusable CryoStack frontend forms.

These forms define user-facing controls only. Backend behavior remains
outside the frontend layer.
"""

from __future__ import annotations

from dataclasses import dataclass

import ipywidgets as W

from .layout import (
    section,
)

from .widgets import (
    dropdown,
    text_input,
)


@dataclass
class CloudEnvironmentForm:
    provider: W.Dropdown
    region: W.Text
    profile: W.Text
    container: W.VBox


def cloud_environment_form(
    *,
    provider: str = "aws",
    region: str = "us-east-2",
    profile: str = "",
) -> CloudEnvironmentForm:

    provider_widget = dropdown(
        description="Provider",
        options=[
            ("AWS", "aws"),
        ],
        value=provider,
    )

    region_widget = text_input(
        description="Region",
        value=region,
        placeholder="us-east-2",
    )

    profile_widget = text_input(
        description="Profile",
        value=profile,
        placeholder="default",
    )

    container = section(
        provider_widget,
        region_widget,
        profile_widget,
    )

    return CloudEnvironmentForm(
        provider=provider_widget,
        region=region_widget,
        profile=profile_widget,
        container=container,
    )