# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Account Connection
# File        : defaults.py
#
# Description :
#     Deterministic default resource names derived from a connected AWS
#     account id.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-09-03
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""
Default cloud resources for an assumed-role connection.

Once an account is connected, a normal user never types a bucket name, a
queue, or a job definition -- they are derived here. Batch names are already
account+region scoped (see :mod:`cryostack_src.cloud.drivers.aws.batch_config`);
only the global S3 bucket needs the account-id suffix.

Advanced/developer overrides still flow through
:func:`cryostack_src.cloud.config.resolve_cloud_config`.
"""

from __future__ import annotations

from dataclasses import dataclass

from cryostack_src.cloud.drivers.aws.batch_config import (
    ECR_REPOSITORY_NAMES,
    JOB_QUEUE_NAME,
    job_definition_name,
)

#: global S3 bucket that holds run I/O -- one per connected account
RUNS_BUCKET_PREFIX = "cryostack-runs"


def default_runs_bucket(account_id: str) -> str:
    """``cryostack-runs-<account-id>`` -- deterministic, per account."""
    account_id = (account_id or "").strip()
    if not account_id.isdigit() or len(account_id) != 12:
        raise ValueError("A 12-digit AWS account id is required to derive the bucket.")
    return f"{RUNS_BUCKET_PREFIX}-{account_id}"


@dataclass(frozen=True)
class CloudDefaults:
    account_id: str
    region: str
    bucket: str
    job_queue: str
    job_definition: str
    ecr_repository: str

    def as_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "region": self.region,
            "bucket": self.bucket,
            "job_queue": self.job_queue,
            "job_definition": self.job_definition,
            "ecr_repository": self.ecr_repository,
        }


def derive_cloud_defaults(
    *, account_id: str, region: str, model: str = "issm"
) -> CloudDefaults:
    """The full set of default resource names for a connected account."""
    model = (model or "issm").strip().lower()
    return CloudDefaults(
        account_id=(account_id or "").strip(),
        region=(region or "").strip(),
        bucket=default_runs_bucket(account_id),
        job_queue=JOB_QUEUE_NAME,
        job_definition=job_definition_name(model),
        ecr_repository=ECR_REPOSITORY_NAMES.get(model, f"cryostack-{model}"),
    )
