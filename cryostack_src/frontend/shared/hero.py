# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Frontend
# Component   : Shared Hero Banner
# File        : hero.py
#
# =============================================================================

from __future__ import annotations

import ipywidgets as W


def hero(
    title: str,
    subtitle: str = "",
):

    html = f"""
    <div class="cryostack-hero">

        <div class="cryostack-title">

            {title}

        </div>

        <div class="cryostack-subtitle">

            {subtitle}

        </div>

    </div>
    """

    return W.HTML(html)