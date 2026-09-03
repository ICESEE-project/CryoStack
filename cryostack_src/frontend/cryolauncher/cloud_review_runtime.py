# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Frontend
# Component   : CryoLauncher Review & Launch callbacks
# File        : cloud_review_runtime.py
#
# Description :
#     UI callbacks for the RUN ESTIMATE line and the REVIEW CLOUD RUN surface.
#     Non-blocking; owns no pricing/estimation logic (that is
#     cryostack_src.cloud.estimate / cryostack_src.cloud.review).
#
# Author(s)   :
#     Brian Kyanjo
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from cryostack_src.frontend.cryolauncher.cloud_environment import (
    set_review_panel,
    set_run_estimate_view,
    show_review_panel,
)
from cryostack_src.frontend.cryolauncher.cloud_runtime import _spawn


@dataclass
class CloudReviewCallbacks:
    refresh_estimate: Callable   # render the compact RUN ESTIMATE line
    review: Callable             # open the full REVIEW CLOUD RUN surface
    back: Callable               # close it
    launch: Callable             # explicit human Launch (drift-checked)


def _round_minutes(minutes: float) -> str:
    m = float(minutes or 0)
    return f"{m:.0f}" if m >= 1 else f"{m:.1f}"


def build_cloud_review_callbacks(
    *,
    widgets,
    review_builder: Callable,          # () -> CloudRunReview  (may hit AWS)
    digest_builder: Callable,          # () -> str             (cheap, sync)
    launch_handler: Callable,          # (CloudRunReview) -> None
    log_output=None,
    to_thread: Callable = asyncio.to_thread,
    spawn: Callable = _spawn,
) -> CloudReviewCallbacks:
    """Wire the estimate line + review surface.

    ``review_builder`` returns a fully-formed ``CloudRunReview`` (fresh account
    verification, readiness, canonical resources, runtime + cost estimate). A
    failed cost lookup still returns a review — it is shown as "unavailable"
    and never blocks Launch.
    """

    _state: dict = {"review": None, "busy": False}

    def _log(*parts):
        if log_output is not None:
            with log_output:
                print("[cloud][review]", *parts)

    def _render_estimate_line(review) -> None:
        set_run_estimate_view(
            widgets,
            visible=review.infrastructure.all_ready,
            runtime_text=f"~{_round_minutes(review.expected_runtime_minutes)} min",
            resource_text=review.resource_summary(),
            cost_text=review.cost_summary(),
            unavailable=not review.cost.available,
        )

    def _run(*, open_panel: bool) -> None:
        if _state["busy"]:
            return
        _state["busy"] = True
        widgets.review_button.disabled = True

        async def _drive() -> None:
            try:
                review = await to_thread(review_builder)
                _state["review"] = review
                _render_estimate_line(review)
                if open_panel:
                    set_review_panel(widgets, review)
                    show_review_panel(widgets, True)
            except Exception as err:  # noqa: BLE001 - estimate/review never crash the panel
                _log("unavailable:", err)
                if open_panel:
                    widgets.review_notice.value = (
                        "<div style='font-size:11px;color:#b23c3c;'>Could not build "
                        f"the review: {err}</div>"
                    )
            finally:
                _state["busy"] = False
                widgets.review_button.disabled = False

        spawn(_drive())

    def refresh_estimate(_=None) -> None:
        _run(open_panel=False)

    def review(_=None) -> None:
        _run(open_panel=True)

    def back(_=None) -> None:
        show_review_panel(widgets, False)

    def launch(_=None) -> None:
        current = _state["review"]
        if current is None:
            review()
            return
        # drift protection: the billable config must not have changed since the
        # review was opened.
        try:
            live_digest = digest_builder()
        except Exception:  # noqa: BLE001
            live_digest = current.digest
        if live_digest != current.digest:
            _state["review"] = None
            widgets.review_notice.value = (
                "<div style='font-size:11px;color:#b23c3c;'>The run configuration "
                "changed since you opened this review. Rebuilding it — review the "
                "updated estimate, then Launch again.</div>"
            )
            _run(open_panel=True)
            return
        if not current.can_launch:
            _log("launch blocked:", "; ".join(current.blocked_reasons))
            return
        show_review_panel(widgets, False)
        _log("launching…")
        launch_handler(current)

    return CloudReviewCallbacks(
        refresh_estimate=refresh_estimate,
        review=review,
        back=back,
        launch=launch,
    )
