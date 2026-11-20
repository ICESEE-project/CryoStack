"""Cached cloud exports share the manager's guarded archive path."""
from pathlib import Path


def download_cloud_results(manager, *, fetch_results, figures_only=False):
    """Use the selected owner's retained output; fetch only if none is retained.

    Explicit Re-fetch remains a separate action. Credentials/network failures
    must not prevent exporting already retrieved work. No intermediate figure
    directory, metadata-preserving copy or flattened filenames is needed.
    """
    token_factory = getattr(manager, "result_download_token", None)
    current_check = getattr(manager, "result_download_is_current", None)
    if not callable(token_factory) or not callable(current_check):
        raise RuntimeError("Reload CryoLauncher, then reopen this run before downloading results.")
    token = token_factory()
    outputs = manager.cached_result_outputs()
    if outputs is None:
        outputs = fetch_results()
    if outputs is None:
        return False
    outputs = Path(outputs)
    filename = "figures_bundle.zip" if figures_only else "results_bundle.zip"
    return manager.package_and_download(outputs, filename=filename,
        figures_only=figures_only, expected_run_token=token)
