#!/usr/bin/env python3

"""
CryoStack registry-driven health checks.

Examples:

    python deployment/health_check.py

    python deployment/health_check.py --wait 60

    python deployment/health_check.py \
        --application frozen-legacies
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]

CONFIG = (
    ROOT
    / "deployment"
    / "applications.yaml"
)

BASE_URL = "http://127.0.0.1:8080"


@dataclass(frozen=True)
class HealthTarget:

    name: str
    path: str

    expected_statuses: tuple[int, ...] = (
        200,
    )

    required_text: tuple[str, ...] = ()


def load_registry() -> dict[str, Any]:

    if not CONFIG.exists():

        raise FileNotFoundError(
            f"Deployment registry not found: "
            f"{CONFIG}"
        )

    with CONFIG.open(
        "r",
        encoding="utf-8",
    ) as handle:

        registry = (
            yaml.safe_load(
                handle
            )
            or {}
        )

    if not isinstance(
        registry,
        dict,
    ):

        raise ValueError(
            "Deployment registry must "
            "contain a YAML mapping."
        )

    return registry


def normalize_statuses(
    values,
) -> tuple[int, ...]:

    if values is None:
        return (
            200,
        )

    if isinstance(
        values,
        int,
    ):
        return (
            values,
        )

    return tuple(
        int(value)
        for value in values
    )


def normalize_required_text(
    value,
) -> tuple[str, ...]:

    if value is None:
        return ()

    if isinstance(
        value,
        str,
    ):
        return (
            value,
        )

    return tuple(
        str(item)
        for item in value
    )


def target_from_config(
    name: str,
    config: dict[str, Any],
) -> HealthTarget:

    path = str(
        config.get(
            "path",
            "",
        )
    ).strip()

    if not path:

        raise ValueError(
            f"Health target '{name}' "
            f"is missing a path."
        )

    if not path.startswith(
        "/"
    ):
        path = (
            "/"
            + path
        )

    return HealthTarget(

        name=
            name,

        path=
            path,

        expected_statuses=
            normalize_statuses(
                config.get(
                    "expected_statuses"
                )
            ),

        required_text=
            normalize_required_text(
                config.get(
                    "required_text"
                )
            ),
    )


def registered_health_targets(
    registry: dict[str, Any],
) -> dict[str, HealthTarget]:

    targets: dict[
        str,
        HealthTarget,
    ] = {}


    # --------------------------------------------------------
    # Platform-level health targets
    # --------------------------------------------------------

    platform = (
        registry.get(
            "platform"
        )
        or {}
    )

    platform_health = (
        platform.get(
            "health"
        )
        or {}
    )

    for (
        name,
        config,
    ) in platform_health.items():

        targets[
            str(name)
        ] = target_from_config(
            str(name),
            config or {},
        )


    # --------------------------------------------------------
    # Application health targets
    # --------------------------------------------------------

    applications = (
        registry.get(
            "applications"
        )
        or {}
    )

    for (
        app_name,
        app,
    ) in applications.items():

        health = (
            app.get(
                "health"
            )
            or {}
        )

        target_name = (
            health.get(
                "target"
            )
        )

        if not target_name:
            continue


        # The health block may contain only:
        #
        #   target: frozen-legacies
        #
        # If so, use the first declared route.

        path = (
            health.get(
                "path"
            )
        )

        if not path:

            routes = (
                app.get(
                    "routes"
                )
                or []
            )

            if routes:

                path = routes[
                    0
                ]


        config = dict(
            health
        )

        config[
            "path"
        ] = path


        targets[
            str(
                target_name
            )
        ] = target_from_config(
            str(
                target_name
            ),
            config,
        )


    return targets


def check_target(
    target: HealthTarget,
    *,
    timeout: float = 10.0,
) -> tuple[bool, str]:

    url = (
        BASE_URL.rstrip("/")
        + target.path
    )


    request = urllib.request.Request(

        url,

        method=
            "GET",

        headers={
            "User-Agent":
                "CryoStack-HealthCheck/1.0",
        },
    )


    try:

        with urllib.request.urlopen(
            request,
            timeout=timeout,
        ) as response:

            status = (
                response.status
            )


            if (
                status
                not in target.expected_statuses
            ):

                return (
                    False,
                    f"HTTP {status}",
                )


            if (
                target.required_text
            ):

                body = (
                    response.read()
                    .decode(
                        "utf-8",
                        errors="replace",
                    )
                )


                missing = [
                    text
                    for text
                    in target.required_text
                    if text not in body
                ]


                if missing:

                    return (
                        False,
                        "missing content: "
                        + ", ".join(
                            repr(value)
                            for value
                            in missing
                        ),
                    )


            return (
                True,
                f"HTTP {status}",
            )


    except urllib.error.HTTPError as error:

        if (
            error.code
            in target.expected_statuses
        ):

            return (
                True,
                f"HTTP {error.code}",
            )


        return (
            False,
            f"HTTP {error.code}",
        )


    except Exception as error:

        return (
            False,
            f"{type(error).__name__}: "
            f"{error}",
        )


def check_targets(
    targets: list[HealthTarget],
    *,
    timeout: float,
) -> bool:

    healthy = True


    print()
    print(
        "CryoStack health check"
    )

    print(
        "----------------------"
    )


    for target in targets:

        ok, detail = check_target(
            target,
            timeout=timeout,
        )


        marker = (
            "✓"
            if ok
            else "✗"
        )


        print(
            f"{marker} "
            f"{target.name:22} "
            f"{target.path:26} "
            f"{detail}"
        )


        if not ok:

            healthy = False


    print()


    return healthy


def wait_for_health(
    targets: list[HealthTarget],
    *,
    wait_seconds: float,
    request_timeout: float,
    interval: float = 2.0,
) -> bool:

    deadline = (
        time.monotonic()
        + wait_seconds
    )

    attempt = 0


    while True:

        attempt += 1


        print(
            "[CryoStack] "
            f"Health-check attempt "
            f"{attempt}"
        )


        healthy = check_targets(
            targets,
            timeout=request_timeout,
        )


        if healthy:

            return True


        if (
            time.monotonic()
            >= deadline
        ):

            return False


        time.sleep(
            interval
        )


def resolve_targets(
    registry: dict[str, Any],
    requested: str | None,
) -> list[HealthTarget]:

    available = (
        registered_health_targets(
            registry
        )
    )


    if requested is None:

        return list(
            available.values()
        )


    target = available.get(
        requested
    )


    if target is None:

        names = ", ".join(
            sorted(
                available
            )
        )


        raise ValueError(
            f"Unknown health-check "
            f"target: {requested}. "
            f"Available: {names}"
        )


    return [
        target
    ]


def list_targets(
    registry: dict[str, Any],
) -> None:

    targets = (
        registered_health_targets(
            registry
        )
    )


    print()
    print(
        "CryoStack health targets"
    )

    print(
        "------------------------"
    )


    for (
        name,
        target,
    ) in targets.items():

        statuses = (
            ", ".join(
                str(value)
                for value
                in target.expected_statuses
            )
        )


        print(
            f"{name:22} "
            f"{target.path:28} "
            f"HTTP {statuses}"
        )


    print()


def main() -> int:

    parser = argparse.ArgumentParser(
        description=(
            "CryoStack registry-driven "
            "runtime health checks."
        )
    )


    parser.add_argument(
        "--application",
        default=None,
        help=(
            "Check one registered "
            "health target."
        ),
    )


    parser.add_argument(
        "--wait",
        type=float,
        default=0.0,
        help=(
            "Wait up to this many "
            "seconds for the selected "
            "targets to become healthy."
        ),
    )


    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help=(
            "Timeout for each "
            "HTTP request."
        ),
    )


    parser.add_argument(
        "--list",
        action="store_true",
        help=(
            "List registered "
            "health targets."
        ),
    )


    args = parser.parse_args()


    try:

        registry = (
            load_registry()
        )


        if args.list:

            list_targets(
                registry
            )

            return 0


        targets = resolve_targets(
            registry,
            args.application,
        )


        if not targets:

            print(
                "[CryoStack] "
                "No health targets "
                "are configured."
            )

            return 0


        if args.wait > 0:

            healthy = (
                wait_for_health(
                    targets,

                    wait_seconds=
                        args.wait,

                    request_timeout=
                        args.timeout,
                )
            )

        else:

            healthy = (
                check_targets(
                    targets,
                    timeout=
                        args.timeout,
                )
            )


        if healthy:

            print(
                "[CryoStack] "
                "Health check passed."
            )

            return 0


        print(
            "[CryoStack][ERROR] "
            "Health check failed."
        )

        return 1


    except Exception as error:

        print(
            "[CryoStack][ERROR]",
            type(error).__name__,
            error,
        )

        return 2


if __name__ == "__main__":

    sys.exit(
        main()
    )