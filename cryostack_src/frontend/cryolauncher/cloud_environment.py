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
        description="S3 prefix:",
        value=s3_prefix,
        placeholder="s3://bucket/prefix",
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

    advanced_body = W.VBox(
        [
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

    body = W.VBox(
        [
            heading,
            provider_widget,
            region_widget,
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
    )