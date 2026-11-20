"""Administrator-approved registration, Google sign-in and approval provisioning.

Acceptance coverage: pending, rejected and suspended accounts are denied
through the UI and the APIs; Google cannot bypass approval; suspension ends
existing sessions and live connections; existing approved users keep
working through the explicit baseline; wrong OAuth state, nonce, issuer or
audience and unsafe account linking are refused; reviewers are notified
once, with retry after a mail outage; unauthorized decisions are refused;
repeated approval keeps one workspace and the allowance override; storage
failure never falls back to the VM.
"""
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from control_center import install_control_center
from control_center.services import AccessService
from control_center.services.registrations import RegistrationService
from icesee_auth import AuthManager, approval
from icesee_auth.approval import DecisionError
from icesee_auth.mailer import MailConfig
from icesee_auth.providers import GoogleProvider
from icesee_auth.security import hash_password

PASSWORD = "correct horse battery"
GOOGLE_CLIENT = "client-123.apps.googleusercontent.com"
REDIRECT = "https://cryostack.test/auth/google/callback"
MAIL = MailConfig(mode="file", sender="cryostack@example.org",
                  base_url="https://cryostack.test", file_dir="unused",
                  admin_emails=("admin@example.org", "nobody@example.org"))


class Clock:
    def __init__(self, now: float = 1_800_000_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


class Google:
    """Stands in for Google's token endpoint and ID-token verification."""

    def __init__(self):
        self.claims: dict = {}
        self.fail_verification = False

    async def exchange(self, form):
        assert form["code_verifier"] and form["grant_type"] == "authorization_code"
        return {"id_token": "signed-token"}

    def verify(self, token, audience):
        if self.fail_verification:
            raise ValueError("bad signature")
        return dict(self.claims)


class Env:
    def __init__(self, tmp_path: Path, *, gate: bool = True, transport=None):
        self.tmp = tmp_path
        self.db = tmp_path / "auth.db"
        self.ws = tmp_path / "ws"
        self.clock = Clock()
        self.sent: list = []
        self.google = Google()
        self.provisioned: list[str] = []
        self.provision_error: Exception | None = None
        self.auth = AuthManager(
            database_path=self.db, secure_cookies=False, clock=self.clock,
            approval_required=gate, mail_config=MAIL,
            mail_transport=transport or (lambda message, config: self.sent.append(message)),
            workspace_provisioner=self._provision, background_interval_s=0,
            google_provider=GoogleProvider(
                client_id=GOOGLE_CLIENT, client_secret="secret", redirect_uri=REDIRECT,
                token_verifier=self.google.verify, token_exchanger=self.google.exchange),
        )
        self.storage = self.auth.storage
        self.access = AccessService(self.storage)
        self.service = RegistrationService(self.auth, self.access)

    def _provision(self, user_id: str) -> dict:
        if self.provision_error is not None:
            raise self.provision_error
        from icesee_auth.provisioning import provision_owner_workspace
        self.provisioned.append(user_id)
        return provision_owner_workspace(user_id, workspace_root=self.ws)

    def app(self) -> web.Application:
        app = web.Application()
        self.auth.install(app)
        app["access_service"] = self.access
        app["control_workspace_root"] = str(self.ws)
        install_control_center(app, auth=self.auth, database_path=self.db)
        return app

    def user(self, name: str, *roles: str, status: str | None = "approved",
             verified: bool = True):
        user = self.storage.create_user(
            email=f"{name}@example.org", display_name=name.title(),
            institution="Test U", password_hash=hash_password(PASSWORD))
        for role in roles:
            self.storage.grant_role(user_id=user.id, role=role)
        if status is not None:
            with self.storage._connect() as c:
                c.execute(
                    "INSERT INTO account_status (user_id, status, registration_method,"
                    " email_verified_at, requested_at, updated_at) VALUES (?, ?, 'test', ?, 1, 1)",
                    (user.id, status, 1.0 if verified else None))
        return user

    def session(self, user) -> dict:
        session = self.storage.create_session(ttl_seconds=3600, user_id=user.id,
                                              now=self.clock())
        return {"icesee_session": session.id}

    def outbox(self) -> list[dict]:
        with sqlite3.connect(self.db) as c:
            c.row_factory = sqlite3.Row
            return [dict(r) for r in c.execute("SELECT * FROM notification_outbox ORDER BY created_at")]

    def audit(self, action=approval.AUDIT_ACTION) -> list[dict]:
        with sqlite3.connect(self.db) as c:
            c.row_factory = sqlite3.Row
            return [dict(r) for r in c.execute(
                "SELECT * FROM access_audit_log WHERE action = ? ORDER BY created_at", (action,))]

    def token_from_outbox(self, template: str) -> str:
        rows = [r for r in self.outbox() if r["template"] == template]
        return json.loads(rows[-1]["context_json"])["token"]

    def run(self, script):
        async def go():
            async with TestClient(TestServer(self.app())) as client:
                return await script(client)
        return asyncio.run(go())


def _cookie(response) -> dict:
    morsel = response.cookies.get("icesee_session")
    return {"icesee_session": morsel.value} if morsel is not None and morsel.value else {}


async def _get(client, path, cookies=None):
    return await client.get(path, cookies=cookies or {}, allow_redirects=False)


async def _post(client, path, cookies=None, data=None, **kw):
    return await client.post(path, cookies=cookies or {}, data=data or {},
                             allow_redirects=False, **kw)


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def _register(client, email="new@example.org", name="New Person"):
    return _post(client, "/auth/register", data={
        "display_name": name, "email": email, "institution": "Ice U",
        "password": PASSWORD, "confirm_password": PASSWORD, "return_to": "/"})


# ── cutover and existing users ─────────────────────────────────────────

def test_gate_refuses_to_start_on_accounts_nobody_baselined(tmp_path):
    first = Env(tmp_path, gate=False)
    owner = first.user("owner", "owner", status=None)
    with pytest.raises(RuntimeError, match="approval-baseline"):
        Env(tmp_path, gate=True).app()

    marker = first.auth.approval.record_baseline(operator="Test Operator",
                                                 reason="existing accounts at cutover")
    assert marker["approved_last_run"] == 1
    gated = Env(tmp_path, gate=True)
    gated.app()
    assert gated.auth.user_is_active(owner.id)
    assert gated.storage.get_user_roles(user_id=owner.id) == ["owner"]
    rows = gated.audit()
    assert [(r["previous_value"], r["new_value"]) for r in rows] == [("no_record", "approved")]
    assert rows[0]["actor_label"] == "migration: Test Operator"
    # idempotent: a second run approves nothing new and keeps the first marker
    again = gated.auth.approval.record_baseline(operator="Someone", reason="again")
    assert again["approved_last_run"] == 0 and again["operator"] == "Test Operator"


def test_existing_session_keeps_working_after_baseline(tmp_path):
    before = Env(tmp_path, gate=False)
    user = before.user("existing", status=None)
    cookies = before.session(user)
    before.auth.approval.record_baseline(operator="op", reason="cutover test")
    env = Env(tmp_path, gate=True)

    async def script(client):
        me = await (await _get(client, "/api/v1/me", cookies)).json()
        experiments = await _get(client, "/api/v1/experiments", cookies)
        return me, experiments.status

    me, status = env.run(script)
    assert me["authenticated"] is True and me["account_status"] == "approved"
    assert status == 200


def test_empty_database_is_baselined_automatically(tmp_path):
    env = Env(tmp_path)
    env.app()
    assert env.auth.approval.baseline()["operator"] == "automatic"


# ── password registration ──────────────────────────────────────────────

def test_registration_is_pending_without_a_session_and_hides_existing_accounts(env):
    existing = env.user("taken")

    async def script(client):
        fresh = await _register(client)
        duplicate = await _register(client, email=existing.email, name="Someone")
        return (fresh.status, await fresh.text(), _cookie(fresh),
                duplicate.status, await duplicate.text())

    status, html, cookies, dup_status, dup_html = env.run(script)
    assert status == dup_status == 200
    strip = lambda text: re.sub(r"[\w.+-]+@example\.org", "EMAIL", text)
    assert strip(html) == strip(dup_html)            # no account enumeration
    user = env.storage.get_user_by_email("new@example.org")
    assert env.auth.approval.effective_status(user.id) == "pending"
    assert not env.auth.user_is_active(user.id)
    sessions = env.storage._connect().execute(
        "SELECT COUNT(*) FROM sessions WHERE user_id = ?", (user.id,)).fetchone()[0]
    assert sessions == 0
    templates = sorted(r["template"] for r in env.outbox())
    assert templates == ["registration_exists", "verify_email"]
    # no reviewer is told before the address is confirmed
    assert not [r for r in env.outbox() if r["template"] == "admin_review"]


def test_email_confirmation_needs_a_post_and_notifies_reviewers_once(env):
    admin = env.user("admin", "admin")

    async def script(client):
        await _register(client)
        token = env.token_from_outbox("verify_email")
        page = await _get(client, f"/auth/verify-email?token={token}")
        user = env.storage.get_user_by_email("new@example.org")
        verified_by_get = env.auth.approval.status(user.id).email_verified
        confirmed = await _post(client, "/auth/verify-email", data={"token": token})
        reused = await _post(client, "/auth/verify-email", data={"token": token})
        await _register(client)                    # retrying the form again
        return page.status, verified_by_get, confirmed.status, reused.status

    page, verified_by_get, confirmed, reused = env.run(script)
    assert page == 200 and verified_by_get is False
    assert confirmed == 200 and reused == 400
    user = env.storage.get_user_by_email("new@example.org")
    assert env.auth.approval.status(user.id).email_verified
    assert env.auth.approval.effective_status(user.id) == "pending"   # still pending
    reviews = [r for r in env.outbox() if r["template"] == "admin_review"]
    # only the configured address that belongs to an approved admin
    assert [r["recipient"] for r in reviews] == [admin.email]
    env.auth.outbox.deliver_due()
    review = next(m for m in env.sent if m["To"] == admin.email)
    body = review.get_content()
    assert f"https://cryostack.test/control/registrations?user={user.id}" in body
    assert "sign-in required" in body and "approve?" not in body.lower()
    assert user.email not in body                      # reviewers see the address in Control Center


def test_registration_is_throttled_per_client_address(env):
    async def script(client):
        statuses = []
        for n in range(12):
            response = await _register(client, email=f"user{n}@example.org")
            statuses.append(response.status)
        return statuses

    statuses = env.run(script)
    assert statuses[:10] == [200] * 10 and statuses[10:] == [429, 429]


# ── the gate on every path ─────────────────────────────────────────────

@pytest.mark.parametrize("status", ["pending", "rejected", "suspended"])
def test_unapproved_accounts_are_denied_through_ui_and_api(env, status):
    user = env.user("applicant", status=status)
    cookies = env.session(user)

    async def script(client):
        login = await _post(client, "/auth/login", data={
            "email": user.email, "password": PASSWORD, "return_to": "/account/"})
        account = await _get(client, "/account/", cookies)
        control = await _get(client, "/control/", cookies)
        api = await _get(client, "/api/v1/experiments", cookies)
        api_body = await api.json()
        compute = await _get(client, "/api/allocations", cookies)
        me = await (await _get(client, "/api/v1/me", cookies)).json()
        status_page = await _get(client, "/auth/status", cookies)
        return (login, account, control, api.status, api_body, compute.status, me,
                status_page.status, await status_page.text())

    login, account, control, api, api_body, compute, me, page_status, page = env.run(script)
    assert login.status == 302 and login.headers["Location"].startswith("/auth/status")
    assert account.status == 302 and account.headers["Location"].startswith("/auth/login")
    assert control.status == 302 and control.headers["Location"].startswith("/auth/status")
    assert api == 403 and api_body["account_status"] == status
    assert compute == 403
    assert me["authenticated"] is False and me["account_status"] == status
    assert env.auth.current_user is not None and not env.auth.user_is_active(user.id)
    assert page_status in (200, 403) and "Sign out" in page


def test_pending_user_cannot_hold_a_role_through_the_gate(env):
    sneaky = env.user("sneaky", "owner", status="pending")
    cookies = env.session(sneaky)

    async def script(client):
        return (await _get(client, "/control/users", cookies)).status

    assert env.run(script) == 302


def test_suspension_revokes_sessions_and_live_connections(env):
    admin = env.user("admin", "admin")
    member = env.user("member")
    cookies = env.session(member)
    closed = []
    env.auth.register_live_connection(member.id, lambda: closed.append(True))

    async def script(client):
        before = (await _get(client, "/api/v1/experiments", cookies)).status
        env.service.decide(actor_user_id=admin.id, target_user_id=member.id,
                           decision="suspend", reason="policy breach under review")
        after = await _get(client, "/api/v1/experiments", cookies)
        return before, after.status

    before, after = env.run(script)
    assert before == 200 and after == 401
    assert closed == [True]
    assert env.storage._connect().execute(
        "SELECT COUNT(*) FROM sessions WHERE user_id = ?", (member.id,)).fetchone()[0] == 0
    row = env.audit()[-1]
    assert (row["actor_user_id"], row["target_user_id"], row["previous_value"],
            row["new_value"], row["reason"]) == (admin.id, member.id, "approved",
                                                 "suspended", "policy breach under review")


def test_suspension_still_applies_with_the_gate_switched_off(tmp_path):
    env = Env(tmp_path, gate=False)
    user = env.user("member", status="suspended")
    assert not env.auth.user_is_active(user.id)
    other = env.user("legacy", status=None)
    assert env.auth.user_is_active(other.id)


# ── decisions and who may make them ────────────────────────────────────

def test_every_control_role_decides_but_never_for_themselves(env):
    owner = env.user("owner", "owner")
    admin = env.user("admin", "admin")
    maintainer = env.user("maint", "maintainer")
    developer = env.user("dev", "developer")
    member = env.user("member")
    other_admin = env.user("admin2", "admin")
    applicant = env.user("applicant", status="pending")

    with pytest.raises(PermissionError):           # no Control Center role
        env.service.decide(actor_user_id=member.id, target_user_id=applicant.id,
                           decision="approve", reason="")
    for actor in (developer, maintainer):          # staff accounts are owner-only
        with pytest.raises(PermissionError):
            env.service.decide(actor_user_id=actor.id, target_user_id=other_admin.id,
                               decision="suspend", reason="not allowed")
    with pytest.raises(PermissionError):           # admin on an admin account
        env.service.decide(actor_user_id=admin.id, target_user_id=other_admin.id,
                           decision="suspend", reason="not allowed")
    with pytest.raises(PermissionError):           # nobody decides for themselves
        env.service.decide(actor_user_id=owner.id, target_user_id=owner.id,
                           decision="suspend", reason="self change")
    with pytest.raises(PermissionError):           # owners must lose the role first
        env.service.decide(actor_user_id=owner.id, target_user_id=owner.id,
                           decision="reject", reason="self change")
    assert env.audit() == []
    with pytest.raises(ValueError):                # reject needs a reason
        env.service.decide(actor_user_id=admin.id, target_user_id=applicant.id,
                           decision="reject", reason="")
    result = env.service.decide(actor_user_id=admin.id, target_user_id=applicant.id,
                                decision="approve", reason="")
    assert result["status"] == "approved"
    assert env.audit()[-1]["reason"] == "Approved after review"
    env.service.decide(actor_user_id=owner.id, target_user_id=other_admin.id,
                       decision="suspend", reason="owner may decide on admins")
    for actor in (developer, maintainer):          # whoever gets there first
        later = env.user(f"later-{actor.id[:6]}", status="pending")
        assert env.service.decide(actor_user_id=actor.id, target_user_id=later.id,
                                  decision="approve", reason="")["status"] == "approved"


def test_approval_waits_for_a_confirmed_email(env):
    admin = env.user("admin", "admin")
    applicant = env.user("unconfirmed", status="pending", verified=False)
    with pytest.raises(DecisionError, match="verified"):
        env.service.decide(actor_user_id=admin.id, target_user_id=applicant.id,
                           decision="approve", reason="")


def test_review_page_and_unauthorized_or_cross_site_decisions(env):
    admin = env.user("admin", "admin")
    developer = env.user("dev", "developer")
    applicant = env.user("applicant", status="pending")
    admin_cookies, dev_cookies = env.session(admin), env.session(developer)

    async def script(client):
        anonymous = await _post(client, f"/control/registrations/{applicant.id}/decision",
                                data={"decision": "approve"})
        page = await _get(client, f"/control/registrations?user={applicant.id}", dev_cookies)
        page_html = await page.text()
        dev = await _post(client, f"/control/registrations/{admin.id}/decision",
                          dev_cookies, {"decision": "suspend", "reason": "staff account"})
        cross = await _post(client, f"/control/registrations/{applicant.id}/decision",
                            admin_cookies, {"decision": "approve"},
                            headers={"Origin": "https://evil.example"})
        mid = env.auth.approval.effective_status(applicant.id)
        ok = await _post(client, f"/control/registrations/{applicant.id}/decision",
                         admin_cookies, {"decision": "approve", "reason": ""})
        return anonymous, page.status, page_html, dev.status, cross.status, mid, ok

    anonymous, page, html, dev, cross, mid, ok = env.run(script)
    assert anonymous.status == 302 and anonymous.headers["Location"].startswith("/auth/login")
    assert page == 200 and applicant.email in html and "Approve</button>" in html
    assert dev == 403 and cross == 403 and mid == "pending"
    assert ok.status == 303 and env.auth.approval.effective_status(applicant.id) == "approved"
    assert "password_hash" not in html and "scrypt" not in html


# ── provisioning ───────────────────────────────────────────────────────

def test_repeated_approval_keeps_one_workspace_and_the_override(env, monkeypatch, tmp_path):
    from cryostack_src.workspace import storage_policy
    from icesee_jupyter_book.applications.frozen_legacies.radar import quota

    monkeypatch.setenv(quota.STORAGE_DB_ENV, str(tmp_path / "quota.db"))
    store, _ = storage_policy.policy()
    admin = env.user("admin", "admin")
    applicant = env.user("applicant", status="pending")
    store.set_override(applicant.id, 7 * quota.GIB, actor=admin.id)

    env.service.decide(actor_user_id=admin.id, target_user_id=applicant.id,
                       decision="approve", reason="")
    assert env.auth.provision_due()["ready"] == 1
    first = env.auth.approval.provisioning(applicant.id)
    assert first["status"] == "ready" and first["allowance_source"] == "override"
    assert first["allowance_bytes"] == 7 * quota.GIB

    env.service.decide(actor_user_id=admin.id, target_user_id=applicant.id,
                       decision="suspend", reason="temporary hold")
    env.service.decide(actor_user_id=admin.id, target_user_id=applicant.id,
                       decision="reinstate", reason="hold lifted")
    env.auth.approval.retry_provisioning(applicant.id)
    assert env.auth.provision_due()["ready"] == 1

    owners = list((env.ws / "users").iterdir())
    assert len(owners) == 1 and owners[0].name == first["owner_key"]
    assert list(owners[0].iterdir()) == []                 # nothing written to reserve space
    assert store.override(applicant.id) == 7 * quota.GIB

    other = env.user("default", status="pending")
    env.service.decide(actor_user_id=admin.id, target_user_id=other.id,
                       decision="approve", reason="")
    env.auth.provision_due()
    detail = env.auth.approval.provisioning(other.id)
    assert detail["allowance_source"] == "default"
    assert detail["allowance_bytes"] == store.settings()["default_quota_bytes"]


def test_storage_failure_is_retryable_and_never_falls_back_to_the_vm(env, monkeypatch):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_MOUNT", str(env.tmp / "cedar-mount"))
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_VOLUME_ID", "volume-1")
    admin = env.user("admin", "admin")
    applicant = env.user("applicant", status="pending")
    env.service.decide(actor_user_id=admin.id, target_user_id=applicant.id,
                       decision="approve", reason="")

    assert env.auth.provision_due() == {"ready": 0, "retry": 1, "failed": 0}
    state = env.auth.approval.provisioning(applicant.id)
    assert state["status"] == "queued" and "WorkspaceStorageUnavailable" in state["last_error"]
    assert not env.ws.exists()                              # nothing on the VM
    assert env.auth.provision_due()["retry"] == 0           # backing off, not hammering

    for _ in range(6):
        env.clock.now += 3600
        env.auth.provision_due()
    assert env.auth.approval.provisioning(applicant.id)["status"] == "failed"

    monkeypatch.delenv("CRYOSTACK_WORKSPACE_MOUNT")
    env.service.retry_provisioning(actor_user_id=admin.id, target_user_id=applicant.id)
    assert env.auth.provision_due()["ready"] == 1


def test_pending_accounts_get_no_workspace(env):
    env.user("pending", status="pending")
    assert env.auth.provision_due() == {"ready": 0, "retry": 0, "failed": 0}
    assert not env.ws.exists()


# ── email outbox ───────────────────────────────────────────────────────

def test_reviewers_are_notified_once_with_retry_after_a_mail_outage(tmp_path):
    attempts = []

    def flaky(message, config):
        attempts.append(message["To"])
        if len(attempts) <= 2:
            raise ConnectionRefusedError("relay down")

    env = Env(tmp_path, transport=flaky)
    admin = env.user("admin", "admin")
    applicant = env.user("applicant", status="pending")
    for _ in range(3):
        env.auth._queue_review_notices(applicant, method="password")
    assert len([r for r in env.outbox() if r["template"] == "admin_review"]) == 1

    first = env.auth.outbox.deliver_due()
    assert first["retry"] == 2 and first["sent"] == 0       # both messages failed
    assert env.auth.outbox.deliver_due() == {"sent": 0, "retry": 0, "cancelled": 0, "skipped": 0}
    env.clock.now += 61
    second = env.auth.outbox.deliver_due()
    assert second["sent"] == 2
    env.clock.now += 3600
    assert env.auth.outbox.deliver_due()["sent"] == 0       # never twice
    review = [r for r in env.outbox() if r["template"] == "admin_review"][0]
    assert review["status"] == "sent" and review["recipient"] == admin.email
    assert attempts.count(admin.email) == 2
    # the outage never touched the account's status
    assert env.auth.approval.effective_status(applicant.id) == "pending"


def test_reviewer_notice_is_dropped_once_the_account_is_decided(env):
    admin = env.user("admin", "admin")
    applicant = env.user("applicant", status="pending")
    env.auth._queue_review_notices(applicant, method="password")
    env.service.decide(actor_user_id=admin.id, target_user_id=applicant.id,
                       decision="approve", reason="")
    result = env.auth.outbox.deliver_due()
    assert result["cancelled"] == 1
    templates = {m["Subject"] for m in env.sent}
    assert "CryoStack registration needs review" not in templates
    assert "Your CryoStack account is approved" in templates


def test_disabled_mail_sends_nothing_and_links_never_use_the_host_header(tmp_path):
    env = Env(tmp_path)
    env.auth.outbox.config = MailConfig()                 # the default: disabled
    applicant = env.user("applicant", status="pending")
    env.auth._send_verification(applicant)
    assert env.auth.outbox.deliver_due()["sent"] == 0 and env.sent == []

    env.auth.outbox.config = MAIL
    env.auth.outbox.deliver_due()
    body = env.sent[0].get_content()
    assert "https://cryostack.test/auth/verify-email?token=" in body
    row = env.outbox()[0]
    assert json.loads(row["context_json"])["token"] == "[removed]"   # scrubbed after delivery


def test_mail_configuration_problems_are_reported_not_guessed():
    assert MailConfig(mode="smtp").problems()
    bad = MailConfig(mode="smtp", sender="a@b.org", base_url="http://x.org",
                     smtp_host="relay", smtp_username="u")
    problems = " ".join(bad.problems())
    assert "https://" in problems and "PASSWORD_FILE" in problems
    assert MailConfig.from_env({}).admin_emails == ()
    public = MailConfig(mode="smtp", sender="a@b.org", base_url="https://x.org",
                        smtp_host="relay", smtp_password_file="/secret").public()
    assert "/secret" not in json.dumps(public)


# ── password recovery ──────────────────────────────────────────────────

def test_password_reset_is_generic_single_use_and_signs_out_everywhere(env):
    user = env.user("member")
    cookies = env.session(user)

    async def script(client):
        known = await _post(client, "/auth/forgot", data={"email": user.email})
        unknown = await _post(client, "/auth/forgot", data={"email": "ghost@example.org"})
        token = env.token_from_outbox("password_reset")
        form = await _get(client, f"/auth/reset?token={token}")
        short = await _post(client, "/auth/reset", data={
            "token": token, "password": "short", "confirm_password": "short"})
        done = await _post(client, "/auth/reset", data={
            "token": token, "password": "a brand new secret", "confirm_password": "a brand new secret"})
        again = await _post(client, "/auth/reset", data={
            "token": token, "password": "another secret 1", "confirm_password": "another secret 1"})
        old_session = await _get(client, "/api/v1/experiments", cookies)
        login = await _post(client, "/auth/login", data={
            "email": user.email, "password": "a brand new secret", "return_to": "/"})
        return (await known.text(), await unknown.text(), form.status, short.status,
                done.status, again.status, old_session.status, login.status)

    known, unknown, form, short, done, again, old_session, login = env.run(script)
    assert known == unknown
    assert (form, short, done, again, old_session, login) == (200, 400, 200, 400, 401, 302)


def test_expired_reset_link_is_refused(env):
    user = env.user("member")
    token = env.auth.approval.issue_token(user_id=user.id, email=user.email,
                                          purpose=approval.PASSWORD_RESET)
    env.clock.now += 3601
    assert env.auth.approval.consume_token(token, approval.PASSWORD_RESET) is None


# ── Google OpenID Connect ──────────────────────────────────────────────

def _claims(nonce, **overrides):
    claims = {"iss": "https://accounts.google.com", "aud": GOOGLE_CLIENT,
              "sub": "google-sub-1", "email": "scientist@gmail.example",
              "email_verified": True, "name": "Ice Scientist", "nonce": nonce}
    claims.update(overrides)
    return claims


async def _google(client, env, cookies=None, *, claims=None, state=None, keep_cookie=True):
    begin = await _get(client, "/auth/google?return_to=/frozen-legacies/", cookies)
    assert begin.status == 302
    query = parse_qs(urlsplit(begin.headers["Location"]).query)
    assert query["code_challenge_method"] == ["S256"] and query["redirect_uri"] == [REDIRECT]
    nonce = query["nonce"][0]
    env.google.claims = claims(nonce) if callable(claims) else _claims(nonce)
    # a different browser: its own (anonymous) session cookie
    browser = ({**(cookies or {}), **_cookie(begin)} if keep_cookie
               else {"icesee_session": "another-browser"})
    return await _get(client, f"/auth/google/callback?code=abc&state={state or query['state'][0]}",
                      browser)


def test_google_sign_up_is_pending_and_cannot_bypass_approval(env):
    async def script(client):
        callback = await _google(client, env)
        cookies = _cookie(callback)
        api = await _get(client, "/api/v1/experiments", cookies)
        app = await _get(client, "/control/", cookies)
        return callback, api.status, app

    callback, api, app = env.run(script)
    assert callback.status == 302 and callback.headers["Location"].startswith("/auth/status")
    user = env.storage.get_user_by_email("scientist@gmail.example")
    assert env.auth.approval.effective_status(user.id) == "pending"
    assert env.auth.approval.status(user.id).registration_method == "google"
    assert api == 403 and app.headers["Location"].startswith("/auth/status")
    # Google confirmed the address, so reviewers are told at once
    assert [r["template"] for r in env.outbox()].count("admin_review") == 0  # no reviewer account yet
    assert "applicant_pending" in [r["template"] for r in env.outbox()]


@pytest.mark.parametrize("case", ["state", "session", "nonce", "issuer", "audience",
                                  "unverified", "signature"])
def test_google_rejects_forged_or_mismatched_responses(env, case):
    claims = {
        "nonce": lambda n: _claims("not-the-nonce"),
        "issuer": lambda n: _claims(n, iss="https://evil.example"),
        "audience": lambda n: _claims(n, aud="someone-else"),
        "unverified": lambda n: _claims(n, email_verified=False),
    }.get(case)
    env.google.fail_verification = case == "signature"

    async def script(client):
        return await _google(client, env, claims=claims,
                             state="forged-state" if case == "state" else None,
                             keep_cookie=case != "session")

    response = env.run(script)
    assert response.status == 400
    assert env.storage.get_user_by_email("scientist@gmail.example") is None


def test_google_never_links_an_existing_account_by_email(env):
    existing = env.user("scientist")

    async def script(client):
        return await _google(client, env, claims=lambda n: _claims(n, email=existing.email))

    response = env.run(script)
    assert response.status == 409
    assert env.storage.list_user_identities(user_id=existing.id) == []


def test_approved_user_links_google_and_then_signs_in_with_it(env):
    member = env.user("member")
    cookies = env.session(member)

    async def script(client):
        linked = await _google(client, env, cookies)
        again = await _google(client, env)
        return linked, again

    linked, again = env.run(script)
    assert linked.status == 302 and linked.headers["Location"] == "/frozen-legacies/"
    assert [i.provider for i in env.storage.list_user_identities(user_id=member.id)] == ["google"]
    assert again.status == 302 and again.headers["Location"] == "/frozen-legacies/"
    assert env.storage.get_user_by_email("scientist@gmail.example") is None


def test_google_sign_in_of_a_suspended_account_lands_on_its_status(env):
    member = env.user("member")
    cookies = env.session(member)
    admin = env.user("admin", "admin")

    async def script(client):
        await _google(client, env, cookies)
        env.service.decide(actor_user_id=admin.id, target_user_id=member.id,
                           decision="suspend", reason="testing suspension")
        return await _google(client, env)

    response = env.run(script)
    assert response.headers["Location"].startswith("/auth/status")


def test_google_sign_up_stays_closed_without_the_gate(tmp_path):
    env = Env(tmp_path, gate=False)

    async def script(client):
        return await _google(client, env)

    assert env.run(script).status == 409
    assert env.storage.get_user_by_email("scientist@gmail.example") is None


def test_github_sign_up_is_pending_too(env, monkeypatch):
    from icesee_auth.providers.base import ExternalIdentity, OAuthAuthentication

    github = env.auth._github_provider
    monkeypatch.setattr(github, "client_id", "gh")
    monkeypatch.setattr(github, "client_secret", "gh-secret")
    monkeypatch.setattr(github, "redirect_uri", "https://cryostack.test/auth/github/callback")

    async def exchange(**kw):
        return OAuthAuthentication(access_token="t")

    async def identity(_auth):
        return ExternalIdentity(provider="github", subject="42", username="octo",
                                email="octo@example.org", display_name="Octo")

    monkeypatch.setattr(github, "exchange_code", exchange)
    monkeypatch.setattr(github, "fetch_identity", identity)

    async def script(client):
        begin = await _get(client, "/auth/github")
        state = parse_qs(urlsplit(begin.headers["Location"]).query)["state"][0]
        return await _get(client, f"/auth/github/callback?code=c&state={state}", _cookie(begin))

    response = env.run(script)
    user = env.storage.get_user_by_email("octo@example.org")
    assert env.auth.approval.effective_status(user.id) == "pending"
    assert response.headers["Location"].startswith("/auth/status")



def test_an_approved_account_can_be_selected_and_suspended_from_its_user_page(env):
    admin = env.user("admin", "admin")
    member = env.user("member")
    cookies = env.session(admin)

    async def script(client):
        user_page = await (await _get(client, f"/control/users/{member.id}", cookies)).text()
        selected = await (await _get(client, f"/control/registrations?user={member.id}",
                                     cookies)).text()
        done = await _post(client, f"/control/registrations/{member.id}/decision", cookies,
                           {"decision": "suspend", "reason": "account shared with others"})
        return user_page, selected, done.status

    user_page, selected, status = env.run(script)
    assert f"/control/registrations?user={member.id}" in user_page and "approved" in user_page
    assert "Selected account" in selected and "Suspend</button>" in selected
    assert status == 303 and env.auth.approval.effective_status(member.id) == "suspended"


def test_accounts_without_a_status_after_the_baseline_are_queued_as_pending(env):
    env.auth.approval.record_baseline(operator="op", reason="cutover test")
    late = env.user("late", status=None)                   # e.g. made while the gate was off
    pending = env.auth.approval.list_accounts(status="pending")
    assert [row["id"] for row in pending] == [late.id] and pending[0]["no_record"]
    assert not env.auth.user_is_active(late.id)
    admin = env.user("admin", "admin")
    env.service.decide(actor_user_id=admin.id, target_user_id=late.id,
                       decision="approve", reason="")
    assert env.auth.user_is_active(late.id)


def test_unconfirmed_applicants_are_not_offered_approval(env):
    admin = env.user("admin", "admin")
    applicant = env.user("unconfirmed", status="pending", verified=False)
    assert env.service.allowed_decisions(actor_user_id=admin.id,
                                         target_user_id=applicant.id) == ["reject", "suspend"]


def test_owner_only_pilot_blocks_other_roles_and_notices(env, monkeypatch):
    monkeypatch.setenv("CRYOSTACK_APPROVAL_OWNER_ONLY", "1")
    owner = env.user("owner", "owner")
    admin = env.user("admin", "admin")
    applicant = env.user("applicant", status="pending")
    for role in ("admin", "maintainer", "developer"):
        actor = admin if role == "admin" else env.user(role, role)
        assert not env.service.can_decide(actor_user_id=actor.id)
        with pytest.raises(PermissionError):
            env.service.decide(actor_user_id=actor.id, target_user_id=applicant.id,
                               decision="approve", reason="pilot")
    from dataclasses import replace
    env.auth.outbox.config = replace(MAIL, admin_emails=(owner.email, admin.email))
    assert env.auth.outbox.reviewers() == ([owner.email], [admin.email])
    assert env.service.decide(actor_user_id=owner.id, target_user_id=applicant.id,
                              decision="approve", reason="pilot")["status"] == "approved"
