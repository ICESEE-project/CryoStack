from __future__ import annotations

from ..panels.output_workspace import build_output_workspace


def build_run_details(*, log_output, results_output, download_controls, log_controls):
    return build_output_workspace(
        log_output=log_output,
        results_output=results_output,
        download_controls=download_controls,
        log_controls=log_controls,
    )
