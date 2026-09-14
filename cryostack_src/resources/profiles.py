"""Compute-resource (cluster) profiles: declarative site facts.

A CryoStack container image ships portable science and nothing site-specific.
Facts that depend on *where* a run executes belong here instead -- as data, not
as literals scattered through the gateway UIs.

Ownership boundaries (kept explicit in the code that consumes this module):

    RESOURCE            login host, ssh port, VPN / MFA requirements, supported
                        access + authentication mechanisms, key-registration
                        method + portal, remote-identity verification command,
                        scheduler defaults (partition, wall time), whether an
                        allocation is required, MATLAB license mechanism.
                        --> ComputeProfile (this module). Never personal.

    USER x RESOURCE     HPC username, remote working directory, allocation /
                        account, access preference, auth configuration.
                        --> per-user, per-resource. B2 adds persistence. Until
                        then these stay BLANK and are never inferred from the
                        server process environment.

    USER               notification email. --> per-user. Blank until B2.

    RUN                job name, nodes, tasks, tasks/node, memory, and per-run
                        overrides of partition / wall time. --> run config.

    SECRET / EPHEMERAL bootstrap password, connector pairing capabilities.
                        --> never persisted, never in a profile.

A ComputeProfile therefore must NEVER contain a person's username, allocation,
project directory, email address, SSH key, credential, or password. PACE /
Phoenix facts below are institutional facts about the resource.

The MATLAB license value is runtime configuration, never provenance: it is
passed to ``apptainer exec --env`` at submission and is never written to the run
manifest, the Run Plan, or the execution log.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_ENV_NAME_RE = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*\Z")

#: how a resource expects an SSH public key / token to be registered
KEY_REGISTRATION_METHODS = ("automatic", "portal", "manual")

#: access transports CryoStack actually implements today
ACCESS_MODES = ("connector", "direct")

#: SSH authentication mechanisms CryoStack actually implements today. Institution
#: certificates / short-lived credentials are NOT here -- no executable path yet.
AUTH_MODES = ("ssh_key", "password_bootstrap")


@dataclass(frozen=True)
class SchedulerDefaults:
    """Resource-owned scheduler defaults. A run may override these."""

    partition: str = ""
    wall_time: str = ""


@dataclass(frozen=True)
class ComputeProfile:
    name: str

    # ---- RESOURCE / SITE facts (safe to ship; never personal) -------------
    login_host: str = ""
    ssh_port: int = 22
    #: short hint for the "HPC username" field, e.g. "your PACE username"
    username_hint: str = ""
    requires_vpn: bool = False
    requires_mfa: bool = False
    #: does the connector/direct SSH path here use ssh-agent?
    ssh_agent_supported: bool = False
    supported_access_modes: tuple[str, ...] = ("connector",)
    auth_modes: tuple[str, ...] = ("ssh_key",)
    #: "shared" -> Direct SSH from the CryoStack server uses one shared
    #: service-account identity (the normal multi-user path is the Connector);
    #: "single_tenant" -> the deployment declares the server is single-user, so
    #: server-side credentials are acceptable.
    direct_ssh_trust: str = "shared"
    key_registration_method: str = "manual"
    portal_url: str = ""
    portal_name: str = ""
    portal_steps: tuple[str, ...] = ()
    #: command whose stdout is the remote identity, compared to the expected
    #: HPC username by B3's "Check SSH".
    verification_command: str = "whoami"
    scheduler_defaults: SchedulerDefaults = field(default_factory=SchedulerDefaults)
    account_required: bool = False

    # ---- MATLAB licensing (unchanged behaviour) --------------------------
    matlab_license_env: str = "MLM_LICENSE_FILE"
    matlab_license_value: str | None = None

    def __post_init__(self) -> None:
        if not _ENV_NAME_RE.match(self.matlab_license_env):
            raise ValueError(
                f"invalid MATLAB license env var name: {self.matlab_license_env!r}"
            )
        if self.key_registration_method not in KEY_REGISTRATION_METHODS:
            raise ValueError(
                f"key_registration_method must be one of {KEY_REGISTRATION_METHODS}"
            )
        if self.direct_ssh_trust not in ("shared", "single_tenant"):
            raise ValueError("direct_ssh_trust must be 'shared' or 'single_tenant'")
        if int(self.ssh_port) <= 0:
            raise ValueError(f"ssh_port must be positive: {self.ssh_port!r}")

    # ---- MATLAB helpers (unchanged) -------------------------------------
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


# GT PACE / Phoenix -- institutional facts about the resource.
_PACE = ComputeProfile(
    name="pace",
    login_host="login-phoenix-rh9.pace.gatech.edu",
    ssh_port=22,
    username_hint="your PACE username (your GT username)",
    requires_vpn=True,
    requires_mfa=False,
    ssh_agent_supported=False,
    supported_access_modes=("connector", "direct"),
    auth_modes=("ssh_key", "password_bootstrap"),
    key_registration_method="automatic",
    verification_command="whoami",
    scheduler_defaults=SchedulerDefaults(partition="cpu-large", wall_time="04:00:00"),
    account_required=True,
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

    An unknown name yields a profile with only neutral defaults -- no login
    host, no VPN/MFA claims, connector-only access, no scheduler defaults, no
    MATLAB license -- so a non-PACE resource never inherits PACE-specific
    information.
    """
    key = (name or "").strip().lower()
    if key in COMPUTE_PROFILES:
        return COMPUTE_PROFILES[key]
    return ComputeProfile(name=key or "unknown")


def initial_remote_fields(cluster_name: str | None) -> dict:
    """Initial Remote Connection / scheduler widget values for a freshly opened
    gateway.

    RESOURCE facts come from the resolved :class:`ComputeProfile`.
    USER x RESOURCE and USER fields (HPC username, remote working directory,
    Slurm allocation, notification email) are **blank** -- there is no
    user-scoped source yet (B2), and they must never be inferred from the Voila
    service account's environment.
    """
    p = get_compute_profile(cluster_name)
    return {
        # RESOURCE
        "login_host": p.login_host,
        "ssh_port": p.ssh_port,
        "username_hint": p.username_hint or "your HPC username",
        "partition": p.scheduler_defaults.partition,
        "wall_time": p.scheduler_defaults.wall_time,
        "account_required": p.account_required,
        # USER x RESOURCE / USER -- fail closed, blank until B2
        "hpc_username": "",
        "remote_directory": "",
        "slurm_account": "",
        "notification_email": "",
    }
