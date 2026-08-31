"""
CryoLauncher application UI.
"""

from ipywidgets import VBox

from .panels.run_settings import (
    build_run_settings_panel,
)

from .panels.status_panel import (
    build_status_panel,
)

from .panels.logs_panel import (
    build_logs_panel,
)

from .panels.results_panel import (
    build_results_panel,
)


def build_cryolauncher_ui():

    return VBox([
        build_run_settings_panel(),
        build_status_panel(),
        build_logs_panel(),
        build_results_panel(),
    ])