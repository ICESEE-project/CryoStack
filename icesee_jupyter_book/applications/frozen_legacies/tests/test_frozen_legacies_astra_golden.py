"""ASTRA parity without the reference script: the port must reproduce the
results ASTRA itself produced for a fixed strip and action sequence
(``astra_golden.json``). When the reference script is present, the goldens
are also re-derived from it, so they cannot drift from ASTRA."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[3]
for _p in (str(_REPO), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import frozen_legacies_astra_golden as golden
import frozen_legacies_astra_reference as reference


@pytest.fixture(scope="module")
def nav(tmp_path_factory):
    path = tmp_path_factory.mktemp("nav") / "nav.csv"
    path.write_text(golden.NAV)
    return path


def _committed():
    return json.loads(golden.GOLDEN.read_text(encoding="utf-8"))


def test_port_reproduces_the_committed_astra_results(nav):
    expected = _committed()
    ours = golden.run_port(golden.strip(), nav)
    assert len(ours["steps"]) == len(expected["steps"]) == len(golden.SEQUENCE)
    for i, (got, want) in enumerate(zip(ours["steps"], expected["steps"])):
        assert got == want, f"step {i}: {golden.SEQUENCE[i]}"
    assert ours["csv"] == expected["csv"]


def test_goldens_cover_the_behaviour_that_matters():
    expected = _committed()
    titles = [s["title"] for s in expected["steps"]]
    assert titles[0] == "A-scope 1: CBD 471" and titles[-1] == "A-scope 4: CBD 474"
    rows = expected["csv"].splitlines()
    assert rows[0].startswith("A-scope Number,FLT,") and len(rows) == 4
    assert [r.split(",")[0] for r in rows[1:]] == ["1", "2", "4"]      # numbering skips
    assert [r.split(",")[22] for r in rows[1:]] == ["471", "477", "483"]  # CBD by row order
    assert len({s["slider"] for s in expected["steps"]}) >= 4             # several windows


@pytest.mark.skipif(not reference.available(),
                    reason="ASTRA reference script not present; committed goldens are checked instead")
def test_committed_goldens_match_the_astra_reference(nav, tmp_path):
    derived = golden.run_astra(golden.strip(), nav, tmp_path)
    expected = _committed()
    assert derived["steps"] == expected["steps"]
    assert derived["csv"] == expected["csv"]
