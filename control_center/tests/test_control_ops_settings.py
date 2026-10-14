"""Settings service: allowlist, validation, precedence, audit and rollback."""

from __future__ import annotations

import pytest

from control_center.ops_store import OpsStore
from control_center.services import settings as S


@pytest.fixture
def store(tmp_path):
    return OpsStore(tmp_path / "ops.db")


def _service(store, environ=None):
    S._EXPORTED.clear()
    return S.SettingsService(store, environ={} if environ is None else environ)


def _setting(service, key):
    return next(s for s in service.describe() if s["key"] == key)


ACTOR = {"actor_id": "u-1", "actor_label": "maint@example.org"}


def test_every_setting_is_allowlisted_and_non_secret():
    for definition in S.SETTINGS:
        lowered = definition.env.lower()
        assert not any(hint in lowered for hint in S._SECRET_HINTS)
        assert definition.kind in ("int", "bool", "choice")
        assert definition.restart in ("none", "gateway")
        assert definition.reader and definition.description
        if definition.kind == "int":
            assert definition.minimum <= definition.default <= definition.maximum
    assert len({d.key for d in S.SETTINGS}) == len(S.SETTINGS)
    assert len({d.env for d in S.SETTINGS}) == len(S.SETTINGS)


@pytest.mark.parametrize("key,value", [
    ("frozen_legacies.ursa_concurrency", "0"),
    ("frozen_legacies.ursa_concurrency", "9"),
    ("frozen_legacies.ursa_concurrency", "1.5"),
    ("frozen_legacies.ursa_concurrency", "two"),
    ("frozen_legacies.ursa_concurrency", ""),
    ("frozen_legacies.ursa_timeout_s", "59"),
    ("frozen_legacies.working_cache_mb", "99999999999"),
    ("gateway.app_start_mode", "eager"),
    ("platform.perf_instrumentation", "maybe"),
])
def test_validation_rejects_out_of_range_and_malformed_values(store, key, value):
    service = _service(store)
    with pytest.raises(S.SettingsError):
        service.change(key=key, value=value, reason="test", **ACTOR)
    assert store.stored_settings() == {}
    assert store.audit() == []


def test_unknown_keys_and_missing_reasons_are_rejected(store):
    service = _service(store)
    for key in ("frozen_legacies.ursa_root", "CRYOSTACK_FROZEN_LEGACIES_URSA_PYTHON", "", None,
                "../etc/passwd"):
        with pytest.raises(S.SettingsError, match="Unknown setting"):
            service.change(key=key, value="1", reason="test", **ACTOR)
    with pytest.raises(S.SettingsError, match="reason"):
        service.change(key="cloud.poll_seconds", value="30", reason="   ", **ACTOR)
    with pytest.raises(S.SettingsError, match="limited"):
        service.change(key="cloud.poll_seconds", value="30", reason="x" * 501, **ACTOR)
    assert store.stored_settings() == {}


def test_values_are_parsed_to_their_types(store):
    service = _service(store)
    assert service.change(key="cloud.poll_seconds", value=" 45 ", reason="r", **ACTOR)["value"] == 45
    assert service.change(key="platform.perf_instrumentation", value="on", reason="r",
                          **ACTOR)["value"] is True
    assert service.change(key="gateway.app_start_mode", value="LAZY", reason="r",
                          **ACTOR)["value"] == "lazy"


def test_precedence_environment_over_stored_over_default(store):
    environ = {"CRYOSTACK_FROZEN_LEGACIES_URSA_CONCURRENCY": "3"}
    service = _service(store, environ)
    service.apply_at_startup()
    pinned = _setting(service, "frozen_legacies.ursa_concurrency")
    assert (pinned["source"], pinned["configured_value"]) == ("environment", 3)
    assert pinned["shadowed"] is False

    service.change(key="frozen_legacies.ursa_concurrency", value="5", reason="r", **ACTOR)
    pinned = _setting(service, "frozen_legacies.ursa_concurrency")
    assert pinned["source"] == "environment" and pinned["shadowed"] is True
    assert pinned["configured_value"] == 3 and pinned["stored_value"] == 5
    assert environ["CRYOSTACK_FROZEN_LEGACIES_URSA_CONCURRENCY"] == "3"   # never overridden

    default = _setting(service, "cloud.poll_seconds")
    assert (default["source"], default["configured_value"]) == ("default", 20)


def test_stored_values_are_exported_at_startup(store):
    first = _service(store)
    first.change(key="frozen_legacies.radar_decodes", value="2", reason="r", **ACTOR)
    environ = {}
    second = _service(store, environ)
    second.apply_at_startup()
    assert environ["CRYOSTACK_FROZEN_LEGACIES_RADAR_DECODES"] == "2"
    item = _setting(second, "frozen_legacies.radar_decodes")
    assert (item["source"], item["running_value"], item["pending_restart"]) == ("stored", 2, False)
    # a later service instance does not mistake the exported value for an operator pin
    S.SettingsService(store, environ=environ)
    third = S.SettingsService(store, environ=environ)
    assert "CRYOSTACK_FROZEN_LEGACIES_RADAR_DECODES" not in third.pinned


def test_restart_semantics(store):
    environ = {}
    service = _service(store, environ)
    service.apply_at_startup()
    # read on every use: exported immediately
    service.change(key="frozen_legacies.ursa_timeout_s", value="120", reason="r", **ACTOR)
    assert environ["CRYOSTACK_FROZEN_LEGACIES_URSA_TIMEOUT"] == "120"
    live = _setting(service, "frozen_legacies.ursa_timeout_s")
    assert live["restart_required"] is False and live["pending_restart"] is False
    # read at start: pending until the gateway restarts
    service.change(key="frozen_legacies.ursa_concurrency", value="2", reason="r", **ACTOR)
    assert "CRYOSTACK_FROZEN_LEGACIES_URSA_CONCURRENCY" not in environ
    pending = _setting(service, "frozen_legacies.ursa_concurrency")
    assert pending["pending_restart"] is True
    assert (pending["running_value"], pending["configured_value"]) == (1, 2)
    # reset of a live setting removes the exported variable again
    service.reset(key="frozen_legacies.ursa_timeout_s", reason="back", **ACTOR)
    assert "CRYOSTACK_FROZEN_LEGACIES_URSA_TIMEOUT" not in environ


def test_every_change_is_audited_and_can_be_rolled_back(store):
    service = _service(store)
    first = service.change(key="cloud.poll_seconds", value="30", reason="slower polling", **ACTOR)
    second = service.change(key="cloud.poll_seconds", value="60", reason="even slower",
                            actor_id="u-2", actor_label="admin@example.org")
    audit = service.audit()
    assert [a["id"] for a in audit] == [second["audit_id"], first["audit_id"]]
    newest = audit[0]
    assert (newest["old_value"], newest["new_value"]) == (30, 60)
    assert (newest["actor_id"], newest["actor_label"], newest["reason"]) == (
        "u-2", "admin@example.org", "even slower")
    assert newest["action"] == "set" and newest["created_at"] > 0

    rolled = service.rollback(audit_id=second["audit_id"], **ACTOR)
    assert rolled["value"] == 30
    assert _setting(service, "cloud.poll_seconds")["configured_value"] == 30
    entry = service.audit()[0]
    assert entry["action"] == "rollback" and entry["rollback_of"] == second["audit_id"]
    assert entry["reason"] == f"Rollback of change #{second['audit_id']}"

    # rolling back the first change returns to "no stored value" (the default)
    service.rollback(audit_id=first["audit_id"], reason="undo", **ACTOR)
    item = _setting(service, "cloud.poll_seconds")
    assert (item["source"], item["configured_value"]) == ("default", 20)
    assert store.stored_settings() == {}
    assert len(service.audit()) == 4

    with pytest.raises(S.SettingsError):
        service.rollback(audit_id=9999, **ACTOR)
    with pytest.raises(S.SettingsError):
        service.rollback(audit_id="x", **ACTOR)


def test_store_file_is_private(tmp_path):
    store = OpsStore(tmp_path / "ops.db")
    assert (store.path.stat().st_mode & 0o777) == 0o600
