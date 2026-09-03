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

    connect_actions = W.HBox(
        [recheck_button, disconnect_button],
        layout=W.Layout(gap="8px", display="none"),
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

    if setup_url:
        widgets.open_setup_link.value = (
            f"<a href='{escape_attr(setup_url)}' target='_blank' rel='noopener' "
            "style='font-size:12px;font-weight:600;'>▶ Open AWS Setup</a>"
        )

    if form_open is not None:
        widgets.connect_form.layout.display = "flex" if form_open else "none"

    def _show_connected_actions(show: bool) -> None:
        widgets.connect_actions.layout.display = "flex" if show else "none"

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
        return

    if status == "error":
        widgets.aws_account_status.value = status_badge("fail", label="Not verified")
        reason = summary.get("status_reason", "") or "Verification failed."
        detail.value = (
            f"<div style='font-size:11px;color:#b23c3c;line-height:1.45;'>{escape_text(reason)}</div>"
        )
        widgets.connect_button.layout.display = "none"
        widgets.connect_form.layout.display = "flex"
        _show_connected_actions(False)
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
        return

    # disconnected
    widgets.aws_account_status.value = status_badge("idle", label="Not connected")
    detail.value = (
        f"<div style='font-size:11px;color:#66758d;line-height:1.45;'>{_DISCONNECTED_BLURB}</div>"
    )
    widgets.connect_button.layout.display = "inline-flex"
    widgets.connect_form.layout.display = "none"
    _show_connected_actions(False)


def escape_text(value: str) -> str:
    from html import escape

    return escape(str(value or ""))


def escape_attr(value: str) -> str:
    from html import escape

    return escape(str(value or ""), quote=True)


def build_cloud_environment_card(
    *,
    region: str = "us-east-2",
    profile: str = "",
    s3_prefix: str = "",
    job_queue: str = "",
    job_definition: str = "",
    job_name: str = "icesheets",
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
            "Developer / override settings. Not needed when an AWS account is "
            "connected — CryoStack derives the bucket, queue and job "
            "definition automatically."
            "</div>"
        ),
    )

    advanced_body = W.VBox(
        [
            advanced_caption,
            profile_widget,
            s3_prefix_widget,
            job_queue_widget,
            job_definition_widget,
            job_name_widget,
        ],
        layout=W.Layout(
            width="100%",
            gap="5px",
            padding="6px 0",
        ),
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

    infra_heading = W.HTML(
        value=(
            "<div style='font-size:12px;font-weight:700;color:#172033;"
            "letter-spacing:.02em;margin-top:2px;'>INFRASTRUCTURE</div>"
        ),
    )

    body = W.VBox(
        [
            heading,
            provider_widget,
            region_widget,
            aws_account["aws_account_section"],
            infra_heading,
            status_panel,
            actions,
            advanced,
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
    )