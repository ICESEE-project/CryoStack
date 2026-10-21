from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .models import RunInfo

MANIFEST_NAME = ".cryostack-run.json"
SCHEMA = "cryostack.run"
VERSION = 2
#: schema versions this build can read
SUPPORTED_VERSIONS = (1, 2)


def write_manifest(run: RunInfo, workspace: Path) -> Path:
    workspace.mkdir(parents=True, exist_ok=True)
    path = workspace / MANIFEST_NAME
    payload = {
        "schema": SCHEMA,
        "version": VERSION,
        "run": {
            "id": run.id,
            "name": run.name,
            "model": run.model,
            "backend": run.backend,
            "execution_mode": run.execution_mode,
            "status": run.status,
            "job_id": run.jobid,
            "created": run.created.isoformat(),
            "finished": run.finished.isoformat() if run.finished else None,
            "workspace": str(workspace.resolve()),
            "remote_directory": str(run.remote_directory) if run.remote_directory else None,
            "results_directory": str(run.results_directory) if run.results_directory else None,
            "figures_directory": str(run.figures_directory) if run.figures_directory else None,
            "log_file": str(run.log_file) if run.log_file else None,
            "command": run.command,
            "notes": run.notes,
            "metadata": run.metadata,
            "container": run.container or {},
            "software": run.software or {},
        },
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)
    return path


def read_manifest(path: Path) -> RunInfo:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != SCHEMA or payload.get("version") not in SUPPORTED_VERSIONS:
        raise ValueError("Unsupported CryoStack run manifest")
    data = payload["run"]
    # The manifest's own directory is the run workspace. A different recorded
    # path means the workspace was moved (e.g. the storage migration to the
    # durable data root); local paths inside the old workspace follow it.
    recorded = Path(data["workspace"]).resolve()
    workspace = path.parent.resolve()

    def optional_path(name):
        value = data.get(name)
        if not value:
            return None
        local = Path(value)
        if recorded != workspace and local.is_absolute():
            try:
                return workspace / local.resolve().relative_to(recorded)
            except ValueError:
                pass
        return local
    return RunInfo(
        id=str(data["id"]), name=str(data["name"]), model=str(data["model"]),
        backend=str(data["backend"]), execution_mode=str(data["execution_mode"]),
        status=str(data.get("status") or "submitted"),
        created=datetime.fromisoformat(data["created"]),
        finished=datetime.fromisoformat(data["finished"]) if data.get("finished") else None,
        workspace_directory=workspace,
        remote_directory=optional_path("remote_directory"),
        results_directory=optional_path("results_directory"),
        figures_directory=optional_path("figures_directory"),
        log_file=optional_path("log_file"), jobid=data.get("job_id"),
        command=str(data.get("command") or ""), notes=str(data.get("notes") or ""),
        metadata=dict(data.get("metadata") or {}),
        # v1 manifests have no provenance -> {}
        container=dict(data.get("container") or {}),
        software=dict(data.get("software") or {}),
    )
