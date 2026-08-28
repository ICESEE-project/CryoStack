from __future__ import annotations

from pathlib import Path
from typing import Any

from .history import RunHistory
from .models import RunInfo


class WorkspaceBridge:
    def __init__(self, *, persistence: Any | None = None) -> None:
        self.history = RunHistory()
        self._persistence = persistence
        self._manager = None

    def attach_manager(self, manager) -> None:
        self._manager = manager
        for run in manager.refresh():
            self.history.add(run)

    def register_run(self, run: RunInfo) -> None:
        self.history.add(run)
        if self._manager is not None:
            self._manager.register_run(run)

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
        metadata: dict | None = None,
    ) -> RunInfo:
        run = self.history.start(
            name=name,
            model=model,
            backend=backend,
            execution_mode=execution_mode,
            jobid=jobid,
            remote_directory=remote_directory,
            log_file=log_file,
            metadata=metadata,
        )
        if self._manager is not None:
            self._manager.register_run(run)
        return run

    def refresh(self):
        if self._manager is None:
            return self.runs()
        runs = self._manager.refresh()
        self.history.clear()
        for run in runs:
            self.history.add(run)
        return runs

    def list_runs(self):
        return self.refresh()

    def select_run(self, run_id):
        return self._manager.select_run(run_id) if self._manager else self.run(run_id)

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
