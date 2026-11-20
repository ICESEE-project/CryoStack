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
# SPDX-License-Identifier: MIT
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
import os
import re
import stat
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

from cryostack_src.cloud.s3_uri import S3LocationError
from cryostack_src.cloud.s3_uri import bucket_name as _s3_bucket_name

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


_RUN_PREFIX_RE = re.compile(r"\A(?:[A-Za-z0-9][A-Za-z0-9._-]{0,63}/)*\Z")


def _validate_staged_inputs(local: Path, target: str) -> None:
    """Fail before transfer on escaped targets, special files or empty code.

    Do not parse Python with the web server's interpreter: scientific images
    may legitimately use a different Python version. No model code executes.
    """
    name = Path(target)
    if name.is_absolute() or "\\" in target or ".." in name.parts:
        raise CloudStagingError("run target must be a relative path inside the staged example")
    if not target or not (local / target).is_file():
        raise CloudStagingError(f"run target {target!r} is not present in the staged run directory")
    try:
        def unreadable(error):
            raise error

        for parent, directories, files in os.walk(local, followlinks=False, onerror=unreadable):
            for entry in directories + files:
                mode = (Path(parent) / entry).lstat().st_mode
                if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                    raise CloudStagingError(
                        "staged inputs contain a symbolic link or special file; "
                        "copy ordinary input files into the example before launching")
        # Read incrementally so even an oversized whitespace-only script does
        # not allocate its entire contents in the shared web process.
        with (local / target).open("rb") as script:
            while chunk := script.read(65536):
                if chunk.strip():
                    return
        raise CloudStagingError("run target is empty; save a nonempty script before launching")
    except OSError:
        raise CloudStagingError("could not read staged inputs; check file permissions") from None


def stage_run_inputs(
    config: AWSConfig,
    *,
    source,
    model: str,
    run_target: str,
    bucket: str,
    run_id: str | None = None,
    run_prefix: str = "",
    working_directory: str = ".",
    s3=None,
) -> CloudRunStaging:
    """Upload a staged run to ``s3://<bucket>/runs/<run-id>/input/`` and write
    the execution descriptor. Returns the S3 run location and run id.

    ``s3`` is an injectable ``callable(args: list[str]) -> (code, out, err)`` for
    ``aws s3 ...`` (defaults to the driver's ``run_aws``); it lets tests mock all
    transfer without touching AWS.
    """
    if not (bucket or "").strip():
        raise CloudStagingError("a cloud run needs an S3 bucket")
    try:                                             # accept a name or an s3:// URI
        bucket = _s3_bucket_name(bucket)
    except S3LocationError as err:
        raise CloudStagingError(str(err)) from None
    if not is_supported_cloud_model(model):
        raise CloudStagingError(
            f"model {model!r} has no supported cloud runtime yet -- not staging.")

    local = _local_dir(source)
    target = (run_target or "").strip()
    _validate_staged_inputs(local, target)

    run_id = (run_id or _mint_run_id()).strip()
    if not _RUN_ID_RE.match(run_id):
        raise CloudStagingError(f"unsafe run id: {run_id!r}")

    prefix = (run_prefix or "").strip().strip("/")
    prefix = f"{prefix}/" if prefix else ""
    if not _RUN_PREFIX_RE.match(prefix):
        raise CloudStagingError(f"unsafe run prefix: {run_prefix!r}")

    s3_run = f"s3://{bucket}/runs/{prefix}{run_id}"
    s3_input = f"{s3_run}/input"
    s3_outputs = f"{s3_run}/outputs"
    invoke = s3 or (lambda args: run_aws(config, args))

    staged_files = sorted(
        str(p.relative_to(local)) for p in local.rglob("*") if p.is_file())

    # Validate the runtime contract before transferring any participant bytes.
    descriptor = build_run_descriptor(
        model=model, run_target=target, working_directory=working_directory)
    if not descriptor_is_clean(descriptor):
        raise CloudStagingError("execution descriptor failed its no-secrets check")

    # 1. the staged tree, verbatim
    code, out, err = invoke(
        ["s3", "sync", f"{local}/", f"{s3_input}/", "--only-show-errors", "--no-follow-symlinks"])
    if code != 0:
        raise CloudStagingError(
            (err or out).strip()
            or f"failed to upload the staged run to {s3_input}/")

    # 2. the execution descriptor (inputs only -- no paths, no secrets)
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
