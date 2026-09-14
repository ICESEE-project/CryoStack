# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Models
# Component   : Workflow Capability Resolution
# File        : workflow_capabilities.py
#
# Author(s)   :
#     Brian Kyanjo
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""One authoritative statement of what a SELECTED WORKFLOW actually needs.

Before this, "does this run need a MATLAB license?" was answered by checking
``model == "issm"`` independently in the UI, preflight, and review code --
correct for a direct ISSM run, but wrong for ICESEE, which is a data-
assimilation framework that can wrap ISSM, Icepack, or (in principle) both as
its forward model. An ICESEE run whose forecast model is ISSM needs a MATLAB
license exactly like a direct ISSM run does; an ICESEE run using only Icepack
does not. Keying the check on the top-level ``model`` name alone silently
missed that case.

:func:`resolve_workflow_capabilities` is the single place that answers this
(and the analogous EC2/GPU/multi-node questions) for any caller -- UI
visibility, preflight gating, review rendering, submission -- so the answer
is always consistent and never re-derived ad hoc.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkflowCapabilities:
    """What the currently selected workflow needs and may use.

    ``uses_issm``/``uses_icepack`` are not mutually exclusive -- an ICESEE
    run may use both (a coupled forecast) or neither (e.g. the synthetic
    Lorenz-96 example, which needs no external forward model at all).
    """

    uses_issm: bool = False
    uses_icepack: bool = False
    #: True exactly when ``uses_issm`` -- ISSM is CryoStack's only
    #: MATLAB-driven forward model today. Kept as its own field (rather than
    #: inlining ``uses_issm`` at every call site) so a future MATLAB-driven
    #: model only has to change this resolver, not every caller.
    requires_matlab_license: bool = False
    #: EC2 is an AWS Batch compute-layer choice orthogonal to which forward
    #: model runs -- every current workflow may target it.
    supports_ec2: bool = True
    #: Mirrors the single global image-level fact (no CUDA runtime in the
    #: tested combined image) -- never re-derived per model.
    supports_gpu: bool = False
    #: Mirrors the single global runtime fact (no scientific runner does
    #: distributed MPI across Batch nodes yet) -- never re-derived per model.
    supports_multinode: bool = False


def resolve_workflow_capabilities(
    *, model: str, forecast_model: str = "",
) -> WorkflowCapabilities:
    """Resolve the capabilities of the currently selected workflow.

    ``model`` is the top-level CryoStack workflow selector: ``"issm"``,
    ``"icepack"``, or ``"icesee"``. For ``"issm"``/``"icepack"`` the forward
    model IS the workflow, so ``uses_issm``/``uses_icepack`` follow directly.

    ``"icesee"`` is a DA framework: which forward model(s) it drives is
    described by ``forecast_model`` (free text carried in the run's DA
    config, e.g. ``params.yaml``'s ``modeling-parameters.model_name`` --see
    ``icesee_jupyter_book.core.run_records``). It is matched case-
    insensitively for the substrings ``"issm"``/``"icepack"`` it names;
    neither matching (e.g. the synthetic ``"lorenz96"`` example) means the
    run needs no external forward model, hence no MATLAB license.
    """
    from cryostack_src.cloud.drivers.aws.batch_config import (
        GPU_IMAGE_QUALIFIED,
        MULTINODE_RUNTIME_SUPPORTED,
    )

    key = (model or "").strip().lower()
    fc = (forecast_model or "").strip().lower()

    if key == "issm":
        uses_issm, uses_icepack = True, False
    elif key == "icepack":
        uses_issm, uses_icepack = False, True
    elif key == "icesee":
        uses_issm = "issm" in fc
        uses_icepack = "icepack" in fc
    else:
        uses_issm = uses_icepack = False

    return WorkflowCapabilities(
        uses_issm=uses_issm,
        uses_icepack=uses_icepack,
        requires_matlab_license=uses_issm,
        supports_ec2=True,
        supports_gpu=GPU_IMAGE_QUALIFIED,
        supports_multinode=MULTINODE_RUNTIME_SUPPORTED,
    )
