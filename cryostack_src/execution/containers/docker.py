# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Execution
# Component   : Docker Runtime
# File        : docker.py
#
# Description :
#     Provides low-level Docker operations used by CryoStack container
#     execution and publishing workflows.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-08-25
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""
Docker runtime helpers for CryoStack.

This module contains Docker-specific operations only. It has no AWS,
Slurm, frontend, or experiment logic.
"""

from __future__ import annotations

import shutil
import subprocess

from .models import (
    ContainerImage,
)


class DockerUnavailableError(
    RuntimeError
):
    """
    Raised when Docker is not available.
    """


def docker_available() -> bool:
    """
    Return whether the Docker executable is available.
    """

    return shutil.which(
        "docker"
    ) is not None


def require_docker() -> None:
    """
    Ensure Docker is available.
    """

    if not docker_available():
        raise DockerUnavailableError(
            "Docker is not available in PATH."
        )


def run_docker(
    arguments: list[str],
    *,
    input_text: str | None = None,
) -> tuple[int, str, str]:
    """
    Execute a Docker command.
    """

    require_docker()

    process = subprocess.run(
        [
            "docker",
            *arguments,
        ],
        input=input_text,
        capture_output=True,
        text=True,
    )

    return (
        process.returncode,
        process.stdout,
        process.stderr,
    )


def inspect_image(
    reference: str,
) -> bool:
    """
    Return whether a Docker image exists locally.
    """

    code, _, _ = run_docker(
        [
            "image",
            "inspect",
            reference,
        ]
    )

    return code == 0


def build_image(
    image: ContainerImage,
) -> None:
    """
    Build a Docker image from its configured Dockerfile.
    """

    if image.dockerfile is None:
        raise ValueError(
            "Container image has no Dockerfile."
        )

    if image.context is None:
        raise ValueError(
            "Container image has no build context."
        )

    code, stdout, stderr = run_docker(
        [
            "build",
            "--tag",
            image.local_reference,
            "--file",
            str(image.dockerfile),
            str(image.context),
        ]
    )

    if code != 0:
        raise RuntimeError(
            (stderr or stdout).strip()
            or "Docker image build failed."
        )


def tag_image(
    source: str,
    target: str,
) -> None:
    """
    Tag a Docker image.
    """

    code, stdout, stderr = run_docker(
        [
            "tag",
            source,
            target,
        ]
    )

    if code != 0:
        raise RuntimeError(
            (stderr or stdout).strip()
            or "Docker image tagging failed."
        )


def push_image(
    reference: str,
) -> None:
    """
    Push a Docker image.
    """

    code, stdout, stderr = run_docker(
        [
            "push",
            reference,
        ]
    )

    if code != 0:
        raise RuntimeError(
            (stderr or stdout).strip()
            or "Docker image push failed."
        )