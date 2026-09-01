"""B3: remote-access readiness -- distinct from the ICESEE-Spack ``EnvStatus``.

    credential exists  !=  access verified

A key on disk is not proof the current user can act as the configured HPC
identity on the selected resource. ``AccessState`` models the path from
"resource selected" to "ready to run"; ``verify_remote_identity`` runs the
resource's verification command and compares the real remote identity against
the configured HPC username; ``enforce_remote_access`` is the Run-time gate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AccessState(str, Enum):
    RESOURCE_SELECTED = "resource_selected"
    IDENTITY_INCOMPLETE = "identity_incomplete"          # no HPC username / remote workspace
    PREREQUISITE_REQUIRED = "prerequisite_required"      # VPN / MFA / connector not connected
    CREDENTIAL_MISSING = "credential_missing"            # no SSH key yet
    PORTAL_REGISTRATION_REQUIRED = "portal_registration_required"
    CREDENTIAL_AVAILABLE = "credential_available"        # key exists -- NOT verified
    VERIFICATION_PENDING = "verification_pending"        # never ran Check SSH
    SSH_VERIFIED = "ssh_verified"
    IDENTITY_MISMATCH = "identity_mismatch"              # remote whoami != configured
    ACCESS_FAILED = "access_failed"                      # connection / auth error
    READY = "ready"


#: states that must stop a Run
_RUN_BLOCKING = {
    AccessState.IDENTITY_INCOMPLETE,
    AccessState.PREREQUISITE_REQUIRED,
    AccessState.CREDENTIAL_MISSING,
    AccessState.PORTAL_REGISTRATION_REQUIRED,
    AccessState.VERIFICATION_PENDING,
    AccessState.IDENTITY_MISMATCH,
    AccessState.ACCESS_FAILED,
}


def run_blocked(state: AccessState) -> bool:
    return state in _RUN_BLOCKING


@dataclass(frozen=True)
class AccessInputs:
    hpc_username: str = ""
    remote_directory: str = ""
    access_mode: str = "connector"           # resolved: "direct" | "connector"
    key_exists: bool = True                   # unknown -> assume present (verification is the real gate)
    connector_online: bool | None = None      # None = n/a (direct)
    verified_identity: str | None = None      # remote whoami, if it was run
    verification_error: str | None = None
    # resource facts
    requires_vpn: bool = False
    requires_mfa: bool = False
    key_registration_method: str = "automatic"
    direct_ssh_trust: str = "shared"          # "shared" | "single_tenant"
    account_required: bool = False
    account: str = ""
    environment_ready: bool | None = None     # ICESEE-Spack probe, if checked


def classify_access_state(i: AccessInputs) -> AccessState:
    if not i.hpc_username.strip() or not i.remote_directory.strip():
        return AccessState.IDENTITY_INCOMPLETE

    if i.access_mode == "connector" and i.connector_online is False:
        return AccessState.PREREQUISITE_REQUIRED

    if i.verification_error:
        return AccessState.ACCESS_FAILED

    if i.verified_identity is not None:
        if i.verified_identity.strip().lower() != i.hpc_username.strip().lower():
            return AccessState.IDENTITY_MISMATCH
        if i.environment_ready:
            return AccessState.READY
        return AccessState.SSH_VERIFIED

    # not verified yet
    if not i.key_exists:
        if i.key_registration_method == "portal":
            return AccessState.PORTAL_REGISTRATION_REQUIRED
        return AccessState.CREDENTIAL_MISSING
    return AccessState.VERIFICATION_PENDING


# ── remote-identity verification ────────────────────────────────────────
@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    expected: str
    remote_identity: str | None = None
    mismatch: bool = False
    error: str | None = None


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def identity_result_from_output(
    *, whoami_line: str, expected_username: str
) -> VerificationResult:
    """Compare an *already captured* remote identity line to the configured HPC
    username -- no extra round trip.

    Used by the Check SSH button, whose connectivity probe already runs
    ``hostname && whoami && ...`` in one command: when the resource's
    verification command is just ``whoami`` there is no reason to invoke a
    second remote command. The Run gate never uses this -- it always
    re-verifies fresh via :func:`verify_remote_identity`.
    """
    expected = (expected_username or "").strip()
    remote = _first_line(whoami_line or "")
    if not expected:
        return VerificationResult(ok=False, expected="", error="no HPC username configured")
    if not remote:
        return VerificationResult(ok=False, expected=expected, error="no identity in connectivity output")
    if remote.lower() != expected.lower():
        return VerificationResult(ok=False, expected=expected, remote_identity=remote, mismatch=True)
    return VerificationResult(ok=True, expected=expected, remote_identity=remote)


def can_reuse_connectivity_identity(verification_command: str) -> bool:
    """True when the Check SSH connectivity probe (``hostname && whoami && …``)
    already yields what the resource's identity check needs, so a second remote
    invocation can be skipped."""
    return (verification_command or "whoami").strip().lower() in ("", "whoami")


def verify_remote_identity(bridge, *, verification_command: str, expected_username: str) -> VerificationResult:
    """Run ``verification_command`` over the active transport and compare its
    output to ``expected_username``. ``bridge`` is a ``RemoteBridge`` (duck: it
    provides ``check_backend(command=, timeout=)``)."""
    expected = (expected_username or "").strip()
    if not expected:
        return VerificationResult(ok=False, expected="", error="no HPC username configured")

    cmd = (verification_command or "whoami").strip() or "whoami"
    try:
        res = bridge.check_backend(command=cmd, timeout=30)
    except Exception as err:  # connector missing, ssh failure, ...
        return VerificationResult(ok=False, expected=expected, error=f"{type(err).__name__}: {err}")

    if not res.get("ok"):
        hint = _first_line(res.get("stderr") or "") or _first_line(res.get("stdout") or "") \
            or f"exit {res.get('returncode')}"
        return VerificationResult(ok=False, expected=expected, error=hint)

    remote = _first_line(res.get("stdout") or "")
    if not remote:
        return VerificationResult(ok=False, expected=expected, error="verification command produced no output")

    if remote.lower() != expected.lower():
        return VerificationResult(ok=False, expected=expected, remote_identity=remote, mismatch=True)

    return VerificationResult(ok=True, expected=expected, remote_identity=remote)


# ── Run-time gate ─────────────────────────────────────────────────────
@dataclass
class AccessGateResult:
    ok: bool
    state: AccessState
    messages: list[str] = field(default_factory=list)   # shown on block
    warnings: list[str] = field(default_factory=list)   # shown but not blocking


def enforce_remote_access(
    bridge,
    *,
    profile,
    access_mode: str,                # "auto" | "direct" | "connector" -- resolved below via `resolved_mode`
    resolved_mode: str,              # "direct" | "connector"
    hpc_username: str,
    remote_directory: str,
    connector_online: bool | None = None,
    run_identity_check: bool = True,
) -> AccessGateResult:
    """The Run gate. Verifies remote identity fresh (no stale state) and blocks
    on incomplete config / prerequisites / identity mismatch / access failure.
    """
    verified = None
    verr = None
    if (
        run_identity_check
        and hpc_username.strip()
        and remote_directory.strip()
        and not (resolved_mode == "connector" and connector_online is False)
    ):
        v = verify_remote_identity(
            bridge,
            verification_command=getattr(profile, "verification_command", "whoami"),
            expected_username=hpc_username,
        )
        if v.ok:
            verified = v.remote_identity
        elif v.mismatch:
            verified = v.remote_identity  # classify -> IDENTITY_MISMATCH
        else:
            verr = v.error

    inputs = AccessInputs(
        hpc_username=hpc_username,
        remote_directory=remote_directory,
        access_mode=resolved_mode,
        connector_online=connector_online,
        verified_identity=verified,
        verification_error=verr,
        requires_vpn=getattr(profile, "requires_vpn", False),
        requires_mfa=getattr(profile, "requires_mfa", False),
        key_registration_method=getattr(profile, "key_registration_method", "automatic"),
        direct_ssh_trust=getattr(profile, "direct_ssh_trust", "shared"),
    )
    state = classify_access_state(inputs)

    warnings: list[str] = []
    if resolved_mode == "direct" and inputs.direct_ssh_trust == "shared":
        warnings.append(
            "[access][WARN] Direct SSH from the CryoStack server uses a shared "
            "service-account identity and is NOT per-user isolated. Use the "
            "CryoStack Connector for multi-user access."
        )

    if not run_blocked(state):
        return AccessGateResult(ok=True, state=state, warnings=warnings)

    msg = {
        AccessState.IDENTITY_INCOMPLETE:
            ["[access] Configure your HPC username and remote workspace for this "
             "resource before running."],
        AccessState.PREREQUISITE_REQUIRED:
            ["[access] The CryoStack Connector for this session is not connected. "
             "Pair it from the Connector Setup page, then retry."],
        AccessState.CREDENTIAL_MISSING:
            ["[access] No SSH credential is configured for this resource yet. "
             "Generate/register a key, then Check SSH."],
        AccessState.PORTAL_REGISTRATION_REQUIRED:
            ["[access] This resource requires your SSH key to be registered "
             "through its institutional portal. Do that, then Check SSH."],
        AccessState.VERIFICATION_PENDING:
            ["[access] Remote identity has not been verified. Click Check SSH; "
             "Run is blocked until it succeeds."],
        AccessState.IDENTITY_MISMATCH:
            [f"[access][BLOCKED] The remote account is '{verified}', but the "
             f"configured HPC username is '{hpc_username.strip()}'. Run will not "
             "submit under a different identity — fix the HPC username or your "
             "SSH access."],
        AccessState.ACCESS_FAILED:
            [f"[access][BLOCKED] Could not verify remote access: {verr}",
             "[access] Check host / username / VPN / SSH key, then Check SSH."],
    }.get(state, [f"[access][BLOCKED] {state.value}"])

    return AccessGateResult(ok=False, state=state, messages=msg + warnings, warnings=[])
