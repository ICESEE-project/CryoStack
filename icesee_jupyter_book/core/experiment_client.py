"""HTTP client helpers for CryoStack experiment tracking."""

from __future__ import annotations

import json
from typing import Any
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError


BASE_URL = "http://127.0.0.1:8080"


def _json_request(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    cookie: str | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    data = None

    headers = {
        "Accept": "application/json",
    }

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    if cookie:
        headers["Cookie"] = cookie

    req = urllib_request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urllib_request.urlopen(
            req,
            timeout=timeout,
        ) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}

    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"CryoStack API returned HTTP {exc.code}: {body}"
        ) from exc

    except URLError as exc:
        raise RuntimeError(
            f"CryoStack API is unavailable: {exc}"
        ) from exc


def create_experiment(
    *,
    cookie: str,
    application: str,
    name: str,
    backend: str,
    configuration: dict[str, Any],
    cluster: str | None = None,
    working_directory: str | None = None,
    output_directory: str | None = None,
    log_path: str | None = None,
    job_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    status: str = "queued",
) -> dict[str, Any]:
    return _json_request(
        "POST",
        "/api/v1/experiments",
        cookie=cookie,
        payload={
            "application": application,
            "name": name,
            "backend": backend,
            "configuration": configuration,
            "cluster": cluster,
            "working_directory": working_directory,
            "output_directory": output_directory,
            "log_path": log_path,
            "job_id": job_id,
            "metadata": metadata or {},
            "status": status,
        },
    )


def update_experiment(
    *,
    cookie: str,
    experiment_id: str,
    **fields: Any,
) -> dict[str, Any]:
    payload = {
        key: value
        for key, value in fields.items()
        if value is not None
    }

    return _json_request(
        "PATCH",
        f"/api/v1/experiments/{experiment_id}",
        cookie=cookie,
        payload=payload,
    )
