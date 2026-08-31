"""Deterministic, model-aware scientific visualization for CryoStack.

Each model gets its own renderer module (``issm`` today, ``icepack`` later).
The generic Results UI stays model-neutral and drives these through a small,
fixed API. No AI / agents are involved -- an agent may *call* this layer later,
but it is never required for normal visualization.
"""
from __future__ import annotations

from .issm import (
    RenderResult,
    figure_name,
    recommended_plots,
    render_field,
    render_recommended,
    render_timeseries,
)

__all__ = [
    "RenderResult", "figure_name", "recommended_plots", "render_field",
    "render_recommended", "render_timeseries",
]
