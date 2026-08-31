# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Remote
# Component   : Driver Base
# File        : base.py
#
# =============================================================================

from __future__ import annotations

from abc import ABC
from abc import abstractmethod


class RemoteDriver(ABC):

    @abstractmethod
    def submit(self, **kwargs):
        ...

    @abstractmethod
    def status(self, job_id):
        ...

    @abstractmethod
    def logs(self, job_id):
        ...

    @abstractmethod
    def terminate(self, job_id):
        ...