# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : Cloud Infrastructure Smoke Test
# File        : smoke.py
#
# Description :
#     A license-neutral check that CryoStack can actually reach the AWS
#     infrastructure a cloud run needs -- identity, S3, Batch, ECR -- WITHOUT
#     submitting a billable Batch job.
#
# Author(s)   :
#     Brian Kyanjo
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""Cloud infrastructure smoke test.

This is **not** an ISSM run. It verifies the pipeline's *plumbing*:

    CryoStack -> AWS identity -> S3 write/read/delete (under the user's own
    prefix) -> Batch queue + job definition reachable -> ECR image present.

It does not run a container, does not submit a job, and does not touch a
MATLAB license -- so it works on an account with no ISSM licence configured.
The only AWS cost is a few bytes of S3 I/O that is deleted immediately.

The full "container actually runs" smoke test (a tiny job that writes a
structured test output and syncs it back) is a *manual* step in the AWS
acceptance checklist -- it needs the ``smoke`` branch of the baked runner and
a real, human-authorised submission.

Every AWS call goes through an injectable ``aws(args) -> (code, out, err)`` so
the whole module is offline-testable.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from .drivers.aws.auth import run_aws
from .drivers.aws.models import AWSConfig
from .s3_uri import S3LocationError
from .s3_uri import bucket_name as _s3_bucket_name

_PASS, _FAIL, _SKIP = "PASS", "FAIL", "SKIP"


@dataclass
class SmokeCheck:
    name: str
    status: str
    detail: str = ""


@dataclass
class SmokeReport:
    checks: list[SmokeCheck] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.status != _FAIL for c in self.checks)

    @property
    def infrastructure_ready(self) -> bool:
        """True iff every non-skipped check passed -- i.e. a real cloud run
        would not fail on plumbing (it could still fail on the MATLAB licence,
        which this test deliberately does not check)."""
        return self.ok and any(c.status == _PASS for c in self.checks)

    def add(self, name, status, detail=""):
        self.checks.append(SmokeCheck(name, status, detail))

    def lines(self) -> list[str]:
        mark = {_PASS: "PASS", _FAIL: "FAIL", _SKIP: "SKIP"}
        return [f"  [{mark[c.status]}] {c.name}"
                + (f" — {c.detail}" if c.detail else "") for c in self.checks]


def run_infrastructure_smoke_test(
    *,
    region: str,
    bucket: str,
    user_prefix: str,
    job_queue: str = "",
    job_definition: str = "",
    ecr_repository: str = "",
    profile: str | None = None,
    credentials: dict | None = None,
    aws=None,
) -> SmokeReport:
    """Probe the AWS infrastructure a cloud run needs. Never submits a job.

    ``credentials`` (assumed-role temporary env, BYO-AWS) wins over ``profile``
    so a connected user's smoke test probes *their* account.
    """
    config = AWSConfig(
        region=region,
        profile=None if credentials else profile,
        credentials=credentials,
    )
    invoke = aws or (lambda args: run_aws(config, args))
    report = SmokeReport()

    try:                                    # accept a name or an s3:// URI
        bucket = _s3_bucket_name(bucket)
    except S3LocationError as err:
        report.add("S3 bucket", _FAIL, str(err))
        return report

    # 1. identity ---------------------------------------------------------
    code, out, err = invoke(["sts", "get-caller-identity", "--output", "json"])
    if code != 0:
        report.add("AWS identity", _FAIL, (err or out).strip()[:200]
                   or "aws sts get-caller-identity failed")
        return report                       # nothing else can work
    try:
        acct = json.loads(out or "{}").get("Account", "?")
    except ValueError:
        acct = "?"
    report.add("AWS identity", _PASS, f"account {acct}")

    # 2. S3 write / read / delete under the caller's own run prefix ------
    prefix = (user_prefix or "").strip().strip("/")
    key = f"runs/{prefix}/_smoke/probe-{int(time.time())}.txt" if prefix \
        else f"runs/_smoke/probe-{int(time.time())}.txt"
    uri = f"s3://{bucket}/{key}"
    payload = f"cryostack cloud smoke test {time.time()}\n"
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp()) / "probe.txt"
    tmp.write_text(payload)
    back = tmp.with_name("probe_back.txt")
    try:
        c1, _, e1 = invoke(["s3", "cp", str(tmp), uri, "--only-show-errors"])
        if c1 != 0:
            report.add("S3 write (your prefix)", _FAIL,
                       (e1 or "").strip()[:200] or f"cannot write {uri}")
        else:
            c2, _, e2 = invoke(["s3", "cp", uri, str(back), "--only-show-errors"])
            match = c2 == 0 and back.is_file() and back.read_text() == payload
            report.add("S3 write + read (your prefix)", _PASS if match else _FAIL,
                       "" if match else (e2 or "read-back mismatch").strip()[:200])
            c3, _, _ = invoke(["s3", "rm", uri, "--only-show-errors"])
            report.add("S3 cleanup", _PASS if c3 == 0 else _FAIL,
                       "" if c3 == 0 else "could not delete the probe object")
    finally:
        tmp.unlink(missing_ok=True)
        back.unlink(missing_ok=True)

    # 3. Batch job queue -----------------------------------------------
    if job_queue:
        code, out, err = invoke(
            ["batch", "describe-job-queues", "--job-queues", job_queue,
             "--output", "json"])
        state = ""
        if code == 0:
            try:
                qs = json.loads(out or "{}").get("jobQueues", [])
                state = (qs[0].get("state", ""), qs[0].get("status", "")) if qs else ()
            except (ValueError, IndexError, AttributeError):
                state = ()
        ok = code == 0 and state and state[0] == "ENABLED"
        report.add("Batch job queue", _PASS if ok else _FAIL,
                   f"{job_queue}: {state}" if code == 0
                   else (err or "").strip()[:200])
    else:
        report.add("Batch job queue", _SKIP, "no queue configured")

    # 4. Batch job definition ----------------------------------------
    if job_definition:
        name = job_definition.split(":", 1)[0]
        code, out, err = invoke(
            ["batch", "describe-job-definitions", "--job-definition-name", name,
             "--status", "ACTIVE", "--output", "json"])
        found = False
        if code == 0:
            try:
                found = bool(json.loads(out or "{}").get("jobDefinitions", []))
            except ValueError:
                found = False
        report.add("Batch job definition", _PASS if found else _FAIL,
                   f"{name} (ACTIVE)" if found
                   else (err or f"no ACTIVE {name}").strip()[:200])
    else:
        report.add("Batch job definition", _SKIP, "no job definition configured")

    # 5. ECR image ---------------------------------------------------
    if ecr_repository:
        code, out, err = invoke(
            ["ecr", "describe-images", "--repository-name", ecr_repository,
             "--output", "json"])
        has_image = False
        if code == 0:
            try:
                has_image = bool(json.loads(out or "{}").get("imageDetails", []))
            except ValueError:
                has_image = False
        report.add("ECR image", _PASS if has_image else _FAIL,
                   f"{ecr_repository}" if has_image
                   else (err or f"no images in {ecr_repository}").strip()[:200])
    else:
        report.add("ECR image", _SKIP, "no repository configured")

    return report
