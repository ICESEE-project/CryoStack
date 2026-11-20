# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : Hosted Pilot Participant Identity
# File        : identity.py
#
# Description :
#     Deterministic, non-reversible participant keys and the AWS names,
#     S3 prefixes and tags derived from them for the hosted pilot account.
#     Definitions only -- no AWS calls.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-11-15
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: MIT
#
# =============================================================================

"""
Participant identity for the CryoStack hosted pilot.

Many invited participants share ONE project-owned AWS account. Everything a
participant owns there is named after a **participant key**:

    key = sha256(b"cryostack-pilot\\0" + user_id)[:16]        (16 lowercase hex)

The key is stable (same user -> same key), AWS-name-safe, and does not reveal
the CryoStack user id or e-mail address. The raw user id must never appear in
an AWS name, tag, S3 key, log line or exception message -- every helper here
takes the user id and returns only key-derived values, and no error raised
here echoes the user id back.

    S3      s3://<bucket>/pilot/<key>/runs/<run-id>/{input,outputs}/
    IAM     cryostack-pilot-job-<key>
    Batch   cryostack-pilot-<key>-<model>
    secret  cryostack/pilot/<key>/matlab-license      (ISSM only, optional)
    tags    cryostack:participant = <key>
"""

from __future__ import annotations

import hashlib
import re

#: Domain separator so a pilot key can never equal a hash CryoStack derives
#: from the same user id for another purpose.
_KEY_DOMAIN = b"cryostack-pilot\0"
PARTICIPANT_KEY_LENGTH = 16

#: Top-level S3 prefix that holds every hosted-pilot object.
PILOT_PREFIX = "pilot/"
#: Common name prefix of every per-participant AWS resource.
PILOT_NAME_PREFIX = "cryostack-pilot-"
PILOT_JOB_ROLE_PREFIX = f"{PILOT_NAME_PREFIX}job-"

#: Secrets Manager names of pilot participants' own MATLAB-license secrets.
#: Sits under the existing CryoStack-managed ``cryostack/`` prefix
#: (``drivers/aws/secrets.py::SECRET_NAME_PREFIX``) and is the ONLY prefix the
#: pilot ECS execution role may read.
PILOT_SECRET_PREFIX = "cryostack/pilot/"
PILOT_SECRET_LEAF = "matlab-license"

IAM_ROLE_NAME_MAX = 64
BATCH_NAME_MAX = 128
TAG_VALUE_MAX = 256

TAG_PILOT = "cryostack:pilot"
TAG_PARTICIPANT = "cryostack:participant"
TAG_RESERVATION = "cryostack:reservation"
TAG_RUN = "cryostack:run"
TAG_MODEL = "cryostack:model"

_KEY_RE = re.compile(r"\A[0-9a-f]{16}\Z")
#: Same shape as ``drivers/aws/staging.py::_RUN_ID_RE`` (a test pins the two
#: together) so a run id minted by staging is always valid here.
_RUN_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_MODEL_RE = re.compile(r"\A[a-z][a-z0-9]{0,31}\Z")
#: The tag-value characters every AWS service accepts: letters, digits,
#: spaces and ``_ . : / = + - @``. Deliberately ASCII-only.
_TAG_VALUE_RE = re.compile(r"\A[A-Za-z0-9 _.:/=+@-]{1,256}\Z")
_IAM_ROLE_NAME_RE = re.compile(r"\A[A-Za-z0-9+=,.@_-]{1,64}\Z")
_BATCH_NAME_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")


class PilotIdentityError(ValueError):
    """A participant, run or tag value cannot be used in the pilot account.

    Messages never contain the raw user id.
    """


def participant_key(user_id: str) -> str:
    """Stable, non-reversible 16-hex-character key for one CryoStack user.

    The user id is hashed exactly as given (no trimming or case folding), so
    callers must always pass the same canonical id for the same person.
    """
    if not isinstance(user_id, str) or not user_id.strip():
        raise PilotIdentityError("a pilot participant needs a non-empty user id")
    digest = hashlib.sha256(_KEY_DOMAIN + user_id.encode("utf-8")).hexdigest()
    return digest[:PARTICIPANT_KEY_LENGTH]


def is_participant_key(value: str) -> bool:
    """Whether ``value`` has the shape of a participant key."""
    return isinstance(value, str) and bool(_KEY_RE.match(value))


def normalize_model(model: str) -> str:
    """Lower-case model name, restricted to what is safe inside AWS names."""
    name = (model or "").strip().lower() if isinstance(model, str) else ""
    if not _MODEL_RE.match(name):
        raise PilotIdentityError("a pilot model name must be 1-32 lowercase letters or digits")
    return name


def validate_run_id(run_id: str) -> str:
    """Return ``run_id`` unchanged if it has the staging run-id shape."""
    if not isinstance(run_id, str) or not _RUN_ID_RE.match(run_id):
        raise PilotIdentityError("unsafe run id for a pilot run")
    return run_id


def participant_prefix(user_id: str) -> str:
    """``pilot/<key>/`` -- the only S3 prefix this participant may touch."""
    return f"{PILOT_PREFIX}{participant_key(user_id)}/"


def run_prefix(user_id: str, run_id: str) -> str:
    """``pilot/<key>/runs/<run-id>/`` -- one run's input/ and outputs/ root."""
    return f"{participant_prefix(user_id)}runs/{validate_run_id(run_id)}/"


def participant_job_role_name(user_id: str) -> str:
    """IAM role name of this participant's Batch job (task) role."""
    name = f"{PILOT_JOB_ROLE_PREFIX}{participant_key(user_id)}"
    assert len(name) <= IAM_ROLE_NAME_MAX and _IAM_ROLE_NAME_RE.match(name)
    return name


def participant_job_definition_name(user_id: str, model: str) -> str:
    """Batch job-definition name for this participant and model.

    The key comes before the model so one IAM resource pattern
    (``job-definition/cryostack-pilot-<key>-*``) covers exactly this
    participant's definitions and nobody else's.
    """
    name = f"{PILOT_NAME_PREFIX}{participant_key(user_id)}-{normalize_model(model)}"
    assert len(name) <= BATCH_NAME_MAX and _BATCH_NAME_RE.match(name)
    return name


def participant_secret_name(user_id: str) -> str:
    """Secrets Manager name of this participant's own MATLAB-license secret:
    ``cryostack/pilot/<key>/matlab-license``. The fixed leaf after the key
    means no other participant's name can be a prefix or extension of it."""
    return f"{PILOT_SECRET_PREFIX}{participant_key(user_id)}/{PILOT_SECRET_LEAF}"


def validate_tag_value(value: str, *, what: str = "tag value") -> str:
    """Return ``value`` if it fits the AWS tag-value charset and length."""
    if not isinstance(value, str) or not _TAG_VALUE_RE.match(value):
        raise PilotIdentityError(
            f"{what} must be 1-{TAG_VALUE_MAX} characters of letters, digits, "
            "spaces or _ . : / = + - @")
    return value


def participant_tags(user_id: str, *, model: str | None = None) -> dict[str, str]:
    """Tags that identify a participant-owned resource (no run details)."""
    tags = {TAG_PILOT: "true", TAG_PARTICIPANT: participant_key(user_id)}
    if model is not None:
        tags[TAG_MODEL] = normalize_model(model)
    return tags


def job_tags(
    user_id: str,
    *,
    reservation_id: str,
    run_id: str,
    model: str,
) -> dict[str, str]:
    """Tags for one submitted pilot job (``aws batch submit-job --tags``).

    The participant value is the key -- never the user id or an e-mail
    address. ``reservation_id`` is the funding-ledger reservation the job is
    charged to; it must itself be an opaque id, not personal data.
    """
    tags = participant_tags(user_id, model=model)
    tags[TAG_RESERVATION] = validate_tag_value(reservation_id, what="reservation id")
    tags[TAG_RUN] = validate_tag_value(validate_run_id(run_id), what="run id")
    return tags
