"""Icepack result-package reader: honest status reporting, no fabricated
solution/field taxonomy, and pickup by the WorkspaceManager reader resolver."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cryostack_src.models.icepack import discover_results
from cryostack_src.models.icepack.results import SCHEMA, IcepackResultPackage


def _pkg(root, meta=None, figures=(), model_files=()):
    out = Path(root) / "outputs"
    (out / "figures").mkdir(parents=True, exist_ok=True)
    (out / "model").mkdir(parents=True, exist_ok=True)
    for f in figures:
        (out / "figures" / f).write_bytes(b"\x89PNG\r\n")
    for m in model_files:
        (out / "model" / m).write_bytes(b"\x89HDF\r\n")
    if meta is not None:
        (out / "metadata.json").write_text(json.dumps(meta))
    return discover_results(root)


def test_missing_outputs_is_missing(tmp_path):
    p = discover_results(tmp_path / "nope")
    assert p.status == "missing"
    assert p.outputs is None
    assert p.model is None


def test_schema_conformant_artifacts_package(tmp_path):
    meta = {"schema": SCHEMA, "version": 1, "model": "icepack",
            "status": "artifacts", "solutions": [], "fields": [],
            "figures": ["u.png"], "model_files": [], "note": "…"}
    p = _pkg(tmp_path, meta=meta, figures=["u.png"])
    assert isinstance(p, IcepackResultPackage)
    assert p.status == "artifacts"
    assert p.schema == SCHEMA
    assert p.model == "icepack"
    # honest: no structured field access
    assert p.is_readable() is False
    assert p.available_solutions() == []
    assert p.available_fields("anything") == []
    assert p.recommended_plots() == []
    assert [Path(f).name for f in p.legacy_artifacts()["figures"]] == ["u.png"]


def test_empty_package_reported_as_empty(tmp_path):
    meta = {"schema": SCHEMA, "status": "empty", "figures": [], "model_files": []}
    p = _pkg(tmp_path, meta=meta)
    assert p.status == "empty"


def test_outputs_without_metadata_but_with_figures_is_artifacts(tmp_path):
    p = _pkg(tmp_path, meta=None, figures=["fig1.png"])
    assert p.status == "artifacts"
    assert p.schema is None                      # no metadata to claim one


def test_outputs_with_nothing_recognisable_is_legacy(tmp_path):
    out = tmp_path / "outputs"
    (out / "model").mkdir(parents=True)
    (out / "mesh").mkdir()
    p = discover_results(tmp_path)
    assert p.status == "legacy"


def test_workspace_manager_resolves_the_icepack_reader():
    from cryostack_src.workspace.manager import _result_reader_for
    assert _result_reader_for("icepack") is discover_results
    # unknown model still falls back safely
    from cryostack_src.models.issm.results import discover_results as issm_discover
    assert _result_reader_for("issm") is issm_discover
