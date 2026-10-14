"""Shared radar source registry: operator configuration, validated, never
exposing server paths, never linking to explorer data implicitly."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[3]
for _p in (str(_REPO), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from frozen_legacies_radar_fixtures import write_nav, write_registry, write_tiff
from icesee_jupyter_book.applications.frozen_legacies.radar import sources as sources_mod
from icesee_jupyter_book.applications.frozen_legacies.radar.sources import (
    SOURCES_ENV,
    is_valid_source_key,
    load_sources,
)


@pytest.fixture
def data(tmp_path):
    (tmp_path / "radar").mkdir()
    write_tiff(tmp_path / "radar" / "F127-C0471_C0483.tiff")
    write_nav(tmp_path / "radar" / "127.csv")
    return tmp_path


def _load(monkeypatch, registry):
    monkeypatch.setenv(SOURCES_ENV, str(registry))
    return load_sources()


def test_relative_paths_resolve_against_the_registry(data, monkeypatch):
    registry = write_registry(data / "sources.yaml", (
        "  - key: f127\n"
        "    tiff: radar/F127-C0471_C0483.tiff\n"
        "    nav: radar/127.csv\n"
    ))
    source = _load(monkeypatch, registry)["f127"]
    assert source.tiff_path == (data / "radar" / "F127-C0471_C0483.tiff").resolve()
    assert source.nav_path == (data / "radar" / "127.csv").resolve()
    assert (source.flight, source.cbd_start, source.cbd_end) == ("127", 471, 483)
    assert source.status == "development" and source.dataset_id is None


def test_public_description_has_no_paths(data, monkeypatch):
    registry = write_registry(data / "sources.yaml", (
        "  - key: f127\n    tiff: radar/F127-C0471_C0483.tiff\n"
    ))
    public = _load(monkeypatch, registry)["f127"].public()
    assert str(data) not in repr(public)
    assert public["filename"] == "F127-C0471_C0483.tiff" and public["has_nav"] is False


@pytest.mark.parametrize("entry", [
    "  - key: ../escape\n    tiff: radar/F127-C0471_C0483.tiff\n",
    "  - key: UPPER\n    tiff: radar/F127-C0471_C0483.tiff\n",
    "  - key: ok\n    tiff: radar/missing.tiff\n",
    "  - key: ok\n    tiff: radar/127.csv\n",
    "  - key: ok\n    tiff: radar\n",
    "  - key: ok\n    tiff: radar/F127-C0471_C0483.tiff\n    nav: radar/missing.csv\n",
    "  - key: ok\n    tiff: radar/F127-C0471_C0483.tiff\n    status: public\n",
    "  - key: ok\n",
    "  - just-a-string\n",
])
def test_invalid_entries_are_skipped(data, monkeypatch, entry):
    registry = write_registry(data / "sources.yaml", entry)
    assert _load(monkeypatch, registry) == {}


def test_duplicate_keys_keep_the_first(data, monkeypatch):
    registry = write_registry(data / "sources.yaml", (
        "  - key: f127\n    title: first\n    tiff: radar/F127-C0471_C0483.tiff\n"
        "  - key: f127\n    title: second\n    tiff: radar/F127-C0471_C0483.tiff\n"
    ))
    assert _load(monkeypatch, registry)["f127"].title == "first"


def test_no_registry_means_no_shared_sources(tmp_path, monkeypatch):
    monkeypatch.delenv(SOURCES_ENV, raising=False)
    monkeypatch.setattr(sources_mod, "DEFAULT_SOURCES_FILE", tmp_path / "absent.yaml")
    assert load_sources() == {}
    monkeypatch.setenv(SOURCES_ENV, str(tmp_path / "also-absent.yaml"))
    assert load_sources() == {}


def test_unreadable_registry_is_empty(data, monkeypatch):
    bad = data / "bad.yaml"
    bad.write_text("sources: [unterminated", encoding="utf-8")
    assert _load(monkeypatch, bad) == {}


def test_default_registry_is_the_untracked_local_file():
    assert sources_mod.DEFAULT_SOURCES_FILE.name == "radar_sources.local.yaml"
    gitignore = (_REPO / ".gitignore").read_text(encoding="utf-8")
    assert "frozen_legacies/radar_sources.local.yaml" in gitignore


@pytest.mark.parametrize("key, ok", [
    ("f127-c0471-c0483", True), ("a", True), ("a.b_c-1", True),
    ("", False), ("-a", False), ("A", False), ("a/b", False), ("..", False),
    ("a" * 65, False), (None, False), (5, False),
])
def test_source_keys(key, ok):
    assert is_valid_source_key(key) is ok
