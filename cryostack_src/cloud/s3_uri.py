# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : S3 location normalization
# File        : s3_uri.py
#
# Description :
#     One canonical representation for "where in S3" a cloud run reads and
#     writes, and the only place that parses / builds an ``s3://`` string.
#
# Author(s)   :
#     Brian Kyanjo
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""Canonical S3 location handling for CryoStack cloud execution.

Two representations, and exactly one function that converts between them:

* **bucket name** -- ``cryostack-runs-713938953301`` -- what every AWS API
  parameter that says ``Bucket=`` / ``--bucket`` wants;
* **``s3://`` URI** -- ``s3://cryostack-runs-.../runs/<user>/<run-id>`` -- what
  the ``aws s3 sync`` / ``aws s3 cp`` CLI and the container's
  ``CRYOSTACK_S3_RUN`` env want.

The UI field may hold any of ``bucket``, ``s3://bucket``, ``s3://bucket/``, or
``s3://bucket/some/prefix``. :func:`parse_s3_location` normalizes all of them to
``S3Location(bucket, prefix)`` -- a bad scheme, an empty bucket, or a malformed
bucket name raises :class:`S3LocationError`. An actual key prefix is **kept**
(it is never silently dropped) and becomes the base under which the per-user
``runs/<safe-user>/<run-id>`` tree is nested.

Do not add ``.replace("s3://", "")`` anywhere else -- call these helpers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# S3 bucket naming: lowercase letters, digits, '.', '-'; 3-63 chars; must start
# and end alphanumeric. (We do not enforce the "no consecutive dots" / "not an
# IP" edge rules -- AWS will, and CryoStack's own default names are clean.)
_BUCKET_RE = re.compile(r"\A[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]\Z")
_SCHEME_RE = re.compile(r"\As3://", re.IGNORECASE)
# a run-key prefix: zero or more safe "/"-separated segments
_PREFIX_RE = re.compile(r"\A(?:[A-Za-z0-9][A-Za-z0-9._-]{0,127}/?)*\Z")


class S3LocationError(ValueError):
    """The S3 bucket / URI a user gave cannot be normalized."""


@dataclass(frozen=True)
class S3Location:
    """A bucket and an optional key prefix (no leading/trailing slash)."""

    bucket: str
    prefix: str = ""

    def uri(self, *subkeys: str) -> str:
        """``s3://<bucket>[/<prefix>][/<subkeys...>]`` -- the CLI form."""
        parts = [
            seg.strip("/")
            for seg in (self.prefix, *subkeys)
            if seg and seg.strip("/")
        ]
        tail = "/".join(parts)
        return f"s3://{self.bucket}" + (f"/{tail}" if tail else "")

    def child(self, *subkeys: str) -> "S3Location":
        """A new location whose prefix is this one plus ``subkeys``."""
        parts = [
            seg.strip("/")
            for seg in (self.prefix, *subkeys)
            if seg and seg.strip("/")
        ]
        return S3Location(bucket=self.bucket, prefix="/".join(parts))


def parse_s3_location(value: str) -> S3Location:
    """Normalize ``bucket`` / ``s3://bucket`` / ``s3://bucket/pre/fix`` to an
    :class:`S3Location`. Raises :class:`S3LocationError` on anything else."""
    raw = (value or "").strip()
    if not raw:
        raise S3LocationError("An S3 bucket is required.")
    if "://" in raw and not _SCHEME_RE.match(raw):
        raise S3LocationError(
            f"An S3 location must be a bucket name or an s3:// URI, not {raw!r}.")

    body = _SCHEME_RE.sub("", raw)                      # 'bucket' or 'bucket/a/b'
    if body.startswith("/"):                            # s3:/// -> empty bucket
        raise S3LocationError("The S3 bucket name is empty.")
    bucket, _, prefix = body.partition("/")
    bucket = bucket.strip().lower()
    prefix = prefix.strip().strip("/")

    if not bucket:
        raise S3LocationError("The S3 bucket name is empty.")
    if not _BUCKET_RE.match(bucket):
        raise S3LocationError(
            f"{bucket!r} is not a valid S3 bucket name (lowercase letters, "
            "digits, '.', '-'; 3-63 characters).")
    if prefix and not _PREFIX_RE.match(prefix + "/"):
        raise S3LocationError(f"{prefix!r} is not a usable S3 key prefix.")

    return S3Location(bucket=bucket, prefix=prefix)


def bucket_name(value: str) -> str:
    """Just the bucket name -- for an AWS API ``Bucket=`` / ``--bucket`` arg."""
    return parse_s3_location(value).bucket


def s3_uri(value: str, *subkeys: str) -> str:
    """A full ``s3://`` URI, optionally with extra key segments appended."""
    return parse_s3_location(value).uri(*subkeys)
