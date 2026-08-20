from __future__ import annotations

import json
import time

from ..storage import ControlStorage


class ExperimentService:

    def __init__(
        self,
        storage: ControlStorage,
    ) -> None:

        self.storage = storage


    def list_experiments(
        self,
    ) -> list[dict]:

        return self.storage.list_experiments()


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

        try:
            experiment["configuration"] = json.loads(
                experiment.get(
                    "configuration_snapshot_json",
                    "{}",
                )
                or "{}"
            )

        except Exception:
            experiment["configuration"] = {}

        try:
            experiment["metadata"] = json.loads(
                experiment.get(
                    "metadata_json",
                    "{}",
                )
                or "{}"
            )

        except Exception:
            experiment["metadata"] = {}

        events = (
            self.storage
            .list_experiment_events(
                experiment_id=experiment_id
            )
        )

        for event in events:

            try:
                event["metadata"] = json.loads(
                    event.get(
                        "metadata_json",
                        "{}",
                    )
                    or "{}"
                )

            except Exception:
                event["metadata"] = {}

        experiment["events"] = events

        start = (
            experiment.get("started_at")
            or experiment.get("created_at")
        )

        end = (
            experiment.get("finished_at")
            or time.time()
        )

        experiment["runtime_seconds"] = (
            max(
                0,
                int(end - start),
            )
            if start
            else None
        )

        return experiment