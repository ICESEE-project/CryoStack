# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Frontend
# Component   : Shared Frontend
# File        : __init__.py
#
# Description :
#     Public shared frontend components used throughout CryoStack.
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
Shared frontend building blocks.
"""

from .theme import (
    CRYOSTACK_FRONTEND_CSS,
)

from .status import (
    normalize_status,
    status_badge,
)

from .cards import (
    detail_row,
    environment_item,
    section_heading,
)

from .layout import (
    page,
    section,
    row,
    two_column,
    toolbar,
    scroll_panel,
)

from .widgets import (
    primary_button,
    secondary_button,
    danger_button,
    success_button,
    output_panel,
    text_input,
    dropdown,
)

from .forms import (
    CloudEnvironmentForm,
    cloud_environment_form,
)

from .hero import hero

__all__ = [
    "CRYOSTACK_FRONTEND_CSS",
    "normalize_status",
    "status_badge",
    "detail_row",
    "environment_item",
    "section_heading",

    "page",
    "section",
    "row",
    "two_column",
    "toolbar",
    "scroll_panel",

    "primary_button",
    "secondary_button",
    "danger_button",
    "success_button",
    "output_panel",
    "text_input",
    "dropdown",

    "CloudEnvironmentForm",
    "cloud_environment_form",

    "hero",
]