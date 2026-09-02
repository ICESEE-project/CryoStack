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
from cryostack_src.cloud.s3_uri import S3LocationError, parse_s3_location

_REGION_RE = re.compile(r"\A[a-z]{2}-[a-z]+-\d\Z")

DEFAULT_CLOUD_REGION = "us-east-2"
SUPPORTED_CLOUD_PROVIDERS = ("aws",)


@dataclass
class CloudRunConfig:
    provider: str = "aws"
    region: str = DEFAULT_CLOUD_REGION
    #: bucket **name** only -- ready for an AWS API ``Bucket=`` arg
    bucket: str = ""
    #: optional key prefix from an ``s3://bucket/some/prefix`` URI; the per-user
    #: ``runs/<safe-user>/<run-id>`` tree is nested under it
    base_prefix: str = ""
    profile: str | None = None
    job_queue: str = ""
    job_definition: str = ""
    #: the raw user input that could not be normalized (validation reports it)
    bucket_error: str = ""

    def provenance(self) -> dict:
        """The non-secret subset safe to record in run metadata."""
        out = {
            "provider": self.provider,
            "region": self.region,
            "bucket": self.bucket,
            "base_prefix": self.base_prefix,
            "job_queue": self.job_queue,
            "job_definition": self.job_definition,
        }
        return {k: v for k, v in out.items() if v}


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
    """Fill deterministic defaults and normalize the S3 location.

    ``bucket`` may be a bare name, ``s3://name``, or ``s3://name/prefix`` -- it
    is split into ``bucket`` (name only) + ``base_prefix``. A value that cannot
    be normalized is kept in ``bucket_error`` for :func:`validate_cloud_config`
    to report; this function never raises.
    """
    provider = (provider or "aws").strip().lower()
    bucket_name, base_prefix, bucket_error = "", "", ""
    if (bucket or "").strip():
        try:
            loc = parse_s3_location(bucket)
            bucket_name, base_prefix = loc.bucket, loc.prefix
        except S3LocationError as err:
            bucket_error = str(err)
    return CloudRunConfig(
        provider=provider,
        region=(region or "").strip() or DEFAULT_CLOUD_REGION,
        bucket=bucket_name,
        base_prefix=base_prefix,
        bucket_error=bucket_error,
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

    if config.bucket_error:
        problems.append(config.bucket_error)
    elif not config.bucket:
        problems.append("An S3 bucket is required for cloud run inputs and outputs.")
    else:
        try:
            parse_s3_location(config.bucket)          # revalidate the resolved name
        except S3LocationError as err:
            problems.append(str(err))

    if not config.job_queue:
        problems.append("A Batch job queue is required.")
    if not config.job_definition:
        problems.append("A Batch job definition is required.")

    return problems
