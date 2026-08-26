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
#     interface for cloud discovery, provisioning, and job lifecycle
#     operations.
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
High-level CryoStack cloud manager.

CloudManager is the public cloud API used by execution backends and
frontends. Provider-specific behavior remains inside cloud drivers.
"""

from __future__ import annotations

from .drivers import (
    AWSDriver,
    CloudDriver,
)


class CloudManager:
    """
    Provider-independent CryoStack cloud manager.
    """

    def driver(
        self,
        *,
        provider: str,
        region: str,
        profile: str | None = None,
        submitter=None,
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
                submitter=submitter,
            )

        raise ValueError(
            f"Unsupported cloud provider: {provider}"
        )

    # ---------------------------------------------------------
    # Discovery / provisioning
    # ---------------------------------------------------------

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

    def bootstrap(
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
        ).bootstrap(
            bucket=bucket,
        )

    # ---------------------------------------------------------
    # Runtime lifecycle
    # ---------------------------------------------------------

    def submit(
        self,
        *,
        provider: str,
        region: str,
        profile: str | None = None,
        submitter=None,
        **kwargs,
    ):

        return self.driver(
            provider=provider,
            region=region,
            profile=profile,
            submitter=submitter,
        ).submit(
            **kwargs
        )

    def status(
        self,
        *,
        provider: str,
        region: str,
        job_id: str,
        profile: str | None = None,
    ):

        return self.driver(
            provider=provider,
            region=region,
            profile=profile,
        ).status(
            job_id
        )

    def logs(
        self,
        *,
        provider: str,
        region: str,
        job_id: str,
        profile: str | None = None,
    ):

        return self.driver(
            provider=provider,
            region=region,
            profile=profile,
        ).logs(
            job_id
        )

    def terminate(
        self,
        *,
        provider: str,
        region: str,
        job_id: str,
        profile: str | None = None,
    ):

        return self.driver(
            provider=provider,
            region=region,
            profile=profile,
        ).terminate(
            job_id
        )