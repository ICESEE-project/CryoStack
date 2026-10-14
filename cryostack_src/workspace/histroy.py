from __future__ import annotations

from .models import RunInfo


class RunHistory:

    def __init__(self):

        self._runs = {}

    def add(self, run):

        self._runs[run.id] = run

    def remove(self, run_id):

        self._runs.pop(run_id, None)

    def get(self, run_id):

        return self._runs.get(run_id)

    def all(self):

        return list(self._runs.values())

    def clear(self):

        self._runs.clear()