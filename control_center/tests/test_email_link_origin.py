"""Email-link forms retain a usable browser Origin without leaking token URLs."""
from __future__ import annotations

from icesee_auth import approval
from icesee_auth.security import verify_password
from control_center.tests.test_registration_approval import Env, PASSWORD, _get, _post, _register


def test_verification_form_preserves_origin_and_refuses_cross_site_token_use(tmp_path):
    env = Env(tmp_path)

    async def script(client):
        assert (await _register(client)).status == 200
        user = env.storage.get_user_by_email("new@example.org")
        token = env.token_from_outbox("verify_email")
        response = await _get(client, f"/auth/verify-email?token={token}")
        assert response.status == 200
        # strict-origin sends only scheme/host/port, never the token query,
        # while allowing browsers to attach a same-origin form POST Origin.
        assert response.headers["Referrer-Policy"] == "strict-origin"
        assert not env.auth.approval.status(user.id).email_verified
        assert env.auth.approval.peek_token(token, approval.VERIFY_EMAIL) == user.id
        for origin in ("https://unrelated.example", "null"):
            denied = await _post(client, "/auth/verify-email", data={"token": token},
                                 headers={"Origin": origin})
            assert denied.status == 403
            assert not env.auth.approval.status(user.id).email_verified
            assert env.auth.approval.peek_token(token, approval.VERIFY_EMAIL) == user.id
        origin = str(client.make_url("/").origin())
        confirmed = await _post(client, "/auth/verify-email", data={"token": token},
                                headers={"Origin": origin, "Referer": origin + "/"})
        assert confirmed.status == 200
        assert env.auth.approval.status(user.id).email_verified
        assert env.auth.approval.effective_status(user.id) == "pending"
        replay = await _post(client, "/auth/verify-email", data={"token": token},
                             headers={"Origin": origin})
        assert replay.status == 400

    env.run(script)


def test_password_reset_form_preserves_origin_and_refuses_cross_site_token_use(tmp_path):
    env = Env(tmp_path)
    user = env.user("member")
    original_hash = user.password_hash
    token = env.auth.approval.issue_token(user_id=user.id, email=user.email,
                                          purpose=approval.PASSWORD_RESET)
    new_password = "isolated test replacement secret"
    data = {"token": token, "password": new_password, "confirm_password": new_password}

    async def script(client):
        response = await _get(client, f"/auth/reset?token={token}")
        assert response.status == 200
        assert response.headers["Referrer-Policy"] == "strict-origin"
        assert env.storage.get_user_by_id(user.id).password_hash == original_hash
        assert env.auth.approval.peek_token(token, approval.PASSWORD_RESET) == user.id
        for origin in ("https://unrelated.example", "null"):
            denied = await _post(client, "/auth/reset", data=data, headers={"Origin": origin})
            assert denied.status == 403
            assert env.storage.get_user_by_id(user.id).password_hash == original_hash
            assert env.auth.approval.peek_token(token, approval.PASSWORD_RESET) == user.id
        origin = str(client.make_url("/").origin())
        changed = await _post(client, "/auth/reset", data=data,
                              headers={"Origin": origin, "Referer": origin + "/"})
        assert changed.status == 200
        current = env.storage.get_user_by_id(user.id)
        assert verify_password(new_password, current.password_hash)
        assert not verify_password(PASSWORD, current.password_hash)
        assert env.auth.approval.peek_token(token, approval.PASSWORD_RESET) is None
        replay = await _post(client, "/auth/reset", data=data, headers={"Origin": origin})
        assert replay.status == 400

    env.run(script)
