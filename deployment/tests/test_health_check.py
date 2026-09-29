"""Health-target registration: a registration without a path must never
overwrite an existing target (the old ``/None`` false alarm)."""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

_DEPLOYMENT = Path(__file__).resolve().parents[1]
if str(_DEPLOYMENT) not in sys.path:
    sys.path.insert(0, str(_DEPLOYMENT))

import health_check as hc


def _registry(applications: dict) -> dict:
    return {
        "platform": {
            "health": {
                "cryostack": {"path": "/", "expected_statuses": [200]},
            },
        },
        "applications": applications,
    }


def test_pathless_registration_keeps_platform_target():
    targets = hc.registered_health_targets(_registry({
        "application-docs": {"health": {"target": "cryostack"}},
    }))
    assert targets["cryostack"].path == "/"
    assert targets["cryostack"].expected_statuses == (200,)


def test_application_route_is_still_registered():
    targets = hc.registered_health_targets(_registry({
        "frozen-legacies": {
            "routes": ["/frozen-legacies/"],
            "health": {"target": "frozen-legacies"},
        },
        "livist-docs": {
            "health": {"target": "livist-docs", "path": "livist/docs/"},
        },
    }))
    assert targets["frozen-legacies"].path == "/frozen-legacies/"
    assert targets["livist-docs"].path == "/livist/docs/"


def test_missing_path_never_becomes_none_route():
    targets = hc.registered_health_targets(_registry({
        "cryostack-book": {"routes": ["/"], "health": {"target": "cryostack"}},
        "application-docs": {"routes": [], "health": {"target": "cryostack"}},
        "orphan": {"health": {"target": "orphan"}},
    }))
    assert all(t.path != "/None" for t in targets.values())
    assert "orphan" not in targets
    assert targets["cryostack"].path == "/"


def test_repository_registry_has_no_none_route():
    registry = yaml.safe_load(
        (_DEPLOYMENT / "applications.yaml").read_text(encoding="utf-8"))
    targets = hc.registered_health_targets(registry)
    assert targets["cryostack"].path == "/"
    assert all(t.path != "/None" for t in targets.values())
