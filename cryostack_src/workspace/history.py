from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from .models import RunInfo


class RunHistory:
    def __init__(self) -> None:
        self._runs: dict[str, RunInfo] = {}

    def add(self, run: RunInfo) -> None:
        self._runs[run.id] = run

    def remove(self, run_id: str) -> None:
        self._runs.pop(run_id, None)

    def get(self, run_id: str) -> RunInfo | None:
        return self._runs.get(run_id)

    def all(self) -> list[RunInfo]:
        return list(self._runs.values())

    def clear(self) -> None:
        self._runs.clear()

    def start(
        self,
        *,
        name: str,
        model: str,
        backend: str,
        execution_mode: str,
        jobid: str | None,
        remote_directory: Path,
        log_file: Path | None,
        metadata: dict | None = None,
        container: dict | None = None,
        software: dict | None = None,
    ) -> RunInfo:
        run = RunInfo(
            id=str(uuid4()),
            name=name,
            model=model,
            backend=backend,
            execution_mode=execution_mode,
            status="running",
            jobid=jobid,
            remote_directory=remote_directory,
            log_file=log_file,
            metadata=dict(metadata or {}),
            container=dict(container or {}),
            software=dict(software or {}),
        )
        self.add(run)
        return run
