#!/usr/bin/env python3

"""
CryoStack deployment preflight checks.

Run this before stopping any live services.

Examples:

    python deployment/preflight.py

    python deployment/preflight.py --application frozen-legacies

    python deployment/preflight.py --application livist
"""

from __future__ import annotations

import argparse
import shutil
import sys, os
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]

CONFIG = (
    ROOT
    / "deployment"
    / "applications.yaml"
)


# ============================================================
# Output helpers
# ============================================================

def ok(
    message: str,
) -> None:

    print(
        f"✓ {message}"
    )


def warn(
    message: str,
) -> None:

    print(
        f"! {message}"
    )


def fail(
    message: str,
) -> None:

    print(
        f"✗ {message}"
    )


# ============================================================
# Registry
# ============================================================

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


    applications = (
        registry.get(
            "applications"
        )
    )


    if not isinstance(
        applications,
        dict,
    ):

        raise ValueError(
            "Deployment registry is missing "
            "a valid 'applications' mapping."
        )


    return registry


# ============================================================
# Dependency validation
# ============================================================

def validate_dependencies(
    applications: dict[str, Any],
) -> None:

    visiting: set[str] = set()
    visited: set[str] = set()


    def visit(
        name: str,
    ) -> None:

        if name in visited:
            return


        if name in visiting:

            raise RuntimeError(
                "Dependency cycle detected "
                f"at application '{name}'."
            )


        app = applications.get(
            name
        )


        if app is None:

            raise ValueError(
                f"Unknown application dependency: "
                f"{name}"
            )


        visiting.add(
            name
        )


        for dependency in (
            app.get(
                "dependencies"
            )
            or []
        ):

            if (
                dependency
                not in applications
            ):

                raise ValueError(
                    f"Application '{name}' "
                    f"depends on unknown application "
                    f"'{dependency}'."
                )


            visit(
                dependency
            )


        visiting.remove(
            name
        )

        visited.add(
            name
        )


    for name in applications:

        visit(
            name
        )


# ============================================================
# Application selection
# ============================================================

def dependency_closure(
    applications: dict[str, Any],
    target: str | None,
) -> list[str]:

    if target is None:

        return list(
            applications
        )


    if target not in applications:

        available = ", ".join(
            sorted(
                applications
            )
        )

        raise ValueError(
            f"Unknown application: {target}. "
            f"Available: {available}"
        )


    ordered: list[str] = []

    visited: set[str] = set()


    def visit(
        name: str,
    ) -> None:

        if name in visited:
            return


        app = applications[
            name
        ]


        for dependency in (
            app.get(
                "dependencies"
            )
            or []
        ):

            visit(
                dependency
            )


        visited.add(
            name
        )

        ordered.append(
            name
        )


    visit(
        target
    )

    return ordered


# ============================================================
# Command validation
# ============================================================

def commands_for_app(
    app: dict[str, Any],
) -> set[str]:

    commands: set[str] = set()


    requirements = (
        app.get(
            "requirements"
        )
        or {}
    )


    for command in (
        requirements.get(
            "commands"
        )
        or []
    ):

        commands.add(
            str(
                command
            )
        )


    # Also inspect the executable from each build command.
    # This catches commands that were registered but were not
    # repeated explicitly under requirements.

    for step in (
        app.get(
            "build"
        )
        or []
    ):

        command = (
            step.get(
                "command"
            )
            or []
        )


        if not command:
            continue


        executable = str(
            command[0]
        )


        # Relative or absolute script paths are validated
        # separately instead of searching PATH.

        if (
            "/" in executable
            or executable.startswith(".")
        ):
            continue


        commands.add(
            executable
        )


    return commands

def check_commands(
    applications: dict[str, Any],
    names: list[str],
) -> list[str]:

    errors: list[str] = []


    commands: set[str] = set()


    for name in names:

        commands.update(
            commands_for_app(
                applications[
                    name
                ]
            )
        )


    print()
    print(
        "Command availability"
    )
    print(
        "--------------------"
    )


    for command in sorted(
        commands
    ):

        path = shutil.which(
            command
        )


        if path is None:

            fail(
                f"{command} not found in PATH"
            )

            errors.append(
                f"Missing executable: "
                f"{command}"
            )

        else:

            ok(
                f"{command}: {path}"
            )


    return errors

def check_repository_paths(
    applications: dict[str, Any],
    names: list[str],
) -> list[str]:

    errors: list[str] = []


    print()
    print(
        "Repository paths"
    )
    print(
        "----------------"
    )


    required_paths = {

        "repository":
            ROOT,

        "deployment registry":
            CONFIG,

        "Jupyter Book":
            ROOT
            / "icesee_jupyter_book",

        "service launcher":
            ROOT
            / "bin"
            / "start_icesee_services.sh",

    }


    for label, path in (
        required_paths.items()
    ):

        if path.exists():

            ok(
                f"{label}: {path}"
            )

        else:

            fail(
                f"{label}: {path}"
            )

            errors.append(
                f"Missing path: "
                f"{path}"
            )


    for name in names:

        app = applications[
            name
        ]


        working_directory = (
            app.get(
                "working_directory"
            )
        )


        if working_directory:

            path = (
                ROOT
                / working_directory
            ).resolve()


            if path.exists():

                ok(
                    f"{name} working directory: "
                    f"{path}"
                )

            else:

                fail(
                    f"{name} working directory: "
                    f"{path}"
                )

                errors.append(
                    f"Missing working directory "
                    f"for {name}: {path}"
                )


    return errors

def check_build_command_paths(
    applications: dict[str, Any],
    names: list[str],
) -> list[str]:

    errors: list[str] = []


    print()
    print(
        "Build command paths"
    )
    print(
        "-------------------"
    )


    checked = False


    for name in names:

        app = applications[
            name
        ]


        cwd = ROOT


        working_directory = (
            app.get(
                "working_directory"
            )
        )


        if working_directory:

            cwd = (
                ROOT
                / working_directory
            ).resolve()


        for step in (
            app.get(
                "build"
            )
            or []
        ):

            command = (
                step.get(
                    "command"
                )
                or []
            )


            if len(command) < 2:
                continue


            executable = str(
                command[0]
            )


            if executable not in {
                "bash",
                "sh",
                "python",
                "python3",
            }:

                continue


            candidate = str(
                command[1]
            )


            # -m and other interpreter options are not paths.

            if candidate.startswith(
                "-"
            ):
                continue


            path = Path(
                candidate
            )


            if not path.is_absolute():

                path = (
                    cwd
                    / path
                ).resolve()


            checked = True


            if path.exists():

                ok(
                    f"{name}: {path}"
                )

            else:

                fail(
                    f"{name}: {path}"
                )

                errors.append(
                    f"Build command path "
                    f"does not exist for "
                    f"{name}: {path}"
                )


    if not checked:

        print(
            "(no file-based build "
            "commands to validate)"
        )


    return errors

def check_writable_locations(
    applications: dict[str, Any],
    names: list[str],
) -> list[str]:

    errors: list[str] = []


    print()
    print(
        "Writable build locations"
    )
    print(
        "------------------------"
    )


    locations = {
        ROOT,
        ROOT
        / "icesee_jupyter_book",
    }


    for name in names:

        app = applications[
            name
        ]


        working_directory = (
            app.get(
                "working_directory"
            )
        )


        if working_directory:

            locations.add(
                (
                    ROOT
                    / working_directory
                ).resolve()
            )


        for artifact in (
            app.get(
                "artifacts"
            )
            or []
        ):

            artifact_path = (
                ROOT
                / artifact
            ).resolve()


            locations.add(
                artifact_path.parent
            )


    for path in sorted(
        locations,
        key=str,
    ):

        existing = path


        while (
            not existing.exists()
            and existing != existing.parent
        ):

            existing = (
                existing.parent
            )


        if (
            existing.exists()
            and os.access(
                existing,
                os.W_OK,
            )
        ):

            ok(
                str(path)
            )

        else:

            fail(
                str(path)
            )

            errors.append(
                f"Build location is "
                f"not writable: {path}"
            )


    return errors

def check_known_external_sources(
    names: list[str],
) -> list[str]:

    errors: list[str] = []


    print()
    print(
        "External application sources"
    )
    print(
        "----------------------------"
    )


    sources = {}


    if (
        "frozen-legacies"
        in names
    ):

        sources[
            "Frozen Legacies"
        ] = (
            ROOT
            / "external"
            / "FrozenLegacies"
        )


    if (
        "livist" in names
        or "livist-docs" in names
    ):

        sources[
            "LIVIST"
        ] = (
            ROOT
            / "external"
            / "living-ice-sheet-temperature"
        )


    if not sources:

        print(
            "(none required)"
        )

        return errors


    for label, path in (
        sources.items()
    ):

        if path.exists():

            ok(
                f"{label}: {path}"
            )

        else:

            fail(
                f"{label}: {path}"
            )

            errors.append(
                f"Missing external source: "
                f"{path}"
            )


    return errors

def main() -> int:

    parser = argparse.ArgumentParser(
        description=(
            "Validate CryoStack deployment "
            "requirements before build/restart."
        )
    )


    parser.add_argument(
        "--application",
        default=None,
        help=(
            "Validate one application and "
            "its dependencies instead of "
            "the full platform."
        ),
    )


    args = parser.parse_args()


    try:

        registry = load_registry()


        applications = (
            registry[
                "applications"
            ]
        )


        validate_dependencies(
            applications
        )


        names = dependency_closure(
            applications,
            args.application,
        )


        print()
        print(
            "=================================================="
        )
        print(
            "CryoStack deployment preflight"
        )
        print(
            "=================================================="
        )


        if args.application:

            print(
                "Target:",
                args.application,
            )

        else:

            print(
                "Target: full platform"
            )


        print(
            "Applications:",
            ", ".join(
                names
            ),
        )


        errors: list[str] = []


        errors.extend(
            check_repository_paths(
                applications,
                names,
            )
        )


        errors.extend(
            check_known_external_sources(
                names
            )
        )


        errors.extend(
            check_commands(
                applications,
                names,
            )
        )


        errors.extend(
            check_build_command_paths(
                applications,
                names,
            )
        )


        errors.extend(
            check_writable_locations(
                applications,
                names,
            )
        )


        print()
        print(
            "=================================================="
        )


        if errors:

            print(
                "CryoStack preflight FAILED"
            )

            print(
                "=================================================="
            )

            print()


            for error in errors:

                print(
                    " -",
                    error,
                )


            print()

            print(
                "No runtime services "
                "should be stopped."
            )

            return 1


        print(
            "CryoStack preflight PASSED"
        )

        print(
            "=================================================="
        )

        print()

        print(
            "Deployment environment is "
            "ready."
        )

        return 0


    except Exception as error:

        print()
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