from __future__ import annotations

from pathlib import Path
from typing import Any

from .history import RunHistory
from .models import RunInfo


class WorkspaceBridge:
    def __init__(self, *, persistence: Any | None = None) -> None:
        self.history = RunHistory()
        self._persistence = persistence

    def register_run(self, run: RunInfo) -> None:
        self.history.add(run)

    def start_run(
        self,
        *,
        name: str,
        model: str,
        backend: str,
        execution_mode: str,
        jobid: str | None,
        remote_directory: Path,
        log_file: Path | None,
    ) -> RunInfo:
        return self.history.start(
            name=name,
            model=model,
            backend=backend,
            execution_mode=execution_mode,
            jobid=jobid,
            remote_directory=remote_directory,
            log_file=log_file,
        )

    def runs(self) -> list[RunInfo]:
        return self.history.all()

    def run(self, run_id: str) -> RunInfo | None:
        return self.history.get(run_id)

    def delete(self, run_id: str) -> None:
        self.history.remove(run_id)

    def widget(self):
        if self._persistence is None:
            return None
        return self._persistence.widget()

    def save(self, *, application: str, state: dict) -> None:
        if self._persistence is not None:
            self._persistence.save(application=application, state=state)
