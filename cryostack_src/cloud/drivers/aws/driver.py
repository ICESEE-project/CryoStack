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
"""

from __future__ import annotations

from ..base import CloudDriver

from .auth import (
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
    ):
        """
        Prepare the AWS environment required by CryoStack.

        Returns
        -------
        dict
            Summary of all discovered and provisioned resources.
        """

        return {
            "account": self.account(),
            "capabilities": self.capabilities(),
            "storage": self.prepare_storage(bucket=bucket),
            "network": self.network(),
            "iam": self.iam(),
            "registry": self.registry(),
            "batch": self.batch(),
        }