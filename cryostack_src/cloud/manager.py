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
# Central cloud orchestration layer. Selects a cloud provider driver
# (currently AWS) and exposes a provider-independent API to the
# execution layer.
#
# Author(s)   :
# Brian Kyanjo
#
# Created     : 2026-08-25
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

from __future__ import annotations

from .drivers.aws import AWSDriver


class CloudManager:
    """
    Provider-independent cloud manager.

    The execution layer talks only to this class.
    """

    def __init__(
        self,
        *,
        provider: str = "aws",
        region: str = "us-east-2",
        profile: str | None = None,
    ):

        provider = provider.lower()

        if provider == "aws":

            self.driver = AWSDriver(
                region=region,
                profile=profile,
            )

        else:

            raise RuntimeError(
                f"Unsupported cloud provider: {provider}"
            )

    def submit(self, **kwargs):

        return self.driver.submit(**kwargs)

    def status(self, job_id):

        return self.driver.status(job_id)

    def logs(self, job_id):

        return self.driver.logs(job_id)

    def terminate(self, job_id):

        return self.driver.terminate(job_id)