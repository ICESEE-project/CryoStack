from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .storage import AuthStorage, Experiment

from .application_registry import get_application


def account_navigation(source_application: str = ""):
    source_application = (
        source_application or ""
    ).strip().lower()

    app = get_application(source_application)

    source_query = (
        f"?from={source_application}"
        if source_application
        else ""
    )

    return (
        app["url"],
        f"← Back to {app['title']}",
        source_query,
    )
    
class ExperimentService:
    def __init__(
        self,
        database_path: Path | None = None,
    ) -> None:
        default_database = (
            Path(__file__).resolve().parent.parent
            / "var"
            / "cryostack_auth.db"
        )

        self._storage = AuthStorage(
            database_path or default_database
        )

    def create(
        self,
        *,
        user_id: str,
        application: str,
        name: str,
        backend: str,
        configuration: dict[str, Any],
        configuration_id: str | None = None,
        job_id: str | None = None,
        cluster: str | None = None,
        working_directory: str | None = None,
        output_directory: str | None = None,
        log_path: str | None = None,
        metadata: dict[str, Any] | None = None,
        status: str = "queued",
    ) -> Experiment:
        return self._storage.create_experiment(
            user_id=user_id,
            configuration_id=configuration_id,
            application=application,
            name=name,
            backend=backend,
            status=status,
            configuration_snapshot_json=json.dumps(
                configuration,
                sort_keys=True,
            ),
            job_id=job_id,
            cluster=cluster,
            working_directory=working_directory,
            output_directory=output_directory,
            log_path=log_path,
            metadata_json=json.dumps(
                metadata or {},
                sort_keys=True,
            ),
        )

    def update(
        self,
        *,
        user_id: str,
        experiment_id: str,
        **fields: Any,
    ) -> Experiment | None:
        metadata = fields.pop("metadata", None)

        return self._storage.update_experiment(
            user_id=user_id,
            experiment_id=experiment_id,
            metadata_json=(
                json.dumps(metadata, sort_keys=True)
                if metadata is not None
                else None
            ),
            **fields,
        )