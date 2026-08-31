# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Run Input Staging
# File        : staging.py
#
# Description :
#     Uploads a StagedExample (produced by the application layer's
#     stage_example_for_run) into an S3 run prefix as cloud execution input.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-08-31
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""
AWS S3 run-input staging for CryoStack.

The application layer already produced an authoritative working copy of the
run (``WorkspaceManager.stage_example_for_run`` -> ``StagedExample``): canonical
example + user edits + Basic-mode ``cryostack_md_overrides.m`` + injected
``runme.m`` + referenced datasets under ``data/`` + ``postprocess_icesee.m``.
This helper only *transports* that tree:

    s3://<bucket>/runs/<run-id>/
    ├── input/                 <- the whole StagedExample tree, verbatim
    │   └── cryostack-run.json <- execution descriptor (model / run_target / ...)
    └── outputs/               <- written by the cloud runner

It never re-stages from canonical examples, never invents scientific files, and
never writes credentials, local user paths or a MATLAB license value.
"""

from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from cryostack_src.cloud.runtime import (
    RUN_DESCRIPTOR_NAME,
    build_run_descriptor,
    descriptor_is_clean,
    is_supported_cloud_model,
)

from .auth import run_aws
from .models import AWSConfig

_RUN_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


class CloudStagingError(RuntimeError):
    """A cloud run could not be staged; no Batch job should be submitted."""


@dataclass
class CloudRunStaging:
    run_id: str
    s3_run: str
    s3_input: str
    s3_outputs: str
    descriptor: dict
    staged_files: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


def _mint_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    import uuid

    return f"cloud-{stamp}-{uuid.uuid4().hex[:8]}"


def _local_dir(source) -> Path:
    """Accept a ``StagedExample`` (has ``.path``) or a path."""
    raw = getattr(source, "path", source)
    path = Path(raw).expanduser().resolve()
    if not path.is_dir():
        raise CloudStagingError(f"staged run directory does not exist: {path}")
    if path == Path(path.anchor):
        raise CloudStagingError("refusing to stage a filesystem root")
    return path


def stage_run_inputs(
    config: AWSConfig,
    *,
    source,
    model: str,
    run_target: str,
    bucket: str,
    run_id: str | None = None,
    working_directory: str = ".",
    s3=None,
) -> CloudRunStaging:
    """Upload a staged run to ``s3://<bucket>/runs/<run-id>/input/`` and write
    the execution descriptor. Returns the S3 run location and run id.

    ``s3`` is an injectable ``callable(args: list[str]) -> (code, out, err)`` for
    ``aws s3 ...`` (defaults to the driver's ``run_aws``); it lets tests mock all
    transfer without touching AWS.
    """
    if not bucket:
        raise CloudStagingError("a cloud run needs an S3 bucket")
    if not is_supported_cloud_model(model):
        raise CloudStagingError(
            f"model {model!r} has no supported cloud runtime yet -- not staging.")

    local = _local_dir(source)
    target = (run_target or "").strip()
    if not target or (local / target).is_file() is False:
        raise CloudStagingError(
            f"run target {run_target!r} is not present in the staged run directory")

    run_id = (run_id or _mint_run_id()).strip()
    if not _RUN_ID_RE.match(run_id):
        raise CloudStagingError(f"unsafe run id: {run_id!r}")

    s3_run = f"s3://{bucket}/runs/{run_id}"
    s3_input = f"{s3_run}/input"
    s3_outputs = f"{s3_run}/outputs"
    invoke = s3 or (lambda args: run_aws(config, args))

    staged_files = sorted(
        str(p.relative_to(local)) for p in local.rglob("*") if p.is_file())

    # 1. the staged tree, verbatim
    code, out, err = invoke(
        ["s3", "sync", f"{local}/", f"{s3_input}/", "--only-show-errors"])
    if code != 0:
        raise CloudStagingError(
            (err or out).strip()
            or f"failed to upload the staged run to {s3_input}/")

    # 2. the execution descriptor (inputs only -- no paths, no secrets)
    descriptor = build_run_descriptor(
        model=model, run_target=target, working_directory=working_directory)
    if not descriptor_is_clean(descriptor):
        raise CloudStagingError("execution descriptor failed its no-secrets check")

    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    ) as handle:
        json.dump(descriptor, handle, indent=2, sort_keys=True)
        descriptor_path = handle.name
    try:
        code, out, err = invoke(
            ["s3", "cp", descriptor_path, f"{s3_input}/{RUN_DESCRIPTOR_NAME}",
             "--only-show-errors"])
    finally:
        Path(descriptor_path).unlink(missing_ok=True)
    if code != 0:
        raise CloudStagingError(
            (err or out).strip() or "failed to upload the execution descriptor")

    staged_files.append(RUN_DESCRIPTOR_NAME)
    return CloudRunStaging(
        run_id=run_id, s3_run=s3_run, s3_input=s3_input, s3_outputs=s3_outputs,
        descriptor=descriptor, staged_files=sorted(set(staged_files)),
        messages=[f"staged {len(staged_files)} file(s) to {s3_input}/"],
    )
