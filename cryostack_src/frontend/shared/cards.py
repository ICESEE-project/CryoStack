# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Frontend
# Component   : Shared Cards
# File        : cards.py
#
# Description :
#     Provides reusable presentation components used across CryoStack
#     scientific application frontends.
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
Reusable CryoStack frontend cards.
"""

from __future__ import annotations

from html import escape

from .status import (
    status_badge,
)


def section_heading(
    title: str,
    description: str = "",
) -> str:

    description_html = ""

    if description:

        description_html = (
            f"<p>{escape(description)}</p>"
        )

    return f"""
    <div class="cryostack-section-heading">
      <h2>{escape(title)}</h2>
      {description_html}
    </div>
    """


def detail_row(
    label: str,
    value: str,
) -> str:

    return f"""
    <div class="cryostack-detail-row">

      <span class="cryostack-detail-label">
        {escape(label)}
      </span>

      <span class="cryostack-detail-value">
        {escape(value)}
      </span>

    </div>
    """


def environment_item(
    label: str,
    state: str,
    *,
    value: str | None = None,
) -> str:

    value_text = (
        value
        or state.title()
    )

    return f"""
    <div class="cryostack-environment-item">

      <div class="cryostack-environment-item-label">
        {escape(label)}
      </div>

      <div class="cryostack-environment-item-value">
        {status_badge(
            state,
            label=value_text,
        )}
      </div>

    </div>
    """