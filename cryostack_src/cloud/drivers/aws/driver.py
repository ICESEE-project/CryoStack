# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Driver
# File        : driver.py
#
# Description :
#     Provides the high-level AWS cloud driver used by CryoStack to
#     discover and prepare AWS resources.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-08-24
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""
AWS cloud driver for CryoStack.

The driver combines AWS authentication, storage, networking, IAM,
registry, Batch, and capability discovery behind one interface.

Resource provisioning is introduced incrementally. Storage and IAM
can currently be prepared automatically, while registry and AWS Batch
resources remain discovery-only until their provisioning layers are
completed.
"""

from __future__ import annotations

from ..base import CloudDriver

from .auth import (
    AWSCredentialsError,
    discover_account,
)

from .batch import (
    discover_batch_resources,
)

from .capabilities import (
    discover_capabilities,
)

from .iam import (
    discover_iam_resources,
)

from .iam_provision import (
    ensure_iam_resources,
)

from .models import (
    AWSConfig,
)

from .network import (
    discover_network_resources,
)

from .registry import (
    discover_registry_resources,
)

from .storage import (
    prepare_storage,
)

from .registry_provision import (
    ensure_registry_resources,
)


class AWSDriver(
    CloudDriver
):
    """
    CryoStack AWS cloud driver.
    """

    name = "aws"

    def __init__(
        self,
        *,
        region: str = "us-east-2",
        profile: str | None = None,
    ) -> None:

        self.config = AWSConfig(
            region=region,
            profile=profile,
        )

    def account(
        self,
    ):

        return discover_account(
            self.config
        )

    def capabilities(
        self,
    ):

        return discover_capabilities(
            self.config
        )

    def prepare_storage(
        self,
        *,
        bucket: str | None = None,
    ):

        return prepare_storage(
            self.config,
            bucket=bucket,
        )

    def network(
        self,
    ):

        return discover_network_resources(
            self.config
        )

    def iam(
        self,
    ):

        return discover_iam_resources(
            self.config
        )

    def registry(
        self,
    ):

        return discover_registry_resources(
            self.config
        )

    def batch(
        self,
    ):

        return discover_batch_resources(
            self.config
        )

    def bootstrap(
        self,
        *,
        bucket: str | None = None,
    ) -> dict:
        """
        Prepare the AWS environment currently supported by CryoStack.

        The bootstrap sequence currently:

        1. verifies the AWS connection,
        2. prepares S3 run storage,
        3. discovers usable networking,
        4. prepares required IAM roles,
        5. discovers ECR repositories,
        6. discovers AWS Batch resources,
        7. recalculates the final capability state.

        Registry and Batch provisioning will be added separately.
        """

        messages: list[str] = []

        #
        # ---------------------------------------------------------
        # Account
        # ---------------------------------------------------------
        #
        account = self.account()

        if not account.authenticated:

            return {
                "success": False,
                "provider": self.name,
                "region": self.config.region,
                "account": account,
                "storage": None,
                "network": None,
                "iam": None,
                "registry": None,
                "batch": None,
                "capabilities": self.capabilities(),
                "messages": [
                    "AWS account is not connected.",
                ],
            }

        messages.append(
            "AWS account connected."
        )

        #
        # ---------------------------------------------------------
        # Storage
        # ---------------------------------------------------------
        #
        try:

            storage = self.prepare_storage(
                bucket=bucket,
            )

        except AWSCredentialsError:

            return {
                "success": False,
                "provider": self.name,
                "region": self.config.region,
                "account": account,
                "storage": None,
                "network": None,
                "iam": None,
                "registry": None,
                "batch": None,
                "capabilities": None,
                "messages": [
                    "AWS credentials are not available.",
                ],
            }

        if storage.created:

            messages.append(
                "CryoStack S3 storage created."
            )

        else:

            messages.append(
                "CryoStack S3 storage already exists."
            )

        #
        # ---------------------------------------------------------
        # Network
        # ---------------------------------------------------------
        #
        network = self.network()

        if (
            network.vpc_id
            and network.subnet_ids
            and network.security_group_ids
        ):

            messages.append(
                "AWS networking discovered."
            )

        else:

            messages.append(
                "AWS networking is incomplete."
            )

        #
        # ---------------------------------------------------------
        # IAM
        # ---------------------------------------------------------
        #
        iam_result = ensure_iam_resources(
            self.config,
            bucket=storage.bucket,
        )

        iam = iam_result.resources

        if iam_result.created:

            messages.append(
                "Created IAM resources: "
                + ", ".join(
                    iam_result.created
                )
            )

        if iam_result.reused:

            messages.append(
                "Reused IAM resources: "
                + ", ".join(
                    iam_result.reused
                )
            )

        #
        # ---------------------------------------------------------
        # Registry
        # ---------------------------------------------------------
        #
        registry_result = self.prepare_registry(
            include_icepack=False,
        )

        registry = registry_result.resources

        if registry_result.created:

            messages.append(
                "Created ECR repositories: "
                + ", ".join(
                    registry_result.created
                )
            )

        if registry_result.reused:

            messages.append(
                "Reused ECR repositories: "
                + ", ".join(
                    registry_result.reused
                )
            )

        #
        # ---------------------------------------------------------
        # Batch discovery
        # ---------------------------------------------------------
        #
        batch = self.batch()

        if (
            batch.compute_environment
            and batch.job_queue
            and batch.issm_job_definition
        ):

            messages.append(
                "AWS Batch environment discovered."
            )

        else:

            messages.append(
                "AWS Batch environment is incomplete."
            )

        #
        # Recalculate after provisioning.
        #
        capabilities = self.capabilities()

        success = bool(
            capabilities.authenticated
            and capabilities.storage_ready
            and capabilities.network_ready
            and capabilities.iam_ready
        )

        return {
            "success": success,
            "provider": self.name,
            "region": self.config.region,
            "account": account,
            "storage": storage,
            "network": network,
            "iam": iam,
            "registry": registry,
            "batch": batch,
            "capabilities": capabilities,
            "messages": messages,
        }

    def prepare_registry(
        self,
        *,
        include_icepack: bool = False,
    ):

        return ensure_registry_resources(
            self.config,
            include_icepack=include_icepack,
        )