"""Owner-managed backup approvers have registration scope and no platform role."""
from __future__ import annotations

from dataclasses import replace

import pytest

from icesee_auth.approval import DecisionError
from icesee_auth.registration_approvers import AUDIT_ACTION, RegistrationApproverStore
from control_center.tests.test_registration_approval import Env, _get, _post


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("CRYOSTACK_APPROVAL_OWNER_ONLY", "1")
    env = Env(tmp_path)
    owner = env.user("owner", "owner")
    delegate = env.user("backup")
    store = RegistrationApproverStore(env.storage, clock=env.clock)
    return env, owner, delegate, store


def test_owner_grant_persists_audits_and_never_grants_platform_roles(setup):
    env, owner, delegate, store = setup
    roles_before = env.storage.get_user_roles(user_id=delegate.id)
    assert store.grant(actor_user_id=owner.id, email="  BACKUP@EXAMPLE.ORG  ",
                       reason="Backup reviewer while owner is away") is True
    again = RegistrationApproverStore(env.storage, clock=env.clock)
    assert again.is_authorized(delegate.id)
    assert again.authorized_emails() == [delegate.email]
    entry = again.list_entries()[0]
    assert entry["user_id"] == delegate.id and entry["email"] == delegate.email
    assert entry["granted_by"] == owner.id and entry["active"] is True
    assert env.storage.get_user_roles(user_id=delegate.id) == roles_before == []
    assert store.grant(actor_user_id=owner.id, email=delegate.email) is False
    assert len(store.list_entries()) == 1
    assert store.revoke(actor_user_id=owner.id, target_user_id=delegate.id,
                        reason="Owner is available again") is True
    assert not again.is_authorized(delegate.id) and again.authorized_emails() == []
    audits = env.audit(AUDIT_ACTION)
    assert [(row["previous_value"], row["new_value"]) for row in audits] == [
        ("disabled", "enabled"), ("enabled", "disabled")]
    assert all(row["actor_user_id"] == owner.id and row["target_user_id"] == delegate.id
               for row in audits)
    assert env.storage.get_user_roles(user_id=delegate.id) == []


def test_only_an_approved_verified_owner_manages_approvers(setup):
    env, owner, delegate, store = setup
    admin = env.user("admin", "admin")
    unverified_owner = env.user("unverified-owner", "owner", verified=False)
    suspended_owner = env.user("suspended-owner", "owner", status="suspended")
    pending_owner = env.user("pending-owner", "owner", status="pending")
    store.grant(actor_user_id=owner.id, email=delegate.email)
    other = env.user("other")
    for actor in (admin, delegate, unverified_owner, suspended_owner, pending_owner):
        with pytest.raises(PermissionError):
            store.grant(actor_user_id=actor.id, email=other.email)
        with pytest.raises(PermissionError):
            store.revoke(actor_user_id=actor.id, target_user_id=delegate.id)
    assert store.authorized_emails() == [delegate.email]
    assert len(env.audit(AUDIT_ACTION)) == 1


def test_targets_need_an_existing_approved_confirmed_account(setup):
    env, owner, delegate, store = setup
    with pytest.raises(LookupError):
        store.grant(actor_user_id=owner.id, email="missing@example.org")
    for name, status, verified in (("pending", "pending", True),
                                   ("unconfirmed", "approved", False),
                                   ("suspended", "suspended", True),
                                   ("rejected", "rejected", True)):
        target = env.user(name, status=status, verified=verified)
        with pytest.raises(ValueError):
            store.grant(actor_user_id=owner.id, email=target.email)
    assert store.list_entries() == [] and env.audit(AUDIT_ACTION) == []


def test_suspension_email_change_and_unverification_disable_grant_dynamically(setup):
    env, owner, delegate, store = setup
    store.grant(actor_user_id=owner.id, email=delegate.email)
    with env.storage._connect() as connection:
        connection.execute("UPDATE account_status SET status='suspended' WHERE user_id=?", (delegate.id,))
    assert not store.is_authorized(delegate.id) and store.authorized_emails() == []
    assert store.list_entries()[0]["active"] is False
    with env.storage._connect() as connection:
        connection.execute("UPDATE account_status SET status='approved' WHERE user_id=?", (delegate.id,))
        connection.execute("UPDATE users SET email='changed@example.org' WHERE id=?", (delegate.id,))
    assert not store.is_authorized(delegate.id) and store.authorized_emails() == []
    with env.storage._connect() as connection:
        connection.execute("UPDATE users SET email=? WHERE id=?", (delegate.email, delegate.id))
        connection.execute("UPDATE account_status SET email_verified_at=NULL WHERE user_id=?", (delegate.id,))
    assert not store.is_authorized(delegate.id) and store.authorized_emails() == []
    assert env.storage.get_user_roles(user_id=delegate.id) == []


def test_delegate_only_decides_pending_ordinary_accounts_and_never_self(setup):
    env, owner, delegate, store = setup
    store.grant(actor_user_id=owner.id, email=delegate.email)
    applicant = env.user("applicant", status="pending")
    unverified = env.user("unverified", status="pending", verified=False)
    staff = env.user("pending-staff", "admin", status="pending")
    member = env.user("member")
    suspended = env.user("held", status="suspended")
    assert env.service.can_decide(actor_user_id=delegate.id)
    assert set(env.service.allowed_decisions(actor_user_id=delegate.id, target_user_id=applicant.id)) == {"approve", "reject"}
    assert env.service.allowed_decisions(actor_user_id=delegate.id, target_user_id=unverified.id) == ["reject"]
    for target in (staff, member, suspended, delegate, owner):
        assert env.service.allowed_decisions(actor_user_id=delegate.id, target_user_id=target.id) == []
    for target, decision in ((staff, "approve"), (member, "suspend"),
                             (suspended, "reinstate"), (delegate, "suspend")):
        with pytest.raises(PermissionError):
            env.service.decide(actor_user_id=delegate.id, target_user_id=target.id,
                               decision=decision, reason="Outside registration scope")
    with pytest.raises(DecisionError):
        env.service.decide(actor_user_id=delegate.id, target_user_id=unverified.id,
                           decision="approve", reason="")
    result = env.service.decide(actor_user_id=delegate.id, target_user_id=applicant.id,
                                decision="approve", reason="Research participant reviewed")
    assert result["status"] == "approved"
    assert env.audit()[-1]["actor_user_id"] == delegate.id
    rejected = env.user("rejected-applicant", status="pending")
    assert env.service.decide(actor_user_id=delegate.id, target_user_id=rejected.id,
                              decision="reject", reason="Application does not meet pilot criteria")["status"] == "rejected"
    with pytest.raises(PermissionError):
        env.service.retry_provisioning(actor_user_id=delegate.id, target_user_id=applicant.id)
    with pytest.raises(PermissionError):
        env.service.retry_notification(actor_user_id=delegate.id, row_id="unknown")
    assert env.storage.get_user_roles(user_id=delegate.id) == []


def test_delegate_access_is_limited_to_registration_routes_and_decisions(setup):
    env, owner, delegate, store = setup
    store.grant(actor_user_id=owner.id, email=delegate.email)
    applicant = env.user("applicant", status="pending")
    ordinary = env.user("ordinary")
    delegate_session = env.session(delegate)

    async def script(client):
        page = await _get(client, "/control/registrations", delegate_session)
        assert page.status == 200
        html = await page.text()
        assert 'href="/control/users"' not in html and 'href="/control/settings"' not in html
        assert 'href="/control/users/' not in html
        assert "/control/registrations/approvers/add" not in html
        response = await _get(client, "/api/control/registrations", delegate_session)
        assert response.status == 200
        overview = await response.json()
        assert overview["registration_only"] is True
        assert overview["mail"] == {} and overview["provisioning"] == []
        assert overview["approvers"] == [] and overview["baseline"] is None
        for path in ("/control/", "/control/users", "/control/settings", "/api/control/users", "/api/control/dashboard"):
            assert (await _get(client, path, delegate_session)).status == 403
        assert (await _get(client, "/control/registrations", env.session(ordinary))).status == 403
        cross = await _post(client, f"/control/registrations/{applicant.id}/decision",
                            delegate_session, {"decision": "approve"},
                            headers={"Origin": "https://attacker.example"})
        assert cross.status == 403
        assert env.auth.approval.effective_status(applicant.id) == "pending"
        approved = await _post(client, f"/control/registrations/{applicant.id}/decision",
                               delegate_session, {"decision": "approve"})
        assert approved.status == 303
        assert env.auth.approval.effective_status(applicant.id) == "approved"
        assert (await _post(client, f"/control/registrations/{applicant.id}/provisioning",
                            delegate_session)).status == 403
        assert (await _post(client, "/control/registrations/notifications/unknown/retry",
                            delegate_session)).status == 403
        store.revoke(actor_user_id=owner.id, target_user_id=delegate.id)
        assert (await _get(client, "/control/registrations", delegate_session)).status == 403
        assert (await _get(client, "/api/control/registrations", delegate_session)).status == 403

    env.run(script)


def test_owner_panel_add_remove_and_cross_site_management_controls(setup):
    env, owner, delegate, store = setup
    admin = env.user("admin", "admin")
    other = env.user("other")
    owner_session, admin_session = env.session(owner), env.session(admin)

    async def script(client):
        page = await _get(client, "/control/registrations", owner_session)
        assert page.status == 200
        assert "Registration approvers" in await page.text()
        add = "/control/registrations/approvers/add"
        assert (await _post(client, add, admin_session, {"email": delegate.email})).status == 403
        cross = await _post(client, add, owner_session, {"email": delegate.email},
                            headers={"Origin": "https://attacker.example"})
        assert cross.status == 403 and store.authorized_emails() == []
        added = await _post(client, add, owner_session,
                            {"email": delegate.email, "reason": "Owner-selected backup"})
        assert added.status == 303 and store.is_authorized(delegate.id)
        page = await _get(client, "/control/registrations", owner_session)
        assert delegate.email in await page.text()
        assert (await _post(client, add, env.session(delegate), {"email": other.email})).status == 403
        remove = f"/control/registrations/approvers/{delegate.id}/remove"
        assert (await _post(client, remove, env.session(delegate))).status == 403
        assert (await _post(client, remove, owner_session,
                            headers={"Origin": "https://attacker.example"})).status == 403
        assert store.is_authorized(delegate.id)
        removed = await _post(client, remove, owner_session, {"reason": "Owner available again"})
        assert removed.status == 303 and not store.is_authorized(delegate.id)
        assert env.storage.get_user_roles(user_id=delegate.id) == []

    env.run(script)


def test_dynamic_delegate_mail_is_deduplicated_and_revoked_notice_is_canceled(setup):
    env, owner, delegate, store = setup
    env.auth.outbox.config = replace(env.auth.outbox.config, admin_emails=(owner.email,))
    store.grant(actor_user_id=owner.id, email=delegate.email)
    applicant = env.user("applicant", status="pending")
    for _ in range(3):
        env.auth._queue_review_notices(applicant, method="password")
    notices = [row for row in env.outbox() if row["template"] == "admin_review"]
    assert sorted(row["recipient"] for row in notices) == sorted([owner.email, delegate.email])
    authorized, refused = env.auth.outbox.reviewers()
    assert sorted(authorized) == sorted([owner.email, delegate.email])
    store.revoke(actor_user_id=owner.id, target_user_id=delegate.id)
    result = env.auth.outbox.deliver_due()
    assert result["cancelled"] == 1 and result["sent"] == 2
    sent_reviewers = [message["To"] for message in env.sent
                      if message["Subject"] == "CryoStack registration needs review"]
    assert sent_reviewers == [owner.email]
    notice = next(row for row in env.outbox() if row["recipient"] == delegate.email)
    assert notice["status"] == "cancelled"
    assert env.auth.approval.effective_status(applicant.id) == "pending"


def test_new_backup_is_notified_for_existing_confirmed_waiting_registrations(setup):
    env, owner, delegate, store = setup
    confirmed = env.user("waiting-confirmed", status="pending")
    unconfirmed = env.user("waiting-unconfirmed", status="pending", verified=False)
    store.grant(actor_user_id=owner.id, email=delegate.email)
    env.service.notify_waiting_reviewers()
    env.service.notify_waiting_reviewers()
    notices = [row for row in env.outbox() if row["template"] == "admin_review"]
    assert [(row["user_id"], row["recipient"]) for row in notices] == [(confirmed.id, delegate.email)]
    assert all(row["user_id"] != unconfirmed.id for row in notices)


def test_revocation_before_decision_transaction_cannot_be_raced(setup, monkeypatch):
    env, owner, delegate, store = setup
    store.grant(actor_user_id=owner.id, email=delegate.email)
    applicant = env.user("applicant", status="pending")
    original = env.auth.approval.decide

    def revoked_before_commit(**kwargs):
        store.revoke(actor_user_id=owner.id, target_user_id=delegate.id)
        return original(**kwargs)

    monkeypatch.setattr(env.auth.approval, "decide", revoked_before_commit)
    with pytest.raises(PermissionError):
        env.service.decide(actor_user_id=delegate.id, target_user_id=applicant.id,
                           decision="approve", reason="Reviewer was removed concurrently")
    assert env.auth.approval.effective_status(applicant.id) == "pending"
    assert env.audit() == []
    assert not [row for row in env.outbox() if row["template"] == "decision"]


def test_existing_staff_view_and_owner_only_pilot_policy_stay_intact(setup):
    env, owner, delegate, store = setup
    admin = env.user("admin", "admin")
    applicant = env.user("applicant", status="pending")
    assert env.service.can_view(actor_user_id=admin.id)
    assert not env.service.can_decide(actor_user_id=admin.id)
    assert env.service.allowed_decisions(actor_user_id=admin.id, target_user_id=applicant.id) == []
    overview = env.service.overview(actor_user_id=admin.id)
    assert overview["registration_only"] is False
    assert overview["mail"]["mode"] == "file"
    assert overview["can_manage_approvers"] is False
    assert set(env.service.allowed_decisions(actor_user_id=owner.id, target_user_id=applicant.id)) == {"approve", "reject", "suspend"}
    assert env.storage.get_user_roles(user_id=admin.id) == ["admin"]


def test_delegate_cannot_approve_an_account_without_verification_record(setup):
    env, owner, delegate, store = setup
    store.grant(actor_user_id=owner.id, email=delegate.email)
    recordless = env.user("recordless", status=None)
    assert env.auth.approval.status(recordless.id) is None
    assert "approve" not in env.service.allowed_decisions(
        actor_user_id=delegate.id, target_user_id=recordless.id)
    with pytest.raises((PermissionError, DecisionError)):
        env.service.decide(actor_user_id=delegate.id, target_user_id=recordless.id,
                           decision="approve", reason="Must have a confirmed email record")
    assert env.auth.approval.status(recordless.id) is None
    assert not [row for row in env.outbox() if row["template"] == "decision"]


def test_regrant_resumes_canceled_pending_review_once_without_reviving_decided_notice(setup):
    env, owner, delegate, store = setup
    store.grant(actor_user_id=owner.id, email=delegate.email)
    applicant = env.user("waiting-backlog", status="pending")
    env.auth._queue_review_notices(applicant, method="password")
    original = next(row for row in env.outbox() if row["template"] == "admin_review")
    store.revoke(actor_user_id=owner.id, target_user_id=delegate.id)
    first = env.auth.outbox.deliver_due()
    assert first["cancelled"] == 1
    assert next(row for row in env.outbox() if row["id"] == original["id"])["status"] == "cancelled"
    assert not [message for message in env.sent if message["Subject"] == "CryoStack registration needs review"]

    store.grant(actor_user_id=owner.id, email=delegate.email)
    env.service.notify_waiting_reviewers()
    env.service.notify_waiting_reviewers()
    resumed = [row for row in env.outbox() if row["template"] == "admin_review"
               and row["user_id"] == applicant.id and row["recipient"] == delegate.email]
    assert len(resumed) == 1 and resumed[0]["id"] == original["id"]
    assert resumed[0]["status"] == "queued"
    assert env.auth.outbox.deliver_due()["sent"] == 1
    env.service.notify_waiting_reviewers()
    assert env.auth.outbox.deliver_due()["sent"] == 0
    sent_reviewers = [message["To"] for message in env.sent
                      if message["Subject"] == "CryoStack registration needs review"]
    assert sent_reviewers == [delegate.email]

    decided = env.user("already-decided", status="pending")
    env.auth._queue_review_notices(decided, method="password")
    env.service.decide(actor_user_id=owner.id, target_user_id=decided.id,
                       decision="approve", reason="Owner completed this review")
    assert env.auth.outbox.deliver_due()["cancelled"] == 1
    canceled = next(row for row in env.outbox()
                    if row["template"] == "admin_review" and row["user_id"] == decided.id)
    assert canceled["status"] == "cancelled"
    env.service.notify_waiting_reviewers()
    assert next(row for row in env.outbox() if row["id"] == canceled["id"])["status"] == "cancelled"
    assert env.auth.outbox.deliver_due()["sent"] == 0
