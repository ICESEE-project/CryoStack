"""ICESEE local / cloud / remote-fetch run directories are per-user
(Phase C-3): the gateway routes every `run_dir(...)` through a per-user root
instead of the process-global BOOK/icesee_runs/.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_GW = _REPO / "icesee_jupyter_book/ui/icesee_gateway.py"


def test_gateway_routes_run_dir_through_a_per_user_root():
    src = _GW.read_text()
    assert "from cryostack_src.workspace import resolve_workspace_user, user_run_root" in src
    assert 'user_run_root(app="icesee")' in src
    # no bare run_dir() call survives outside comments
    for line in src.splitlines():
        code = line.split("#", 1)[0]
        assert "run_dir()" not in code, line
    assert src.count("_icesee_run_dir_base()") >= 4          # helper + call sites
    assert "run_dir_base=_icesee_run_dir_base()" in src


def test_run_ids_are_unique_not_second_granular():
    src = _GW.read_text()
    # timestamp + uuid suffix -> no same-second collisions
    assert "uuid.uuid4().hex[:6]" in src
    lo = src.index("def _new_icesee_run_id")
    body = src[lo:lo + 200]
    assert "datetime.now().strftime" in body and "uuid" in body


@pytest.mark.parametrize("builder", ["build_icesee_ui"])
def test_icesee_ui_still_builds(builder, monkeypatch):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "iso-test-user")
    monkeypatch.setenv("USER", "iso-svc")
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesee_gateway import build_icesee_ui
    page = build_icesee_ui()
    assert page is not None
