"""Run LYRA (Layered-echo Yield from Radiometric Archives) on one TIFF.

This is a standalone script executed in a subprocess by the Frozen Legacies
automatic-picking job (``radar/automatic.py``). It uses only the standard
library; LYRA's own scripts run in child processes under the same Python,
which must have LYRA's dependencies (NumPy, pandas, matplotlib, Pillow).

LYRA runs unmodified, exactly as its guide describes, from the LYRA root:

1. ``codes/detect_frames.py <tiff> --method segment`` -- frames and CBDs
2. ``codes/calibrate.py <tiff>``  -- per-frame calibration (phase 3)
3. ``codes/echoes.py <tiff>``     -- surface/bed echoes, ice thickness (phase 4)

LYRA's phase 2 is an interactive desktop picker. Phase 3 refuses to run
without at least one human reference-line pick for the TIFF, so phases 3 and
4 run only when the user supplied LYRA's own calibration-guidance file
(``F<flight>_cal_picks.json``, optionally ``F<flight>_cal_derived.json``);
otherwise the run stops after phase 1. Nothing is ever invented in their
place.

If the server that started the run dies without stopping it (killed, out
of memory), the run notices within seconds and stops LYRA, so no orphaned
LYRA keeps working for a job the restarted server reports as interrupted.

LYRA's scripts write next to their own source (``codes/..``), so each run
gets a private copy of the code in its work area (copied, not linked: the
scripts resolve their own path) with the TIFF linked in under its canonical
LYRA name in ``tiff/<flight>/``. The run summary is written to
``<work>/lyra-run.json``.

Exit status: 0 when phase 1 produced a frame index (whatever later phases
did -- the summary says); 3 when phase 1 produced nothing; 4 when LYRA could
not be found or imported; 2 for invalid arguments.

``--check`` is the health check of a LYRA environment: it imports LYRA's
library modules from a private copy, exactly as a run does, prints one JSON line with the
interpreter and package versions (no paths), and exits 0; it exits 4 when the
import fails.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time

#: LYRA's canonical TIFF name (``lyra._CANONICAL_RE``)
CANONICAL = re.compile(r"^\d+_\d+_\d+-reel_begin_end\.tiff$", re.IGNORECASE)
#: frame keys LYRA's picker writes (``pick_calibration._row_fkey``)
GUIDE_KEY = re.compile(r"^(CBD\d{1,6}(_f\d{1,4})?|fr\d{1,4})$")
GUIDE_NUMBERS = ("mb", "ref")
GUIDE_LISTS = {"x_grid": 32, "y_grid": 8}
MAX_GUIDE_BYTES = 1024 * 1024
MAX_GUIDE_FRAMES = 5000
#: files of LYRA's code copied into a run (its scripts and digit templates)
CODE_SUFFIXES = (".py", ".npy")
#: library modules a run imports (never the phase scripts: they run on import)
LIBRARY_MODULES = ("lyra", "segment_ocr", "build_digit_templates")
HEALTH_PACKAGES = ("numpy", "pandas", "matplotlib", "PIL")
PHASE_TAIL = 20

_child: subprocess.Popen | None = None
#: the process that started this run (the gateway); when it dies without
#: stopping the run (killed, out of memory), the run stops too
_parent = os.getppid()
PARENT_POLL_S = 2.0


class GuidanceError(ValueError):
    """The calibration-guidance file is not LYRA's format."""


def validate_picks(doc) -> dict:
    """LYRA ``F<flight>_cal_picks.json``: ``{frame key: {mb, ref, x_grid,
    y_grid, exclude, exclude_reason}}``. Values are checked, never changed."""
    if not isinstance(doc, dict) or not doc:
        raise GuidanceError("The calibration picks must be a non-empty JSON object.")
    if len(doc) > MAX_GUIDE_FRAMES:
        raise GuidanceError("The calibration picks list too many frames.")
    for key, picks in doc.items():
        if not isinstance(key, str) or not GUIDE_KEY.fullmatch(key):
            raise GuidanceError(f"Unexpected frame key {str(key)[:40]!r} in the calibration picks.")
        if not isinstance(picks, dict):
            raise GuidanceError(f"Picks of {key} must be an object.")
        for name, value in picks.items():
            if name in GUIDE_NUMBERS:
                if value is not None and (isinstance(value, bool)
                                          or not isinstance(value, (int, float))):
                    raise GuidanceError(f"{key}.{name} must be a number.")
            elif name in GUIDE_LISTS:
                if (not isinstance(value, list) or len(value) > GUIDE_LISTS[name]
                        or any(isinstance(v, bool) or not isinstance(v, (int, float))
                               for v in value)):
                    raise GuidanceError(f"{key}.{name} must be a short list of numbers.")
            elif name == "exclude":
                if not isinstance(value, bool):
                    raise GuidanceError(f"{key}.exclude must be true or false.")
            elif name == "exclude_reason":
                if not isinstance(value, str) or len(value) > 300:
                    raise GuidanceError(f"{key}.exclude_reason must be short text.")
            else:
                raise GuidanceError(f"Unexpected field {str(name)[:40]!r} in {key}.")
    return doc


def validate_derived(doc) -> dict:
    """LYRA ``F<flight>_cal_derived.json`` (written by its picker)."""
    if not isinstance(doc, dict):
        raise GuidanceError("The derived calibration must be a JSON object.")
    for name in ("x_spacing_px", "y_spacing_px", "us_per_px", "db_per_px"):
        value = doc.get(name)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                  or not value > 0):
            raise GuidanceError(f"{name} must be a positive number.")
    return doc


def load_json(path: str, validate) -> dict:
    if os.path.getsize(path) > MAX_GUIDE_BYTES:
        raise GuidanceError("The calibration-guidance file is too large.")
    with open(path, encoding="utf-8") as handle:
        try:
            doc = json.load(handle)
        except ValueError:
            raise GuidanceError("The calibration-guidance file is not valid JSON.") from None
    return validate(doc)


def _stage_code(lyra_root: str, run_root: str) -> None:
    source = os.path.join(lyra_root, "codes")
    target = os.path.join(run_root, "codes")
    os.makedirs(target)
    for entry in sorted(os.scandir(source), key=lambda e: e.name):
        if entry.name.endswith(CODE_SUFFIXES) and entry.is_file(follow_symlinks=False):
            shutil.copyfile(entry.path, os.path.join(target, entry.name))


def _tail(path: str) -> list[str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return []
    return [line[:300] for line in lines if "findfont" not in line][-PHASE_TAIL:]


def _run_phase(name: str, args: list[str], run_root: str, logs: str) -> dict:
    """One LYRA script, exactly as its guide runs it, from the LYRA root."""
    global _child
    log = os.path.join(logs, f"{name}.log")
    started = time.time()
    print(f"[lyra] {name}: {' '.join(args)}", flush=True)
    with open(log, "wb") as handle:
        _child = subprocess.Popen([sys.executable, "-I", *args], cwd=run_root,
                                  stdout=handle, stderr=subprocess.STDOUT)
        while True:
            try:
                code = _child.wait(timeout=PARENT_POLL_S)
                break
            except subprocess.TimeoutExpired:
                if os.getppid() != _parent:
                    print(f"[lyra] {name}: the server stopped; stopping LYRA.", flush=True)
                    _terminate(signal.SIGTERM, None)
        _child = None
    tail = _tail(log)
    for line in tail:
        print(f"[lyra:{name}] {line}", flush=True)
    return {"exit": code, "seconds": round(time.time() - started, 1), "log_tail": tail}


def _write_progress(work: str, *, phase: str, status: str, phases: dict) -> None:
    """Publish a small atomic status document for the supervising service.

    The runner owns this file. It deliberately contains no paths, command
    lines, or user input, so it is safe for the owner-scoped API to expose.
    """
    doc = {"schema": "cryostack.frozen_legacies.lyra_progress", "version": 1,
           "phase": phase, "status": status, "updated_at": time.time(),
           "phases": {name: {key: value for key, value in result.items()
                              if key in ("exit", "seconds")}
                      for name, result in phases.items()}}
    target = os.path.join(work, "lyra-progress.json")
    temporary = f"{target}.{os.getpid()}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(doc, handle, separators=(",", ":"), allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)


def _terminate(signum, _frame):
    if _child is not None and _child.poll() is None:
        _child.terminate()
        try:
            _child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _child.kill()
    sys.exit(128 + signum)


def _relative_outputs(run_root: str, flight: int) -> dict:
    out = os.path.join(run_root, "output", f"F{flight}")
    found = {}
    for phase in ("phase1", "phase3", "phase4"):
        directory = os.path.join(out, phase)
        files = []
        for base, _dirs, names in os.walk(directory):
            for name in names:
                files.append(os.path.relpath(os.path.join(base, name), out))
        found[phase] = sorted(files)
    return found


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lyra-root", required=True)
    parser.add_argument("--tiff")
    parser.add_argument("--canonical-name")
    parser.add_argument("--flight", type=int)
    parser.add_argument("--work")
    parser.add_argument("--picks")
    parser.add_argument("--derived")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    os.environ.setdefault("MPLBACKEND", "Agg")
    lyra_root = os.path.abspath(args.lyra_root)
    if not os.path.isfile(os.path.join(lyra_root, "codes", "lyra.py")):
        print("LYRA could not be found.", flush=True)
        return 4
    if args.check:
        return _report_health(lyra_root)

    if not (args.tiff and args.canonical_name and args.flight and args.work):
        parser.error("--tiff, --canonical-name, --flight and --work are required")
    if not CANONICAL.fullmatch(args.canonical_name) or "/" in args.canonical_name:
        print("The canonical LYRA TIFF name is invalid.", flush=True)
        return 2
    if not 0 < args.flight < 100000:
        print("The flight number is invalid.", flush=True)
        return 2
    try:
        picks = load_json(args.picks, validate_picks) if args.picks else None
        derived = load_json(args.derived, validate_derived) if args.derived else None
    except (GuidanceError, OSError) as error:
        print(f"Calibration guidance rejected: {error}", flush=True)
        return 2

    signal.signal(signal.SIGTERM, _terminate)
    work = os.path.abspath(args.work)
    run_root = os.path.join(work, "LYRA")
    logs = os.path.join(work, "logs")
    os.makedirs(logs, exist_ok=True)
    _stage_code(lyra_root, run_root)
    flight_dir = os.path.join(run_root, "tiff", str(args.flight))
    os.makedirs(flight_dir)
    os.symlink(os.path.abspath(args.tiff), os.path.join(flight_dir, args.canonical_name))
    phase1_dir = os.path.join(run_root, "output", f"F{args.flight}", "phase1")
    os.makedirs(phase1_dir)
    tiff_arg = f"tiff/{args.flight}/{args.canonical_name}"

    summary = {"schema": "cryostack.frozen_legacies.lyra_run", "version": 1,
               "flight": args.flight, "canonical_name": args.canonical_name,
               "ocr_method": "segment", "guidance": picks is not None,
               "guidance_derived": derived is not None, "phases": {}, "stopped": None}
    _write_progress(work, phase="phase1", status="running", phases=summary["phases"])
    summary["phases"]["phase1"] = _run_phase(
        "phase1", ["codes/detect_frames.py", tiff_arg, "--method", "segment"], run_root, logs)
    _write_progress(work, phase="phase1", status="completed", phases=summary["phases"])
    index_csv = os.path.join(phase1_dir, f"F{args.flight}_frame_index.csv")
    if summary["phases"]["phase1"]["exit"] != 0 or not os.path.isfile(index_csv):
        summary["stopped"] = "phase1-failed"
    elif picks is None:
        summary["stopped"] = "calibration-guidance-required"
    else:
        with open(os.path.join(phase1_dir, f"F{args.flight}_cal_picks.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(picks, handle, indent=2)
        if derived is not None:
            with open(os.path.join(phase1_dir, f"F{args.flight}_cal_derived.json"), "w",
                      encoding="utf-8") as handle:
                json.dump(derived, handle, indent=2)
        _write_progress(work, phase="phase3", status="running", phases=summary["phases"])
        summary["phases"]["phase3"] = _run_phase(
            "phase3", ["codes/calibrate.py", tiff_arg], run_root, logs)
        _write_progress(work, phase="phase3", status="completed", phases=summary["phases"])
        if summary["phases"]["phase3"]["exit"] != 0:
            summary["stopped"] = "phase3-refused"
        else:
            _write_progress(work, phase="phase4", status="running", phases=summary["phases"])
            summary["phases"]["phase4"] = _run_phase(
                "phase4", ["codes/echoes.py", tiff_arg], run_root, logs)
            _write_progress(work, phase="phase4", status="completed", phases=summary["phases"])
            if summary["phases"]["phase4"]["exit"] != 0:
                summary["stopped"] = "phase4-failed"
    summary["outputs"] = _relative_outputs(run_root, args.flight)
    with open(os.path.join(work, "lyra-run.json"), "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    _write_progress(work, phase=next(reversed(summary["phases"])), status="finished",
                    phases=summary["phases"])
    print(json.dumps({"lyra": summary["stopped"] or "completed"}), flush=True)
    return 3 if summary["stopped"] == "phase1-failed" else 0


def _report_health(lyra_root: str) -> int:
    import importlib
    import platform
    import tempfile

    # LYRA's modules create directories next to their own source when
    # imported (build_digit_templates: output/F125), so the check imports a
    # private copy, exactly as a run does; LYRA's own tree is never written
    # and may be read-only.
    sys.dont_write_bytecode = True
    scratch = tempfile.mkdtemp(prefix="lyra-check-")
    try:
        _stage_code(lyra_root, os.path.join(scratch, "LYRA"))
        sys.path.insert(0, os.path.join(scratch, "LYRA", "codes"))
        for name in LIBRARY_MODULES:
            importlib.import_module(name)
    except Exception as error:                       # missing dependency, broken install
        print(f"LYRA could not be imported: {type(error).__name__}: {error}", flush=True)
        return 4
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    versions = {}
    for name in HEALTH_PACKAGES:
        module = sys.modules.get(name)
        versions[name] = getattr(module, "__version__", None) if module else None
    print(json.dumps({"lyra": "importable", "python": platform.python_version(),
                      "packages": versions}, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
