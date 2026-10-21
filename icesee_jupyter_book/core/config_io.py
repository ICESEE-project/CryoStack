# ============================================================
# YAML helpers
# ============================================================
from __future__ import annotations

import yaml
from pathlib import Path

def load_yaml(p: Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def dump_yaml(d: dict, p: Path) -> None:
    p.write_text(yaml.safe_dump(d, sort_keys=False), encoding="utf-8")


def with_legacy_parallel_flag(config: dict) -> dict:
    """``config`` with ``enkf-parameters.parallel_flag`` filled in when absent.

    ICESEE before October 2026 reads that key (``serial`` for execution mode
    0, ``MPI_model`` for the parallel modes); newer ICESEE ignores it. Remote
    resources run their own ICESEE-Spack install, which may be either."""
    enkf = dict(config.get("enkf-parameters") or {})
    if "parallel_flag" in enkf:
        return config
    enkf["parallel_flag"] = "serial" if str(enkf.get("execution_mode", 1)).strip() == "0" else "MPI_model"
    return {**config, "enkf-parameters": enkf}
