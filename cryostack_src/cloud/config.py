# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : Cloud Configuration
# File        : config.py
#
# Description :
#     Provider-neutral resolution + validation of the small set of cloud
#     configuration a user actually supplies.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-09-01
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""
Cloud run configuration.

The user supplies only what is genuinely needed:

    provider   aws
    region     us-east-2
    bucket     the S3 bucket CryoStack owns for run I/O   (or an s3://bucket[/...] URI)
    profile    optional named AWS CLI profile

Queue and job-definition names are *deterministic* -- CryoStack provisions
``cryostack-queue`` / ``cryostack-<model>`` -- so they are resolved here, not
typed by the user, though an explicit override is still accepted.

Nothing in a :class:`CloudRunConfig` is ever persisted to workspace state or
run provenance except the non-secret facts (provider, region, bucket, queue,
job definition). ``profile`` is a local CLI selector, not a credential.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from cryostack_src.cloud.drivers.aws.batch_config import (
    JOB_QUEUE_NAME,
    job_definition_name,
)

_REGION_RE = re.compile(r"\A[a-z]{2}-[a-z]+-\d\Z")
_BUCKET_RE = re.compile(r"\A[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]\Z")
_S3_URI_RE = re.compile(r"\As3://(?P<bucket>[a-z0-9][a-z0-9.-]{1,61}[a-z0-9])(?:/.*)?\Z")

DEFAULT_CLOUD_REGION = "us-east-2"
SUPPORTED_CLOUD_PROVIDERS = ("aws",)


@dataclass
class CloudRunConfig:
    provider: str = "aws"
    region: str = DEFAULT_CLOUD_REGION
    bucket: str = ""
    profile: str | None = None
    job_queue: str = ""
    job_definition: str = ""

    def provenance(self) -> dict:
        """The non-secret subset safe to record in run metadata."""
        out = {
            "provider": self.provider,
            "region": self.region,
            "bucket": self.bucket,
            "job_queue": self.job_queue,
            "job_definition": self.job_definition,
        }
        return {k: v for k, v in out.items() if v}


def _bucket_from(value: str) -> str:
    v = (value or "").strip()
    m = _S3_URI_RE.match(v)
    if m:
        return m.group("bucket")
    return v


def resolve_cloud_config(
    *,
    provider: str = "aws",
    region: str = "",
    bucket: str = "",
    profile: str = "",
    model: str = "",
    job_queue: str = "",
    job_definition: str = "",
) -> CloudRunConfig:
    """Fill deterministic defaults for anything the user did not supply."""
    provider = (provider or "aws").strip().lower()
    return CloudRunConfig(
        provider=provider,
        region=(region or "").strip() or DEFAULT_CLOUD_REGION,
        bucket=_bucket_from(bucket),
        profile=(profile or "").strip() or None,
        job_queue=(job_queue or "").strip() or JOB_QUEUE_NAME,
        job_definition=(job_definition or "").strip() or job_definition_name(model),
    )


def validate_cloud_config(config: CloudRunConfig, *, model: str = "") -> list[str]:
    """Return a list of short, actionable problems (empty == ready to submit)."""
    problems: list[str] = []

    if config.provider not in SUPPORTED_CLOUD_PROVIDERS:
        problems.append(
            f"Provider {config.provider!r} is not supported (only: "
            f"{', '.join(SUPPORTED_CLOUD_PROVIDERS)})."
        )

    if not config.region or not _REGION_RE.match(config.region):
        problems.append("Region must look like 'us-east-2'.")

    if not config.bucket:
        problems.append("An S3 bucket is required for cloud run inputs and outputs.")
    elif not _BUCKET_RE.match(config.bucket):
        problems.append(
            "S3 bucket name is not valid (lowercase letters, digits, '.', '-'; "
            "3-63 chars)."
        )

    if not config.job_queue:
        problems.append("A Batch job queue is required.")
    if not config.job_definition:
        problems.append("A Batch job definition is required.")

    return problems
