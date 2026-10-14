"""Run URSA (Unsupervised Retrieval of Signal for A-scopes) on one TIFF.

This is a standalone script executed in a subprocess by the Frozen Legacies
automatic-picking job (``radar/automatic.py``). It uses only the standard
library plus URSA itself, so it can run under a separate Python environment
that has URSA's dependencies (OpenCV, NumPy, SciPy, pandas, matplotlib).

URSA is run unmodified, non-interactively, exactly as its own entry point
does for one image (``main.py``): default configuration, optional
navigation via ``load_navigation_file``, ``AScope.process_image``.

Exit status: 0 when URSA wrote ``<stem>_pick.csv``; 3 when it finished
without results; 4 when URSA could not be imported.

``--check`` is the health check of an URSA environment: it imports URSA's
modules exactly as a run does (which imports OpenCV, scikit-image, SciPy,
pandas and matplotlib), prints one JSON line with the interpreter and
package versions (no paths), and exits 0; it exits 4 when the import fails.
"""
from __future__ import annotations

import argparse
import os
import sys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ursa-root", required=True)
    parser.add_argument("--tiff")
    parser.add_argument("--output")
    parser.add_argument("--nav")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if not args.check and not (args.tiff and args.output):
        parser.error("--tiff and --output are required")

    os.environ.setdefault("MPLBACKEND", "Agg")
    root = os.path.abspath(args.ursa_root)
    sys.path.insert(0, os.path.join(root, "functions"))
    sys.path.insert(0, root)
    try:
        from ascope_processor import AScope          # noqa: E402
        from main import load_navigation_file       # noqa: E402
    except Exception as error:                       # missing dependency, broken install
        print(f"URSA could not be imported: {type(error).__name__}: {error}", flush=True)
        return 4
    if args.check:
        return _report_health()

    os.makedirs(args.output, exist_ok=True)
    processor = AScope()
    processor.set_output_directory(args.output)
    if args.nav:
        nav_dict = load_navigation_file(args.nav)
        if nav_dict:
            processor.nav_dict = nav_dict
    processor.set_interactive_mode(enabled=False, defer_frame_plots=False)
    processor.process_image(args.tiff, args.output)

    stem = os.path.splitext(os.path.basename(args.tiff))[0]
    return 0 if os.path.isfile(os.path.join(args.output, f"{stem}_pick.csv")) else 3


#: modules whose versions identify an URSA environment
HEALTH_MODULES = ("numpy", "scipy", "pandas", "matplotlib", "cv2", "skimage")


def _report_health() -> int:
    import importlib
    import json
    import platform

    versions = {}
    for name in HEALTH_MODULES:
        module = sys.modules.get(name)
        if module is None:
            try:
                module = importlib.import_module(name)
            except Exception:
                module = None
        versions[name] = getattr(module, "__version__", None) if module else None
    print(json.dumps({"ursa": "importable", "python": platform.python_version(),
                      "packages": versions}, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
