"""Provider transport contracts and isolated end-to-end signup delivery.

HTTP responses are simulated at the TLS client boundary. No real provider is
contacted and these tests do not establish production delivery or inbox receipt.
"""
from __future__ import annotations

import io
import json
import logging
import re
import ssl
import smtplib
from dataclasses import replace
from email.message import EmailMessage
from urllib.error import HTTPError
from urllib.request import HTTPSHandler

import pytest

from icesee_auth import mailer
from icesee_auth.mailer import MailConfig
from control_center.tests.test_registration_approval import (
    Env, PASSWORD, _cookie, _get, _post, _register,
)


class Response(io.BytesIO):
    status = 200

    def getcode(self):
        return self.status


class HTTP:
    """Exercise provider request building without making a network connection."""

    def __init__(self, provider, *, failures=0):
        self.provider = provider
        self.failures = failures
        self.requests = []
        self.handlers = []

    def build_opener(self, *handlers):
        self.handlers.append(handlers)
        https = next(h for h in handlers if isinstance(h, HTTPSHandler))
        assert https._context.verify_mode == ssl.CERT_REQUIRED
        assert https._context.check_hostname is True
        assert any(type(h).__name__ == "_NoRedirect" for h in handlers)
        return self

    def open(self, request, *, timeout):
        assert 0 < timeout <= 60
        self.requests.append(request)
        if self.failures:
            self.failures -= 1
            raise HTTPError(
                request.full_url, 429,
                "secret-provider-key verification-token private@example.org",
                {}, io.BytesIO(b'{"message":"secret-provider-key verification-token"}'),
            )
        receipt = f"receipt-{len(self.requests)}"
        body = ({"id": receipt} if self.provider == "resend" else
                {"ErrorCode": 0, "Message": "OK", "MessageID": receipt})
        return Response(json.dumps(body).encode())

    def payloads(self):
        return [json.loads(r.data) for r in self.requests]


def config(tmp_path, provider, *, admins=()):
    credential = tmp_path / f"{provider}.secret"
    credential.write_text("secret-provider-key\n", encoding="utf-8")
    credential.chmod(0o600)
    field = ("resend_api_key_file" if provider == "resend" else
             "postmark_server_token_file")
    return MailConfig(
        mode=provider, sender="cryostack@example.org", base_url="https://cryostack.test",
        admin_emails=admins, **{field: str(credential)},
    )


def use_provider(env, monkeypatch, cfg, http):
    monkeypatch.setattr(mailer, "build_opener", http.build_opener)
    env.auth.outbox.config = cfg
    env.auth.outbox._transport = None


@pytest.mark.parametrize("provider", ["resend", "postmark"])
def test_provider_configuration_is_explicit_and_hides_credentials(tmp_path, provider):
    cfg = config(tmp_path, provider)
    assert cfg.delivers and cfg.problems() == []
    public = json.dumps(cfg.public())
    assert "secret-provider-key" not in public and ".secret" not in public
    assert MailConfig(mode=provider, sender=cfg.sender, base_url=cfg.base_url).problems()
    key = ("CRYOSTACK_RESEND_API_KEY_FILE" if provider == "resend" else
           "CRYOSTACK_POSTMARK_SERVER_TOKEN_FILE")
    field = "resend_api_key_file" if provider == "resend" else "postmark_server_token_file"
    assert getattr(MailConfig.from_env({"CRYOSTACK_MAIL_MODE": provider, key: "/private/key"}), field) == "/private/key"


@pytest.mark.parametrize("provider", ["resend", "postmark"])
def test_provider_submission_has_verified_tls_and_expected_auth(tmp_path, monkeypatch, caplog, provider):
    env = Env(tmp_path)
    http = HTTP(provider)
    use_provider(env, monkeypatch, config(tmp_path, provider), http)
    env.auth.outbox.enqueue(dedupe_key="exists:1", template="registration_exists",
                            recipient="member@example.org", context={})
    with caplog.at_level(logging.INFO, logger="icesee_auth.mailer"):
        assert env.auth.outbox.deliver_due()["sent"] == 1
    request = http.requests[0]
    payload = http.payloads()[0]
    assert request.method == "POST"
    headers = {k.lower(): v for k, v in request.header_items()}
    if provider == "resend":
        assert request.full_url == "https://api.resend.com/emails"
        assert headers["authorization"] == "Bearer secret-provider-key"
        assert headers["idempotency-key"]
        assert payload["from"] == "cryostack@example.org"
        assert payload["to"] == ["member@example.org"]
        assert "https://cryostack.test/auth/login" in payload["text"]
    else:
        assert request.full_url == "https://api.postmarkapp.com/email"
        assert headers["x-postmark-server-token"] == "secret-provider-key"
        assert payload["From"] == "cryostack@example.org"
        assert payload["To"] == "member@example.org"
        assert payload["MessageStream"] == "outbound"
        assert payload["TrackOpens"] is False and payload["TrackLinks"] == "None"
    assert env.outbox()[0]["status"] == "sent"
    assert "receipt-1" in caplog.text
    assert "secret-provider-key" not in caplog.text and "member@example.org" not in caplog.text
    # Submission success is logged as provider acceptance, never inbox delivery.
    assert "accepted" in caplog.text and "inbox" not in caplog.text.lower()
    assert env.auth.outbox.deliver_due()["sent"] == 0
    assert len(http.requests) == 1


@pytest.mark.parametrize("provider", ["resend", "postmark"])
def test_provider_failure_retries_without_secrets_or_auth_state_changes(tmp_path, monkeypatch, caplog, provider):
    env = Env(tmp_path)
    user = env.user("unverified", status="pending", verified=False)
    env.auth._send_verification(user)
    token = env.token_from_outbox("verify_email")
    http = HTTP(provider, failures=1)
    use_provider(env, monkeypatch, config(tmp_path, provider), http)
    with caplog.at_level(logging.INFO, logger="icesee_auth.mailer"):
        assert env.auth.outbox.deliver_due()["retry"] == 1
        row = env.outbox()[0]
        assert row["status"] == "queued" and row["attempts"] == 1
        assert "429" in row["last_error"]
        assert env.auth.approval.effective_status(user.id) == "pending"
        assert not env.auth.approval.status(user.id).email_verified
        assert not env.auth.user_is_active(user.id)
        assert env.auth.outbox.deliver_due()["sent"] == 0
        env.clock.now += 61
        assert env.auth.outbox.deliver_due()["sent"] == 1
    for text in (caplog.text, row["last_error"]):
        assert "secret-provider-key" not in text and "verification-token" not in text
        assert "private@example.org" not in text and token not in text
    assert http.requests[0].data == http.requests[1].data
    if provider == "resend":
        first = {k.lower(): v for k, v in http.requests[0].header_items()}
        second = {k.lower(): v for k, v in http.requests[1].header_items()}
        assert first["idempotency-key"] == second["idempotency-key"]
    assert json.loads(env.outbox()[0]["context_json"])["token"] == "[removed]"
    assert not env.auth.approval.status(user.id).email_verified


@pytest.mark.parametrize("provider", ["resend", "postmark", "smtp-gt"])
def test_signup_confirmation_owner_approval_and_login_through_provider(tmp_path, monkeypatch, provider):
    monkeypatch.setenv("CRYOSTACK_APPROVAL_OWNER_ONLY", "1")
    env = Env(tmp_path)
    owner = env.user("owner", "owner")
    admin = env.user("admin", "admin")
    if provider == "smtp-gt":
        http = GTTransport(monkeypatch)
        env.auth.outbox.config = gt_config(admin_emails=(owner.email, admin.email))
        env.auth.outbox._transport = None
    else:
        http = HTTP(provider)
        use_provider(env, monkeypatch, config(tmp_path, provider, admins=(owner.email, admin.email)), http)
    subject_key = "subject" if provider == "resend" else "Subject"
    body_key = "text" if provider == "resend" else "TextBody"
    to_key = "to" if provider == "resend" else "To"

    async def script(client):
        response = await _register(client)
        assert response.status == 200 and _cookie(response) == {}
        applicant = env.storage.get_user_by_email("new@example.org")
        assert not env.auth.user_is_active(applicant.id)
        assert not [r for r in env.outbox() if r["template"] == "admin_review"]
        assert env.auth.outbox.deliver_due()["sent"] == 1
        confirmation = http.payloads()[0]
        assert confirmation[subject_key] == "Confirm your CryoStack email address"
        token = re.search(r"/auth/verify-email\?token=(\S+)", confirmation[body_key]).group(1)
        # A provider-accepted email cannot verify or approve an account itself.
        assert not env.auth.approval.status(applicant.id).email_verified
        assert (await _get(client, f"/auth/verify-email?token={token}")).status == 200
        assert not env.auth.approval.status(applicant.id).email_verified
        assert (await _post(client, "/auth/verify-email", data={"token": token})).status == 200
        assert (await _post(client, "/auth/verify-email", data={"token": token})).status == 400
        assert env.auth.approval.status(applicant.id).email_verified
        assert env.auth.approval.effective_status(applicant.id) == "pending"
        assert env.auth.outbox.deliver_due()["sent"] == 2
        notices = http.payloads()[1:]
        review = next(p for p in notices if p[subject_key] == "CryoStack registration needs review")
        assert review[to_key] == ([owner.email] if provider == "resend" else owner.email)
        assert "/control/registrations?user=" in review[body_key]
        assert not [r for r in env.outbox() if r["template"] == "admin_review" and r["recipient"] == admin.email]
        pending = await _post(client, "/auth/login", data={
            "email": applicant.email, "password": PASSWORD, "return_to": "/account/"})
        assert pending.status == 302 and pending.headers["Location"].startswith("/auth/status")
        pending_cookies = _cookie(pending)
        assert (await _get(client, "/api/v1/experiments", pending_cookies)).status == 403
        client.session.cookie_jar.clear()
        denied = await _post(client, f"/control/registrations/{applicant.id}/decision",
                             env.session(admin), {"decision": "approve"})
        assert denied.status == 403
        client.session.cookie_jar.clear()
        approved = await _post(client, f"/control/registrations/{applicant.id}/decision",
                               env.session(owner), {"decision": "approve"})
        assert approved.status == 303
        assert env.auth.approval.effective_status(applicant.id) == "approved"
        assert env.auth.outbox.deliver_due()["sent"] == 1
        decision = http.payloads()[-1]
        assert decision[subject_key] == "Your CryoStack account is approved"
        assert "/auth/login" in decision[body_key]
        client.session.cookie_jar.clear()
        login = await _post(client, "/auth/login", data={
            "email": applicant.email, "password": PASSWORD, "return_to": "/account/"})
        assert login.status == 302 and login.headers["Location"] == "/account/"
        assert (await _get(client, "/api/v1/experiments", _cookie(login))).status == 200
        assert all(r["status"] == "sent" for r in env.outbox())

    env.run(script)


def test_smtp_transport_preserves_certificate_validation(tmp_path, monkeypatch):
    env = Env(tmp_path)
    seen = {}

    class SMTP:
        def __init__(self, host, port, *, timeout):
            seen.update(host=host, port=port, timeout=timeout)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def starttls(self, *, context):
            seen["tls"] = context

        def send_message(self, message):
            seen["message"] = message
            return {}

    monkeypatch.setattr(mailer.smtplib, "SMTP", SMTP)
    env.auth.outbox.config = MailConfig(
        mode="smtp", sender="cryostack@example.org", base_url="https://cryostack.test",
        smtp_host="outbound.mail.gatech.edu", smtp_port=587,
    )
    env.auth.outbox._transport = None
    env.auth.outbox.enqueue(dedupe_key="smtp:1", template="registration_exists",
                            recipient="member@example.org", context={})
    assert env.auth.outbox.deliver_due()["sent"] == 1
    assert seen["host"] == "outbound.mail.gatech.edu" and seen["port"] == 587
    assert seen["tls"].verify_mode == ssl.CERT_REQUIRED
    assert seen["tls"].check_hostname is True


def gt_config(**kwargs):
    return MailConfig(mode="smtp", sender="CryoStack <cryostack@eas.gatech.edu>",
                      base_url="https://cryostack.test", smtp_host="outbound.mail.gatech.edu",
                      smtp_port=25, smtp_tls_policy="gt-relay-exception", **kwargs)


class GTTransport:
    def __init__(self, monkeypatch, *, reject_tls=False):
        self.messages = []
        self.tls_started = False
        harness = self

        class SMTP:
            def __init__(self, host, port, *, timeout):
                assert host == "outbound.mail.gatech.edu" and port == 25
                assert timeout > 0

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def starttls(self, *, context):
                assert context.check_hostname is False
                assert context.verify_mode == ssl.CERT_NONE
                if reject_tls:
                    raise smtplib.SMTPNotSupportedError("STARTTLS unavailable")
                harness.tls_started = True

            def send_message(self, message):
                assert harness.tls_started
                harness.messages.append(message)

        monkeypatch.setattr(mailer.smtplib, "SMTP", SMTP)

    def payloads(self):
        return [{"Subject": str(m["Subject"]), "To": str(m["To"]),
                 "TextBody": m.get_content()} for m in self.messages]


@pytest.mark.parametrize("change", [
    {"smtp_host": "mail.smtp2go.com"}, {"smtp_host": "outbound.mail.gatech.edu.evil.test"},
    {"smtp_port": 587}, {"smtp_security": "ssl"}, {"smtp_security": "none"},
    {"smtp_username": "user", "smtp_password_file": "/private/password"},
    {"smtp_password_file": "/private/password"}, {"smtp_tls_policy": "false"},
    {"smtp_tls_policy": ""},
])
def test_gt_exception_is_scoped_and_cannot_send_with_invalid_config(monkeypatch, change):
    cfg = replace(gt_config(), **change)
    assert cfg.problems()
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid exception must fail before connecting")
    monkeypatch.setattr(mailer.smtplib, "SMTP", forbidden)
    with pytest.raises(mailer.MailConfigError):
        mailer.Outbox(None, config=cfg)._send(EmailMessage())


def test_gt_exception_requires_explicit_configuration_and_is_visible():
    assert MailConfig.from_env({}).smtp_tls_policy == "verified"
    assert MailConfig.from_env({"CRYOSTACK_SMTP_TLS_POLICY": "gt-relay-exception"}).smtp_tls_policy == "gt-relay-exception"
    assert gt_config().public()["smtp_tls_policy"] == "gt-relay-exception"
    assert gt_config().problems() == []


def test_gt_missing_starttls_retries_without_plaintext_or_auth_changes(tmp_path, monkeypatch, caplog):
    env = Env(tmp_path)
    user = env.user("unverified", status="pending", verified=False)
    env.auth._send_verification(user)
    transport = GTTransport(monkeypatch, reject_tls=True)
    env.auth.outbox.config = gt_config()
    env.auth.outbox._transport = None
    with caplog.at_level(logging.INFO, logger="icesee_auth.mailer"):
        assert env.auth.outbox.deliver_due()["retry"] == 1
    assert transport.messages == []
    assert "gt-relay-exception" in caplog.text
    assert env.auth.approval.effective_status(user.id) == "pending"
    assert not env.auth.approval.status(user.id).email_verified


@pytest.mark.parametrize("cfg", [MailConfig(), MailConfig(mode="resend", sender="cryostack@example.org", base_url="https://cryostack.test")])
def test_signup_reports_unavailable_delivery_before_creating_account(tmp_path, cfg):
    env = Env(tmp_path)
    env.auth.outbox.config = cfg

    async def script(client):
        response = await _register(client)
        assert response.status == 503
        assert response.headers["Retry-After"] == "300"
        assert env.storage.get_user_by_email("new@example.org") is None
        assert env.outbox() == []
        return await response.text()

    html = env.run(script)
    assert "on its way" not in html and "sent a confirmation" not in html.lower()


def test_unavailable_resend_preserves_existing_verification_token(tmp_path):
    from icesee_auth import approval

    env = Env(tmp_path)
    user = env.user("waiting", status="pending", verified=False)
    env.auth._send_verification(user)
    token = env.token_from_outbox("verify_email")
    initial_rows = env.outbox()
    env.auth.outbox.config = MailConfig()

    async def script(client):
        response = await _post(client, "/auth/status/resend", env.session(user))
        assert response.status == 503
        assert response.headers["Retry-After"] == "300"

    env.run(script)
    assert env.outbox() == initial_rows
    assert env.auth.approval.peek_token(token, approval.VERIFY_EMAIL) == user.id
    assert not env.auth.approval.status(user.id).email_verified
    assert env.auth.approval.effective_status(user.id) == "pending"


@pytest.mark.parametrize("provider", ["resend", "postmark"])
def test_provider_must_return_a_success_receipt_before_row_is_sent(tmp_path, monkeypatch, provider):
    env = Env(tmp_path)
    http = HTTP(provider)

    def rejected(request, *, timeout):
        return Response(json.dumps({"ErrorCode": 422, "Message": "private@example.org secret-provider-key"}).encode())

    http.open = rejected
    use_provider(env, monkeypatch, config(tmp_path, provider), http)
    env.auth.outbox.enqueue(dedupe_key="bad-response", template="registration_exists",
                            recipient="member@example.org", context={})
    result = env.auth.outbox.deliver_due()
    assert result["sent"] == 0 and result["retry"] == 1
    row = env.outbox()[0]
    assert row["status"] == "queued" and row["sent_at"] is None
    assert "secret-provider-key" not in row["last_error"]
    assert "private@example.org" not in row["last_error"]


@pytest.mark.parametrize("template", ["verify_email", "password_reset"])
def test_recovered_provider_drops_superseded_and_expired_links(tmp_path, monkeypatch, template):
    from icesee_auth import approval

    env = Env(tmp_path)
    user = env.user("waiting", status="pending", verified=False)
    http = HTTP("resend")
    use_provider(env, monkeypatch, config(tmp_path, "resend"), http)
    tokens = []
    for number in range(2):
        token = env.auth.approval.issue_token(user_id=user.id, email=user.email, purpose=template)
        tokens.append(token)
        env.auth.outbox.enqueue(dedupe_key=f"{template}:{number}", template=template,
                                recipient=user.email, user_id=user.id,
                                context={"display_name": user.display_name, "token": token})
    result = env.auth.outbox.deliver_due()
    assert result["cancelled"] == 1 and result["sent"] == 1
    assert len(http.requests) == 1
    assert tokens[1] in http.payloads()[0]["text"] and tokens[0] not in http.payloads()[0]["text"]
    expired = env.auth.approval.issue_token(user_id=user.id, email=user.email, purpose=template)
    env.auth.outbox.enqueue(dedupe_key=f"{template}:expired", template=template,
                            recipient=user.email, user_id=user.id,
                            context={"display_name": user.display_name, "token": expired})
    env.clock.now += approval.TOKEN_TTL[template] + 1
    result = env.auth.outbox.deliver_due()
    assert result["cancelled"] == 1 and result["sent"] == 0
    assert len(http.requests) == 1
    assert all(json.loads(row["context_json"])["token"] == "[removed]" for row in env.outbox())
