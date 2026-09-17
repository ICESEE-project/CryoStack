# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Secrets Manager (guided ISSM MATLAB license setup)
# File        : secrets.py
#
# Description :
#     Creates the ONE kind of CryoStack-managed Secrets Manager secret this
#     platform currently needs: an ISSM MATLAB license value
#     (MLM_LICENSE_FILE), plus a metadata-only DescribeSecret lookup to
#     recover an existing secret's ARN on a name collision. No value
#     read/update/delete operations -- the runtime VALUE read path
#     (GetSecretValue via the ECS execution role) already exists in
#     cryostack_src/cloud/matlab_license.py and iam_policies.py.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-09-14
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""AWS Secrets Manager: guided creation of the ISSM MATLAB-license secret.

This is the ONLY Secrets Manager write operation CryoStack performs. It
exists so a connected BYO-AWS user can create the secret
:doc:`matlab_license.py </docs/developer_guide>` expects
(``MLM_LICENSE_FILE``, a plaintext ``PORT@HOST`` string) directly from the
UI instead of the AWS console -- the manual "paste an existing ARN" path
this module does not touch remains fully supported and unchanged.

:func:`describe_matlab_license_secret` is the one read this module
performs, and it is metadata-only (ARN/name, never the value) -- it
exists so a name collision on create (:class:`SecretAlreadyExists`) can
recover the pre-existing secret's ARN and complete "CryoStack will keep
using it automatically" instead of leaving the connection permanently
unable to reference a secret it is already entitled to create.

Security shape, enforced here:

* the secret VALUE is written to the AWS CLI's own stdin
  (``--secret-string file:///dev/stdin``), never argv, never an env var,
  never a temp file -- it cannot appear in a process listing (``ps``),
  shell history, or this module's own error text;
* :func:`create_matlab_license_secret` returns ONLY non-secret metadata
  (``{"arn", "name"}``) -- the value is never logged, returned, or
  interpolated into any exception message;
* the secret NAME is restricted to the ``cryostack/`` prefix
  (:data:`SECRET_NAME_PREFIX``) -- the same prefix the cross-account
  execution role's ``secretsmanager:CreateSecret`` IAM grant is scoped to
  (see ``cryostack_src/cloud/connect/cloudformation.py``); a name outside
  that prefix is rejected here BEFORE any AWS call, so the (expected) IAM
  denial is never the only thing stopping a mis-scoped name.
* an existing secret of the same name is never overwritten -- AWS itself
  refuses a duplicate ``CreateSecret`` (``ResourceExistsException``), which
  is surfaced here as :class:`SecretAlreadyExists` rather than retried as
  an update.
"""
from __future__ import annotations

import json
import re

from .auth import run_aws
from .models import AWSConfig

#: CryoStack-managed secrets live under this prefix -- the ONLY prefix the
#: cross-account execution role's secretsmanager:CreateSecret grant
#: authorizes (a StringLike condition on secretsmanager:Name).
SECRET_NAME_PREFIX = "cryostack/"

#: AWS Secrets Manager secret-name charset: letters, digits, and / _ + = . @ -
#: (AWS's own documented allowed set), max 512 characters.
_NAME_RE = re.compile(r"\A[A-Za-z0-9/_+=.@-]{1,512}\Z")


class SecretNameInvalid(ValueError):
    """The requested secret name is empty, malformed, or outside the
    CryoStack-managed prefix the IAM grant restricts CreateSecret to."""


class SecretAlreadyExists(RuntimeError):
    """A secret with this exact name already exists in this account/Region.
    CreateSecret is refused rather than silently reusing or overwriting it."""


class SecretCreateError(RuntimeError):
    """CreateSecret failed for a reason other than a name collision (e.g.
    AccessDenied). The message is sanitized CLI stderr text -- the
    ``--secret-string`` value was never on argv, so it cannot appear here,
    but nothing about this exception is ever built from the raw value."""


class SecretDescribeError(RuntimeError):
    """DescribeSecret failed -- e.g. the connected role has not been
    granted ``secretsmanager:DescribeSecret`` yet (see
    ``cryostack_src.cloud.connect.cloudformation``'s
    ``CryoStackMatlabLicenseSecretDescribe`` statement -- an existing
    connection made before this grant existed needs 'Update role
    permissions' once), or no secret exists under this name at all."""


def validate_secret_name(name: str) -> str:
    """Return ``name`` stripped, or raise :class:`SecretNameInvalid`.

    Enforced BEFORE any AWS call: non-empty, the ``cryostack/`` prefix the
    IAM policy depends on, and AWS's own allowed character set. This is a
    name-shape check only -- it never inspects or accepts a license VALUE.
    """
    n = (name or "").strip()
    if not n:
        raise SecretNameInvalid("Secret name cannot be empty.")
    if not n.startswith(SECRET_NAME_PREFIX):
        raise SecretNameInvalid(
            f"Secret name must start with {SECRET_NAME_PREFIX!r} -- this is "
            "the only prefix CryoStack's AWS role is permitted to create."
        )
    if not _NAME_RE.match(n):
        raise SecretNameInvalid(
            "Secret name may only contain letters, digits, and / _ + = . @ -"
        )
    return n


def create_matlab_license_secret(
    config: AWSConfig,
    *,
    name: str,
    value: str,
) -> dict:
    """Create a NEW AWS Secrets Manager secret holding ``value`` as a
    **plaintext** SecretString -- the exact ``MLM_LICENSE_FILE`` value AWS
    Batch injects verbatim into the ISSM container (see
    ``matlab_license.py``): never a JSON object.

    Returns ``{"arn": <secret ARN>, "name": <secret name>}`` only -- never
    the value. Raises :class:`SecretNameInvalid` (bad name, checked before
    any AWS call), :class:`ValueError` (empty value),
    :class:`SecretAlreadyExists` (a same-named secret already exists), or
    :class:`SecretCreateError` (any other AWS CLI failure, e.g. AccessDenied).
    """
    clean_name = validate_secret_name(name)
    if not (value or "").strip():
        raise ValueError("A license value is required.")

    code, stdout, stderr = run_aws(
        config,
        [
            "secretsmanager", "create-secret",
            "--name", clean_name,
            "--secret-string", "file:///dev/stdin",
            "--output", "json",
        ],
        input=value,
    )

    if code != 0:
        text = (stderr or stdout or "").strip()
        if "ResourceExistsException" in text:
            raise SecretAlreadyExists(
                f"A secret named {clean_name!r} already exists."
            )
        raise SecretCreateError(
            text[:500] or "AWS Secrets Manager create-secret failed."
        )

    payload = json.loads(stdout or "{}")
    arn = (payload.get("ARN") or "").strip()
    if not arn:
        raise SecretCreateError(
            "AWS Secrets Manager did not return a secret ARN."
        )
    return {"arn": arn, "name": (payload.get("Name") or clean_name)}


def describe_matlab_license_secret(config: AWSConfig, *, name: str) -> dict:
    """Look up an EXISTING secret's (non-secret) ARN by name.

    Metadata only, via ``secretsmanager:DescribeSecret`` -- the secret's
    VALUE is never read, requested, or returned by this call. Used ONLY to
    recover CryoStack's own reference to a secret that already exists
    under the fixed CryoStack-managed name (i.e. after
    :func:`create_matlab_license_secret` raised :class:`SecretAlreadyExists`)
    so "Configure license" can complete automatically instead of leaving
    a working secret permanently unreferenced -- never to inspect an
    arbitrary, caller-supplied secret name (the same ``cryostack/`` prefix
    check :func:`validate_secret_name` already enforces for creation
    applies here too).

    Returns ``{"arn": <secret ARN>, "name": <secret name>}``. Raises
    :class:`SecretNameInvalid` (bad name, checked before any AWS call) or
    :class:`SecretDescribeError` (no such secret, access denied -- e.g. the
    connected role predates the ``CryoStackMatlabLicenseSecretDescribe``
    IAM grant and needs an "Update role permissions" pass -- or any other
    AWS CLI failure).
    """
    clean_name = validate_secret_name(name)

    code, stdout, stderr = run_aws(
        config,
        [
            "secretsmanager", "describe-secret",
            "--secret-id", clean_name,
            "--output", "json",
        ],
    )

    if code != 0:
        text = (stderr or stdout or "").strip()
        raise SecretDescribeError(
            text[:500] or "AWS Secrets Manager describe-secret failed."
        )

    payload = json.loads(stdout or "{}")
    arn = (payload.get("ARN") or "").strip()
    if not arn:
        raise SecretDescribeError(
            "AWS Secrets Manager did not return a secret ARN."
        )
    return {"arn": arn, "name": (payload.get("Name") or clean_name)}
