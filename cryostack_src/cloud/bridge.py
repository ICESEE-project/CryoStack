from __future__ import annotations

from collections.abc import Callable
from typing import Any

from cryostack_src.execution.backend import ExecutionResult, ExecutionStatus
from cryostack_src.execution.cloud import CloudBackend

from .manager import CloudManager


class CloudBridge:
    """Stable, presentation-neutral API for CryoLauncher cloud operations."""

    def __init__(
        self,
        *,
        provider: str = "aws",
        region: str = "us-east-2",
        profile: str | None = None,
        submitter: Callable[..., Any] | None = None,
        results_sync: Callable[..., Any] | None = None,
    ) -> None:
        self.provider = provider
        self.region = region
        self.profile = profile
        self.submitter = submitter
        self.results_sync = results_sync
        self.backend = CloudBackend(
            provider=provider,
            region=region,
            profile=profile,
            submitter=submitter,
        )
        self.manager = CloudManager()

    def submit(self, **kwargs) -> ExecutionResult:
        if self.submitter is not None:
            return self.backend.submit(**kwargs)

        selected_backend = kwargs.get("backend", "")
        model = kwargs.get("model", "")
        s3_prefix = kwargs.get("s3_prefix", "")
        job_queue = kwargs.get("job_queue", "")
        job_definition = kwargs.get("job_definition", "")
        job_name = kwargs.get("job_name", "icesheets")

        return ExecutionResult(
            success=True,
            backend="cloud",
            messages=[
                "[cloud] Placeholder for AWS Batch submission.",
                f"[cloud] backend : {selected_backend}",
                f"[cloud] model   : {model}",
                f"[cloud] region  : {self.region or 'us-east-1'}",
                f"[cloud] profile : {self.profile or '(default)'}",
                f"[cloud] bucket  : {s3_prefix or '(not set)'}",
                f"[cloud] queue   : {job_queue or '(not set)'}",
                f"[cloud] job def : {job_definition or '(not set)'}",
                f"[cloud] job name: {job_name or 'icesheets'}",
                "[cloud] Next step is to adapt submit_cloud_example for model-only workflows.",
            ],
        )

    def status(self, *, job_id: str) -> ExecutionStatus:
        return self.backend.status(job_id=job_id)

    def logs(self, *, job_id: str) -> str:
        return self.backend.logs(job_id=job_id)

    def terminate(self, *, job_id: str):
        return self.backend.terminate(job_id=job_id)

    def results(self, *, s3_uri: str, **kwargs):
        if self.results_sync is None:
            raise RuntimeError("Cloud result synchronization is not configured.")
        return self.results_sync(s3_uri=s3_uri, **kwargs)

    def check_environment(self):
        return self.manager.capabilities(
            provider=self.provider,
            region=self.region,
            profile=self.profile,
        )

    def prepare_environment(self, *, bucket: str | None = None):
        return self.manager.bootstrap(
            provider=self.provider,
            region=self.region,
            profile=self.profile,
            bucket=bucket,
        )
