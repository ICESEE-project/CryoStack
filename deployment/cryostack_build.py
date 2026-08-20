#!/usr/bin/env python3

"""
CryoStack Deployment Engine

Build CryoStack applications from the dependency-aware
deployment registry in applications.yaml.

Examples:

    python deployment/cryostack_build.py list

    python deployment/cryostack_build.py build frozen-legacies

    python deployment/cryostack_build.py build livist

    python deployment/cryostack_build.py build all
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

import yaml
import json


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "deployment" / "applications.yaml"

def load_registry() -> dict:

    if not CONFIG.exists():
        raise FileNotFoundError(
            f"CryoStack deployment registry not found: {CONFIG}"
        )

    with CONFIG.open(
        "r",
        encoding="utf-8",
    ) as handle:

        registry = (
            yaml.safe_load(handle)
            or {}
        )

    if not isinstance(registry, dict):
        raise ValueError(
            "CryoStack deployment registry must contain a YAML mapping."
        )

    if "applications" not in registry:
        raise ValueError(
            "CryoStack deployment registry is missing 'applications'."
        )

    return registry

def dependency_order(
    ctx: BuildContext,
    name: str,
) -> list[str]:

    require_application(
        ctx,
        name,
    )

    ordered: list[str] = []
    visited: set[str] = set()
    visiting: set[str] = set()


    def visit(
        current: str,
    ) -> None:

        if current in visited:
            return

        if current in visiting:
            raise RuntimeError(
                f"Dependency cycle detected at '{current}'."
            )

        app = require_application(
            ctx,
            current,
        )

        visiting.add(
            current
        )

        for dependency in (
            app.get("dependencies")
            or []
        ):

            visit(
                dependency
            )

        visiting.remove(
            current
        )

        visited.add(
            current
        )

        ordered.append(
            current
        )


    visit(
        name
    )

    return ordered

RESTART_SCOPE_PRIORITY = {
    "none": 0,
    "gui": 1,
    "connector": 1,
    "all": 2,
}


def application_restart_scope(
    app: dict,
) -> str:

    restart = (
        app.get("restart")
        or {}
    )

    scope = str(
        restart.get(
            "scope",
            "none",
        )
    ).strip().lower()

    if scope not in RESTART_SCOPE_PRIORITY:

        raise ValueError(
            f"Invalid restart scope: {scope}"
        )

    return scope


def resolve_restart_scope(
    ctx: BuildContext,
    names: list[str],
) -> str:

    scopes = [
        application_restart_scope(
            ctx.apps[name]
        )
        for name in names
    ]

    if "all" in scopes:
        return "all"

    has_gui = (
        "gui" in scopes
    )

    has_connector = (
        "connector" in scopes
    )

    if (
        has_gui
        and has_connector
    ):
        return "all"

    if has_gui:
        return "gui"

    if has_connector:
        return "connector"

    return "none"

def print_application_policy(
    ctx: BuildContext,
    name: str,
) -> None:

    ordered = dependency_order(
        ctx,
        name,
    )

    target = ctx.apps[name]

    health = (
        target.get("health")
        or {}
    )

    payload = {
        "target":
            name,

        "applications":
            ordered,

        "restart_scope":
            resolve_restart_scope(
                ctx,
                ordered,
            ),

        "health_target":
            health.get(
                "target"
            ),

        "routes":
            target.get(
                "routes"
            )
            or [],
    }

    print(
        json.dumps(
            payload
        )
    )

class BuildContext:

    def __init__(self):

        self.registry = load_registry()

        self.platform = (
            self.registry.get("platform")
            or {}
        )

        self.apps = (
            self.registry.get("applications")
            or {}
        )

        self.root = ROOT

        # Applications successfully built during this invocation.
        self.built: set[str] = set()

        # Dependency stack used for cycle detection.
        self.visiting: set[str] = set()


def require_application(
    ctx: BuildContext,
    name: str,
) -> dict:

    app = ctx.apps.get(name)

    if app is None:

        available = ", ".join(
            sorted(ctx.apps)
        )

        raise ValueError(
            f"Unknown CryoStack application: {name}. "
            f"Available applications: {available}"
        )

    return app


def list_applications(
    ctx: BuildContext,
) -> None:

    print()
    print("CryoStack Applications")
    print("----------------------")

    for name, app in ctx.apps.items():

        title = (
            app.get("title")
            or name
        )

        dependencies = (
            app.get("dependencies")
            or []
        )

        dependency_text = (
            ", ".join(dependencies)
            if dependencies
            else "-"
        )

        print(
            f"{name:22} "
            f"{title:32} "
            f"depends on: {dependency_text}"
        )

    print()


def run_command(
    command,
    *,
    cwd: Path,
) -> None:

    command = [
        str(value)
        for value in command
    ]

    if not command:
        raise ValueError(
            "Build command cannot be empty."
        )

    print()
    print(
        ">",
        " ".join(command),
    )

    subprocess.run(
        command,
        cwd=str(cwd),
        check=True,
    )


def validate_artifacts(
    ctx: BuildContext,
    app: dict,
) -> None:

    missing = []

    for artifact in (
        app.get("artifacts")
        or []
    ):

        path = (
            ctx.root
            / artifact
        )

        if not path.exists():
            missing.append(path)

    if not missing:
        return

    print()
    print("Missing artifacts:")

    for path in missing:
        print(
            "   ",
            path,
        )

    raise RuntimeError(
        "Build completed, but one or more required artifacts "
        "were not produced."
    )


def check_requirements(
    app: dict,
) -> None:

    requirements = (
        app.get("requirements")
        or {}
    )

    for command in (
        requirements.get("commands")
        or []
    ):

        if shutil.which(command) is None:

            raise RuntimeError(
                f"Required executable "
                f"'{command}' was not found in PATH."
            )


def clean_outputs(
    ctx: BuildContext,
    app: dict,
) -> None:

    for entry in (
        app.get("clean")
        or []
    ):

        relative_path = (
            entry.get("path")
            if isinstance(entry, dict)
            else entry
        )

        if not relative_path:
            continue

        path = (
            ctx.root
            / relative_path
        )

        if not path.exists():
            continue

        print(
            f"[CryoStack] Cleaning {path}"
        )

        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


def build_application(
    ctx: BuildContext,
    name: str,
) -> None:

    app = require_application(
        ctx,
        name,
    )

    title = (
        app.get("title")
        or name
    )

    print()
    print("=" * 60)
    print(
        f"CryoStack build: {title}"
    )
    print("=" * 60)

    check_requirements(
        app
    )

    clean_outputs(
        ctx,
        app,
    )

    working_directory = (
        app.get(
            "working_directory"
        )
    )

    cwd = ctx.root

    if working_directory:

        cwd = (
            ctx.root
            / working_directory
        ).resolve()

        if not cwd.exists():
            raise FileNotFoundError(
                f"Working directory does not exist "
                f"for {name}: {cwd}"
            )

    build_steps = (
        app.get("build")
        or []
    )

    for step in build_steps:

        step_name = (
            step.get("name")
            or "Build step"
        )

        command = (
            step.get("command")
            or []
        )

        print()
        print(
            f"[CryoStack] {step_name}"
        )

        run_command(
            command,
            cwd=cwd,
        )

    validate_artifacts(
        ctx,
        app,
    )

    print()
    print(
        f"✓ {title} completed"
    )


def build_recursive(
    ctx: BuildContext,
    name: str,
) -> None:

    if name in ctx.built:
        return

    require_application(
        ctx,
        name,
    )

    if name in ctx.visiting:

        raise RuntimeError(
            f"Dependency cycle detected "
            f"while resolving '{name}'."
        )

    ctx.visiting.add(
        name
    )

    app = ctx.apps[name]

    for dependency in (
        app.get("dependencies")
        or []
    ):

        build_recursive(
            ctx,
            dependency,
        )

    ctx.visiting.remove(
        name
    )

    build_application(
        ctx,
        name,
    )

    ctx.built.add(
        name
    )


def build_all(
    ctx: BuildContext,
) -> None:

    for name in ctx.apps:

        build_recursive(
            ctx,
            name,
        )


def main() -> None:

    parser = argparse.ArgumentParser(
        description=(
            "CryoStack dependency-aware deployment builder"
        )
    )

    subparsers = parser.add_subparsers(
        dest="command"
    )

    subparsers.add_parser(
        "list",
        help="List registered CryoStack applications.",
    )

    build_parser = (
        subparsers.add_parser(
            "build",
            help="Build one application or the full platform.",
        )
    )

    build_parser.add_argument(
        "target",
        help=(
            "Application name or 'all'."
        ),
    )

    policy_parser = (
        subparsers.add_parser(
            "policy",
            help="Print deployment policy for an application.",
        )
    )

    policy_parser.add_argument(
        "target",
    )

    args = parser.parse_args()

    ctx = BuildContext()

    if args.command == "list":

        list_applications(
            ctx
        )

        return

    if args.command == "build":

        if args.target == "all":

            build_all(
                ctx
            )

        else:

            build_recursive(
                ctx,
                args.target,
            )

        return

    if args.command == "policy":

        print_application_policy(
            ctx,
            args.target,
        )

        return

    parser.print_help()


if __name__ == "__main__":
    main()