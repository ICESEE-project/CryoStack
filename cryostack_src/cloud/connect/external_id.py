# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Account Connection
# File        : external_id.py
#
# Description :
#     Generation of the cryptographically unique STS ExternalId that binds
#     one CryoStack user to one AWS account connection.
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
STS ExternalId minting.

The ExternalId is the confused-deputy defence: the user's cross-account role
trust policy requires ``sts:ExternalId`` to equal this exact value, so the
CryoStack principal can only assume the role on behalf of *this* connection.

It is unique per (CryoStack user, connection). It is connection metadata, not
a secret -- but it is still never exposed to another user (the per-user store
enforces that) and never logged at INFO.

Charset is restricted to what AWS accepts for ``ExternalId``
(``A-Za-z0-9 +=,.@:/-``); we use ``[A-Za-z0-9_-]`` from :func:`secrets.token_urlsafe`
plus two ``:`` separators.
"""

from __future__ import annotations

import secrets

from cryostack_src.workspace.identity import WorkspaceUser

_PREFIX = "cryostack"
#: entropy of the random tail, in bytes (token_urlsafe ~1.3 chars/byte)
_RANDOM_BYTES = 24


def generate_external_id(user: WorkspaceUser) -> str:
    """Return a fresh ExternalId bound to ``user``.

    Shape: ``cryostack:<safe-user-id>:<url-safe-random>``. The user segment
    makes a leaked-and-reused value from a different user visually obvious in
    an audit; the random tail (>= 190 bits) makes it unguessable.
    """
    user_segment = (user.safe_id or "user")[:48]
    return f"{_PREFIX}:{user_segment}:{secrets.token_urlsafe(_RANDOM_BYTES)}"


def external_id_belongs_to(external_id: str, user: WorkspaceUser) -> bool:
    """True if ``external_id`` was minted for ``user`` (defence-in-depth check)."""
    parts = (external_id or "").split(":")
    if len(parts) != 3 or parts[0] != _PREFIX:
        return False
    return parts[1] == (user.safe_id or "user")[:48]
