"""params.yaml helpers: the parallel_flag older ICESEE installs still read."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from icesee_jupyter_book.core.config_io import with_legacy_parallel_flag


def test_parallel_flag_follows_the_execution_mode():
    serial = with_legacy_parallel_flag({"enkf-parameters": {"execution_mode": 0}})
    full = with_legacy_parallel_flag({"enkf-parameters": {"execution_mode": 2}, "other": {"a": 1}})
    assert serial["enkf-parameters"]["parallel_flag"] == "serial"
    assert full["enkf-parameters"]["parallel_flag"] == "MPI_model" and full["other"] == {"a": 1}
    assert with_legacy_parallel_flag({})["enkf-parameters"]["parallel_flag"] == "MPI_model"


def test_an_explicit_parallel_flag_is_kept():
    config = {"enkf-parameters": {"execution_mode": 0, "parallel_flag": "MPI"}}
    assert with_legacy_parallel_flag(config) is config
