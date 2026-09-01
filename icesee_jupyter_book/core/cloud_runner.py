# ============================================================
# Cloud backend (AWS CLI + AWS Batch)
# ============================================================

from __future__ import annotations

import re
import time
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config_io import dump_yaml
from .example_discovery import find_run_script
from .local_runner import run_dir

@dataclass
class AWSBatchConfig:
    region: str = "us-east-1"
    profile: str | None = None
    s3_prefix: str = ""  # s3://bucket/prefix
    job_queue: str = ""
    job_definition: str = ""  # name[:revision]
    job_name: str = "icesee"


def _aws_cmd(cfg: AWSBatchConfig) -> list[str]:
    cmd = ["aws"]
    if cfg.profile:
        cmd += ["--profile", cfg.profile]
    if cfg.region:
        cmd += ["--region", cfg.region]
    return cmd


def _run(cmd: list[str]) -> tuple[int, str, str]:
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def _parse_s3(s3_uri: str) -> tuple[str, str]:
    m = re.match(r"^s3://([^/]+)/(.*)$", s3_uri.rstrip("/"))
    if not m:
        raise ValueError("S3 path must look like: s3://bucket/prefix")
    return m.group(1), m.group(2)


def aws_test(cfg: AWSBatchConfig) -> None:
    code, out, err = _run(_aws_cmd(cfg) + ["sts", "get-caller-identity"])
    if code != 0:
        raise RuntimeError(err or out)


def aws_batch_submit(
    cfg: AWSBatchConfig,
    local_run_dir: Path,
    example_name: str,
    run_script_name: str,
) -> dict:
    if not cfg.s3_prefix or not cfg.job_queue or not cfg.job_definition:
        raise ValueError("Cloud config missing: s3_prefix/job_queue/job_definition")

    run_id = time.strftime("%Y%m%d-%H%M%S")
    bucket, prefix = _parse_s3(cfg.s3_prefix)
    s3_run = f"s3://{bucket}/{prefix}/{run_id}"

    params_path = local_run_dir / "params.yaml"
    if not params_path.exists():
        raise FileNotFoundError(f"params.yaml not found: {params_path}")

    # upload params
    code, out, err = _run(_aws_cmd(cfg) + ["s3", "cp", str(params_path), f"{s3_run}/params.yaml"])
    if code != 0:
        raise RuntimeError(err or out)

    manifest = {"run_id": run_id, "example": example_name, "run_script": run_script_name}
    (local_run_dir / "cloud_manifest.json").write_text(json.dumps(manifest, indent=2))
    _run(_aws_cmd(cfg) + ["s3", "cp", str(local_run_dir / "cloud_manifest.json"), f"{s3_run}/cloud_manifest.json"])

    env = [
        {"name": "ICESEE_S3_RUN", "value": s3_run},
        {"name": "ICESEE_EXAMPLE", "value": example_name},
        {"name": "ICESEE_RUN_SCRIPT", "value": run_script_name},
    ]

    submit_cmd = _aws_cmd(cfg) + [
        "batch",
        "submit-job",
        "--job-name",
        f"{cfg.job_name}-{run_id}",
        "--job-queue",
        cfg.job_queue,
        "--job-definition",
        cfg.job_definition,
        "--container-overrides",
        json.dumps({"environment": env}),
    ]
    code, out, err = _run(submit_cmd)
    if code != 0:
        raise RuntimeError(err or out)

    job_id = json.loads(out)["jobId"]
    return {"run_id": run_id, "batch_job_id": job_id, "s3_run": s3_run}


def aws_batch_status(cfg: AWSBatchConfig, job_id: str) -> dict:
    code, out, err = _run(_aws_cmd(cfg) + ["batch", "describe-jobs", "--jobs", job_id])
    if code != 0:
        raise RuntimeError(err or out)
    job = json.loads(out)["jobs"][0]
    return {"status": job.get("status", "?"), "reason": job.get("statusReason", "")}

@dataclass
class CloudSubmitResult:
    success: bool
    run_dir: Path
    batch_job_id: str
    s3_run: str
    run_id: str
    messages: list[str]


def submit_cloud_example(
    *,
    example_name: str,
    example_cfg: dict,
    config: dict,
    region: str,
    profile: str | None,
    s3_prefix: str,
    job_queue: str,
    job_definition: str,
    job_name: str,
    run_dir_base: "Path | str | None" = None,
    run_dir_name: str | None = None,
) -> CloudSubmitResult:
    rd = run_dir(run_dir_base, run_dir_name)
    dump_yaml(config, rd / "params.yaml")

    cfg = AWSBatchConfig(
        region=region or "us-east-1",
        profile=(profile or None),
        s3_prefix=s3_prefix,
        job_queue=job_queue,
        job_definition=job_definition,
        job_name=job_name or "icesee",
    )

    aws_test(cfg)
    resp = aws_batch_submit(cfg, rd, example_name, find_run_script(example_cfg).name)

    messages = [
        "[cloud] Submitted.",
        f"batch_job_id: {resp['batch_job_id']}",
        f"s3_run      : {resp['s3_run']}",
        "",
        "[batch image requirement]",
        "Your AWS Batch container must read ICESEE_S3_RUN and ICESEE_RUN_SCRIPT,",
        "download params.yaml from S3, run, then sync results back to S3.",
    ]

    return CloudSubmitResult(
        success=True,
        run_dir=rd,
        batch_job_id=resp["batch_job_id"],
        s3_run=resp["s3_run"],
        run_id=resp["run_id"],
        messages=messages,
    )