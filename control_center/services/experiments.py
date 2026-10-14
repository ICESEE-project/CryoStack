"""
Control Center view of the shared experiments table.

Read-only by design: the Control Center cannot hold a researcher's SSH or
Connector session or their bring-your-own AWS role, so it never changes a
run (no cancel/retry) and never decides a run's outcome. Each record is
shown with what its application recorded: status, the bounded and redacted
failure summary, the scientific configuration (filter, ensemble size, ...)
and the requested -- and, only when recorded, measured -- resources. An
active record that stopped receiving updates is shown as "status unknown
since <time>", never as failed.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable

from ..storage import ControlStorage
from .compute import (
    STALE_AFTER_SECONDS,
    _execution_view,
    redact_text,
)


#: list columns kept from the stored row, as before
_LIST_FIELDS = (
    "id", "application", "name", "backend", "status", "job_id", "cluster",
    "created_at", "updated_at", "finished_at", "user_email", "user_name",
)

#: computed fields added to every list row and detail record
_VIEW_FIELDS = (
    "target", "runtime_seconds", "exit_code", "error", "failure",
    "resources", "overview", "status_unknown_since",
)


def _json(
    raw,
) -> dict:

    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}

    return value if isinstance(value, dict) else {}


class ExperimentService:

    def __init__(
        self,
        storage: ControlStorage,
        *,
        clock: Callable[[], float] = time.time,
        stale_after: float = STALE_AFTER_SECONDS,
    ) -> None:

        self.storage = storage
        self._clock = clock
        self.stale_after = stale_after


    def _view(
        self,
        row: dict,
        *,
        now: float,
    ) -> dict:

        view = _execution_view(
            row,
            now=now,
            last_failure=None,
            stale_after=self.stale_after,
        )

        return {
            field: view[field]
            for field in _VIEW_FIELDS
        }


    def list_experiments(
        self,
        *,
        limit: int = 100,
    ) -> list[dict]:

        with self.storage._connect() as connection:

            rows = connection.execute(
                """
                SELECT
                    e.id,
                    e.application,
                    e.name,
                    e.backend,
                    e.status,
                    e.job_id,
                    e.cluster,
                    e.exit_code,
                    e.error_message,
                    e.configuration_snapshot_json,
                    e.metadata_json,
                    e.created_at,
                    e.started_at,
                    e.updated_at,
                    e.finished_at,

                    u.email AS user_email,
                    u.display_name AS user_name

                FROM experiments e

                JOIN users u
                    ON u.id = e.user_id

                ORDER BY e.created_at DESC

                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()

        now = self._clock()

        experiments = []

        for row in rows:

            row = dict(row)

            item = {
                field: row.get(field)
                for field in _LIST_FIELDS
            }

            item.update(
                self._view(row, now=now)
            )

            experiments.append(item)

        return experiments


    def get_experiment(
        self,
        *,
        experiment_id: str,
    ) -> dict | None:

        experiment = self.storage.get_experiment(
            experiment_id=experiment_id,
        )

        if experiment is None:
            return None

        experiment["configuration"] = _json(
            experiment.get("configuration_snapshot_json")
        )

        experiment["metadata"] = _json(
            experiment.get("metadata_json")
        )

        events = (
            self.storage
            .list_experiment_events(
                experiment_id=experiment_id
            )
        )

        for event in events:

            event["metadata"] = _json(
                event.get("metadata_json")
            )

            if event.get("message"):
                event["message"] = redact_text(
                    event["message"],
                    limit=500,
                )

        experiment["events"] = events

        experiment.update(
            self._view(
                experiment,
                now=self._clock(),
            )
        )

        if experiment.get("error_message"):
            experiment["error_message"] = redact_text(
                experiment["error_message"],
                limit=500,
            )

        return experiment
