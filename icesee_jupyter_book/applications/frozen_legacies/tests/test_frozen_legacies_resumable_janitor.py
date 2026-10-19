from __future__ import annotations

import json
import pytest

from icesee_jupyter_book.applications.frozen_legacies.radar import resumable_intake as RI
from icesee_jupyter_book.applications.frozen_legacies.radar import resumable_janitor as J
from icesee_jupyter_book.applications.frozen_legacies.radar.storage import StorageError
from icesee_jupyter_book.applications.frozen_legacies.tests.test_frozen_legacies_resumable_intake import configured, declaration


def _age(intake, sid, timestamp):
    target = intake / ".upload-sessions" / sid / "session.json"
    document = json.loads(target.read_text())
    document["updated_at"] = timestamp
    target.write_text(json.dumps(document))


def test_expiry_is_two_phase_audited_and_owner_scoped(tmp_path, monkeypatch):
    intake = configured(tmp_path, monkeypatch)
    monkeypatch.setenv("CRYOSTACK_FROZEN_LEGACIES_UPLOAD_MAX_IDLE_SECONDS", "10")
    monkeypatch.setenv("CRYOSTACK_FROZEN_LEGACIES_UPLOAD_RECOVERY_GRACE_SECONDS", "5")
    sid = RI.create("owner-a", declaration())["session_id"]
    _age(intake, sid, 100)
    assert J.inventory("owner-b", now=120) == []
    assert J.expire("owner-a", now=120)["eligible"] == 1
    assert RI.status(sid, "owner-a")["state"] == "open"
    assert J.expire("owner-a", now=120, dry_run=False)["marked_expired"] == 1
    with pytest.raises(StorageError, match="grace"):
        J.cleanup(sid, "owner-a", now=124, dry_run=False)
    assert J.cleanup(sid, "owner-a", now=125)["removed"] is False
    assert J.cleanup(sid, "owner-a", now=125, dry_run=False)["removed"] is True
    assert not (intake / ".upload-sessions" / sid).exists()
    audit = (intake / ".upload-sessions" / J.AUDIT_NAME).read_text()
    assert '"action": "expire"' in audit and '"action": "cleanup"' in audit


def test_never_removes_finalized_unknown_or_linked_data(tmp_path, monkeypatch):
    intake = configured(tmp_path, monkeypatch)
    monkeypatch.setenv("CRYOSTACK_FROZEN_LEGACIES_UPLOAD_MAX_IDLE_SECONDS", "0")
    monkeypatch.setenv("CRYOSTACK_FROZEN_LEGACIES_UPLOAD_RECOVERY_GRACE_SECONDS", "0")
    finalized = RI.create("owner", declaration())["session_id"]
    RI.mark_finalized(finalized, "owner", "source-127")
    with pytest.raises(StorageError, match="Finalized"):
        J.cleanup(finalized, "owner", now=100, dry_run=False)
    unknown = intake / ".upload-sessions" / ("in-" + "x" * 32)
    unknown.mkdir(); (unknown / "valuable.bin").write_bytes(b"keep")
    J.expire("operator", administrator=True, now=100, dry_run=False)
    assert unknown.exists()
    linked = RI.create("owner", declaration())["session_id"]
    _age(intake, linked, 0)
    J.expire("owner", now=100, dry_run=False)
    outside = tmp_path / "outside"; outside.write_bytes(b"valuable")
    (intake / ".upload-sessions" / linked / "unsafe").symlink_to(outside)
    with pytest.raises(StorageError, match="unsafe link"):
        J.cleanup(linked, "owner", now=100, dry_run=False)
    assert outside.read_bytes() == b"valuable"


def test_admin_can_manage_other_owner_but_owner_cannot(tmp_path, monkeypatch):
    intake = configured(tmp_path, monkeypatch)
    monkeypatch.setenv("CRYOSTACK_FROZEN_LEGACIES_UPLOAD_MAX_IDLE_SECONDS", "0")
    monkeypatch.setenv("CRYOSTACK_FROZEN_LEGACIES_UPLOAD_RECOVERY_GRACE_SECONDS", "0")
    sid = RI.create("owner", declaration())["session_id"]
    _age(intake, sid, 0)
    J.expire("admin", administrator=True, now=100, dry_run=False)
    with pytest.raises(StorageError, match="not found"):
        J.cleanup(sid, "stranger", now=100)
    assert J.cleanup(sid, "admin", administrator=True, now=100, dry_run=False)["removed"]
