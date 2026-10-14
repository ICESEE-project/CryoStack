#!/usr/bin/env python3
"""Plan and collect an ICESEE MPI strong/weak-scaling benchmark.

``plan`` writes one case directory per (ranks, Nens) point -- a copy of a
base ``params.yaml`` with only ``Nens`` and ``data_path`` changed -- plus the
``mpiexec`` command for each case. It runs nothing; submit the commands
through the site's normal Slurm path.

``collect`` reads the "Performance Metrics" table ICESEE already logs for
every finished case (``diagnostics/icesee_timing.log`` or the run log, via
``icesee_jupyter_book.core.run_monitor``) and writes speedup / efficiency
per phase. A case with no table is reported as missing, never estimated.

Strong scaling: fixed Nens, increasing ranks.  Weak scaling: Nens grows with
the rank count (``--nens-per-rank``).
"""
from __future__ import annotations

import argparse
import csv
import json
import shlex
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

PHASES = (
    ("wall", "Wall-Clock Time (max)"),
    ("forecast", "Forecast Step Time"),
    ("analysis", "Analysis Step Time"),
    ("ensemble_init", "Ensemble Init Time"),
    ("file_io", "Total File I/O Time"),
    ("forecast_noise", "Forecast Noise Time"),
)


def _set_param(params: dict, key: str, value) -> None:
    """Set ``key`` in whichever section already holds it (ICESEE flattens
    sections), else in ``enkf-parameters``."""
    for section in params.values():
        if isinstance(section, dict) and key in section:
            section[key] = value
            return
    params.setdefault("enkf-parameters", {})[key] = value


def plan(args) -> dict:
    import yaml

    base = yaml.safe_load(Path(args.params).read_text())
    ranks = [int(r) for r in args.ranks.split(",") if r.strip()]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cases = []
    for mode in ("strong", "weak"):
        if mode == "weak" and not args.nens_per_rank:
            continue
        for p in ranks:
            nens = args.nens if mode == "strong" else args.nens_per_rank * p
            name = f"{mode}-np{p:03d}-nens{nens:04d}"
            case = out / name
            case.mkdir(exist_ok=True)
            params = json.loads(json.dumps(base))
            _set_param(params, "Nens", nens)
            _set_param(params, "data_path", str((case / "_modelrun_datasets").resolve()))
            (case / "params.yaml").write_text(yaml.safe_dump(params, sort_keys=False))
            command = (f"cd {shlex.quote(str(case.resolve()))} && "
                       f"mpiexec -n {p} python {shlex.quote(str(Path(args.run_script).resolve()))} "
                       f"-F params.yaml > run.log 2>&1")
            cases.append({"name": name, "mode": mode, "ranks": p, "nens": nens, "command": command})
    manifest = {"params": str(Path(args.params).resolve()), "cases": cases}
    (out / "plan.json").write_text(json.dumps(manifest, indent=2))
    (out / "commands.txt").write_text("\n".join(c["command"] for c in cases) + "\n")
    return manifest


def collect(args) -> list[dict]:
    from icesee_jupyter_book.core.run_monitor import inspect_run_progress

    out = Path(args.out)
    manifest = json.loads((out / "plan.json").read_text())
    rows = []
    for case in manifest["cases"]:
        report = inspect_run_progress(out / case["name"])
        row = {k: case[k] for k in ("name", "mode", "ranks", "nens")}
        timings = report.timings
        row["icesee_reported_ranks"] = timings.reported_ranks if timings else None
        for key, label in PHASES:
            row[key] = timings.seconds(label) if timings else None
        rows.append(row)

    for mode in ("strong", "weak"):
        series = sorted((r for r in rows if r["mode"] == mode and r["wall"]), key=lambda r: r["ranks"])
        if not series:
            continue
        ref = series[0]
        for r in series:
            for key, _label in PHASES:
                if r[key] and ref[key]:
                    ratio = ref[key] / r[key]
                    if mode == "strong":
                        r[f"{key}_speedup"] = round(ratio, 4)
                        r[f"{key}_efficiency"] = round(ratio * ref["ranks"] / r["ranks"], 4)
                    else:
                        r[f"{key}_efficiency"] = round(ratio, 4)

    base_fields = ["name", "mode", "ranks", "nens", "icesee_reported_ranks"] + [k for k, _ in PHASES]
    fields = base_fields + sorted({k for r in rows for k in r} - set(base_fields))
    with (out / "scaling.csv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    missing = [r["name"] for r in rows if r["wall"] is None]
    if missing:
        print("No ICESEE timing table (not reported) for: " + ", ".join(missing))
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan", help="write case directories and commands (runs nothing)")
    p.add_argument("--params", required=True, help="base ICESEE params.yaml")
    p.add_argument("--run-script", required=True, help="the example's run_*.py")
    p.add_argument("--ranks", default="1,2,4,8,16,32")
    p.add_argument("--nens", type=int, default=32, help="strong-scaling ensemble size")
    p.add_argument("--nens-per-rank", type=int, default=0, help="weak scaling: Nens = this x ranks")
    p.add_argument("--out", required=True)
    c = sub.add_parser("collect", help="tabulate ICESEE's own timing tables")
    c.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.command == "plan":
        manifest = plan(args)
        print(f"{len(manifest['cases'])} cases written to {args.out}/plan.json and commands.txt")
    else:
        rows = collect(args)
        print(f"{len(rows)} cases tabulated in {args.out}/scaling.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
