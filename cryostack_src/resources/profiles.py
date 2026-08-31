"""Compute-resource (cluster) profiles: site-specific runtime configuration.

A CryoStack container image ships portable science and nothing site-specific.
Facts that depend on *where* a run executes belong here instead.

Today the only such fact is MATLAB licensing. ISSM runs MATLAB inside the
portable ICESEE container, and the public image is deliberately license-neutral
(no server baked in), so every compute resource declares its own license
mechanism. PACE / Phoenix use the Georgia Tech campus license server; another
resource can point at a different server, or configure nothing if it licenses
MATLAB some other way (in which case ISSM container runs there fail fast at
submission with a clear message instead of hanging on a license checkout).

The license value is runtime configuration, never provenance: it is passed to
``apptainer exec --env`` at submission and is never written to the run manifest,
the Run Plan, or the execution log.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_ENV_NAME_RE = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*\Z")


@dataclass(frozen=True)
class ComputeProfile:
    name: str
    # ISSM runs MATLAB inside the container. An empty value means this resource
    # has not configured MATLAB licensing.
    matlab_license_env: str = "MLM_LICENSE_FILE"
    matlab_license_value: str | None = None

    def __post_init__(self) -> None:
        if not _ENV_NAME_RE.match(self.matlab_license_env):
            raise ValueError(
                f"invalid MATLAB license env var name: {self.matlab_license_env!r}"
            )

    @property
    def has_matlab_license(self) -> bool:
        return bool((self.matlab_license_value or "").strip())

    def matlab_license_config(self) -> dict | None:
        """Runtime config for submission, or ``None`` when unconfigured.

        Never provenance -- the value is spliced into the apptainer command only.
        """
        if not self.has_matlab_license:
            return None
        return {
            "env_var": self.matlab_license_env,
            "value": self.matlab_license_value.strip(),
        }


# GT PACE / Phoenix -- the Georgia Tech campus MATLAB license server.
_PACE = ComputeProfile(
    name="pace",
    matlab_license_env="MLM_LICENSE_FILE",
    matlab_license_value="1711@matlablic.ecs.gatech.edu",
)

COMPUTE_PROFILES: dict[str, ComputeProfile] = {
    "pace": _PACE,
    "phoenix": _PACE,
    "pace-phoenix": _PACE,
}


def get_compute_profile(name: str | None) -> ComputeProfile:
    """Look up a compute profile by cluster name (case-insensitive).

    An unknown name yields a profile with no site configuration rather than an
    error, so non-MATLAB workflows on other clusters keep working unchanged.
    """
    key = (name or "").strip().lower()
    if key in COMPUTE_PROFILES:
        return COMPUTE_PROFILES[key]
    return ComputeProfile(name=key or "unknown", matlab_license_value=None)
