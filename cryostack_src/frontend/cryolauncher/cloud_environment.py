# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Frontend
# Component   : ICESEE Cloud Environment
# File        : cloud_environment.py
#
# Description :
#     Provides the Cloud Environment panel used by the ICESEE frontend.
#     The component presents user-facing cloud configuration and keeps
#     infrastructure-specific settings inside an Advanced section.
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
ICESEE Cloud Environment frontend component.

This module contains presentation and widget state only. It does not
perform cloud authentication, provisioning, submission, or other backend
operations.
"""

from __future__ import annotations

from dataclasses import dataclass

import ipywidgets as W

from cryostack_src.frontend.shared import (
    primary_button,
    secondary_button,
    status_badge,
    toolbar,
)


@dataclass
class CloudEnvironmentWidgets:
    """
    Widget references exposed to the gateway.

    Existing gateway callbacks can continue reading and writing these
    widgets during the frontend migration.
    """

    provider: W.Dropdown
    region: W.Text
    profile: W.Text

    s3_prefix: W.Text
    job_queue: W.Text
    job_definition: W.Text
    job_name: W.Text
    #: Basic (primary) path: the scientist enters only the license value.
    #: CryoStack creates/reuses a CryoStack-managed secret under a fixed
    #: default name (never shown) and stores only the resulting ARN --
    #: the value widget is a masked Password -- never rendered, logged, or
    #: persisted -- and is cleared after a successful (or failed) attempt.
    matlab_license_value: "W.Password"
    matlab_license_create_button: W.Button
    matlab_license_create_status: "W.HTML"
    #: shown instead of the entry form once an ARN is configured.
    matlab_license_configured_row: "W.HBox"
    matlab_license_reconfigure_button: W.Button
    #: shown instead of the Reconfigure button when the configured ARN is
    #: CryoStack's own fixed-name managed secret (no in-app rotate path).
    matlab_license_rotate_note: "W.HTML"
    #: the entry form (caption + value field + Configure button + status) --
    #: hidden once configured, shown again while reconfiguring.
    matlab_license_entry_box: "W.VBox"
    #: Advanced (secondary): paste the ARN of a secret the user already
    #: manages themselves. The only place the Secrets Manager ARN / secret
    #: terminology is shown by default.
    matlab_license_arn: W.Text
    matlab_license_save_button: W.Button
    matlab_license_advanced: "W.Accordion"
    #: the whole MATLAB license row (heading + entry/configured state +
    #: advanced accordion) -- toggled independently of the Advanced cloud
    #: settings accordion, on whether the SELECTED WORKFLOW needs MATLAB
    #: (see cryostack_src.models.workflow_capabilities), never on
    #: Basic/Advanced mode alone -- Basic/Advanced only controls how much
    #: AWS implementation detail is exposed within this box.
    matlab_license_box: "W.VBox"

    #: INSTITUTIONAL CONNECTION -- shown only when the resolved workflow's
    #: CloudMatlabLicense.requires_tunnel is True (set by the caller from
    #: cryostack_src.models.workflow_capabilities + the already-resolved
    #: CloudExecution.matlab_license, exactly like matlab_license_box's own
    #: visibility). Reads/drives the SAME Connector pairing/session Remote
    #: uses (via caller-supplied check_connected/open_connector/disconnect
    #: callables in wire_institutional_connection_widgets) -- never a
    #: second Connector implementation, pairing, identity, or session.
    #: Never shows tunnel/relay/websocket/session id/token/vendor-daemon/
    #: host-port/MLM_LICENSE_FILE wording -- only that the Connector is (or
    #: is not) connected.
    institutional_connection_box: "W.VBox"
    institutional_connection_status: "W.HTML"
    #: the compact pairing-code line (Remote's own connector_pairing_
    #: status_html), shown only while a session exists and is not yet
    #: online -- empty otherwise.
    institutional_connection_pairing_info: "W.HTML"
    #: the one real "open a new tab" pairing-page link (Remote's own
    #: connector_pairing_link_html) -- Cloud's complete pairing flow
    #: (create session -> show code + link -> pair -> connected) lives
    #: entirely in this box, sourced from the SAME Connector session
    #: Remote uses. Empty except while waiting to pair.
    institutional_connection_pairing_link: "W.HTML"
    institutional_connection_open_button: W.Button
    institutional_connection_recheck_button: W.Button
    institutional_connection_disconnect_button: W.Button

    #: Advanced: AWS Batch compute environment -- "fargate" (default) or "ec2"
    compute_mode: W.Dropdown
    #: EC2-only knobs, revealed only while compute_mode == "ec2"
    ec2_max_vcpus: W.IntText
    ec2_instance_types: W.Text
    ec2_options_box: W.VBox
    #: EC2 sub-modes (progressive disclosure -- each reveals its own controls
    #: only while selected). Every one defaults to the plain/valid case.
    ec2_capacity: W.Dropdown              # "on_demand" (default) | "spot"
    ec2_accelerator: W.Dropdown           # "none" (default) | "gpu"
    ec2_network: W.Dropdown               # "default" (default) | "custom"
    ec2_topology: W.Dropdown              # "single_node" (default) | "multi_node"
    ec2_vpc_id: W.Text
    ec2_subnet_ids: W.Text
    ec2_security_group_ids: W.Text
    ec2_network_box: W.VBox               # shown only while ec2_network == "custom"
    ec2_node_count: W.IntText
    ec2_multinode_box: W.VBox             # shown only while ec2_topology == "multi_node"

    account_status: W.HTML
    storage_status: W.HTML
    registry_status: W.HTML
    compute_status: W.HTML

    test_button: W.Button
    prepare_button: W.Button

    advanced: W.Accordion

    container: W.VBox

    # -- "Connect AWS Account" onboarding (C7.2) --------------------------
    #: the whole AWS ACCOUNT block (status line + connect card)
    aws_account_section: W.VBox
    #: "● Connected" / "● Not connected" badge line
    aws_account_status: W.HTML
    #: account id / region / access / last-verified (connected) OR the
    #: short "use your own account" explainer (disconnected)
    aws_account_detail: W.HTML
    #: disconnected -> reveals the 3-step card
    connect_button: W.Button
    #: the collapsible 3-step card (hidden until Connect is clicked)
    connect_form: W.VBox
    #: the Re-check / Disconnect row shown only when connected
    connect_actions: W.HBox
    #: an <a target="_blank"> to the CloudFormation Quick Create page
    open_setup_link: W.HTML
    #: the ONLY value a user may need to paste back
    role_arn_input: W.Text
    verify_button: W.Button
    #: connected -> re-run AssumeRole with the stored role ARN
    recheck_button: W.Button
    #: connected -> remove the (non-secret) connection metadata
    disconnect_button: W.Button
    #: connected -> open a CloudFormation *Update stack* link for the SAME
    #: stack/role/ExternalId, so a permissions fix that landed in the
    #: template after this account connected can be applied without
    #: disconnecting, reconnecting, or getting a new Role ARN
    update_role_button: W.Button
    #: an <a target="_blank"> to the CloudFormation Update stack page, or an
    #: inline error -- populated only after Update role permissions is
    #: clicked; empty otherwise
    update_role_link: W.HTML
    #: error (verification failed) -> the Retry connection / Change AWS
    #: account row -- the recovery escape hatch for a stranded connection
    recovery_actions: W.HBox
    #: repair/re-verify THIS account -- reopens the form, reusing the saved
    #: ExternalId, and prepopulates the saved Role ARN
    retry_button: W.Button
    #: abandon this local connection attempt and start onboarding a
    #: different AWS account (mints a fresh ExternalId; no AWS resources of
    #: the previous account are touched)
    change_account_button: W.Button
    #: -- staged "Change AWS account" (does NOT touch the active connection
    #: until the replacement itself verifies) ------------------------------
    #: the whole "connecting a new AWS account" card; hidden until
    #: change_account_button starts it, hidden again on Cancel or success
    change_account_panel: W.VBox
    #: explains the current active connection is untouched + warns about
    #: reusing the same AWS console session (AlreadyExistsException)
    change_account_notice: W.HTML
    #: shows the pending attempt's own verification error, if any
    change_account_status: W.HTML
    change_setup_link: W.HTML
    change_role_arn_input: W.Text
    change_verify_button: W.Button
    #: abandon the staged attempt; the active connection is untouched
    change_cancel_button: W.Button

    # -- RUN ESTIMATE + Review & Launch (C7.4) --------------------------
    #: compact "expected runtime · resources · estimated cost" block
    run_estimate_section: W.VBox
    run_estimate_line: W.HTML
    review_button: W.Button
    #: the REVIEW CLOUD RUN surface (hidden until Review & Launch)
    review_panel: W.VBox
    review_body: W.HTML
    review_notice: W.HTML
    review_back_button: W.Button
    launch_button: W.Button

    # -- CLOUD RUN active-run surface (C7.5) ---------------------------
    #: compact live status card, hidden until a run is launched
    active_run_section: W.VBox
    active_run_title: W.HTML
    active_run_status: W.HTML
    active_run_detail: W.HTML
    active_run_diagnostics: W.HTML
    active_run_actions: W.HBox
    active_run_log_button: W.Button
    active_run_results_button: W.Button
    active_run_terminate_button: W.Button


def _status_row(
    label: str,
    *,
    state: str = "idle",
    text: str = "Not prepared",
) -> tuple[W.HBox, W.HTML]:

    status = W.HTML(
        value=status_badge(
            state,
            label=text,
        ),
        layout=W.Layout(
            width="auto",
        ),
    )

    row = W.HBox(
        [
            W.HTML(
                value=(
                    f"""
                    <div
                      style="
                        font-size:12px;
                        color:#66758d;
                        min-width:130px;
                      "
                    >
                      {label}
                    </div>
                    """
                ),
                layout=W.Layout(
                    width="140px",
                ),
            ),
            status,
        ],
        layout=W.Layout(
            width="100%",
            align_items="center",
            gap="8px",
            padding="3px 0",
        ),
    )

    return row, status


def set_cloud_status(
    widget: W.HTML,
    *,
    state: str,
    label: str,
) -> None:
    """
    Update one Cloud Environment status indicator.
    """

    widget.value = status_badge(
        state,
        label=label,
    )


_DISCONNECTED_BLURB = (
    "Use your own AWS account and credits. CryoStack uses temporary role "
    "access and does not store your AWS access keys."
)


def _build_aws_account_section() -> dict:
    """The AWS ACCOUNT block: a status line plus the collapsible 3-step
    "Connect your AWS account" card. Contains no access-key / secret field --
    the only value a user may paste back is the Role ARN."""

    aws_account_status = W.HTML(
        value=status_badge("idle", label="Not connected"),
    )

    aws_account_detail = W.HTML(
        value=(
            f"<div style='font-size:11px;color:#66758d;line-height:1.45;'>"
            f"{_DISCONNECTED_BLURB}</div>"
        ),
    )

    connect_button = primary_button("Connect AWS Account", icon="aws")

    open_setup_link = W.HTML(
        value=(
            "<span style='font-size:11px;color:#96a1b4;'>"
            "Setup link appears after you start…</span>"
        ),
    )

    role_arn_input = W.Text(
        description="Role ARN:",
        placeholder="arn:aws:iam::<account>:role/CryoStackExecutionRole",
        layout=W.Layout(width="100%"),
        style={"description_width": "110px"},
    )

    verify_button = primary_button("Verify connection", icon="check")

    steps = W.HTML(
        value="""
        <div style="font-size:12px;font-weight:700;color:#172033;margin-bottom:4px;">
          CONNECT YOUR AWS ACCOUNT
        </div>
        <ol style="font-size:11px;color:#66758d;line-height:1.6;margin:0 0 6px 16px;padding:0;">
          <li>Open AWS setup</li>
          <li>Create the CryoStack access role</li>
          <li>Return here and verify</li>
        </ol>
        """,
    )

    connect_form = W.VBox(
        [steps, open_setup_link, role_arn_input, verify_button],
        layout=W.Layout(
            width="100%",
            gap="6px",
            padding="8px",
            border="1px solid #dfe6ef",
            display="none",           # revealed on Connect
        ),
    )

    recheck_button = secondary_button("Re-check", icon="refresh")
    disconnect_button = secondary_button("Disconnect", icon="unlink")
    #: a normal secondary action, not visually emphasized -- CryoStack has
    #: no reliable way to tell a connected account's stack was created from
    #: an older published template (AWSConnection records no template
    #: version), so this is offered plainly rather than inventing that
    #: version state.
    update_role_button = secondary_button("Update role permissions", icon="wrench")

    connect_actions = W.HBox(
        [recheck_button, disconnect_button, update_role_button],
        layout=W.Layout(gap="8px", flex_wrap="wrap", display="none"),
    )

    update_role_link = W.HTML(value="")

    # -- failed-verification recovery: shown ONLY in the "error" state ---
    retry_button = primary_button("Retry connection", icon="redo")
    change_account_button = secondary_button("Change AWS account", icon="exchange")

    recovery_actions = W.HBox(
        [retry_button, change_account_button],
        layout=W.Layout(gap="8px", display="none"),
    )

    # -- staged "Change AWS account" card: separate from connect_form so it
    # can be shown ALONGSIDE the still-active connection's own status ------
    change_account_notice = W.HTML(
        value=(
            "<div style='font-size:11px;color:#66758d;line-height:1.5;'>"
            "Your current connection above is kept until this new one "
            "verifies. If your browser is still signed into AWS as the "
            "<b>same</b> account, use <b>Retry connection</b> instead -- "
            "creating another CryoStack access role in an account that "
            "already has one fails with <code>AlreadyExistsException</code>."
            "</div>"
        ),
    )
    change_setup_link = W.HTML(
        value=(
            "<span style='font-size:11px;color:#96a1b4;'>"
            "Setup link appears after you start…</span>"
        ),
    )
    change_role_arn_input = W.Text(
        description="Role ARN:",
        placeholder="arn:aws:iam::<account>:role/CryoStackExecutionRole",
        layout=W.Layout(width="100%"),
        style={"description_width": "110px"},
    )
    change_account_status = W.HTML()
    change_verify_button = primary_button("Verify new account", icon="check")
    change_cancel_button = secondary_button("Cancel — back to current account", icon="ban")

    change_account_panel = W.VBox(
        [
            W.HTML(
                "<div style='font-size:12px;font-weight:700;color:#172033;"
                "margin-bottom:2px;'>CONNECTING A NEW AWS ACCOUNT</div>"
            ),
            change_account_notice,
            change_setup_link,
            change_role_arn_input,
            change_account_status,
            W.HBox([change_verify_button, change_cancel_button],
                   layout=W.Layout(gap="8px", flex_wrap="wrap")),
        ],
        layout=W.Layout(
            width="100%", gap="6px", padding="8px",
            border="1px solid #dfe6ef", display="none",   # revealed on Change AWS account
        ),
    )

    heading = W.HTML(
        value=(
            "<div style='font-size:12px;font-weight:700;color:#172033;"
            "letter-spacing:.02em;'>AWS ACCOUNT</div>"
        ),
    )

    aws_account_section = W.VBox(
        [
            heading,
            aws_account_status,
            aws_account_detail,
            connect_button,
            connect_form,
            connect_actions,
            update_role_link,
            recovery_actions,
            change_account_panel,
        ],
        layout=W.Layout(width="100%", gap="5px", padding="6px 0"),
    )

    return {
        "aws_account_section": aws_account_section,
        "aws_account_status": aws_account_status,
        "aws_account_detail": aws_account_detail,
        "connect_button": connect_button,
        "connect_form": connect_form,
        "connect_actions": connect_actions,
        "open_setup_link": open_setup_link,
        "role_arn_input": role_arn_input,
        "verify_button": verify_button,
        "recheck_button": recheck_button,
        "disconnect_button": disconnect_button,
        "update_role_button": update_role_button,
        "update_role_link": update_role_link,
        "recovery_actions": recovery_actions,
        "retry_button": retry_button,
        "change_account_button": change_account_button,
        "change_account_panel": change_account_panel,
        "change_account_notice": change_account_notice,
        "change_account_status": change_account_status,
        "change_setup_link": change_setup_link,
        "change_role_arn_input": change_role_arn_input,
        "change_verify_button": change_verify_button,
        "change_cancel_button": change_cancel_button,
    }


def set_aws_account_view(
    widgets: "CloudEnvironmentWidgets",
    summary: dict,
    *,
    setup_url: str | None = None,
    form_open: bool | None = None,
) -> None:
    """Render the AWS ACCOUNT block from an ``AWSOnboarding.summary()`` dict.

    ``summary["status"]`` is one of ``disconnected`` / ``pending`` /
    ``connected`` / ``error``. Never renders any secret -- ``summary`` carries
    only non-secret connection metadata.
    """

    status = (summary or {}).get("status", "disconnected")
    detail = widgets.aws_account_detail

    if status != "connected":
        # a stale "Open CloudFormation Update stack" link (or error) from a
        # previous connected session must never linger once the account is
        # no longer connected (disconnected, or a fresh error/pending state).
        widgets.update_role_link.value = ""

    if setup_url:
        widgets.open_setup_link.value = (
            f"<a href='{escape_attr(setup_url)}' target='_blank' rel='noopener' "
            "style='font-size:12px;font-weight:600;'>▶ Open AWS Setup</a>"
        )

    if form_open is not None:
        widgets.connect_form.layout.display = "flex" if form_open else "none"

    def _show_connected_actions(show: bool) -> None:
        widgets.connect_actions.layout.display = "flex" if show else "none"

    def _show_recovery_actions(show: bool) -> None:
        widgets.recovery_actions.layout.display = "flex" if show else "none"

    if status == "connected":
        widgets.aws_account_status.value = status_badge("done", label="Connected")
        acct = summary.get("account_id", "")
        region = summary.get("region", "")
        verified = summary.get("verified_at", "") or "just now"
        detail.value = (
            "<table style='font-size:11px;color:#66758d;border-collapse:collapse;'>"
            f"<tr><td style='padding:1px 12px 1px 0;'>Account ID</td><td><code>{escape_text(acct)}</code></td></tr>"
            f"<tr><td style='padding:1px 12px 1px 0;'>Region</td><td>{escape_text(region)}</td></tr>"
            "<tr><td style='padding:1px 12px 1px 0;'>Access</td><td>Temporary role</td></tr>"
            f"<tr><td style='padding:1px 12px 1px 0;'>Last verified</td><td>{escape_text(str(verified))}</td></tr>"
            "</table>"
        )
        widgets.connect_button.layout.display = "none"
        widgets.connect_form.layout.display = "none"
        _show_connected_actions(True)
        _show_recovery_actions(False)
        return

    if status == "error":
        widgets.aws_account_status.value = status_badge("fail", label="Not verified")
        reason = summary.get("status_reason", "") or "Verification failed."
        detail.value = (
            f"<div style='font-size:11px;color:#b23c3c;line-height:1.45;'>{escape_text(reason)}</div>"
        )
        widgets.connect_button.layout.display = "none"
        # The form (Role ARN + Verify) is NOT forced open here -- it stays at
        # whatever the caller last set it to (hidden by default; a prior
        # Retry/Verify in this session left it open). "Retry connection"
        # below is the explicit, discoverable way back into it, prepopulated
        # with the saved Role ARN -- a forgotten ARN is never a dead end.
        _show_connected_actions(False)
        _show_recovery_actions(True)
        return

    if status == "pending":
        widgets.aws_account_status.value = status_badge("running", label="Awaiting role")
        detail.value = (
            "<div style='font-size:11px;color:#66758d;line-height:1.45;'>"
            "Create the role in AWS, then paste the Role ARN below and verify."
            "</div>"
        )
        widgets.connect_button.layout.display = "none"
        widgets.connect_form.layout.display = "flex"
        _show_connected_actions(False)
        _show_recovery_actions(False)
        return

    # disconnected
    widgets.aws_account_status.value = status_badge("idle", label="Not connected")
    detail.value = (
        f"<div style='font-size:11px;color:#66758d;line-height:1.45;'>{_DISCONNECTED_BLURB}</div>"
    )
    widgets.connect_button.layout.display = "inline-flex"
    widgets.connect_form.layout.display = "none"
    _show_connected_actions(False)
    _show_recovery_actions(False)


def set_change_account_panel(
    widgets: "CloudEnvironmentWidgets",
    pending_summary: dict | None,
    *,
    setup_url: str | None = None,
    prefill_role_arn: bool = False,
) -> None:
    """Render the staged "Connecting a new AWS account" card.

    Independent of :func:`set_aws_account_view` -- the active connection's
    own status is rendered separately and is NEVER touched by this function.
    ``pending_summary`` is ``None`` when there is no staged replacement (the
    panel is hidden); otherwise it is the pending connection's own
    ``pending``/``error`` summary. ``prefill_role_arn`` restores a Role ARN
    already saved on the pending attempt (e.g. after a failed Verify, or on
    a page reload) -- never on a fresh Cancel, which clears the field.
    """
    if pending_summary is None:
        widgets.change_account_panel.layout.display = "none"
        return

    widgets.change_account_panel.layout.display = "flex"

    if setup_url:
        widgets.change_setup_link.value = (
            f"<a href='{escape_attr(setup_url)}' target='_blank' rel='noopener' "
            "style='font-size:12px;font-weight:600;'>▶ Open AWS Setup</a>"
        )

    if prefill_role_arn:
        widgets.change_role_arn_input.value = pending_summary.get("role_arn", "") or ""

    if pending_summary.get("status") == "error":
        reason = pending_summary.get("status_reason", "") or "Verification failed."
        widgets.change_account_status.value = (
            f"<div style='font-size:11px;color:#b23c3c;line-height:1.45;'>{escape_text(reason)}</div>"
        )
    else:
        widgets.change_account_status.value = ""


def escape_text(value: str) -> str:
    from html import escape

    return escape(str(value or ""))


def escape_attr(value: str) -> str:
    from html import escape

    return escape(str(value or ""), quote=True)


# ---------------------------------------------------------------------------
# RUN ESTIMATE + Review & Launch (C7.4)
# ---------------------------------------------------------------------------
_BILLING_NOTE = (
    "This is an estimate. AWS charges apply to your AWS account. AWS "
    "promotional/free-tier credits, billing rules and payment methods are "
    "managed by AWS &mdash; check your AWS Billing &amp; Cost Management "
    "console for your credit balance. CryoStack cannot guarantee a run is "
    "covered by those credits."
)


def _build_run_estimate_section() -> dict:
    """The compact RUN ESTIMATE block shown once infrastructure is Ready, plus
    the (hidden) REVIEW CLOUD RUN surface."""

    heading = W.HTML(
        value=(
            "<div style='font-size:12px;font-weight:700;color:#172033;"
            "letter-spacing:.02em;margin-top:2px;'>RUN ESTIMATE</div>"
        ),
    )
    run_estimate_line = W.HTML(
        value=(
            "<div style='font-size:11px;color:#96a1b4;'>"
            "Prepare the cloud environment to see an estimate.</div>"
        ),
    )
    review_button = primary_button("Review & Launch", icon="clipboard-check")

    run_estimate_section = W.VBox(
        [heading, run_estimate_line, review_button],
        layout=W.Layout(width="100%", gap="5px", padding="6px 0", display="none"),
    )

    # -- the review surface (hidden until Review & Launch) -----------
    review_body = W.HTML()
    review_notice = W.HTML(
        value=(
            f"<div style='font-size:10.5px;color:#66758d;line-height:1.5;"
            f"background:#f6f8fb;border:1px solid #e4e9f0;border-radius:6px;"
            f"padding:8px;margin:6px 0;'>{_BILLING_NOTE}</div>"
        ),
    )
    review_back_button = secondary_button("Back", icon="arrow-left")
    launch_button = primary_button("Launch cloud run", icon="cloud-upload-alt")

    review_panel = W.VBox(
        [
            W.HTML(
                "<div style='font-size:13px;font-weight:700;color:#172033;'>"
                "REVIEW CLOUD RUN</div>"
            ),
            review_body,
            review_notice,
            W.HBox([review_back_button, launch_button], layout=W.Layout(gap="8px")),
        ],
        layout=W.Layout(
            width="100%", gap="6px", padding="12px",
            border="1px solid #cbd6e4", background_color="#ffffff",
            display="none",
        ),
    )

    return {
        "run_estimate_section": run_estimate_section,
        "run_estimate_line": run_estimate_line,
        "review_button": review_button,
        "review_panel": review_panel,
        "review_body": review_body,
        "review_notice": review_notice,
        "review_back_button": review_back_button,
        "launch_button": launch_button,
    }


def set_run_estimate_view(
    widgets: "CloudEnvironmentWidgets",
    *,
    visible: bool,
    runtime_text: str = "",
    resource_text: str = "",
    cost_text: str = "",
    unavailable: bool = False,
) -> None:
    """Render the compact RUN ESTIMATE line. Shown only when infrastructure is
    Ready; hidden otherwise."""
    widgets.run_estimate_section.layout.display = "flex" if visible else "none"
    if not visible:
        return
    cost = (
        "<span style='color:#96a1b4;'>Cost estimate unavailable</span>"
        if unavailable
        else f"<b style='font-size:13px;color:#172033;'>{escape_text(cost_text)}</b>"
    )
    widgets.run_estimate_line.value = (
        "<div style='font-size:11px;color:#66758d;line-height:1.7;'>"
        f"Expected runtime&nbsp;&nbsp;{escape_text(runtime_text)}<br>"
        f"Resources&nbsp;&nbsp;{escape_text(resource_text)}<br>"
        f"Estimated cost&nbsp;&nbsp;{cost}"
        "</div>"
    )


def _yn(ready: bool) -> str:
    color = "#2f8f4e" if ready else "#b23c3c"
    return f"<span style='color:{color};'>{'Ready' if ready else 'Not ready'}</span>"


#: the ONE CryoStack-managed secret name Configure License uses -- never
#: shown in the UI or collected from the user. Matches the ``cryostack/``
#: prefix the cross-account role's CreateSecret grant is scoped to (see
#: cryostack_src/cloud/drivers/aws/secrets.py, deployment/cloudformation/
#: cryostack-execution-role.json).
DEFAULT_MATLAB_LICENSE_SECRET_NAME = "cryostack/issm-matlab-license"


def _matlab_license_status_html(message: str, *, ok: bool) -> str:
    color = "#2f8f4e" if ok else "#b23c3c"
    return f"<div style='font-size:11px;color:{color};'>{message}</div>"


def _matlab_license_progress_html(message: str) -> str:
    """A neutral (neither success-green nor error-red) in-progress status
    line -- the operation has not yet succeeded or failed."""
    return f"<div style='font-size:11px;color:#66758d;'>{message}</div>"


def _sanitize_secret_create_error(error: object) -> tuple[str, str]:
    """Map a backend ``SecretCreateError`` to a (scientist-facing message,
    short technical detail) pair. NEITHER string ever carries the raw AWS
    CLI text -- which, as observed live for CreateSecret AccessDenied,
    includes the STS assumed-role ARN and account id -- only a short,
    categorized, human reason. The technical detail is for the Run Log
    (the existing developer/debug channel) only, never the main status.
    """
    text = str(error)
    if "AccessDenied" in text:
        return (
            "Could not configure the MATLAB license. Your CryoStack AWS "
            "connection needs updated permissions. Select 'Update role "
            "permissions', then try again.",
            "Access denied for AWS Secrets Manager CreateSecret.",
        )
    return (
        "Could not configure the MATLAB license. Please try again, or "
        "check your AWS connection.",
        "AWS Secrets Manager CreateSecret failed.",
    )


def _sanitize_secret_describe_error(error: object) -> tuple[str, str]:
    """Map a backend ``SecretDescribeError`` (raised recovering an
    existing secret's ARN after ``SecretAlreadyExists`` -- see
    ``_create_secret`` -- or on a Re-check) to a (scientist-facing
    message, short technical detail) pair, mirroring
    :func:`_sanitize_secret_create_error` exactly. NEITHER string ever
    carries the raw AWS CLI text; the technical detail is for the Run Log
    only. Distinguishing AccessDenied specifically matters here: it is
    the ONLY way a scientist (or whoever reads the Run Log) can tell "the
    connected role does not have this permission yet" apart from "AWS
    Secrets Manager did not respond" or any other failure -- a bare
    'could not automatically confirm it' collapses both into one
    undiagnosable message.
    """
    text = str(error)
    if "AccessDenied" in text:
        return (
            "A MATLAB license is already configured for this AWS "
            "account, but CryoStack's connection does not yet have the "
            "permissions needed to confirm it. Select 'Update role "
            "permissions', then try again.",
            "Access denied for AWS Secrets Manager DescribeSecret.",
        )
    return (
        "A MATLAB license is already configured for this AWS account, "
        "but CryoStack could not automatically confirm it. Please try "
        "again, or check your AWS connection.",
        "AWS Secrets Manager DescribeSecret failed.",
    )


def _is_default_managed_matlab_license_arn(arn: str) -> bool:
    """True when ``arn`` names the ONE fixed-name secret Configure license
    creates (:data:`DEFAULT_MATLAB_LICENSE_SECRET_NAME`, plus the random
    suffix AWS appends to it). Used ONLY to decide whether "Reconfigure"
    can honestly do anything: since no ``PutSecretValue``/``UpdateSecret``
    path exists, a Configure-license retry against this exact fixed name
    always collides (``SecretAlreadyExists``) -- offering an active
    reconfigure form for it would imply a working rotate path that does
    not exist. An ARN naming a DIFFERENT secret (set via Advanced -> "Use
    existing secret") is not CryoStack-managed, and Reconfigure there can
    genuinely create a fresh managed secret, so it stays available.

    A pure string check on the already-non-secret, already-stored ARN --
    no AWS call, no new permission, no change to what is persisted.
    """
    arn = (arn or "").strip()
    marker = ":secret:"
    idx = arn.find(marker)
    if not arn.startswith("arn:aws:secretsmanager:") or idx < 0:
        return False
    name = arn[idx + len(marker):]
    return (name == DEFAULT_MATLAB_LICENSE_SECRET_NAME
            or name.startswith(DEFAULT_MATLAB_LICENSE_SECRET_NAME + "-"))


def _refresh_matlab_license_view(widgets: "CloudEnvironmentWidgets") -> None:
    """Show the configured status once an ARN is set, the entry form
    otherwise. Never reads or displays the secret value -- only whether
    the (non-secret) ARN field is populated.

    Within the configured state, "Reconfigure" is shown only when it can
    honestly do something; for CryoStack's own fixed-name managed secret
    (see :func:`_is_default_managed_matlab_license_arn`) a short static
    note replaces it instead of an active form that would always fail.
    """
    arn = (widgets.matlab_license_arn.value or "").strip()
    configured = bool(arn)
    widgets.matlab_license_entry_box.layout.display = (
        "none" if configured else "flex")
    widgets.matlab_license_configured_row.layout.display = (
        "flex" if configured else "none")

    rotatable = configured and not _is_default_managed_matlab_license_arn(arn)
    widgets.matlab_license_reconfigure_button.layout.display = (
        "inline-flex" if rotatable else "none")
    widgets.matlab_license_rotate_note.layout.display = (
        "none" if rotatable else "flex")


def wire_matlab_license_widgets(widgets: "CloudEnvironmentWidgets", *, owner, log_output) -> None:
    """Prefill the MATLAB-license view from the owner's AWS connection and
    wire the Basic "Configure license" path and the Advanced "Use existing
    secret" path -- both ending at the SAME persisted state:
    ``AWSConnection.matlab_license_secret_arn``.

    The MATLAB license ARN is ONE piece of state per connected AWS account
    -- never a separate implementation per gateway. Every cloud UI that
    shows ``widgets.matlab_license_box`` (CryoLauncher's own Cloud panel,
    ICESEE's) calls this ONE function so a direct ISSM run and an ICESEE
    run using ISSM configure and save the license identically. The license
    VALUE itself never passes through here or is rendered anywhere -- only
    the non-secret Secrets Manager ARN.

    ``owner`` is the :class:`~cryostack_src.workspace.identity.WorkspaceUser`
    whose connection record this ARN is read from / saved to.
    """
    from cryostack_src.cloud.connect import AWSConnectionStore

    #: re-entrancy guard for Configure license -- a click while a
    #: CreateSecret call is already in flight is ignored outright, never
    #: starting a second one (see _create_secret / _set_configuring).
    _license_configure_busy = False

    def _store() -> AWSConnectionStore:
        return AWSConnectionStore(user=owner)

    try:
        existing = _store().load()
        if existing is not None:
            widgets.matlab_license_arn.value = existing.matlab_license_secret_arn
    except Exception:
        pass    # unauthenticated / dev-mode build: leave the field blank
    _refresh_matlab_license_view(widgets)

    def _save(_=None) -> None:
        from cryostack_src.cloud.matlab_license import assert_not_a_license_value

        arn = (widgets.matlab_license_arn.value or "").strip()
        try:
            assert_not_a_license_value(arn)
        except ValueError as e:
            with log_output:
                print("[cloud][ERROR]", e)
            return
        store = _store()
        connection = store.load()
        if connection is None:
            with log_output:
                print("[cloud][ERROR] Connect an AWS account before setting "
                      "a MATLAB license ARN.")
            return
        store.save(connection.with_matlab_license_secret(arn))
        with log_output:
            print("[cloud] MATLAB license ARN saved." if arn
                  else "[cloud] MATLAB license ARN cleared.")
        _refresh_matlab_license_view(widgets)

    widgets.matlab_license_save_button.on_click(_save)

    def _on_reconfigure(_=None) -> None:
        """Reveal the entry form again WITHOUT touching the stored ARN or
        connection -- nothing changes unless Configure license is clicked
        again and succeeds. Never pre-fills the value field.

        Defensive no-op for CryoStack's own fixed-name managed secret (the
        button that reaches this is already hidden for that case by
        _refresh_matlab_license_view -- this guard just ensures a stray or
        programmatic call cannot reveal a form that would always fail)."""
        if _is_default_managed_matlab_license_arn(widgets.matlab_license_arn.value):
            return
        widgets.matlab_license_create_status.value = ""
        widgets.matlab_license_value.value = ""
        widgets.matlab_license_entry_box.layout.display = "flex"
        widgets.matlab_license_configured_row.layout.display = "none"

    widgets.matlab_license_reconfigure_button.on_click(_on_reconfigure)

    # -- guided setup: create/rotate the secret directly from CryoStack ---
    def _clear_raw_value() -> None:
        # the ONLY place the entered license value is ever cleared from --
        # it is never read again after create_matlab_license_secret() (or
        # the validation that precedes it) returns, success or failure.
        widgets.matlab_license_value.value = ""

    def _reconcile_license_access(execution, arn: str) -> bool:
        """Best-effort, IAM-only: if the cloud environment has already been
        prepared once (its ECS execution role exists), immediately grant
        that role read access to THIS secret ARN -- reusing exactly the
        reconciliation Prepare Cloud itself runs on every call
        (cryostack_src.cloud.drivers.aws.iam_provision.ensure_iam_resources
        -> _reconcile_matlab_license_secret), scoped to the one named
        inline policy on the ECS execution role. Never touches S3, ECR, or
        Batch compute/queue/job-definition resources, and never creates IAM
        roles that do not already exist -- if the environment has not been
        prepared yet, this is a no-op and returns False: the next Prepare
        Cloud (already required to provision compute) picks up the stored
        ARN on its own. Any failure here is swallowed -- Prepare Cloud
        remains the source of truth and can always be re-run.
        """
        from cryostack_src.cloud.drivers.aws.iam import discover_iam_resources
        from cryostack_src.cloud.drivers.aws.iam_provision import (
            ensure_iam_resources,
        )
        from cryostack_src.cloud.drivers.aws.models import AWSConfig

        try:
            config = AWSConfig(region=execution.region, credentials=execution.credentials)
            current = discover_iam_resources(config)
            if not current.ecs_execution_role:
                return False
            ensure_iam_resources(
                config,
                bucket=execution.bucket(developer_fallback=""),
                matlab_secret_arn=arn,
            )
            return True
        except Exception:  # noqa: BLE001 -- best-effort; never blocks the UI
            return False

    def _set_configuring(active: bool) -> None:
        widgets.matlab_license_create_button.disabled = active
        widgets.matlab_license_create_button.description = (
            "Configuring license..." if active else "Configure license")

    def _create_secret(_=None) -> None:
        nonlocal _license_configure_busy
        from cryostack_src.cloud.connect import resolve_cloud_execution
        from cryostack_src.cloud.connect.execution import CloudAccessError
        from cryostack_src.cloud.drivers.aws.models import AWSConfig
        from cryostack_src.cloud.drivers.aws.secrets import (
            SecretAlreadyExists,
            SecretCreateError,
            SecretDescribeError,
            SecretNameInvalid,
            create_matlab_license_secret,
            describe_matlab_license_secret,
        )

        if _license_configure_busy:
            return   # a click while an operation is already running -- ignored
        widgets.matlab_license_create_status.value = ""
        # read the raw value ONCE, into a local that is never re-read from
        # the widget after this point (the widget itself is cleared below).
        value = widgets.matlab_license_value.value or ""

        if not value.strip():
            widgets.matlab_license_create_status.value = _matlab_license_status_html(
                "Enter your MATLAB license information first.", ok=False)
            return

        # visible "in progress" state -- set BEFORE any (blocking) AWS call
        # so it renders immediately, and guaranteed to be undone below no
        # matter which branch this call takes.
        _license_configure_busy = True
        _set_configuring(True)
        widgets.matlab_license_create_status.value = _matlab_license_progress_html(
            "Configuring the MATLAB license securely in your AWS account…")

        try:
            # the currently connected AWS account/session and Region -- the
            # SAME fresh-AssumeRole resolution every other cloud operation
            # uses (cryostack_src/cloud/connect/execution.py). Guided
            # creation only makes sense for a connected BYO-AWS account --
            # developer/ambient-credential mode is refused rather than
            # silently creating the secret in the wrong (CryoStack host's
            # own) account.
            try:
                execution = resolve_cloud_execution(user=owner)
            except CloudAccessError as e:
                # reuse the SAME connection/session-failure classifier
                # every other cloud operation's failure message goes
                # through (cloud_run_controller.classify_cloud_failure) --
                # its short message never carries raw AWS CLI text.
                from cryostack_src.frontend.cryolauncher.cloud_run_controller import (
                    classify_cloud_failure,
                )
                _clear_raw_value()
                message, _detail = classify_cloud_failure(e)
                widgets.matlab_license_create_status.value = _matlab_license_status_html(
                    message, ok=False)
                with log_output:
                    print(f"[cloud][ERROR] MATLAB license configuration failed: {message}")
                return
            if not execution.is_byo:
                _clear_raw_value()
                widgets.matlab_license_create_status.value = _matlab_license_status_html(
                    "Connect an AWS account before configuring a MATLAB "
                    "license.", ok=False)
                return

            config = AWSConfig(region=execution.region, credentials=execution.credentials)

            # call Secrets Manager CreateSecret against the ONE fixed
            # CryoStack-managed name -- the value is piped to the AWS
            # CLI's stdin (see secrets.py), never passed as an argument,
            # so it cannot appear in a process listing, this call, or any
            # exception raised from it.
            try:
                result = create_matlab_license_secret(
                    config, name=DEFAULT_MATLAB_LICENSE_SECRET_NAME, value=value)
            except SecretAlreadyExists:
                # The fixed default name already exists in this AWS
                # account (e.g. a prior "Configure license" -- possibly
                # under an earlier connection to this same account --
                # already created it, but THIS connection's own local
                # record no longer names it). CryoStack never overwrites
                # a secret it did not just create, but it CAN recover its
                # own reference to it: a metadata-only DescribeSecret
                # lookup (never the value -- see secrets.py) gets the
                # existing secret's ARN, which is then persisted through
                # the EXACT SAME path a fresh Configure uses below -- so
                # "CryoStack will keep using it automatically" is actually
                # true afterward, not just stated.
                _clear_raw_value()
                try:
                    result = describe_matlab_license_secret(
                        config, name=DEFAULT_MATLAB_LICENSE_SECRET_NAME)
                except SecretDescribeError as e:
                    # never silently pretend to have recovered it -- but
                    # ALSO never discard the actual reason: distinguishing
                    # "the connected role does not have this permission
                    # yet" from any other failure is exactly what lets
                    # this be diagnosed instead of guessed at (see
                    # _sanitize_secret_describe_error).
                    message, detail = _sanitize_secret_describe_error(e)
                    widgets.matlab_license_create_status.value = _matlab_license_status_html(
                        message, ok=False)
                    with log_output:
                        print(f"[cloud][ERROR] MATLAB license recovery failed: {detail}")
                    return
                except Exception:  # noqa: BLE001 -- never let a raw exception
                    # crash the click handler (e.g. a missing AWS CLI, a
                    # network blip -- not an AWS-reported error at all).
                    widgets.matlab_license_create_status.value = _matlab_license_status_html(
                        "A MATLAB license is already configured for this "
                        "AWS account, but CryoStack could not automatically "
                        "confirm it. Please try again, or check your AWS "
                        "connection.", ok=False)
                    with log_output:
                        print("[cloud][ERROR] MATLAB license recovery failed "
                              "(unexpected error, not an AWS response).")
                    return
                widgets.matlab_license_arn.value = result["arn"]
                _save()
                reconciled = _reconcile_license_access(execution, result["arn"])
                widgets.matlab_license_create_status.value = _matlab_license_status_html(
                    "A MATLAB license is already configured for this AWS "
                    "account -- CryoStack will keep using it automatically."
                    if reconciled else
                    "A MATLAB license is already configured for this AWS "
                    "account. Run Prepare cloud to finish setting up your "
                    "cloud environment.", ok=True)
                return
            except (SecretNameInvalid, ValueError) as e:
                # backend-raised, human-authored validation text -- never
                # derived from raw AWS CLI output -- safe to show as-is.
                _clear_raw_value()
                widgets.matlab_license_create_status.value = _matlab_license_status_html(
                    str(e), ok=False)
                return
            except SecretCreateError as e:
                # the ONE place raw (sanitized-by-the-backend-but-still-
                # AWS-authored) CLI error text reaches this function --
                # e.g. CreateSecret AccessDenied, whose message embeds the
                # STS assumed-role ARN. Never shown to Basic mode as-is;
                # only a short, categorized, human message is, and only a
                # short technical phrase (never the raw text) reaches the
                # Run Log.
                _clear_raw_value()
                message, detail = _sanitize_secret_create_error(e)
                widgets.matlab_license_create_status.value = _matlab_license_status_html(
                    message, ok=False)
                with log_output:
                    print(f"[cloud][ERROR] MATLAB license configuration failed: {detail}")
                return
            except Exception:  # noqa: BLE001 -- never let a raw exception surface
                _clear_raw_value()
                widgets.matlab_license_create_status.value = _matlab_license_status_html(
                    "Could not configure the MATLAB license. Please try "
                    "again, or check your AWS connection.", ok=False)
                with log_output:
                    print("[cloud][ERROR] MATLAB license configuration failed "
                          "(unexpected error).")
                return

            # populate the (authoritative) ARN field and persist it through
            # the EXISTING save path -- never a second persistence
            # mechanism -- then clear the raw value immediately.
            widgets.matlab_license_arn.value = result["arn"]
            _clear_raw_value()
            _save()

            # configure required cloud access now, if it is already
            # knowable (the environment has been prepared before) -- IAM-
            # only, never a duplicate of full Prepare Cloud. See
            # _reconcile_license_access.
            reconciled = _reconcile_license_access(execution, result["arn"])

            widgets.matlab_license_create_status.value = _matlab_license_status_html(
                "MATLAB license configured." if reconciled else
                "MATLAB license configured. Run Prepare cloud to finish "
                "setting up your cloud environment.", ok=True)
        finally:
            _license_configure_busy = False
            _set_configuring(False)

    widgets.matlab_license_create_button.on_click(_create_secret)


def wire_institutional_connection_widgets(
    widgets: "CloudEnvironmentWidgets",
    *,
    check_connected,
    session_state,
    open_connector,
    disconnect,
    app: str,
    log_output,
):
    """Wire the INSTITUTIONAL CONNECTION box to the CALLER's existing
    Connector state -- ``check_connected``/``session_state``/
    ``open_connector``/``disconnect`` are the gateway's own Remote-
    connection callables (its ``_connector_is_online``/``SESSION``/
    ``create_or_refresh_connector_session``/``disconnect_connector``),
    reading and driving the SAME Connector binding/session Remote uses.
    This function creates no Connector implementation, pairing, identity,
    or session of its own -- it only renders whatever state those
    callables report, so pairing (or disconnecting) in Remote is
    reflected here on the next refresh, and vice versa.

    Cloud completes the ENTIRE compact pairing flow Remote offers --
    not connected -> waiting (pairing code + pairing-page link) ->
    connected -- using the SAME presentation helpers Remote renders with
    (``connector_pairing_status_html``/``connector_pairing_link_html``
    from ``shared_remote_connection_panel``), never a re-implementation.
    A scientist never has to switch to Remote merely to pair.

    Returns a ``refresh()`` the caller can invoke whenever Remote's own
    Connector state changes, so Cloud stays in sync without polling.
    """
    from icesee_jupyter_book.ui.shared_remote_connection_panel import (
        connector_pairing_link_html,
        connector_pairing_status_html,
    )

    def refresh(_=None) -> None:
        try:
            connected = bool(check_connected())
        except Exception:
            connected = False
        try:
            session = dict(session_state() or {})
        except Exception:
            session = {}
        session_id = session.get("id")

        if connected:
            widgets.institutional_connection_status.value = status_badge(
                "success", label="CryoStack Connector connected")
            widgets.institutional_connection_pairing_info.value = ""
            widgets.institutional_connection_pairing_link.value = ""
        elif session_id:
            # Waiting: a session exists but the Connector has not paired
            # yet -- show the SAME pairing code/link Remote shows, off the
            # SAME session, so the scientist never needs to switch modes.
            widgets.institutional_connection_status.value = status_badge(
                "warning", label="Waiting for Connector")
            widgets.institutional_connection_pairing_info.value = (
                connector_pairing_status_html(
                    session_id=session_id,
                    pairing_code=session.get("pairing_code"), online=False,
                )
            )
            widgets.institutional_connection_pairing_link.value = (
                connector_pairing_link_html(session_id=session_id, app=app)
            )
        else:
            widgets.institutional_connection_status.value = status_badge(
                "idle", label="Connector not connected")
            widgets.institutional_connection_pairing_info.value = ""
            widgets.institutional_connection_pairing_link.value = ""

        # Open Connector... only while there is no session yet; once one
        # exists (waiting or connected) Re-check/Disconnect take over --
        # re-creating a session is never needed to refresh status.
        widgets.institutional_connection_open_button.layout.display = (
            "none" if session_id else "inline-flex")
        widgets.institutional_connection_recheck_button.layout.display = (
            "inline-flex" if session_id else "none")
        widgets.institutional_connection_disconnect_button.layout.display = (
            "inline-flex" if session_id else "none")

    def _open(_=None) -> None:
        try:
            open_connector()
        except Exception as e:  # noqa: BLE001 - never break the panel
            with log_output:
                print("[cloud][ERROR]", type(e).__name__, e)
        # Visible immediately -- the scientist never needs to change
        # execution mode or reload the page to see the pairing code.
        refresh()

    def _disconnect(_=None) -> None:
        try:
            disconnect()
        except Exception as e:  # noqa: BLE001 - never break the panel
            with log_output:
                print("[cloud][ERROR]", type(e).__name__, e)
        refresh()

    widgets.institutional_connection_open_button.on_click(_open)
    widgets.institutional_connection_recheck_button.on_click(refresh)
    widgets.institutional_connection_disconnect_button.on_click(_disconnect)
    refresh()
    return refresh


def set_review_panel(widgets: "CloudEnvironmentWidgets", review) -> None:
    """Render the REVIEW CLOUD RUN body from a ``CloudRunReview`` (no secrets)."""
    r = review
    infra = r.infrastructure
    basis = "".join(f"<div>{escape_text(line)}</div>" for line in r.estimate_basis_lines())
    blocked = ""
    if not r.can_launch:
        items = "".join(f"<li>{escape_text(x)}</li>" for x in r.blocked_reasons)
        blocked = (
            "<div style='font-size:11px;color:#b23c3c;background:#fdf1f1;"
            "border:1px solid #f0d5d5;border-radius:6px;padding:8px;margin-top:6px;'>"
            f"<b>Launch is blocked:</b><ul style='margin:4px 0 0 16px;padding:0;'>{items}</ul>"
            "</div>"
        )
    image_rows = ""
    if getattr(r, "image_reference", ""):
        ref = escape_text(r.image_reference)
        url = getattr(r, "image_public_url", "") or ""
        ref_html = (f"<a href='{escape_text(url)}' target='_blank' "
                    f"rel='noopener noreferrer'>{ref}</a>") if url else ref
        digest = escape_text(r.image_digest or "")
        short = (digest[:22] + "…") if digest.startswith("sha256:") else digest
        image_rows = (
            '<tr><td colspan="2" style="padding-top:6px;font-weight:700;'
            'color:#172033;">Container image</td></tr>'
            f'<tr><td style="padding:1px 12px 1px 0;">Image</td><td>{ref_html} '
            '<span style="color:#96a1b4;">· Tested</span></td></tr>'
            f'<tr><td style="padding:1px 12px 1px 0;">Digest</td>'
            f'<td><code style="font-size:10px;">{short or "—"}</code></td></tr>'
        )

    # ISSM only: a distinct readiness row -- "container image ready" is NOT
    # "ISSM runtime ready" (ISSM drives MATLAB, which needs a license
    # reachable from AWS).
    runtime_row = ""
    _issm_ready = getattr(r, "issm_runtime_ready", None)
    if _issm_ready is not None:
        val = (_yn(True) if _issm_ready
               else "<span style='color:#b23c3c;'>Needs a MATLAB license</span>")
        runtime_row = (
            '<tr><td style="padding:1px 12px 1px 0;">ISSM runtime</td>'
            f'<td>{val}</td></tr>'
        )

    widgets.review_body.value = f"""
      <table style="font-size:11px;color:#66758d;border-collapse:collapse;width:100%;">
        <tr><td colspan="2" style="padding-top:4px;font-weight:700;color:#172033;">Experiment</td></tr>
        <tr><td style="padding:1px 12px 1px 0;width:130px;">Model</td><td>{escape_text(r.model.upper())}</td></tr>
        <tr><td style="padding:1px 12px 1px 0;">Example</td><td>{escape_text(r.example)}</td></tr>
        {image_rows}
        <tr><td colspan="2" style="padding-top:6px;font-weight:700;color:#172033;">AWS</td></tr>
        <tr><td style="padding:1px 12px 1px 0;">Account</td><td><code>{escape_text(r.account_id)}</code></td></tr>
        <tr><td style="padding:1px 12px 1px 0;">Region</td><td>{escape_text(r.region)}</td></tr>
        <tr><td colspan="2" style="padding-top:6px;font-weight:700;color:#172033;">Resources</td></tr>
        <tr><td style="padding:1px 12px 1px 0;">vCPU</td><td>{r.vcpu:g}</td></tr>
        <tr><td style="padding:1px 12px 1px 0;">Memory</td><td>{r.memory_gib:g} GiB</td></tr>
        <tr><td style="padding:1px 12px 1px 0;">Time limit</td><td>{r.time_limit_minutes} min</td></tr>
        <tr><td style="padding:1px 12px 1px 0;">Expected runtime</td><td>~{_review_minutes(r.expected_runtime_minutes)} min</td></tr>
        <tr><td colspan="2" style="padding-top:6px;font-weight:700;color:#172033;">Estimated cost</td></tr>
        <tr><td style="padding:1px 12px 1px 0;"></td>
            <td><b style="font-size:14px;color:#172033;">{escape_text(r.cost_summary())}</b></td></tr>
        <tr><td style="padding:1px 12px 1px 0;vertical-align:top;">Estimate basis</td>
            <td style="font-size:10.5px;color:#8a94a6;">{basis}</td></tr>
        <tr><td colspan="2" style="padding-top:6px;font-weight:700;color:#172033;">Infrastructure</td></tr>
        <tr><td style="padding:1px 12px 1px 0;">Account</td><td>{_yn(infra.account)}</td></tr>
        <tr><td style="padding:1px 12px 1px 0;">Storage</td><td>{_yn(infra.storage)}</td></tr>
        <tr><td style="padding:1px 12px 1px 0;">Container image</td><td>{_yn(infra.container)}</td></tr>
        <tr><td style="padding:1px 12px 1px 0;">Compute ({escape_text(r.compute_backend_label)})</td><td>{_yn(infra.compute)}</td></tr>
        {runtime_row}
      </table>
      {blocked}
    """
    widgets.launch_button.disabled = not r.can_launch


def show_review_panel(widgets: "CloudEnvironmentWidgets", visible: bool) -> None:
    widgets.review_panel.layout.display = "flex" if visible else "none"


def _review_minutes(minutes: float) -> str:
    m = float(minutes)
    return f"{m:.0f}" if m >= 1 else f"{m:.1f}"


# ---------------------------------------------------------------------------
# CLOUD RUN active-run surface (C7.5)
# ---------------------------------------------------------------------------
#: CryoStack run state -> (badge state, user-facing label)
_RUN_STATE_LABELS = {
    "staging": ("running", "Staging…"),
    "submitting": ("running", "Submitting…"),
    "queued": ("running", "Queued"),
    "running": ("running", "Running"),
    "completed": ("done", "Completed"),
    "failed": ("fail", "Failed"),
    "cancelled": ("idle", "Cancelled"),
}


def _build_active_run_section() -> dict:
    """The compact CLOUD RUN status card shown while a launched run is active
    (and on its terminal state). No AWS plumbing on this surface."""

    title = W.HTML()
    status = W.HTML()
    detail = W.HTML()
    diagnostics = W.HTML()      # AWS diagnostics menu -- pure links, no AWS call

    log_button = secondary_button("View log", icon="file-text")
    results_button = primary_button("View results", icon="chart-area")
    terminate_button = W.Button(description="Terminate", icon="stop",
                                button_style="danger",
                                layout=W.Layout(width="auto"))
    actions = W.HBox([log_button, results_button, terminate_button],
                     layout=W.Layout(gap="8px", flex_wrap="wrap"))

    section = W.VBox(
        [
            W.HTML("<div style='font-size:12px;font-weight:700;color:#172033;"
                   "letter-spacing:.02em;'>CLOUD RUN</div>"),
            title, status, detail, diagnostics, actions,
        ],
        layout=W.Layout(
            width="100%", gap="5px", padding="12px",
            border="1px solid #cbd6e4", background_color="#ffffff",
            display="none",
        ),
    )
    return {
        "active_run_section": section,
        "active_run_title": title,
        "active_run_status": status,
        "active_run_detail": detail,
        "active_run_diagnostics": diagnostics,
        "active_run_actions": actions,
        "active_run_log_button": log_button,
        "active_run_results_button": results_button,
        "active_run_terminate_button": terminate_button,
    }


def show_active_run(widgets: "CloudEnvironmentWidgets", visible: bool) -> None:
    widgets.active_run_section.layout.display = "flex" if visible else "none"


def aws_diagnostics_html(resources: dict | None) -> str:
    """The AWS diagnostics menu as an HTML snippet -- a labelled row of
    external links built PURELY from a run's persisted resource snapshot
    (:func:`cryostack_src.cloud.diagnostics.aws_console_links`). No AWS call.
    Empty string when nothing can be linked yet."""
    from cryostack_src.cloud.diagnostics import aws_console_links

    links = aws_console_links(resources)
    if not links:
        return ""
    items = " &nbsp;·&nbsp; ".join(
        f"<a href='{escape_text(x['url'])}' target='_blank' "
        f"rel='noopener noreferrer' title='{escape_text(x.get('detail') or '')}'>"
        f"{escape_text(x['label'])}</a>"
        for x in links
    )
    return (
        "<div style='font-size:10.5px;color:#66758d;margin-top:2px;'>"
        "<span style='color:#8a94a6;font-weight:600;'>AWS diagnostics</span> "
        "&nbsp; " + items + "</div>"
    )


def set_active_run_view(
    widgets: "CloudEnvironmentWidgets",
    *,
    model: str = "",
    example: str = "",
    state: str = "",
    account_id: str = "",
    region: str = "",
    resource_text: str = "",
    elapsed_text: str = "",
    cost_text: str = "",
    expected_text: str = "",
    image_reference: str = "",
    image_digest: str = "",
    image_label: str = "",
    aws_resources: dict | None = None,
) -> None:
    """Render the CLOUD RUN card. ``cost_text`` is a pre-formatted string
    ("<$0.01" / "$0.04" / "Unavailable") -- this function never prices, and
    the diagnostics menu it renders makes no AWS call."""
    badge_state, label = _RUN_STATE_LABELS.get(state, ("running", state or "…"))
    terminal = state in ("completed", "failed", "cancelled")
    running = state in ("staging", "submitting", "queued", "running")

    widgets.active_run_title.value = (
        f"<div style='font-size:12px;color:#66758d;'>"
        f"{escape_text(model.upper())} &middot; {escape_text(example)}</div>"
    )
    pulse = (
        "<span aria-hidden='true' style='display:inline-block;width:7px;"
        "height:7px;border-radius:50%;background:#2f6feb;margin-right:6px;"
        "animation:cryostackPulse 1.4s ease-in-out infinite;'></span>"
        "<style>@keyframes cryostackPulse{0%,100%{opacity:.3}50%{opacity:1}}</style>"
        if running else ""
    )
    widgets.active_run_status.value = (
        f"<div role='status' style='font-size:12px;'>{pulse}"
        f"{status_badge(badge_state, label=label)}</div>"
    )

    rows = [("AWS", f"Account {escape_text(account_id or '—')} &middot; "
                    f"{escape_text(region or '—')}"),
            ("Resources", escape_text(resource_text or "—"))]
    if image_reference:
        _short = image_digest[:19] + "…" if image_digest.startswith("sha256:") else ""
        rows.append(("Image",
                     f"<code style='font-size:10px;'>{escape_text(image_reference)}</code>"
                     + (f" <span style='color:#96a1b4;'>{escape_text(_short)}</span>"
                        if _short else "")))
    if not terminal:
        rows.append(("Elapsed", escape_text(elapsed_text or "00:00")))
        rows.append(("Estimated cost so far",
                     f"{escape_text(cost_text or '—')} "
                     "<span style='color:#96a1b4;'>(estimate)</span>"))
        rows.append(("Expected runtime", escape_text(expected_text or "—")))
    body = "".join(
        f"<tr><td style='padding:1px 12px 1px 0;color:#8a94a6;white-space:nowrap;'>"
        f"{k}</td><td style='color:#66758d;'>{v}</td></tr>"
        for k, v in rows
    )
    note = (
        "<div style='font-size:10px;color:#96a1b4;margin-top:4px;'>Estimated AWS "
        "usage cost. Promotional credits and billing are managed by AWS.</div>"
        if not terminal else ""
    )
    widgets.active_run_detail.value = (
        f"<table style='font-size:11px;border-collapse:collapse;'>{body}</table>{note}"
    )
    widgets.active_run_diagnostics.value = aws_diagnostics_html(aws_resources)

    widgets.active_run_terminate_button.layout.display = (
        "none" if terminal else "inline-flex"
    )
    widgets.active_run_results_button.disabled = state != "completed"


def build_cloud_environment_card(
    *,
    region: str = "us-east-2",
    profile: str = "",
    s3_prefix: str = "",
    job_queue: str = "",
    job_definition: str = "",
    job_name: str = "icesheets",
    matlab_license_secret_arn: str = "",
    aws_batch_compute: str = "fargate",
    ec2_max_vcpus: int = 16,
    ec2_instance_types: str = "optimal",
    ec2_capacity: str = "on_demand",
    ec2_accelerator: str = "none",
    ec2_network: str = "default",
    ec2_topology: str = "single_node",
    ec2_vpc_id: str = "",
    ec2_subnet_ids: str = "",
    ec2_security_group_ids: str = "",
    ec2_node_count: int = 2,
) -> CloudEnvironmentWidgets:
    """
    Build the ICESEE Cloud Environment panel.

    The default view contains only cloud settings meaningful to most
    users. Existing AWS infrastructure fields remain available under
    Advanced so current functionality is preserved.
    """

    # ---------------------------------------------------------
    # Primary cloud configuration
    # ---------------------------------------------------------

    provider_widget = W.Dropdown(
        description="Provider:",
        options=[
            ("Amazon Web Services", "aws"),
        ],
        value="aws",
        layout=W.Layout(
            width="100%",
        ),
        style={
            "description_width": "110px",
        },
    )

    region_widget = W.Text(
        description="Region:",
        value=region,
        placeholder="us-east-2",
        layout=W.Layout(
            width="100%",
        ),
        style={
            "description_width": "110px",
        },
    )

    # ---------------------------------------------------------
    # Environment state
    # ---------------------------------------------------------

    account_row, account_status = _status_row(
        "Account",
        state="idle",
        text="Not connected",
    )

    storage_row, storage_status = _status_row(
        "Storage",
        state="idle",
        text="Not prepared",
    )

    registry_row, registry_status = _status_row(
        "Containers",
        state="idle",
        text="Not prepared",
    )

    compute_row, compute_status = _status_row(
        "Compute",
        state="idle",
        text="Not prepared",
    )

    status_panel = W.VBox(
        [
            account_row,
            storage_row,
            registry_row,
            compute_row,
        ],
        layout=W.Layout(
            width="100%",
            gap="2px",
            padding="6px 0",
        ),
    )

    # ---------------------------------------------------------
    # Primary actions
    # ---------------------------------------------------------

    test_button = secondary_button(
        "Test connection",
        icon="plug",
    )

    prepare_button = primary_button(
        "Prepare cloud",
        icon="cloud",
    )

    actions = toolbar(
        test_button,
        prepare_button,
        gap="8px",
    )

    # ---------------------------------------------------------
    # Advanced infrastructure configuration
    # ---------------------------------------------------------

    profile_widget = W.Text(
        description="Profile:",
        value=profile,
        placeholder="Optional AWS profile",
        layout=W.Layout(
            width="100%",
        ),
        style={
            "description_width": "110px",
        },
    )

    s3_prefix_widget = W.Text(
        description="S3 bucket:",
        value=s3_prefix,
        placeholder="cryostack-runs-<account-id>  (or s3://<bucket>)",
        layout=W.Layout(
            width="100%",
        ),
        style={
            "description_width": "110px",
        },
    )

    job_queue_widget = W.Text(
        description="Queue:",
        value=job_queue,
        placeholder="AWS Batch job queue",
        layout=W.Layout(
            width="100%",
        ),
        style={
            "description_width": "110px",
        },
    )

    job_definition_widget = W.Text(
        description="Job definition:",
        value=job_definition,
        placeholder="job-definition[:revision]",
        layout=W.Layout(
            width="100%",
        ),
        style={
            "description_width": "110px",
        },
    )

    job_name_widget = W.Text(
        description="Job name:",
        value=job_name,
        placeholder="icesheets",
        layout=W.Layout(
            width="100%",
        ),
        style={
            "description_width": "110px",
        },
    )

    advanced_caption = W.HTML(
        value=(
            "<div style='font-size:11px;color:#96a1b4;line-height:1.45;'>"
            "<b>Leave these fields blank</b> to use the CryoStack-prepared "
            "resources for the connected AWS account (bucket, queue and job "
            "definition are derived automatically). Set a field only to "
            "override that specific resource."
            "</div>"
        ),
    )

    # -- Compute environment: Fargate (default) or EC2 (advanced) --------
    compute_mode_widget = W.Dropdown(
        description="Compute:",
        options=[
            ("Fargate — serverless (default)", "fargate"),
            ("EC2 — managed instances (advanced)", "ec2"),
        ],
        value=("ec2" if str(aws_batch_compute).strip().lower() == "ec2"
               else "fargate"),
        layout=W.Layout(width="100%"),
        style={"description_width": "110px"},
    )
    ec2_max_vcpus_widget = W.IntText(
        description="Max vCPUs:",
        value=int(ec2_max_vcpus or 16),
        layout=W.Layout(width="100%"),
        style={"description_width": "110px"},
    )
    ec2_instance_types_widget = W.Text(
        description="Instance types:",
        value=(ec2_instance_types or "optimal"),
        placeholder="optimal   (or e.g. c5,m5,r5)",
        layout=W.Layout(width="100%"),
        style={"description_width": "110px"},
    )
    ec2_options_caption = W.HTML(
        value=(
            "<div style='font-size:11px;color:#96a1b4;line-height:1.45;'>"
            "EC2 runs on managed AWS Batch instances (scale-to-zero when idle) "
            "for heavier CPU / memory than Fargate allows. CryoStack manages "
            "the AMI, the ECS instance role and scaling; you only choose the "
            "ceiling and instance families. <b>optimal</b> lets AWS pick. "
            "Fargate stays the default and is always available."
            "</div>"
        ),
    )
    # -- EC2 sub-modes: capacity / accelerator / network / topology --------
    # Progressive disclosure -- each dropdown reveals ONLY its own extra
    # controls, and only while EC2 is the selected compute mode. Every
    # default is the plain, always-valid case (On-Demand, no accelerator,
    # the discovered default VPC, single node).
    ec2_capacity_widget = W.Dropdown(
        description="Capacity:",
        options=[("On-Demand (default)", "on_demand"), ("Spot", "spot")],
        value=("spot" if str(ec2_capacity).strip().lower() == "spot" else "on_demand"),
        layout=W.Layout(width="100%"), style={"description_width": "110px"},
    )
    ec2_accelerator_widget = W.Dropdown(
        description="Accelerator:",
        options=[("None (default)", "none"), ("GPU (experimental)", "gpu")],
        value=("gpu" if str(ec2_accelerator).strip().lower() == "gpu" else "none"),
        layout=W.Layout(width="100%"), style={"description_width": "110px"},
    )
    ec2_network_widget = W.Dropdown(
        description="Network:",
        options=[("Default (discovered VPC)", "default"),
                 ("Custom / Private", "custom")],
        value=("custom" if str(ec2_network).strip().lower() == "custom" else "default"),
        layout=W.Layout(width="100%"), style={"description_width": "110px"},
    )
    ec2_topology_widget = W.Dropdown(
        description="Execution:",
        options=[("Single node (default)", "single_node"),
                 ("Multi-node (experimental)", "multi_node")],
        value=("multi_node" if str(ec2_topology).strip().lower() == "multi_node"
               else "single_node"),
        layout=W.Layout(width="100%"), style={"description_width": "110px"},
    )

    ec2_vpc_id_widget = W.Text(
        description="VPC id:", value=(ec2_vpc_id or ""),
        placeholder="vpc-xxxxxxxx (optional -- inferred from the subnets if blank)",
        layout=W.Layout(width="100%"), style={"description_width": "110px"},
    )
    ec2_subnet_ids_widget = W.Text(
        description="Subnet ids:", value=(ec2_subnet_ids or ""),
        placeholder="subnet-aaa, subnet-bbb",
        layout=W.Layout(width="100%"), style={"description_width": "110px"},
    )
    ec2_security_group_ids_widget = W.Text(
        description="Security groups:", value=(ec2_security_group_ids or ""),
        placeholder="sg-aaa, sg-bbb   (optional)",
        layout=W.Layout(width="100%"), style={"description_width": "110px"},
    )
    ec2_network_caption = W.HTML(
        value=(
            "<div style='font-size:11px;color:#96a1b4;line-height:1.45;'>"
            "Place the EC2 compute environment into a VPC you already control "
            "instead of the discovered default VPC -- e.g. one already routed "
            "to a private/campus network. CryoStack does not create any VPN, "
            "Direct Connect, Transit Gateway or firewall rule; the VPC must "
            "already have whatever route it needs."
            "</div>"
        ),
    )
    ec2_network_box = W.VBox(
        [ec2_network_caption, ec2_vpc_id_widget, ec2_subnet_ids_widget,
         ec2_security_group_ids_widget],
        layout=W.Layout(width="100%", gap="5px"),
    )
    ec2_network_box.layout.display = (
        "flex" if ec2_network_widget.value == "custom" else "none")

    ec2_node_count_widget = W.IntText(
        description="Node count:", value=int(ec2_node_count or 2),
        layout=W.Layout(width="100%"), style={"description_width": "110px"},
    )
    ec2_multinode_caption = W.HTML(
        value=(
            "<div style='font-size:11px;color:#96a1b4;line-height:1.45;'>"
            "<b>Experimental.</b> Registers an AWS Batch multi-node parallel "
            "job definition (EC2 only). CryoStack's scientific runners do not "
            "yet establish distributed MPI across Batch nodes, so a "
            "scientific run is blocked until that runtime support lands -- "
            "this stages the infrastructure ahead of it."
            "</div>"
        ),
    )
    ec2_multinode_box = W.VBox(
        [ec2_multinode_caption, ec2_node_count_widget],
        layout=W.Layout(width="100%", gap="5px"),
    )
    ec2_multinode_box.layout.display = (
        "flex" if ec2_topology_widget.value == "multi_node" else "none")

    ec2_gpu_caption = W.HTML(
        value=(
            "<div style='font-size:11px;color:#96a1b4;line-height:1.45;'>"
            "<b>Experimental.</b> Stages GPU-capable EC2 infrastructure. The "
            "qualified CryoStack container image has no CUDA runtime, so a "
            "GPU job is blocked at submission until a GPU-qualified image is "
            "available."
            "</div>"
        ),
    )
    ec2_gpu_caption.layout.display = (
        "flex" if ec2_accelerator_widget.value == "gpu" else "none")

    ec2_options_box = W.VBox(
        [ec2_options_caption, ec2_max_vcpus_widget, ec2_instance_types_widget,
         ec2_capacity_widget, ec2_accelerator_widget, ec2_gpu_caption,
         ec2_network_widget, ec2_network_box,
         ec2_topology_widget, ec2_multinode_box],
        layout=W.Layout(width="100%", gap="5px"),
    )
    ec2_options_box.layout.display = (
        "flex" if compute_mode_widget.value == "ec2" else "none")

    def _on_compute_mode_change(change):
        ec2_options_box.layout.display = (
            "flex" if change.get("new") == "ec2" else "none")

    def _on_network_change(change):
        ec2_network_box.layout.display = (
            "flex" if change.get("new") == "custom" else "none")

    def _on_topology_change(change):
        ec2_multinode_box.layout.display = (
            "flex" if change.get("new") == "multi_node" else "none")

    def _on_accelerator_change(change):
        ec2_gpu_caption.layout.display = (
            "flex" if change.get("new") == "gpu" else "none")

    compute_mode_widget.observe(_on_compute_mode_change, names="value")
    ec2_network_widget.observe(_on_network_change, names="value")
    ec2_topology_widget.observe(_on_topology_change, names="value")
    ec2_accelerator_widget.observe(_on_accelerator_change, names="value")

    # ---------------------------------------------------------
    # MATLAB license -- Basic: only the license value. AWS Secrets
    # Manager, ARNs, secret names, MLM_LICENSE_FILE, and IAM are
    # implementation detail CryoStack handles; they appear only inside
    # "Advanced license configuration" below, for the power user who
    # manages their own secret.
    # ---------------------------------------------------------

    matlab_license_heading = W.HTML(
        value=(
            "<div style='font-size:12px;font-weight:700;color:#172033;"
            "letter-spacing:.02em;margin-top:2px;'>MATLAB LICENSE</div>"
        ),
    )

    matlab_license_caption = W.HTML(
        value=(
            "<div style='font-size:11px;color:#66758d;line-height:1.45;'>"
            "ISSM requires a MATLAB license for cloud execution. Enter the "
            "license information provided by your institution. CryoStack "
            "securely configures it in your connected AWS account. This is "
            "normally required only once."
            "</div>"
            "<div style='font-size:10px;color:#96a1b4;line-height:1.4;"
            "margin-top:3px;'>"
            "The MATLAB license service must be reachable from the cloud "
            "environment."
            "</div>"
        ),
    )

    matlab_license_value_widget = W.Password(
        description="MATLAB license:",
        placeholder="e.g. 27000@license.example.edu",
        layout=W.Layout(
            width="100%",
        ),
        style={
            "description_width": "150px",
        },
    )
    matlab_license_create_button = secondary_button(
        "Configure license",
        icon="lock",
    )
    matlab_license_create_status = W.HTML(value="")

    matlab_license_entry_box = W.VBox(
        [
            matlab_license_caption,
            matlab_license_value_widget,
            matlab_license_create_button,
            matlab_license_create_status,
        ],
        layout=W.Layout(
            width="100%",
            gap="5px",
        ),
    )

    # -- configured state: never redisplay the raw or stored secret value,
    # only a status line + a way to reconfigure it.
    matlab_license_configured_status = W.HTML(
        value=(
            "<div style='font-size:11px;color:#2f8f4e;'>"
            "&#10003; MATLAB license configured</div>"
        ),
    )
    matlab_license_reconfigure_button = secondary_button(
        "Reconfigure",
        icon="pencil",
    )
    # -- shown INSTEAD of the Reconfigure button when the configured ARN
    # names CryoStack's own fixed-name managed secret: there is currently
    # no in-app way to change that secret's value (no PutSecretValue path),
    # so offering an active "Reconfigure" form there would always fail --
    # this tells the truth up front instead. See
    # _is_default_managed_matlab_license_arn / _refresh_matlab_license_view.
    matlab_license_rotate_note = W.HTML(
        value=(
            "<div style='font-size:10.5px;color:#8a94a6;'>"
            "To change it, update the secret directly in AWS Secrets "
            "Manager.</div>"
        ),
        layout=W.Layout(display="none"),
    )
    matlab_license_configured_row = W.HBox(
        [
            matlab_license_configured_status,
            matlab_license_reconfigure_button,
            matlab_license_rotate_note,
        ],
        layout=W.Layout(
            width="100%",
            gap="10px",
            align_items="center",
        ),
    )

    # -- Advanced (secondary, visually subordinate): a power/institutional
    # user who already manages their own AWS Secrets Manager secret can
    # point CryoStack at its ARN directly. This is the ONLY place the ARN
    # / secret-name / Secrets Manager terminology is shown by default.
    matlab_license_advanced_caption = W.HTML(
        value=(
            "<div style='font-size:10.5px;color:#8a94a6;line-height:1.4;'>"
            "If you already manage your own AWS Secrets Manager secret for "
            "the MATLAB license, paste its ARN below instead of using "
            "Configure license above. Paste the secret's ARN only -- never "
            "the license value itself."
            "</div>"
        ),
    )
    matlab_license_arn_widget = W.Text(
        description="Existing secret ARN:",
        value=matlab_license_secret_arn,
        placeholder="arn:aws:secretsmanager:<region>:<account>:secret:<name>",
        layout=W.Layout(
            width="100%",
        ),
        style={
            "description_width": "150px",
        },
    )
    matlab_license_save_button = secondary_button(
        "Use existing secret",
        icon="link",
    )
    matlab_license_advanced_body = W.VBox(
        [
            matlab_license_advanced_caption,
            matlab_license_arn_widget,
            matlab_license_save_button,
        ],
        layout=W.Layout(
            width="100%",
            gap="5px",
            padding="6px 0",
        ),
    )
    matlab_license_advanced = W.Accordion(
        children=[
            matlab_license_advanced_body,
        ],
        selected_index=None,
        layout=W.Layout(
            width="100%",
        ),
    )
    matlab_license_advanced.set_title(
        0,
        "Advanced license configuration",
    )

    advanced_body = W.VBox(
        [
            advanced_caption,
            profile_widget,
            s3_prefix_widget,
            job_queue_widget,
            job_definition_widget,
            job_name_widget,
            compute_mode_widget,
            ec2_options_box,
        ],
        layout=W.Layout(
            width="100%",
            gap="5px",
            padding="6px 0",
        ),
    )

    # Independent of the Advanced cloud settings accordion -- and of
    # Basic/Advanced mode -- so a workflow that needs MATLAB (ISSM, or an
    # ICESEE run whose forecast model is ISSM) always shows this box, even
    # in Basic mode. Visibility is set by the caller (the gateway) from
    # cryostack_src.models.workflow_capabilities, not from a Basic/Advanced
    # or model-name check here. Defaults hidden; the gateway sets it
    # correctly on first render. Basic/Advanced mode instead controls how
    # much AWS implementation detail is exposed WITHIN this box (the entry
    # form above vs. the nested "Advanced license configuration" accordion).
    matlab_license_box = W.VBox(
        [
            matlab_license_heading,
            matlab_license_entry_box,
            matlab_license_configured_row,
            matlab_license_advanced,
        ],
        layout=W.Layout(
            width="100%",
            gap="5px",
            display="none",
        ),
    )

    # ---------------------------------------------------------
    # INSTITUTIONAL CONNECTION -- shown immediately below the MATLAB
    # license section, only for a workflow whose already-resolved
    # CloudMatlabLicense.requires_tunnel is True (the caller sets
    # visibility, exactly like matlab_license_box above -- never a
    # Basic/Advanced or model-name check here). No tunnel/relay/
    # WebSocket/session id/token/FlexNet/vendor-daemon/host-port/
    # MLM_LICENSE_FILE wording -- the scientist only needs to know
    # CryoStack needs the Connector to reach their institution. The
    # Connector state shown here is Remote's own Connector binding
    # (wire_institutional_connection_widgets), never a second one.
    # ---------------------------------------------------------
    institutional_connection_heading = W.HTML(
        value=(
            "<div style='font-size:12px;font-weight:700;color:#172033;"
            "letter-spacing:.02em;margin-top:2px;'>INSTITUTIONAL CONNECTION"
            "</div>"
        ),
    )
    institutional_connection_caption = W.HTML(
        value=(
            "<div style='font-size:11px;color:#66758d;line-height:1.45;'>"
            "ISSM requires access to your institution's MATLAB license "
            "service during this cloud run."
            "</div>"
        ),
    )
    institutional_connection_status_widget = W.HTML(
        value=status_badge("idle", label="Connector not connected"),
        layout=W.Layout(width="auto"),
    )
    # The pairing-code line and the pairing-page link -- both empty until
    # a pairing attempt starts, and both rendered by the SAME presentation
    # helpers Remote uses (connector_pairing_status_html /
    # connector_pairing_link_html, wired in wire_institutional_connection_
    # widgets) -- so Cloud's pairing flow is visually and behaviourally
    # identical to Remote's, never a second implementation.
    institutional_connection_pairing_info = W.HTML(value="")
    institutional_connection_pairing_link = W.HTML(value="")
    institutional_connection_open_button = secondary_button(
        "Open Connector...", icon="plug",
    )
    institutional_connection_recheck_button = secondary_button(
        "Re-check", icon="refresh",
    )
    institutional_connection_disconnect_button = secondary_button(
        "Disconnect", icon="unlink",
    )
    institutional_connection_recheck_button.layout.display = "none"
    institutional_connection_disconnect_button.layout.display = "none"
    institutional_connection_actions = toolbar(
        institutional_connection_open_button,
        institutional_connection_recheck_button,
        institutional_connection_disconnect_button,
    )
    institutional_connection_box = W.VBox(
        [
            institutional_connection_heading,
            institutional_connection_caption,
            institutional_connection_status_widget,
            institutional_connection_pairing_info,
            institutional_connection_pairing_link,
            institutional_connection_actions,
        ],
        layout=W.Layout(
            width="100%",
            gap="5px",
            display="none",
        ),
    )

    # Initial state matches whatever ARN (if any) was passed in -- the
    # entry form for nothing configured yet, the configured status once one
    # is. Refreshed live by wire_matlab_license_widgets after this.
    _matlab_license_initially_configured = bool(
        (matlab_license_secret_arn or "").strip()
    )
    matlab_license_entry_box.layout.display = (
        "none" if _matlab_license_initially_configured else "flex"
    )
    matlab_license_configured_row.layout.display = (
        "flex" if _matlab_license_initially_configured else "none"
    )
    _matlab_license_initially_rotatable = (
        _matlab_license_initially_configured
        and not _is_default_managed_matlab_license_arn(matlab_license_secret_arn)
    )
    matlab_license_reconfigure_button.layout.display = (
        "inline-flex" if _matlab_license_initially_rotatable else "none"
    )
    matlab_license_rotate_note.layout.display = (
        "none" if _matlab_license_initially_rotatable else "flex"
    )

    advanced = W.Accordion(
        children=[
            advanced_body,
        ],
        selected_index=None,
        layout=W.Layout(
            width="100%",
        ),
    )

    advanced.set_title(
        0,
        "Advanced cloud settings",
    )

    # ---------------------------------------------------------
    # Card
    # ---------------------------------------------------------

    heading = W.HTML(
        value="""
        <div style="margin-bottom:4px;">
          <div
            style="
              font-size:13px;
              font-weight:700;
              color:#172033;
            "
          >
            Cloud Environment
          </div>

          <div
            style="
              margin-top:3px;
              font-size:11px;
              color:#66758d;
              line-height:1.45;
            "
          >
            Connect your cloud account and let CryoStack prepare the
            resources required for this experiment.
          </div>
        </div>
        """
    )

    aws_account = _build_aws_account_section()
    run_estimate = _build_run_estimate_section()
    active_run = _build_active_run_section()

    def _invalidate_prepared_state(_change=None) -> None:
        """A compute-mode or EC2 Advanced-option change after a successful
        Prepare cloud must not leave a stale "Ready" Compute row, nor an
        open Review & Launch estimate, for a configuration that was never
        actually provisioned -- Prepare cloud must be run again. Storage
        and Containers (S3 / ECR) are compute-mode independent and are left
        as they are; only the Batch compute environment depends on this
        choice. A no-op before any Prepare has ever run (the row is already
        "Not prepared" and the estimate is already hidden)."""
        set_cloud_status(compute_status, state="idle", label="Not prepared")
        run_estimate["run_estimate_section"].layout.display = "none"
        run_estimate["review_panel"].layout.display = "none"

    compute_mode_widget.observe(_invalidate_prepared_state, names="value")
    ec2_capacity_widget.observe(_invalidate_prepared_state, names="value")
    ec2_accelerator_widget.observe(_invalidate_prepared_state, names="value")
    ec2_network_widget.observe(_invalidate_prepared_state, names="value")
    ec2_topology_widget.observe(_invalidate_prepared_state, names="value")

    infra_heading = W.HTML(
        value=(
            "<div style='font-size:12px;font-weight:700;color:#172033;"
            "letter-spacing:.02em;margin-top:2px;'>INFRASTRUCTURE</div>"
        ),
    )

    # Workflow order: connect the account, THEN choose a compute mode
    # (Fargate stays the simple default; EC2 reveals its own Advanced
    # settings) BEFORE Prepare cloud -- not after. `advanced` is placed
    # ahead of the status/actions block so a user reaches Fargate/EC2 and,
    # if EC2, Capacity/Accelerator/Network/Execution, before Prepare cloud;
    # Review & Launch only becomes available once Prepare succeeds (see
    # set_run_estimate_view / _invalidate_prepared_state below).
    body = W.VBox(
        [
            heading,
            provider_widget,
            region_widget,
            aws_account["aws_account_section"],
            advanced,
            matlab_license_box,
            institutional_connection_box,
            infra_heading,
            status_panel,
            actions,
            run_estimate["run_estimate_section"],
            run_estimate["review_panel"],
            active_run["active_run_section"],
        ],
        layout=W.Layout(
            width="100%",
            gap="7px",
        ),
    )

    container = W.VBox(
        [
            body,
        ],
        layout=W.Layout(
            width="100%",
            border="1px solid #dfe6ef",
            padding="12px",
        ),
    )

    return CloudEnvironmentWidgets(
        provider=provider_widget,
        region=region_widget,
        profile=profile_widget,

        s3_prefix=s3_prefix_widget,
        job_queue=job_queue_widget,
        job_definition=job_definition_widget,
        job_name=job_name_widget,
        matlab_license_value=matlab_license_value_widget,
        matlab_license_create_button=matlab_license_create_button,
        matlab_license_create_status=matlab_license_create_status,
        matlab_license_configured_row=matlab_license_configured_row,
        matlab_license_reconfigure_button=matlab_license_reconfigure_button,
        matlab_license_rotate_note=matlab_license_rotate_note,
        matlab_license_entry_box=matlab_license_entry_box,
        matlab_license_arn=matlab_license_arn_widget,
        matlab_license_save_button=matlab_license_save_button,
        matlab_license_advanced=matlab_license_advanced,
        matlab_license_box=matlab_license_box,

        institutional_connection_box=institutional_connection_box,
        institutional_connection_status=institutional_connection_status_widget,
        institutional_connection_pairing_info=institutional_connection_pairing_info,
        institutional_connection_pairing_link=institutional_connection_pairing_link,
        institutional_connection_open_button=institutional_connection_open_button,
        institutional_connection_recheck_button=institutional_connection_recheck_button,
        institutional_connection_disconnect_button=institutional_connection_disconnect_button,

        compute_mode=compute_mode_widget,
        ec2_max_vcpus=ec2_max_vcpus_widget,
        ec2_instance_types=ec2_instance_types_widget,
        ec2_options_box=ec2_options_box,
        ec2_capacity=ec2_capacity_widget,
        ec2_accelerator=ec2_accelerator_widget,
        ec2_network=ec2_network_widget,
        ec2_topology=ec2_topology_widget,
        ec2_vpc_id=ec2_vpc_id_widget,
        ec2_subnet_ids=ec2_subnet_ids_widget,
        ec2_security_group_ids=ec2_security_group_ids_widget,
        ec2_network_box=ec2_network_box,
        ec2_node_count=ec2_node_count_widget,
        ec2_multinode_box=ec2_multinode_box,

        account_status=account_status,
        storage_status=storage_status,
        registry_status=registry_status,
        compute_status=compute_status,

        test_button=test_button,
        prepare_button=prepare_button,

        advanced=advanced,

        container=container,

        aws_account_section=aws_account["aws_account_section"],
        aws_account_status=aws_account["aws_account_status"],
        aws_account_detail=aws_account["aws_account_detail"],
        connect_button=aws_account["connect_button"],
        connect_form=aws_account["connect_form"],
        connect_actions=aws_account["connect_actions"],
        open_setup_link=aws_account["open_setup_link"],
        role_arn_input=aws_account["role_arn_input"],
        verify_button=aws_account["verify_button"],
        recheck_button=aws_account["recheck_button"],
        disconnect_button=aws_account["disconnect_button"],
        update_role_button=aws_account["update_role_button"],
        update_role_link=aws_account["update_role_link"],
        recovery_actions=aws_account["recovery_actions"],
        retry_button=aws_account["retry_button"],
        change_account_button=aws_account["change_account_button"],
        change_account_panel=aws_account["change_account_panel"],
        change_account_notice=aws_account["change_account_notice"],
        change_account_status=aws_account["change_account_status"],
        change_setup_link=aws_account["change_setup_link"],
        change_role_arn_input=aws_account["change_role_arn_input"],
        change_verify_button=aws_account["change_verify_button"],
        change_cancel_button=aws_account["change_cancel_button"],

        run_estimate_section=run_estimate["run_estimate_section"],
        run_estimate_line=run_estimate["run_estimate_line"],
        review_button=run_estimate["review_button"],
        review_panel=run_estimate["review_panel"],
        review_body=run_estimate["review_body"],
        review_notice=run_estimate["review_notice"],
        review_back_button=run_estimate["review_back_button"],
        launch_button=run_estimate["launch_button"],

        active_run_section=active_run["active_run_section"],
        active_run_title=active_run["active_run_title"],
        active_run_status=active_run["active_run_status"],
        active_run_detail=active_run["active_run_detail"],
        active_run_diagnostics=active_run["active_run_diagnostics"],
        active_run_actions=active_run["active_run_actions"],
        active_run_log_button=active_run["active_run_log_button"],
        active_run_results_button=active_run["active_run_results_button"],
        active_run_terminate_button=active_run["active_run_terminate_button"],
    )