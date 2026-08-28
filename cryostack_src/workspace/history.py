from __future__ import annotations

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
