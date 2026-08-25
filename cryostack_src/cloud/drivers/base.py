# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : Cloud Driver Interface
# File        : base.py
#
# Description :
#     Defines the common interface implemented by CryoStack cloud drivers.
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
Common cloud driver interface for CryoStack.

Cloud drivers hide provider-specific implementation details from the
rest of the CryoStack platform.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class CloudDriver(ABC):
    """
    Common interface implemented by CryoStack cloud providers.
    """

    name: str = "unknown"

    @abstractmethod
    def account(self):
        raise NotImplementedError

    @abstractmethod
    def capabilities(self):
        raise NotImplementedError

    @abstractmethod
    def prepare_storage(
        self,
        *,
        bucket: str | None = None,
    ):
        raise NotImplementedError

    @abstractmethod
    def network(self):
        raise NotImplementedError

    @abstractmethod
    def iam(self):
        raise NotImplementedError

    @abstractmethod
    def registry(self):
        raise NotImplementedError

    @abstractmethod
    def batch(self):
        raise NotImplementedError

    @abstractmethod
    def bootstrap(
        self,
        *,
        bucket: str | None = None,
    ):
        """
        Prepare and inspect the cloud environment required by CryoStack.
        """

        raise NotImplementedError

    @abstractmethod
    def prepare_registry(
        self,
        *,
        include_icepack: bool = False,
    ):
        raise NotImplementedError