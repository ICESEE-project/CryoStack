# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : Cloud Manager
# File        : manager.py
#
# Description :
#     Resolves cloud-provider drivers and exposes a provider-independent
#     interface to CryoStack cloud services.
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
High-level cloud manager for CryoStack.

CloudManager is the public entry point for cloud resource discovery
and preparation. Provider-specific behavior is delegated to cloud
drivers.
"""

from __future__ import annotations

from .drivers import (
    AWSDriver,
    CloudDriver,
)


class CloudManager:
    """
    Resolve and interact with CryoStack cloud drivers.
    """

    def driver(
        self,
        *,
        provider: str,
        region: str,
        profile: str | None = None,
    ) -> CloudDriver:

        provider_name = (
            provider
            .strip()
            .lower()
        )

        if provider_name == "aws":

            return AWSDriver(
                region=region,
                profile=profile,
            )

        raise ValueError(
            f"Unsupported cloud provider: {provider}"
        )

    def account(
        self,
        *,
        provider: str,
        region: str,
        profile: str | None = None,
    ):

        return self.driver(
            provider=provider,
            region=region,
            profile=profile,
        ).account()

    def capabilities(
        self,
        *,
        provider: str,
        region: str,
        profile: str | None = None,
    ):

        return self.driver(
            provider=provider,
            region=region,
            profile=profile,
        ).capabilities()

    def prepare_storage(
        self,
        *,
        provider: str,
        region: str,
        profile: str | None = None,
        bucket: str | None = None,
    ):

        return self.driver(
            provider=provider,
            region=region,
            profile=profile,
        ).prepare_storage(
            bucket=bucket,
        )

    def network(
        self,
        *,
        provider: str,
        region: str,
        profile: str | None = None,
    ):

        return self.driver(
            provider=provider,
            region=region,
            profile=profile,
        ).network()

    def iam(
        self,
        *,
        provider: str,
        region: str,
        profile: str | None = None,
    ):

        return self.driver(
            provider=provider,
            region=region,
            profile=profile,
        ).iam()

    def registry(
        self,
        *,
        provider: str,
        region: str,
        profile: str | None = None,
    ):

        return self.driver(
            provider=provider,
            region=region,
            profile=profile,
        ).registry()

    def batch(
        self,
        *,
        provider: str,
        region: str,
        profile: str | None = None,
    ):

        return self.driver(
            provider=provider,
            region=region,
            profile=profile,
        ).batch()