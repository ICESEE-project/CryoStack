# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : Cloud Run Preflight
# File        : preflight.py
#
# Description :
#     Gates that must pass before a billable cloud job is staged or submitted.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-08-31
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: MIT
#
# =============================================================================

"""
Blocking checks for CryoStack cloud execution.

These run *before* anything is staged to S3 or submitted to Batch, so a
misconfigured run never becomes a billable job. The list is intentionally
small and provider-neutral.
"""

from __future__ import annotations

from .runtime import SUPPORTED_CLOUD_MODELS

_NO_MATLAB_LICENSE = (
    "[cloud][ERROR] ISSM cloud execution needs a MATLAB license reachable "
    "from AWS. The container image is ready, but ISSM runtime is not: add an "
    "AWS Secrets Manager secret (MLM_LICENSE_FILE value) in your AWS account "
    "and give CryoStack its ARN in Cloud Environment. The license value "
    "never leaves your account."
)

#: The marker string ``build_cloud_run_review``/``build_icesee_cloud_review``
#: look for ("CryoStack Connector") to keep this reason distinct from
#: _NO_MATLAB_LICENSE's -- telling a scientist to "add a Secrets Manager
#: ARN" when the real, already-satisfied requirement is "pair the
#: Connector" would send them down the wrong path. No tunnel/relay/session/
#: token/port wording -- the scientist only needs to know CryoStack needs
#: the Connector to reach their institution.
_NO_CONNECTOR = (
    "[cloud][ERROR] ISSM cloud execution needs your institution's MATLAB "
    "license service, which requires the CryoStack Connector. Open "
    "Connector... and pair it, then try again."
)


def cloud_run_preflight(
    *,
    model: str,
    matlab_license_configured: bool,
    compute_mode: str | None = None,
    ec2_config=None,
    connector_required: bool = False,
    connector_connected: bool = False,
) -> list[str]:
    """Return the blocking reasons for a cloud run (empty list == clear to go).

    * unknown / unsupported model -> blocked (Icepack cloud is not ready);
    * ISSM without a configured cloud MATLAB license -> blocked. The license
      value itself is never handled here -- only whether one is configured;
    * ``connector_required`` (the caller's already-resolved
      ``CloudMatlabLicense.requires_tunnel``) with no Connector paired
      (``connector_connected`` False) -> blocked, fail-closed, distinct from
      the "license not configured" reason above -- the license CAN be
      configured and this can still block. Never re-derived here: the
      caller (gateway) supplies both booleans from state it already owns
      (the workflow capability and the existing Connector binding Remote
      also reads) -- no new resolution/session/transport logic lives here;
    * an invalid AWS Batch compute selection (Spot/GPU/custom-network/multi-
      node on Fargate; GPU without a GPU-qualified image; multi-node without
      distributed-runner support) -> blocked. ``compute_mode``/``ec2_config``
      are optional and default to "no compute selection" (Fargate, plain) so
      a caller that has not adopted Advanced EC2 is unaffected.
    """
    reasons: list[str] = []
    m = (model or "").strip().lower()

    if m not in SUPPORTED_CLOUD_MODELS:
        reasons.append(
            f"[cloud][ERROR] model {model!r} has no supported cloud runtime yet."
        )
        return reasons

    # single authoritative answer to "does this workflow need MATLAB?" --
    # never "model == issm" duplicated here and in the UI/review layers,
    # which would miss e.g. an ICESEE run whose forecast model is ISSM.
    from cryostack_src.models.workflow_capabilities import (
        resolve_workflow_capabilities,
    )

    capabilities = resolve_workflow_capabilities(model=m)
    if capabilities.requires_matlab_license and not matlab_license_configured:
        reasons.append(_NO_MATLAB_LICENSE)
    elif capabilities.requires_matlab_license and connector_required and not connector_connected:
        reasons.append(_NO_CONNECTOR)

    # AWS Batch compute-mode compatibility matrix lives in ONE place
    # (drivers.aws.batch_config) so the frontend, preflight and provisioning
    # layers all apply the same rules. Lazy import: this module stays
    # provider-neutral for the common case where neither argument is passed.
    if compute_mode is not None or ec2_config is not None:
        from .drivers.aws.batch_config import validate_compute_selection

        reasons.extend(
            f"[cloud][ERROR] {reason}"
            for reason in validate_compute_selection(compute_mode, ec2_config)
        )

    return reasons


def assert_cloud_run_allowed(
    *,
    model: str,
    matlab_license_configured: bool,
    compute_mode: str | None = None,
    ec2_config=None,
    connector_required: bool = False,
    connector_connected: bool = False,
) -> None:
    reasons = cloud_run_preflight(
        model=model, matlab_license_configured=matlab_license_configured,
        compute_mode=compute_mode, ec2_config=ec2_config,
        connector_required=connector_required,
        connector_connected=connector_connected,
    )
    if reasons:
        from .runtime import CloudRuntimeError

        raise CloudRuntimeError(" ".join(reasons))
