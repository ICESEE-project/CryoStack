# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Frontend
# Component   : CryoLauncher Run Settings State
# File        : run_settings_state.py
#
# Description :
#     Owns the primary CryoLauncher run-setting widgets while preserving
#     compatibility with the legacy gateway during the frontend migration.
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

from __future__ import annotations

from dataclasses import dataclass

import ipywidgets as W


@dataclass
class RunSettingsState:
    ui_mode: W.ToggleButtons
    execution_mode: W.Dropdown
    backend: W.Dropdown
    model: W.Dropdown

    example_picker: W.Dropdown
    example_info: W.Textarea
    example_dir: W.Text
    exec_dir: W.Text

    advanced_action: W.Dropdown

    file_picker: W.Dropdown
    file_editor: W.Textarea
    run_target: W.Text

    new_example_name: W.Text
    dataset_upload: W.FileUpload

    container_source: W.Dropdown
    image_uri: W.Text


def build_run_settings_state() -> RunSettingsState:

    ui_mode = W.ToggleButtons(
        options=[
            ("Basic", "basic"),
            ("Advanced", "advanced"),
        ],
        value="basic",
        layout=W.Layout(
            width="auto",
        ),
    )

    execution_mode = W.Dropdown(
        options=[
            ("Remote", "remote"),
            ("Cloud", "cloud"),
        ],
        value="remote",
        layout=W.Layout(
            width="100%",
        ),
    )

    backend = W.Dropdown(
        options=[
            ("ICESEE-Spack", "spack"),
            ("ICESEE-Container", "container"),
        ],
        value="spack",
        layout=W.Layout(
            width="100%",
        ),
    )

    model = W.Dropdown(
        options=[
            ("ISSM", "issm"),
            ("Icepack", "icepack"),
        ],
        value="issm",
        layout=W.Layout(
            width="100%",
        ),
    )

    example_picker = W.Dropdown(
        options=[],
        layout=W.Layout(
            width="100%",
        ),
    )

    example_info = W.Textarea(
        value="",
        disabled=True,
        layout=W.Layout(
            width="100%",
            height="120px",
        ),
    )

    example_dir = W.Text(
        value="",
        layout=W.Layout(
            width="100%",
        ),
    )

    exec_dir = W.Text(
        value="~/runs",
        layout=W.Layout(
            width="100%",
        ),
    )

    advanced_action = W.Dropdown(
        options=[
            ("Run", "run"),
            ("Test", "test"),
            ("Deploy", "deploy"),
        ],
        value="run",
        layout=W.Layout(
            width="100%",
        ),
    )

    file_picker = W.Dropdown(
        options=[],
        layout=W.Layout(
            width="100%",
        ),
    )

    file_editor = W.Textarea(
        value="",
        layout=W.Layout(
            width="100%",
            height="180px",
        ),
    )

    run_target = W.Text(
        value="",
        layout=W.Layout(
            width="100%",
        ),
    )

    new_example_name = W.Text(
        value="",
        layout=W.Layout(
            width="100%",
        ),
    )

    dataset_upload = W.FileUpload(
        multiple=True,
    )

    container_source = W.Dropdown(
        options=[
            ("Registry", "registry"),
            ("Local", "local"),
        ],
        value="registry",
        layout=W.Layout(
            width="100%",
        ),
    )

    image_uri = W.Text(
        value="",
        placeholder="Container image URI",
        layout=W.Layout(
            width="100%",
        ),
    )

    return RunSettingsState(
        ui_mode=ui_mode,
        execution_mode=execution_mode,
        backend=backend,
        model=model,

        example_picker=example_picker,
        example_info=example_info,
        example_dir=example_dir,
        exec_dir=exec_dir,

        advanced_action=advanced_action,

        file_picker=file_picker,
        file_editor=file_editor,
        run_target=run_target,

        new_example_name=new_example_name,
        dataset_upload=dataset_upload,

        container_source=container_source,
        image_uri=image_uri,
    )