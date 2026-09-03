# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Account Connection
# File        : redaction.py
#
# Description :
#     Central guard against a temporary AWS credential leaking into a log
#     line, a persisted record, or run provenance.
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
Redaction of AWS secret material.

Temporary STS credentials (``AWS_ACCESS_KEY_ID`` / ``AWS_SECRET_ACCESS_KEY`` /
``AWS_SESSION_TOKEN``) exist only for the lifetime of one operation. They must
never reach a log, a JSON file on disk, or a run's provenance dict.

* :func:`redact_aws_secrets` returns a deep copy with every secret value
  replaced by ``"<redacted>"`` -- safe to log or display.
* :func:`assert_no_aws_secrets` raises :class:`AWSSecretLeak` if a structure
  about to be persisted still carries secret material -- fail closed.
"""

from __future__ import annotations

from typing import Any

REDACTED = "<redacted>"

#: keys whose *values* are secret credential material (case-insensitive)
_SECRET_KEYS = frozenset(
    k.lower()
    for k in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_SECURITY_TOKEN",
        "AccessKeyId",
        "SecretAccessKey",
        "SessionToken",
        "aws_access_key_id",
        "aws_secret_access_key",
        "aws_session_token",
        "secret_access_key",
        "session_token",
        "Credentials",
    )
)

#: substrings that mark a key as secret even if not in the exact set above
_SECRET_HINTS = ("secretaccesskey", "sessiontoken", "securitytoken")


class AWSSecretLeak(RuntimeError):
    """A structure carrying AWS secret material reached a persist/log boundary."""


def _is_secret_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    low = key.lower()
    if low in _SECRET_KEYS:
        return True
    return any(hint in low for hint in _SECRET_HINTS)


def redact_aws_secrets(obj: Any) -> Any:
    """Deep copy of ``obj`` with every secret credential value replaced.

    A whole ``Credentials`` sub-object is collapsed to ``"<redacted>"`` so a
    raw STS ``assume-role`` response can be logged safely.
    """
    if isinstance(obj, dict):
        out: dict[Any, Any] = {}
        for key, value in obj.items():
            if _is_secret_key(key):
                out[key] = REDACTED
            else:
                out[key] = redact_aws_secrets(value)
        return out
    if isinstance(obj, (list, tuple)):
        return type(obj)(redact_aws_secrets(v) for v in obj)
    return obj


def _has_secret(obj: Any) -> bool:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if _is_secret_key(key) and value not in (None, "", REDACTED):
                return True
            if _has_secret(value):
                return True
        return False
    if isinstance(obj, (list, tuple)):
        return any(_has_secret(v) for v in obj)
    return False


def assert_no_aws_secrets(obj: Any, *, context: str = "record") -> None:
    """Raise :class:`AWSSecretLeak` if ``obj`` still carries secret material."""
    if _has_secret(obj):
        raise AWSSecretLeak(
            f"Refusing to persist/emit {context}: it contains AWS secret "
            "credential material (temporary credentials are never stored)."
        )
