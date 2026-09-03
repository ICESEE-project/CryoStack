# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Account Connection
# File        : context.py
#
# Description :
#     The temporary-credential execution context handed to the existing AWS
#     CLI path for one assumed-role operation.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-09-03
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""
:class:`AWSExecutionContext` -- assumed-role temporary credentials, scoped to
a single operation.

The existing driver runs ``aws ...`` subprocesses via
``cryostack_src.cloud.drivers.aws.auth.run_aws(config, args)``. This context
produces an :class:`AWSConfig` carrying the temporary environment so that
*the same* CLI path runs as the assumed role -- no driver rewrite.

Guarantees:

* the secret triple lives only on the instance, in a ``repr``-suppressed
  field, for the lifetime of the operation;
* ``repr()`` / ``str()`` / ``!r`` never render the secrets;
* the values are never persisted (there is no ``to_dict``) and
  :func:`redact_aws_secrets` scrubs them from any structure that does reach a
  log.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cryostack_src.cloud.drivers.aws.models import AWSConfig

_SECRET_ENV_KEYS = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
)


@dataclass
class AWSExecutionContext:
    """Temporary credentials + identity for one assumed-role operation."""

    account_id: str
    region: str
    role_arn: str
    external_id: str
    expiration: str = ""
    #: {AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN}
    _credentials: dict[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        missing = [k for k in _SECRET_ENV_KEYS if not self._credentials.get(k)]
        if missing:
            raise ValueError(
                f"AWSExecutionContext is missing temporary credential values: "
                f"{', '.join(missing)}"
            )

    # -- safe rendering ----------------------------------------------
    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            "AWSExecutionContext("
            f"account_id={self.account_id!r}, region={self.region!r}, "
            f"role_arn={self.role_arn!r}, expiration={self.expiration!r}, "
            "credentials=<redacted>)"
        )

    __str__ = __repr__

    # -- controlled access to the secret material -------------------
    def environment(self) -> dict[str, str]:
        """A fresh copy of the temporary AWS env for one subprocess."""
        return {k: self._credentials[k] for k in _SECRET_ENV_KEYS}

    def aws_config(self, *, region: str | None = None) -> AWSConfig:
        """An :class:`AWSConfig` the existing driver runs unchanged.

        ``profile`` is deliberately ``None`` -- assumed-role mode never uses a
        local CLI profile.
        """
        return AWSConfig(
            region=(region or self.region),
            profile=None,
            credentials=self.environment(),
        )
