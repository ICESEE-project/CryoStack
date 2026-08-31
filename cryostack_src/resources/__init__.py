"""CryoStack compute-resource configuration."""
from __future__ import annotations

from .profiles import COMPUTE_PROFILES, ComputeProfile, get_compute_profile

__all__ = ["ComputeProfile", "COMPUTE_PROFILES", "get_compute_profile"]
