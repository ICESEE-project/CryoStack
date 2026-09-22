# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : ISSM MATLAB license (cloud runtime readiness)
# File        : matlab_license.py
#
# Description :
#     The configuration seam that makes ISSM CLOUD execution runnable.
#     "Container ready" (the ECR image exists) is NOT the same as
#     "ISSM runtime ready": ISSM drives a full MATLAB (R2024b) inside the
#     combined image, which checks out a network license at start. The image
#     ships NO license (deliberately -- v1.0.1 provenance), and a site
#     license server (e.g. a campus one) is not reachable from AWS
#     Fargate.
#
# Author(s)   :
#     Brian Kyanjo
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: MIT
#
# =============================================================================

"""Resolve the ISSM cloud MATLAB-license readiness for a connected BYO-AWS
account -- **without ever handling the license value**.

Mechanism (AWS-native, BYO):

* the user creates an AWS Secrets Manager secret IN THEIR OWN ACCOUNT whose
  value is the ``MLM_LICENSE_FILE`` string (``<port>@<host>`` for a license
  server they can reach from the Batch compute environment's VPC, or a
  MathWorks online-licensing token);
* they give CryoStack only the secret's **ARN** (a non-secret identifier),
  stored on :class:`~cryostack_src.cloud.connect.models.AWSConnection`;
* Prepare Cloud registers the ISSM job definition with
  ``containerProperties.secrets = [{name: MLM_LICENSE_FILE, valueFrom: <arn>}]``
  and grants the Batch execution role ``secretsmanager:GetSecretValue`` on
  that ARN only (IAM -- outside this module);
* AWS Batch injects the value as an environment variable when the container
  starts. It is never in git, the image, an S3 run artifact, a manifest, a
  command preview, or a CryoStack log.

CryoStack's job here is only: given a connection, say whether ISSM cloud
runtime is configured, and hand the (non-secret) ARN to the provisioning
layer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: the container env var ISSM's MATLAB reads for its network license
MATLAB_LICENSE_ENV = "MLM_LICENSE_FILE"

#: private-service tunnel identifiers (see connector_relay_server.py /
#: connector_core.py / license_tunnel_client.py) -- symbolic only, never a
#: host/port; the paired Connector's own site allow-list resolves them.
TUNNEL_PURPOSE_MATLAB_LICENSE = "matlab-license"
TUNNEL_ENDPOINT_PRIMARY = "primary"
#: the FlexNet vendor-daemon hop, when the site profile confirms one (see
#: ComputeProfile.matlab_license_vendor_port) -- a SECOND, independent
#: local listener/tunnel under the SAME purpose and the SAME grant (grants
#: are purpose-scoped, not (purpose, endpoint)-scoped -- see
#: connector_relay_server.TunnelGrant), never a separate credential.
TUNNEL_ENDPOINT_VENDOR = "vendor"

#: Advanced-diagnostics-only labels for how the license was reached --
#: never shown in Basic mode.
LICENSE_PATH_DIRECT = "direct"
LICENSE_PATH_TUNNEL = "institutional_connector"

#: arn:aws:secretsmanager:<region>:<account>:secret:<name>-<suffix>
_SECRET_ARN_RE = re.compile(
    r"\Aarn:aws:secretsmanager:[a-z0-9-]+:\d{12}:secret:[A-Za-z0-9/_+=.@-]+\Z"
)

#: substrings that would indicate a license VALUE (never an ARN) slipped in
_LICENSE_VALUE_HINTS = ("@", "mlm_license", "license_file", "lm_license")


@dataclass(frozen=True)
class CloudMatlabLicense:
    """Non-secret ISSM cloud-runtime license state for one connection.

    ``requires_tunnel`` is a SITE fact (never per-user, never inferred from
    the secret's value, which this module never reads) -- it says whether
    the institutional license service behind this ARN is reachable from AWS
    Fargate directly or needs the private-service tunnel through the user's
    paired Connector. See :func:`resolve_cloud_matlab_license` and
    ``cryostack_src.resources.profiles.ComputeProfile.
    matlab_license_cloud_requires_tunnel``.
    """

    configured: bool
    mechanism: str          # "secrets-manager" | "none"
    secret_arn: str         # "" unless mechanism == "secrets-manager"
    requires_tunnel: bool = False

    def as_public_dict(self) -> dict:
        return {
            "configured": self.configured,
            "mechanism": self.mechanism,
            "secret_arn": self.secret_arn,
            "requires_tunnel": self.requires_tunnel,
        }

    def batch_secrets_block(self) -> list[dict]:
        """``containerProperties.secrets`` -- empty when unconfigured.

        UNCHANGED by tunnelling: this always resolves to the secret exactly
        as configured (the real institutional endpoint) -- the Secrets
        Manager representation is never touched. Only the running
        container's OWN environment is ever rewritten (to point at the
        local tunnel listener instead), and only at runtime, inside the
        task -- see ``cryostack_src.cloud.runtime.build_cloud_runner``.
        """
        if not (self.configured and self.secret_arn):
            return []
        return [{"name": MATLAB_LICENSE_ENV, "valueFrom": self.secret_arn}]

    def license_path(self) -> str:
        """Advanced-diagnostics-only label -- never shown in Basic mode."""
        if not self.configured:
            return LICENSE_PATH_DIRECT
        return LICENSE_PATH_TUNNEL if self.requires_tunnel else LICENSE_PATH_DIRECT


NOT_CONFIGURED = CloudMatlabLicense(configured=False, mechanism="none", secret_arn="")


def is_secret_arn(value: str) -> bool:
    return bool(_SECRET_ARN_RE.match((value or "").strip()))


def assert_not_a_license_value(value: str) -> None:
    """Fail closed if what was handed in looks like a license VALUE rather
    than a Secrets Manager ARN (defence-in-depth: the value must never enter
    CryoStack)."""
    low = (value or "").strip().lower()
    if not low:
        return
    if low.startswith("arn:aws:secretsmanager:"):
        return
    if any(h in low for h in _LICENSE_VALUE_HINTS) or re.search(r"\d+@", low):
        raise ValueError(
            "Expected an AWS Secrets Manager secret ARN, not a MATLAB license "
            "value. The license value must stay in your AWS account and never "
            "be given to CryoStack."
        )


def site_requires_cloud_license_tunnel() -> bool:
    """Whether THIS deployment's institutional MATLAB license service needs
    the private-service tunnel for a cloud (Fargate) run -- a SITE fact
    (``ComputeProfile.matlab_license_cloud_requires_tunnel``), never a
    per-user or per-run choice, and never derived from the secret's value
    (this module never reads it). CryoStack today ships one canonical
    institutional profile ("pace" -- Georgia Tech); see
    ``cryostack_src/resources/profiles.py`` for the site fact itself.
    """
    from cryostack_src.resources.profiles import get_compute_profile

    return bool(get_compute_profile("pace").matlab_license_cloud_requires_tunnel)


def site_cloud_license_port() -> int:
    """The port number MATLAB should reach the license service on --
    parsed from the SAME site fact Local/Remote execution already uses
    (``ComputeProfile.matlab_license_value``, e.g. ``"1711@matlablic.ecs.
    gatech.edu"``), never from the secret's value. Used only to pick the
    LOCAL tunnel listener's port so ``MLM_LICENSE_FILE`` stays
    ``<same port>@127.0.0.1`` after the rewrite -- see
    :func:`local_mlm_license_file`. Falls back to 1711 (the current site's
    documented port) if the site value is ever missing or unparsable.
    """
    from cryostack_src.resources.profiles import get_compute_profile

    value = (get_compute_profile("pace").matlab_license_value or "").strip()
    match = re.match(r"\A(\d+)@", value)
    return int(match.group(1)) if match else 1711


def site_cloud_license_vendor_port() -> int | None:
    """This deployment's institution-specific FlexNet VENDOR-daemon port,
    if the site profile confirms one (``ComputeProfile.
    matlab_license_vendor_port`` -- e.g. Georgia Tech PACE: 17110).
    ``None`` when the site has no confirmed vendor daemon (a plain
    single-port license service, or simply not yet confirmed) -- see
    :func:`plan_license_tunnel`, which adds the vendor listener's env only
    when this returns a value. Never a universal MATLAB/FlexNet constant.
    """
    from cryostack_src.resources.profiles import get_compute_profile

    port = get_compute_profile("pace").matlab_license_vendor_port
    return int(port) if port else None


class LicenseTunnelUnavailable(RuntimeError):
    """The institutional MATLAB license needs the private-service tunnel,
    but no Connector session is available for this user right now. Callers
    must fail closed on this -- NEVER catch it and fall back to the
    direct (unreachable) address; that would silently attempt a connection
    that is known in advance to fail, or worse, leak the address's DNS
    lookup to a network CryoStack does not control the exposure of.
    """


def plan_license_tunnel(
    *, requires_tunnel: bool, session_id: str | None, relay_url: str,
    mint_grant=None, ttl_seconds: int | None = None,
) -> dict | None:
    """Decide what (if anything) a Batch job submission needs to inject for
    the MATLAB license, given whether the site fact says a tunnel is
    needed (``CloudMatlabLicense.requires_tunnel`` -- the caller resolves
    that once and passes the bool, so this function needs no
    ``CloudMatlabLicense`` object, no secret, and no ARN) and the user's
    Connector session (if any) -- the ONE decision point tying the two
    previously independent subsystems (Cloud/AWS and Remote/Connector)
    together for this purpose.

    ``session_id`` must come from ``connector_relay_client.
    current_binding()`` (the currently authenticated user's own paired
    Connector, resolved server-side) -- NEVER user-entered input. This
    function does not resolve it itself so the caller's binding source is
    unambiguous and auditable at the call site
    (``AWSDriver.submit`` in ``driver.py``).

    Returns ``None`` when no tunnel is needed at all -- the existing direct
    Secrets-Manager-only path is completely untouched in that case. Raises
    :class:`LicenseTunnelUnavailable` when the tunnel IS needed but
    ``session_id`` is falsy (no connector connected) -- this must propagate
    and block submission, never be swallowed into "just try the direct
    address anyway".

    ``mint_grant`` is injected (default
    ``icesee_jupyter_book.core.connector_relay_client.mint_tunnel_grant``)
    purely so this stays unit-testable without a real relay call; the
    caller (driver.py's job-submission path) never needs to pass it.
    """
    if not requires_tunnel:
        return None
    if not session_id:
        raise LicenseTunnelUnavailable(
            "This MATLAB license requires an institutional Connector, but "
            "no Connector is currently connected for this account."
        )
    if mint_grant is None:
        from icesee_jupyter_book.core.connector_relay_client import mint_tunnel_grant
        mint_grant = mint_tunnel_grant

    grant = mint_grant(session_id, TUNNEL_PURPOSE_MATLAB_LICENSE, ttl_seconds=ttl_seconds)
    port = site_cloud_license_port()
    plan = {
        "CRYOSTACK_LICENSE_TUNNEL_REQUIRED": "1",
        "CRYOSTACK_LT_RELAY": relay_url,
        "CRYOSTACK_LT_SESSION": session_id,
        "CRYOSTACK_LT_TOKEN": grant["token"],
        "CRYOSTACK_LT_PURPOSE": TUNNEL_PURPOSE_MATLAB_LICENSE,
        "CRYOSTACK_LT_ENDPOINT": TUNNEL_ENDPOINT_PRIMARY,
        "CRYOSTACK_LT_PORT": str(port),
        # non-secret bookkeeping the caller may want to revoke at run end
        # (connector_relay_client.revoke_tunnel_grant) -- never persisted.
        "_grant_id": grant["grant_id"],
    }

    vendor_port = site_cloud_license_vendor_port()
    if vendor_port is not None:
        # A second, independent local listener for the FlexNet vendor-
        # daemon hop -- reuses the SAME grant/token as the primary tunnel
        # (grants are purpose-scoped, not (purpose, endpoint)-scoped; see
        # connector_relay_server.TunnelGrant), so no second mint call is
        # needed. Only present when the site profile confirms a vendor
        # port -- absent (never a guessed/default port) for a site that
        # does not.
        plan["CRYOSTACK_LT_VENDOR_PORT"] = str(vendor_port)
    return plan


def resolve_cloud_matlab_license(connection) -> CloudMatlabLicense:
    """From an :class:`AWSConnection` (or anything with
    ``matlab_license_secret_arn``). Never raises for a plain missing value;
    an ARN-shaped string that is malformed is treated as unconfigured."""
    arn = (getattr(connection, "matlab_license_secret_arn", "") or "").strip()
    if arn and is_secret_arn(arn):
        return CloudMatlabLicense(
            configured=True, mechanism="secrets-manager", secret_arn=arn,
            requires_tunnel=site_requires_cloud_license_tunnel(),
        )
    return NOT_CONFIGURED


def local_mlm_license_file(port: int, *, host: str = "127.0.0.1") -> str:
    """The ``MLM_LICENSE_FILE`` value MATLAB should see INSIDE the task once
    the local tunnel listener is up -- never written to Secrets Manager,
    never persisted; used only to rewrite the running container's own
    environment for the ``apptainer exec --env`` invocation. See
    ``cryostack_src.cloud.runtime.build_cloud_runner``.
    """
    return f"{int(port)}@{host}"
