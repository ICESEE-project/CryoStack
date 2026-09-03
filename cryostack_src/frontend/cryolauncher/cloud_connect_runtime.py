# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Frontend
# Component   : CryoLauncher "Connect AWS Account" callbacks
# File        : cloud_connect_runtime.py
#
# Description :
#     UI callbacks for the AWS ACCOUNT onboarding block: Connect / Open AWS
#     Setup / Verify / Re-check / Disconnect. Non-blocking; touches widgets
#     only on the event loop; owns no AWS semantics (AWSOnboarding does).
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

from cryostack_src.cloud.connect import OnboardingConfigError, PrincipalNotConfiguredError
from cryostack_src.cloud.connect.assume_role import AssumeRoleError
from cryostack_src.frontend.cryolauncher.cloud_environment import set_aws_account_view
from cryostack_src.frontend.cryolauncher.cloud_runtime import _spawn


@dataclass
class AWSConnectCallbacks:
    connect: Callable          # reveal the 3-step card + build the setup URL
    verify: Callable           # assume role, confirm identity, persist
    recheck: Callable          # re-verify an already-connected account
    disconnect: Callable       # drop the (non-secret) connection metadata
    refresh: Callable          # render current state (call on panel load)


def build_aws_connect_callbacks(
    *,
    widgets,                          # CloudEnvironmentWidgets
    onboarding_factory: Callable,     # () -> AWSOnboarding  (per-user, fresh)
    log_output=None,
    on_connected: Callable | None = None,   # (summary: dict) -> None
    to_thread: Callable = asyncio.to_thread,
    spawn: Callable = _spawn,
) -> AWSConnectCallbacks:
    """Wire the AWS ACCOUNT block to :class:`AWSOnboarding`.

    ``onboarding_factory`` returns a fresh, per-user ``AWSOnboarding`` (the
    connection is owned by the authenticated CryoStack user; nothing here
    trusts a widget for identity).
    """

    _busy = {"on": False}

    def _log(*parts: object) -> None:
        if log_output is None:
            return
        with log_output:
            print("[cloud][connect]", *parts)

    def _render(summary: dict, *, setup_url: str | None = None,
                form_open: bool | None = None) -> None:
        set_aws_account_view(widgets, summary, setup_url=setup_url, form_open=form_open)
        if summary.get("status") == "connected" and on_connected is not None:
            on_connected(summary)

    def _config_error(err: Exception) -> None:
        widgets.aws_account_detail.value = (
            "<div style='font-size:11px;color:#b23c3c;line-height:1.45;'>"
            f"{err}</div>"
        )
        _log("ERROR", err)

    def _set_buttons(disabled: bool) -> None:
        for b in (
            widgets.connect_button, widgets.verify_button,
            widgets.recheck_button, widgets.disconnect_button,
        ):
            b.disabled = disabled

    def refresh(_=None) -> None:
        try:
            _render(onboarding_factory().summary())
        except Exception as err:                       # noqa: BLE001
            _config_error(err)

    # -- Connect: mint/reuse the record, reveal the card, fill the link --
    def connect(_=None) -> None:
        if _busy["on"]:
            return
        try:
            step = onboarding_factory().begin()
        except (PrincipalNotConfiguredError, OnboardingConfigError) as err:
            _config_error(err)
            return
        except Exception as err:                        # noqa: BLE001
            _config_error(err)
            return
        _render(
            onboarding_factory().summary(),
            setup_url=step.setup_url,
            form_open=True,
        )
        _log("ready — open AWS setup, create the role, then paste the Role ARN")

    # -- Verify: the one blocking call, off the event loop --------------
    def _verify_with(worker: Callable, *, prefix: str) -> None:
        if _busy["on"]:
            return
        _busy["on"] = True
        _set_buttons(True)
        widgets.aws_account_status.value = (
            "<span class='cryostack-status cryostack-status-running'>Verifying…</span>"
        )

        async def _drive() -> None:
            try:
                result = await to_thread(worker)
                summary = onboarding_factory().summary()
                _render(summary)
                if result.ok:
                    _log("connected:", result.connection.account_id)
                else:
                    _log("not verified —", result.connection.status_reason)
            except (AssumeRoleError, OnboardingConfigError) as err:
                _config_error(err)
                _render(onboarding_factory().summary())
            except Exception as err:                    # noqa: BLE001
                _config_error(err)
            finally:
                _busy["on"] = False
                _set_buttons(False)

        spawn(_drive())

    def verify(_=None) -> None:
        role_arn = (widgets.role_arn_input.value or "").strip()
        if not role_arn:
            widgets.aws_account_detail.value = (
                "<div style='font-size:11px;color:#b23c3c;'>"
                "Paste the CryoStack access role ARN first.</div>"
            )
            return
        _verify_with(
            lambda: onboarding_factory().verify(role_arn=role_arn),
            prefix="verify",
        )

    def recheck(_=None) -> None:
        _verify_with(lambda: onboarding_factory().recheck(), prefix="recheck")

    def disconnect(_=None) -> None:
        if _busy["on"]:
            return
        try:
            onboarding_factory().disconnect()
        except Exception as err:                        # noqa: BLE001
            _config_error(err)
            return
        widgets.role_arn_input.value = ""
        _render({"status": "disconnected"})
        _log("disconnected — connection metadata removed (no STS credentials "
             "were stored)")

    return AWSConnectCallbacks(
        connect=connect,
        verify=verify,
        recheck=recheck,
        disconnect=disconnect,
        refresh=refresh,
    )
