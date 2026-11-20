"""Session and identity management for the CryoStack web application."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
import sqlite3
import sys
import time
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from html import escape as escape_html
from urllib.parse import quote, urlsplit

import base64
import hashlib
import secrets

from aiohttp import web

from . import access_log, approval
from .approval import ApprovalStore
from .mailer import MailConfig, Outbox
from .security import hash_password, safe_return_to, verify_password
from .storage import AuthStorage, SessionRecord, User

from .templates import (
    account_settings_page,
    auth_page,
    configuration_form_page,
    configurations_page,
    email_field,
    login_fields,
    new_password_fields,
    register_fields,
    experiments_page,
    experiment_detail_page,
)

from .providers import (
    GitHubProvider,
    GoogleProvider,
    GoogleTokenError,
    ORCIDProvider,
)

#: registrations allowed per client address per hour
REGISTER_ADDRESS_LIMIT = 10
#: verification / reset emails per address (and per client address) per hour
EMAIL_SEND_LIMIT = 3
EMAIL_SEND_ADDRESS_LIMIT = 20
HOUR = 3600.0
#: how often the gateway delivers queued email and provisions workspaces
BACKGROUND_INTERVAL_S = 15.0
#: how often a proxied websocket re-checks that its session may continue
LIVE_RECHECK_S = 30.0

#: paths an unapproved signed-in account may still use
_UNAPPROVED_ALLOWED_PREFIXES = ("/auth/", "/api/v1/me")

#: failed password sign-ins allowed per email within the window
LOGIN_FAILURE_LIMIT = 10
#: failed password sign-ins allowed per client address within the window
#: (higher than per email: one campus NAT address serves many people)
LOGIN_ADDRESS_FAILURE_LIMIT = 50
LOGIN_FAILURE_WINDOW_SECONDS = 15 * 60
_LIMITER_MAX_KEYS = 10_000

#: scrypt takes tens of milliseconds; it runs here, never on the event loop,
#: and at most this many at once, so a flood of sign-ins cannot stall the
#: gateway or take every core.
_PASSWORD_WORKERS = 2
_password_executor: concurrent.futures.ThreadPoolExecutor | None = None


def _password_pool() -> concurrent.futures.ThreadPoolExecutor:
    global _password_executor
    if _password_executor is None:
        _password_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=_PASSWORD_WORKERS, thread_name_prefix="password",
        )
    return _password_executor


async def _off_loop(function, *args):
    return await asyncio.get_running_loop().run_in_executor(_password_pool(), function, *args)


_LOOPBACK = {"127.0.0.1", "::1"}


def client_address(request: web.Request) -> str:
    """The sign-in client's address.

    Behind nginx every request arrives from loopback and nginx overwrites
    X-Real-IP with the real peer, so that header is trusted only on loopback
    connections; any other peer is used as-is.
    """
    remote = request.remote or ""
    if remote in _LOOPBACK:
        forwarded = request.headers.get("X-Real-IP", "").strip()
        if forwarded:
            return forwarded
    return remote or "unknown"


class LoginRateLimiter:
    """In-memory throttle for password sign-in failures, keyed by email.

    Keyed by the submitted address whether or not an account exists, so the
    throttle itself does not reveal which addresses are registered.
    """

    def __init__(
        self,
        *,
        limit: int = LOGIN_FAILURE_LIMIT,
        window_seconds: float = LOGIN_FAILURE_WINDOW_SECONDS,
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._failures: dict[str, list[float]] = {}

    def _recent(self, key: str, now: float) -> list[float]:
        cutoff = now - self.window_seconds
        recent = [t for t in self._failures.get(key, ()) if t > cutoff]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)
        return recent

    def blocked(self, key: str, now: float) -> bool:
        return len(self._recent(key, now)) >= self.limit

    def failed(self, key: str, now: float) -> None:
        if len(self._failures) >= _LIMITER_MAX_KEYS:
            for stale in list(self._failures):
                self._recent(stale, now)
            if len(self._failures) >= _LIMITER_MAX_KEYS:
                self._failures.pop(next(iter(self._failures)))
        recent = self._recent(key, now)
        recent.append(now)
        self._failures[key] = recent

    def succeeded(self, key: str) -> None:
        self._failures.pop(key, None)


_DUMMY_PASSWORD_HASH: str | None = None


def _dummy_password_hash() -> str:
    """A real scrypt hash, so unknown-account sign-ins cost the same time."""
    global _DUMMY_PASSWORD_HASH
    if _DUMMY_PASSWORD_HASH is None:
        _DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(24))
    return _DUMMY_PASSWORD_HASH


#: OAuth callback HTTP status -> failure category
_OAUTH_FAILURE_CATEGORY = {
    400: "invalid_request",
    409: "identity_conflict",
    500: "internal_error",
    502: "provider_error",
    503: "provider_not_configured",
}


class AuthManager:
    """Manage CryoStack users, sessions, and authentication routes."""

    def __init__(
        self,
        *,
        database_path: Path | None = None,
        cookie_name: str = "icesee_session",
        session_ttl_seconds: int = 12 * 60 * 60,
        secure_cookies: bool | None = None,
        clock: Callable[[], float] = time.time,
        approval_required: bool | None = None,
        mail_config: MailConfig | None = None,
        mail_transport=None,
        workspace_provisioner=None,
        google_provider: GoogleProvider | None = None,
        background_interval_s: float = BACKGROUND_INTERVAL_S,
    ) -> None:
        if session_ttl_seconds <= 0:
            raise ValueError("session_ttl_seconds must be positive")

        from cryostack_src.storage_layout import default_path

        default_database = default_path("auth", (
            Path(__file__).resolve().parent.parent
            / "var"
            / "cryostack_auth.db"
        ))

        self._storage = AuthStorage(
            database_path
            or Path(
                os.environ.get(
                    "CRYOSTACK_AUTH_DATABASE",
                    default_database,
                )
            )
        )
        self._cookie_name = cookie_name
        self._session_ttl_seconds = session_ttl_seconds
        self._secure_cookies = secure_cookies
        self._clock = clock
        self._login_limiter = LoginRateLimiter()
        self._address_limiter = LoginRateLimiter(limit=LOGIN_ADDRESS_FAILURE_LIMIT)
        self._register_limiter = LoginRateLimiter(
            limit=REGISTER_ADDRESS_LIMIT, window_seconds=HOUR)
        self._email_send_limiter = LoginRateLimiter(
            limit=EMAIL_SEND_LIMIT, window_seconds=HOUR)
        self._email_address_limiter = LoginRateLimiter(
            limit=EMAIL_SEND_ADDRESS_LIMIT, window_seconds=HOUR)

        self._approval_required = (
            approval.approval_required_from_env()
            if approval_required is None
            else bool(approval_required)
        )
        self._approval = ApprovalStore(self._storage, clock=clock)
        self._outbox = Outbox(
            self._storage,
            config=mail_config,
            clock=clock,
            transport=mail_transport,
        )
        self._workspace_provisioner = workspace_provisioner
        self._background_interval_s = background_interval_s
        self._background_task: asyncio.Task | None = None
        #: user id -> close callbacks of that account's live proxied sockets
        self._live_connections: dict[str, set] = {}
        self._google_provider = google_provider or GoogleProvider.from_env(os.environ)
        self._github_provider = GitHubProvider(
            client_id=os.environ.get(
                "CRYOSTACK_GITHUB_CLIENT_ID",
                "",
            ),

            client_secret=os.environ.get(
                "CRYOSTACK_GITHUB_CLIENT_SECRET",
                "",
            ),

            redirect_uri=os.environ.get(
                "CRYOSTACK_GITHUB_REDIRECT_URI",
                "",
            ),
        )

        self._orcid_provider = ORCIDProvider(
            client_id=os.environ.get(
                "CRYOSTACK_ORCID_CLIENT_ID",
                "",
            ),

            client_secret=os.environ.get(
                "CRYOSTACK_ORCID_CLIENT_SECRET",
                "",
            ),

            redirect_uri=os.environ.get(
                "CRYOSTACK_ORCID_REDIRECT_URI",
                "",
            ),

            base_url=os.environ.get(
                "CRYOSTACK_ORCID_BASE_URL",
                "https://orcid.org",
            ),
        )

    @property
    def storage(self) -> AuthStorage:
        return self._storage

    @property
    def approval(self) -> ApprovalStore:
        return self._approval

    @property
    def outbox(self) -> Outbox:
        return self._outbox

    @property
    def approval_required(self) -> bool:
        return self._approval_required

    def check_approval_cutover(self) -> None:
        """Refuse to run the gate over accounts nobody has reviewed.

        With the gate on, an account without a status row is pending. If
        the baseline migration has never run and such accounts exist, every
        current user would be locked out, so the gateway does not start. An
        empty database is baselined automatically: there is no one to lock
        out. After a baseline, accounts created later without a status (for
        example while the gate was off again) stay pending and are reported.
        """
        if not self._approval_required:
            return
        counts = self._approval.counts()
        unreviewed = counts["no_record"]
        if self._approval.baseline() is not None:
            if unreviewed:
                print(f"[auth] {unreviewed} account(s) have no approval status and "
                      "are treated as pending; review them in Control Center.",
                      file=sys.stderr, flush=True)
            return
        if not unreviewed:
            if not any(counts[status] for status in approval.STATUSES):
                self._approval.record_baseline(
                    operator="automatic",
                    reason="New database with no accounts at cutover",
                )
            return
        raise RuntimeError(
            "CRYOSTACK_REGISTRATION_APPROVAL is on but the existing accounts "
            "have not been baselined. Run deployment/auth_db_migrate.py "
            "approval-baseline (see the operator guide) or turn the gate off."
        )

    def install(self, app: web.Application) -> None:
        self.check_approval_cutover()
        app.middlewares.append(self._approval_middleware)
        app.on_startup.append(self._start_background)
        app.on_cleanup.append(self._stop_background)

        app.router.add_get("/api/v1/me", self._handle_me)

        app.router.add_get("/auth/status", self._status_page)
        app.router.add_post("/auth/status/resend", self._resend_verification)
        app.router.add_get("/auth/verify-email", self._verify_email_page)
        app.router.add_post("/auth/verify-email", self._verify_email_submit)
        app.router.add_get("/auth/forgot", self._forgot_page)
        app.router.add_post("/auth/forgot", self._forgot_submit)
        app.router.add_get("/auth/reset", self._reset_page)
        app.router.add_post("/auth/reset", self._reset_submit)

        app.router.add_get("/auth/google", self._google_begin)
        app.router.add_get(
            "/auth/google/callback",
            self._oauth_callback_logged(self._google_callback, "google"),
        )

        app.router.add_get("/auth/login", self._login_page)
        app.router.add_post("/auth/login", self._login_submit)

        app.router.add_get("/auth/register", self._register_page)
        app.router.add_post("/auth/register", self._register_submit)

        app.router.add_post("/auth/logout", self._logout)

        app.router.add_get("/account", self._account_redirect)
        app.router.add_get("/account/", self._account_page)
        app.router.add_post("/account/", self._account_update)

        app.router.add_get(
            "/configurations",
            self._configurations_redirect,
        )

        app.router.add_get(
            "/configurations/",
            self._configurations_page,
        )

        app.router.add_get(
            "/configurations/new",
            self._configuration_new_page,
        )

        app.router.add_post(
            "/configurations/new",
            self._configuration_create,
        )

        app.router.add_get(
            "/configurations/{configuration_id}/edit",
            self._configuration_edit_page,
        )

        app.router.add_post(
            "/configurations/{configuration_id}/edit",
            self._configuration_update,
        )

        app.router.add_post(
            "/configurations/{configuration_id}/delete",
            self._configuration_delete,
        )

        app.router.add_get(
            "/api/v1/experiments",
            self._api_list_experiments,
        )

        app.router.add_post(
            "/api/v1/experiments",
            self._api_create_experiment,
        )

        app.router.add_get(
            "/api/v1/experiments/{experiment_id}",
            self._api_get_experiment,
        )

        app.router.add_patch(
            "/api/v1/experiments/{experiment_id}",
            self._api_update_experiment,
        )

        app.router.add_delete(
            "/api/v1/experiments/{experiment_id}",
            self._api_delete_experiment,
        )

        app.router.add_get(
            "/experiments",
            self._experiments_redirect,
        )

        app.router.add_get(
            "/experiments/",
            self._experiments_page,
        )

        app.router.add_get(
            "/experiments/{experiment_id}",
            self._experiment_detail_page,
        )

        app.router.add_post(
            "/experiments/{experiment_id}/delete",
            self._experiment_delete,
        )

        app.router.add_get(
            "/api/v1/workspaces/{application}",
            self._api_get_workspace,
        )

        app.router.add_put(
            "/api/v1/workspaces/{application}",
            self._api_save_workspace,
        )

        app.router.add_patch(
            "/api/v1/experiments/job/{job_id}",
            self._api_update_experiment_by_job,
        )

        app.router.add_get(
            "/auth/github",
            self._github_begin,
        )

        app.router.add_get(
            "/auth/github/callback",
            self._oauth_callback_logged(
                self._github_callback,
                "github",
            ),
        )

        app.router.add_get(
            "/auth/orcid",
            self._orcid_begin,
        )

        app.router.add_get(
            "/auth/orcid/callback",
            self._oauth_callback_logged(
                self._orcid_callback,
                "orcid",
            ),
        )


    @staticmethod
    def _pkce_verifier() -> str:
        return secrets.token_urlsafe(64)


    @staticmethod
    def _pkce_challenge(verifier: str) -> str:
        digest = hashlib.sha256(
            verifier.encode("ascii")
        ).digest()

        return (
            base64.urlsafe_b64encode(digest)
            .rstrip(b"=")
            .decode("ascii")
        )

    async def _orcid_begin(
        self,
        request: web.Request,
    ) -> web.StreamResponse:

        provider = self._orcid_provider

        if not provider.configured:
            raise web.HTTPServiceUnavailable(
                text=(
                    "ORCID authentication is not "
                    "configured on this server."
                )
            )

        return_to = safe_return_to(
            request.query.get("return_to")
        )

        session = self._get_or_create_session(
            request
        )

        state = secrets.token_urlsafe(32)

        # OAuthFlow currently requires code_verifier.
        # ORCID itself does not need it, so use a harmless
        # random transaction value rather than weakening the
        # database schema yet.
        verifier = self._pkce_verifier()

        self._storage.create_oauth_flow(
            state=state,
            session_id=session.id,
            provider=provider.name,
            code_verifier=verifier,
            return_to=return_to,
            ttl_seconds=600,
            now=self._clock(),
        )

        authorization_url = (
            provider.authorization_url(
                state=state,
                code_challenge=None,
            )
        )

        response = web.HTTPFound(
            authorization_url
        )

        self._set_session_cookie(
            request,
            response,
            session.id,
        )

        raise response

    async def _orcid_callback(
        self,
        request: web.Request,
    ) -> web.StreamResponse:

        provider = self._orcid_provider

        if not provider.configured:
            raise web.HTTPServiceUnavailable(
                text=(
                    "ORCID authentication is not "
                    "configured on this server."
                )
            )

        error = request.query.get("error")

        if error:
            raise web.HTTPBadRequest(
                text=(
                    "ORCID authorization was "
                    "not completed."
                )
            )

        code = str(
            request.query.get("code", "")
        ).strip()

        state = str(
            request.query.get("state", "")
        ).strip()

        if not code or not state:
            raise web.HTTPBadRequest(
                text="Missing ORCID OAuth response."
            )

        flow = self._storage.consume_oauth_flow(
            state=state,
            provider=provider.name,
            now=self._clock(),
        )

        if flow is None:
            raise web.HTTPBadRequest(
                text=(
                    "The ORCID authentication "
                    "request is invalid or expired."
                )
            )

        browser_session_id = request.cookies.get(
            self._cookie_name
        )

        if browser_session_id != flow.session_id:
            raise web.HTTPBadRequest(
                text=(
                    "ORCID authentication session "
                    "does not match."
                )
            )

        try:
            authentication = (
                await provider.exchange_code(
                    code=code,
                    code_verifier=None,
                )
            )

            identity = (
                await provider.fetch_identity(
                    authentication
                )
            )

        except RuntimeError as error:
            raise web.HTTPBadGateway(
                text=str(error)
            )

        stored_identity = (
            self._storage.get_user_identity(
                provider=identity.provider,
                provider_subject=identity.subject,
            )
        )

        current_user = self.current_user(
            request
        )

        # --------------------------------------------------------
        # Existing ORCID identity:
        # allow it to authenticate the linked CryoStack account.
        # --------------------------------------------------------

        if stored_identity is not None:
            user = self._storage.get_user_by_id(
                stored_identity.user_id
            )

            if user is None:
                raise web.HTTPInternalServerError(
                    text=(
                        "ORCID identity references "
                        "a missing CryoStack account."
                    )
                )

        else:
            # ----------------------------------------------------
            # New ORCID identity must be linked from an already
            # authenticated CryoStack account.
            # ----------------------------------------------------

            if current_user is None:
                raise web.HTTPConflict(
                    text=(
                        "This ORCID iD is not yet linked "
                        "to a CryoStack account. Sign in "
                        "to CryoStack first, then connect "
                        "ORCID from Account Settings."
                    )
                )

            try:
                self._storage.create_user_identity(
                    user_id=current_user.id,
                    provider=identity.provider,
                    provider_subject=identity.subject,
                    provider_username=identity.username,
                    provider_email=None,
                    provider_profile_url=(
                        identity.profile_url
                    ),
                    now=self._clock(),
                )

            except sqlite3.IntegrityError:
                raise web.HTTPConflict(
                    text=(
                        "This ORCID iD is already "
                        "linked to another CryoStack "
                        "account."
                    )
                )

            user = current_user

        authenticated = self._start_authenticated_session(
            flow.session_id,
            user_id=user.id,
        )
        request["cryostack_login_user_id"] = user.id

        if authenticated is None:
            raise web.HTTPInternalServerError(
                text="Unable to update the session."
            )

        response = web.HTTPFound(
            self._after_sign_in(
                user,
                safe_return_to(
                    flow.return_to
                ),
            )
        )

        self._set_session_cookie(
            request,
            response,
            authenticated.id,
        )

        raise response

    async def _github_begin(
        self,
        request: web.Request,
    ) -> web.StreamResponse:

        provider = self._github_provider

        if not provider.configured:
            raise web.HTTPServiceUnavailable(
                text=(
                    "GitHub authentication is not "
                    "configured on this server."
                )
            )

        return_to = safe_return_to(
            request.query.get("return_to")
        )

        session = self._get_or_create_session(
            request
        )

        state = secrets.token_urlsafe(32)

        verifier = self._pkce_verifier()

        challenge = self._pkce_challenge(
            verifier
        )

        self._storage.create_oauth_flow(
            state=state,
            session_id=session.id,
            provider=provider.name,
            code_verifier=verifier,
            return_to=return_to,
            ttl_seconds=600,
            now=self._clock(),
        )

        authorization_url = (
            provider.authorization_url(
                state=state,
                code_challenge=challenge,
            )
        )

        response = web.HTTPFound(
            authorization_url
        )

        self._set_session_cookie(
            request,
            response,
            session.id,
        )

        raise response

    async def _github_callback(
        self,
        request: web.Request,
        ) -> web.StreamResponse:

        provider = self._github_provider

        # ========================================================
        # Provider configuration
        # ========================================================

        if not provider.configured:
            raise web.HTTPServiceUnavailable(
                text=(
                    "GitHub authentication is not "
                    "configured on this server."
                )
            )

        # ========================================================
        # GitHub callback error
        # ========================================================

        error = request.query.get("error")

        if error:
            raise web.HTTPBadRequest(
                text=(
                    "GitHub authorization was "
                    "not completed."
                )
            )

        # ========================================================
        # Authorization response
        # ========================================================

        code = str(
            request.query.get(
                "code",
                "",
            )
        ).strip()

        state = str(
            request.query.get(
                "state",
                "",
            )
        ).strip()

        if not code or not state:
            raise web.HTTPBadRequest(
                text=(
                    "Missing GitHub OAuth response."
                )
            )

        # ========================================================
        # Consume one-time OAuth transaction
        # ========================================================

        flow = self._storage.consume_oauth_flow(
            state=state,
            provider=provider.name,
            now=self._clock(),
        )

        if flow is None:
            raise web.HTTPBadRequest(
                text=(
                    "The GitHub authentication "
                    "request is invalid or expired."
                )
            )

        # ========================================================
        # Browser/session binding
        # ========================================================

        browser_session_id = request.cookies.get(
            self._cookie_name
        )

        if browser_session_id != flow.session_id:

            raise web.HTTPBadRequest(
                text=(
                    "GitHub authentication session "
                    "does not match."
                )
            )

        # ========================================================
        # Exchange code
        # ========================================================

        try:
            authentication = await provider.exchange_code(
                code=code,
                code_verifier=flow.code_verifier,
            )

            identity = await provider.fetch_identity(
                authentication
            )

        except RuntimeError as error:

            raise web.HTTPBadGateway(
                text=str(error)
            )

        # ========================================================
        # Existing provider identity?
        # ========================================================

        stored_identity = (
            self._storage.get_user_identity(
                provider=identity.provider,
                provider_subject=(
                    identity.subject
                ),
            )
        )

        user = None

        if stored_identity is not None:

            user = self._storage.get_user_by_id(
                stored_identity.user_id
            )

            if user is None:

                raise web.HTTPInternalServerError(
                    text=(
                        "GitHub identity references "
                        "a missing CryoStack account."
                    )
                )

        else:

            # ====================================================
            # User already signed into CryoStack?
            #
            # If yes, this operation links GitHub.
            # ====================================================

            user = self.current_user(
                request
            )

            if user is not None:

                try:
                    self._storage.create_user_identity(
                        user_id=user.id,

                        provider=(
                            identity.provider
                        ),

                        provider_subject=(
                            identity.subject
                        ),

                        provider_username=(
                            identity.username
                        ),

                        provider_email=(
                            identity.email
                        ),

                        provider_profile_url=(
                            identity.profile_url
                        ),

                        now=self._clock(),
                    )

                except sqlite3.IntegrityError:

                    raise web.HTTPConflict(
                        text=(
                            "This GitHub account is "
                            "already linked to another "
                            "CryoStack account."
                        )
                    )

            else:

                # =================================================
                # New GitHub-based CryoStack account
                # =================================================

                if not identity.email:

                    raise web.HTTPBadRequest(
                        text=(
                            "CryoStack could not obtain "
                            "a verified email address "
                            "from GitHub."
                        )
                    )

                existing_user = (
                    self._storage.get_user_by_email(
                        identity.email
                    )
                )

                # =================================================
                # SECURITY:
                #
                # Never automatically link external identities
                # only because email strings match.
                # =================================================

                if existing_user is not None:

                    raise web.HTTPConflict(
                        text=(
                            "A CryoStack account already "
                            "uses this email address. "
                            "Sign in with your existing "
                            "CryoStack account first, "
                            "then connect GitHub from "
                            "your account."
                        )
                    )

                display_name = (
                    identity.display_name
                    or identity.username
                    or identity.email.split(
                        "@",
                        1,
                    )[0]
                )

                # =================================================
                # Existing users table currently requires a
                # password_hash.
                #
                # Generate an unknown high-entropy password for
                # OAuth-only accounts.
                #
                # We can migrate password_hash to nullable later.
                # =================================================

                unusable_password = (
                    secrets.token_urlsafe(64)
                )

                try:

                    user = self._storage.create_user(
                        email=identity.email,

                        display_name=(
                            display_name
                        ),

                        institution=None,

                        password_hash=hash_password(
                            unusable_password
                        ),

                        now=self._clock(),
                    )

                    self._storage.create_user_identity(
                        user_id=user.id,

                        provider=(
                            identity.provider
                        ),

                        provider_subject=(
                            identity.subject
                        ),

                        provider_username=(
                            identity.username
                        ),

                        provider_email=(
                            identity.email
                        ),

                        provider_profile_url=(
                            identity.profile_url
                        ),

                        now=self._clock(),
                    )

                except sqlite3.IntegrityError:

                    raise web.HTTPConflict(
                        text=(
                            "Unable to create the "
                            "CryoStack account because "
                            "the identity is already "
                            "registered."
                        )
                    )

                if self._approval_required:
                    # GitHub reported this address as verified
                    self._record_registration(
                        user,
                        method="github",
                        email_verified=True,
                    )

        # ========================================================
        # Sanity check
        # ========================================================

        if user is None:

            raise web.HTTPInternalServerError(
                text=(
                    "Unable to resolve CryoStack user "
                    "after GitHub authentication."
                )
            )

        # ========================================================
        # Authenticate existing browser session
        # ========================================================

        authenticated = self._start_authenticated_session(
            flow.session_id,
            user_id=user.id,
        )
        request["cryostack_login_user_id"] = user.id

        if authenticated is None:

            raise web.HTTPInternalServerError(
                text=(
                    "Unable to update the session."
                )
            )

        # ========================================================
        # Return user to original application
        # ========================================================

        response = web.HTTPFound(
            self._after_sign_in(
                user,
                safe_return_to(
                    flow.return_to
                ),
            )
        )

        self._set_session_cookie(
            request,
            response,
            authenticated.id,
        )

        raise response

    # ============================================================
    # Administrator approval
    # ============================================================

    def _redirect_unapproved(self, request: web.Request) -> None:
        """Send a signed-in but unapproved account to its status page."""
        user = self.session_user(request)
        if user is None or self.user_is_active(user.id):
            return
        raise web.HTTPFound(
            "/auth/status?return_to=" + quote(safe_return_to(request.path_qs), safe="")
        )

    def _after_sign_in(self, user: User, return_to: str) -> str:
        if self.user_is_active(user.id):
            return return_to
        return "/auth/status?return_to=" + quote(return_to, safe="")

    @web.middleware
    async def _approval_middleware(self, request: web.Request, handler):
        """Refuse protected APIs to unapproved accounts with a clear 403.

        Defence in depth: those handlers already see such an account as
        signed out, because ``current_user`` returns ``None`` for it.
        """
        if (
            request.path.startswith("/api/")
            and not request.path.startswith(_UNAPPROVED_ALLOWED_PREFIXES)
            and request.cookies.get(self._cookie_name)
        ):
            user = self.session_user(request)
            if user is not None and not self.user_is_active(user.id):
                status = self._approval.effective_status(user.id)
                response = web.json_response(
                    {
                        "error": "account_not_approved",
                        "account_status": status,
                        "status_url": "/auth/status",
                    },
                    status=403,
                )
                self._prepare_no_cache(response)
                return response
        return await handler(request)

    def _require_same_origin(self, request: web.Request) -> None:
        origin = request.headers.get("Origin")
        if origin is not None and urlsplit(origin).netloc != request.host:
            raise web.HTTPForbidden(text="Cross-site request refused.")

    def _record_registration(self, user: User, *, method: str,
                             email_verified: bool) -> None:
        self._approval.register(
            user_id=user.id,
            method=method,
            email_verified=email_verified,
        )
        if email_verified:
            self._queue_review_notices(user, method=method)

    def _queue_review_notices(self, user: User, *, method: str) -> None:
        """Tell reviewers and the applicant; each notice is sent once."""
        self._outbox.notify_reviewers(user=user, method=method)
        self._outbox.enqueue(
            dedupe_key=f"applicant_pending:{user.id}",
            template="applicant_pending",
            recipient=user.email,
            user_id=user.id,
            context={"display_name": user.display_name},
        )

    def notify_decision(self, user: User, *, status: str, audit_id: str) -> None:
        """Queue the applicant's decision email (one per decision)."""
        if status not in (approval.APPROVED, approval.REJECTED, approval.SUSPENDED):
            return
        self._outbox.enqueue(
            dedupe_key=f"decision:{user.id}:{audit_id}",
            template="decision",
            recipient=user.email,
            user_id=user.id,
            context={"display_name": user.display_name, "status": status},
        )

    def _send_verification(self, user: User) -> None:
        token = self._approval.issue_token(
            user_id=user.id, email=user.email, purpose=approval.VERIFY_EMAIL)
        self._outbox.enqueue(
            dedupe_key=f"verify_email:{approval.hash_token(token)}",
            template="verify_email",
            recipient=user.email,
            user_id=user.id,
            context={"display_name": user.display_name, "token": token},
        )

    def _email_throttled(self, request: web.Request, email: str) -> bool:
        """Count one verification/reset email; ``True`` when over the limit."""
        now = self._clock()
        email_key = "email:" + email
        address_key = "address:" + client_address(request)
        if (
            self._email_send_limiter.blocked(email_key, now)
            or self._email_address_limiter.blocked(address_key, now)
        ):
            self._record_access(
                event_type=access_log.LOGIN_RATE_LIMITED,
                outcome="denied",
                category="rate_limited",
                provider="email",
            )
            return True
        self._email_send_limiter.failed(email_key, now)
        self._email_address_limiter.failed(address_key, now)
        return False

    def _card(self, *, title: str, subtitle: str, body_html: str = "",
              notice: str | None = None, error: str | None = None,
              status: int = 200, return_to: str = "/") -> web.Response:
        response = web.Response(
            text=auth_page(
                title=title,
                subtitle=subtitle,
                form_action=None,
                return_to=return_to,
                fields="",
                submit_label="",
                alternate_text="",
                alternate_href="",
                alternate_label="",
                notice=notice,
                error=error,
                body_html=f'<div class="auth-body">{body_html}</div>',
            ),
            content_type="text/html",
            status=status,
        )
        self._prepare_no_cache(response)
        return response

    @staticmethod
    def _sign_out_form() -> str:
        return (
            '<form method="post" action="/auth/logout">'
            '<button class="submit secondary" type="submit">Sign out</button>'
            "</form>"
        )

    def _registration_mail_unavailable(self) -> web.Response | None:
        config = self._outbox.config
        if config.delivers and not config.problems():
            return None
        response = self._card(
            title="Registration email is temporarily unavailable",
            subtitle="Please try again after email delivery has been restored.",
            body_html=(
                "<p>We cannot send a confirmation email right now. "
                "Your account must have a confirmed email address and "
                "administrator approval before you can use CryoStack.</p>"
                '<p><a href="/auth/login">Sign in to an existing account</a>.</p>'
            ),
            status=503,
        )
        response.headers["Retry-After"] = "300"
        return response

    async def _register_for_review(
        self,
        request: web.Request,
        *,
        session: SessionRecord,
        display_name: str,
        email: str,
        institution: str,
        password: str,
        return_to: str,
    ) -> web.Response:
        """Gated registration: pending account, verification email, no session.

        The answer is the same whether or not the address already has an
        account, so the page cannot be used to find registered addresses;
        the owner of an existing address gets an email instead.
        """
        unavailable = self._registration_mail_unavailable()
        if unavailable is not None:
            return unavailable
        now = self._clock()
        address_key = "address:" + client_address(request)
        if self._register_limiter.blocked(address_key, now):
            self._record_access(
                event_type=access_log.LOGIN_RATE_LIMITED,
                outcome="denied",
                category="rate_limited",
                provider="password",
            )
            response = web.Response(
                text=self._render_register(
                    return_to=return_to,
                    display_name=display_name,
                    email=email,
                    institution=institution,
                    error=(
                        "Too many registrations from this network. "
                        "Wait an hour and try again."
                    ),
                ),
                content_type="text/html",
                status=429,
            )
            self._prepare_no_cache(response)
            self._set_session_cookie(request, response, session.id)
            return response
        self._register_limiter.failed(address_key, now)

        password_hash = await _off_loop(hash_password, password)
        existing = self._storage.get_user_by_email(email)
        if existing is None:
            try:
                user = self._storage.create_user(
                    email=email,
                    display_name=display_name,
                    institution=institution or None,
                    password_hash=password_hash,
                    now=now,
                )
            except sqlite3.IntegrityError:
                user = None
            if user is not None:
                self._record_registration(user, method="password", email_verified=False)
                self._send_verification(user)
        else:
            day = int(now // 86400)
            self._outbox.enqueue(
                dedupe_key=f"registration_exists:{existing.id}:{day}",
                template="registration_exists",
                recipient=existing.email,
                user_id=existing.id,
                context={},
            )
            self._record_access(
                event_type=access_log.REGISTER,
                outcome="failure",
                category="registration_conflict",
                user_id=existing.id,
                provider="password",
            )

        return self._card(
            title="Check your email",
            subtitle="One more step before an administrator can review your registration.",
            notice=(
                f"If {email} can receive email, a confirmation email has been "
                "queued for delivery. Check your inbox and spam or junk folder. "
                "The link expires in 3 days. "
                "If it does not arrive, sign in and request another link."
            ),
            body_html=(
                "<p>After you confirm your address, a CryoStack administrator "
                "reviews the registration. You will receive an email with the "
                "decision; until then applications, storage and computing are "
                "not available.</p>"
                '<p>Already have an account? <a href="/auth/login">Sign in</a>.</p>'
            ),
            return_to=return_to,
        )

    async def _status_page(self, request: web.Request) -> web.Response:
        return_to = safe_return_to(request.query.get("return_to"))
        user = self.session_user(request)
        if user is None:
            raise web.HTTPFound(
                "/auth/login?return_to=" + quote(return_to, safe=""))
        if self.user_is_active(user.id):
            raise web.HTTPFound(return_to)

        record = self._approval.status(user.id)
        status = record.status if record is not None else approval.PENDING
        sign_out = self._sign_out_form()
        email = escape_html(user.email)

        if status == approval.PENDING and record is not None and not record.email_verified:
            sent = request.query.get("sent") == "1"
            return self._card(
                title="Confirm your email",
                subtitle="Your registration is not complete yet.",
                notice=(
                    "A new confirmation email has been queued for delivery." if sent else None
                ),
                body_html=(
                    f"<p>A confirmation email was queued for <strong>{email}</strong>. "
                    "Check your inbox and spam or junk folder. "
                    "Open the email to finish registering; an administrator can review "
                    "your account only after that.</p>"
                    '<form method="post" action="/auth/status/resend">'
                    '<button class="submit" type="submit">Send the link again</button>'
                    "</form>"
                    f"{sign_out}"
                ),
            )
        if status == approval.PENDING:
            return self._card(
                title="Awaiting approval",
                subtitle="Your registration is waiting for an administrator.",
                notice=f"Signed in as {user.email}.",
                body_html=(
                    "<p>A CryoStack administrator reviews every new account. "
                    "You will receive an email when yours is decided; you do "
                    "not need to do anything else.</p>"
                    "<p>Until then applications, file storage, computing and "
                    "the Connector are not available to this account.</p>"
                    f"{sign_out}"
                ),
            )
        if status == approval.REJECTED:
            return self._card(
                title="Registration not approved",
                subtitle="This CryoStack account was not approved.",
                body_html=(
                    "<p>If you think this is a mistake, contact the person who "
                    "invited you to CryoStack.</p>"
                    f"{sign_out}"
                ),
                status=403,
            )
        return self._card(
            title="Account suspended",
            subtitle="Access to CryoStack is suspended for this account.",
            body_html=(
                "<p>Your files are kept. Contact the CryoStack organizers if "
                "you have questions.</p>"
                f"{sign_out}"
            ),
            status=403,
        )

    async def _resend_verification(self, request: web.Request) -> web.StreamResponse:
        self._require_same_origin(request)
        user = self.session_user(request)
        if user is None:
            raise web.HTTPSeeOther("/auth/login")
        unavailable = self._registration_mail_unavailable()
        if unavailable is not None:
            return unavailable
        record = self._approval.status(user.id)
        if (
            record is not None
            and record.status == approval.PENDING
            and not record.email_verified
            and not self._email_throttled(request, user.email)
        ):
            self._send_verification(user)
        raise web.HTTPSeeOther("/auth/status?sent=1")

    def _invalid_link(self, what: str) -> web.Response:
        return self._card(
            title="This link does not work",
            subtitle=f"The {what} link is invalid, already used or expired.",
            body_html=(
                '<p><a href="/auth/login">Sign in</a> to request a new one.</p>'
            ),
            status=400,
        )

    async def _verify_email_page(self, request: web.Request) -> web.Response:
        # A GET never changes anything: mail scanners open links too.
        token = str(request.query.get("token", ""))
        if self._approval.peek_token(token, approval.VERIFY_EMAIL) is None:
            return self._invalid_link("confirmation")
        response = self._card(
            title="Confirm your email",
            subtitle="Confirm this address for your CryoStack registration.",
            body_html=(
                '<form method="post" action="/auth/verify-email">'
                f'<input type="hidden" name="token" value="{escape_html(token)}">'
                '<button class="submit" type="submit">Confirm my email</button>'
                "</form>"
            ),
        )
        # Keep token URLs out of Referer while retaining a real Origin on the
        # native confirmation POST; no-referrer makes that Origin null.
        response.headers["Referrer-Policy"] = "strict-origin"
        return response

    async def _verify_email_submit(self, request: web.Request) -> web.Response:
        self._require_same_origin(request)
        form = await request.post()
        token = str(form.get("token", ""))
        user_id = self._approval.consume_token(token, approval.VERIFY_EMAIL)
        user = self._storage.get_user_by_id(user_id) if user_id else None
        if user is None:
            return self._invalid_link("confirmation")
        if self._approval.mark_email_verified(user.id):
            self._record_access(
                event_type=access_log.EMAIL_VERIFIED,
                outcome="success",
                user_id=user.id,
                provider="password",
            )
            record = self._approval.status(user.id)
            self._queue_review_notices(
                user, method=record.registration_method if record else "password")
        return self._card(
            title="Email confirmed",
            subtitle="Thank you. Your registration is now waiting for review.",
            body_html=(
                "<p>You will receive an email when an administrator has "
                "decided. You can sign in at any time to see your status.</p>"
                '<p><a href="/auth/status">Check your status</a></p>'
            ),
        )

    async def _forgot_page(self, request: web.Request) -> web.Response:
        response = web.Response(
            text=auth_page(
                title="Reset your password",
                subtitle="We will email you a link to choose a new password.",
                form_action="/auth/forgot",
                return_to="/",
                fields=email_field(),
                submit_label="Send reset link",
                alternate_text="Remembered it?",
                alternate_href="/auth/login",
                alternate_label="Sign in",
            ),
            content_type="text/html",
        )
        self._prepare_no_cache(response)
        return response

    async def _forgot_submit(self, request: web.Request) -> web.Response:
        self._require_same_origin(request)
        form = await request.post()
        email = str(form.get("email", "")).strip().lower()[:254]
        if "@" in email and not self._email_throttled(request, email):
            user = self._storage.get_user_by_email(email)
            if user is not None:
                token = self._approval.issue_token(
                    user_id=user.id, email=user.email, purpose=approval.PASSWORD_RESET)
                self._outbox.enqueue(
                    dedupe_key=f"password_reset:{approval.hash_token(token)}",
                    template="password_reset",
                    recipient=user.email,
                    user_id=user.id,
                    context={"display_name": user.display_name, "token": token},
                )
        # the same answer whether or not the address has an account
        return self._card(
            title="Check your email",
            subtitle="Password reset",
            notice=(
                "If an account uses that address, a reset link is on its way. "
                "It expires in 1 hour."
            ),
            body_html='<p><a href="/auth/login">Back to sign in</a></p>',
        )

    def _reset_form(self, token: str, error: str | None = None,
                    status: int = 200) -> web.Response:
        response = web.Response(
            text=auth_page(
                title="Choose a new password",
                subtitle="Resetting your password signs you out everywhere.",
                form_action="/auth/reset",
                return_to="/",
                fields=new_password_fields(token),
                submit_label="Save new password",
                alternate_text="",
                alternate_href="",
                alternate_label="",
                error=error,
            ),
            content_type="text/html",
            status=status,
        )
        self._prepare_no_cache(response)
        response.headers["Referrer-Policy"] = "strict-origin"
        return response

    async def _reset_page(self, request: web.Request) -> web.Response:
        token = str(request.query.get("token", ""))
        if self._approval.peek_token(token, approval.PASSWORD_RESET) is None:
            return self._invalid_link("password reset")
        return self._reset_form(token)

    async def _reset_submit(self, request: web.Request) -> web.Response:
        self._require_same_origin(request)
        form = await request.post()
        token = str(form.get("token", ""))
        password = str(form.get("password", ""))
        confirm = str(form.get("confirm_password", ""))
        if len(password) < 8:
            return self._reset_form(
                token, "Your password must contain at least 8 characters.", 400)
        if password != confirm:
            return self._reset_form(token, "The passwords do not match.", 400)
        if self._approval.peek_token(token, approval.PASSWORD_RESET) is None:
            return self._invalid_link("password reset")
        password_hash = await _off_loop(hash_password, password)
        user_id = self._approval.consume_token(token, approval.PASSWORD_RESET)
        if user_id is None:
            return self._invalid_link("password reset")
        self._approval.set_password_hash(user_id, password_hash)
        self.revoke_user(user_id)
        return self._card(
            title="Password changed",
            subtitle="Your new password is saved and you were signed out everywhere.",
            body_html='<p><a href="/auth/login">Sign in</a></p>',
        )

    # ============================================================
    # Google OpenID Connect
    # ============================================================

    async def _google_begin(self, request: web.Request) -> web.StreamResponse:
        provider = self._google_provider
        if not provider.configured:
            raise web.HTTPServiceUnavailable(
                text="Google sign-in is not configured on this server.")

        return_to = safe_return_to(request.query.get("return_to"))
        session = self._get_or_create_session(request)
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        verifier = self._pkce_verifier()

        self._storage.create_oauth_flow(
            state=state,
            session_id=session.id,
            provider=provider.name,
            code_verifier=verifier,
            return_to=return_to,
            ttl_seconds=600,
            now=self._clock(),
            nonce=nonce,
        )
        response = web.HTTPFound(
            provider.authorization_url(
                state=state,
                code_challenge=self._pkce_challenge(verifier),
                nonce=nonce,
            )
        )
        self._set_session_cookie(request, response, session.id)
        raise response

    async def _google_callback(self, request: web.Request) -> web.StreamResponse:
        provider = self._google_provider
        if not provider.configured:
            raise web.HTTPServiceUnavailable(
                text="Google sign-in is not configured on this server.")

        if request.query.get("error"):
            raise web.HTTPBadRequest(text="Google sign-in was not completed.")

        code = str(request.query.get("code", "")).strip()
        state = str(request.query.get("state", "")).strip()
        if not code or not state:
            raise web.HTTPBadRequest(text="Missing Google sign-in response.")

        flow = self._storage.consume_oauth_flow(
            state=state, provider=provider.name, now=self._clock())
        if flow is None or not flow.nonce:
            raise web.HTTPBadRequest(
                text="The Google sign-in request is invalid or expired.")

        if request.cookies.get(self._cookie_name) != flow.session_id:
            raise web.HTTPBadRequest(
                text="Google sign-in session does not match.")

        try:
            authentication = await provider.exchange_code(
                code=code, code_verifier=flow.code_verifier)
            identity = await provider.verify(authentication, nonce=flow.nonce)
        except GoogleTokenError as error:
            request["cryostack_login_failure"] = error.category
            raise web.HTTPBadRequest(text=str(error))
        except RuntimeError as error:
            raise web.HTTPBadGateway(text=str(error))

        stored = self._storage.get_user_identity(
            provider=identity.provider, provider_subject=identity.subject)

        if stored is not None:
            user = self._storage.get_user_by_id(stored.user_id)
            if user is None:
                raise web.HTTPInternalServerError(
                    text="Google identity references a missing CryoStack account.")
        else:
            user = self.current_user(request)
            if user is not None:
                # An approved, signed-in account connecting Google itself.
                try:
                    self._create_google_identity(user, identity)
                except sqlite3.IntegrityError:
                    raise web.HTTPConflict(
                        text="This Google account is already linked to another "
                             "CryoStack account.")
            else:
                user = self._create_google_account(identity)

        authenticated = self._start_authenticated_session(
            flow.session_id, user_id=user.id)
        request["cryostack_login_user_id"] = user.id

        response = web.HTTPFound(
            self._after_sign_in(user, safe_return_to(flow.return_to)))
        self._set_session_cookie(request, response, authenticated.id)
        raise response

    def _create_google_identity(self, user: User, identity) -> None:
        self._storage.create_user_identity(
            user_id=user.id,
            provider=identity.provider,
            provider_subject=identity.subject,
            provider_username=identity.username,
            provider_email=identity.email,
            provider_profile_url=None,
            now=self._clock(),
        )

    def _create_google_account(self, identity) -> User:
        """A new, pending account from a Google identity nobody has linked."""
        if not self._approval_required:
            # Without the approval gate a new account would be usable at
            # once; Google sign-up opens only together with the gate.
            raise web.HTTPConflict(
                text="New accounts cannot be created with Google yet. Sign in "
                     "with your CryoStack account and connect Google from "
                     "Account Settings.")

        if self._storage.get_user_by_email(identity.email) is not None:
            # Never link an existing account only because the email matches.
            raise web.HTTPConflict(
                text="A CryoStack account already uses this email address. "
                     "Sign in with your existing CryoStack account first, then "
                     "connect Google from Account Settings.")

        display_name = (
            identity.display_name or identity.email.split("@", 1)[0]
        )[:120]
        try:
            user = self._storage.create_user(
                email=identity.email,
                display_name=display_name,
                institution=None,
                password_hash=hash_password(secrets.token_urlsafe(64)),
                now=self._clock(),
            )
            self._create_google_identity(user, identity)
        except sqlite3.IntegrityError:
            raise web.HTTPConflict(
                text="Unable to create the CryoStack account because the "
                     "identity is already registered.")
        # Google reported the address as verified
        self._record_registration(user, method="google", email_verified=True)
        return user

    # ============================================================
    # Revocation of live connections
    # ============================================================

    def register_live_connection(self, user_id: str, close) -> Callable[[], None]:
        """Track one long-lived connection; returns its unregister function.

        ``close`` is called (with no arguments, from the event loop) when the
        account is suspended or rejected, or its password is reset.
        """
        closers = self._live_connections.setdefault(user_id, set())
        closers.add(close)

        def unregister() -> None:
            found = self._live_connections.get(user_id)
            if found is not None:
                found.discard(close)
                if not found:
                    self._live_connections.pop(user_id, None)

        return unregister

    def revoke_user(self, user_id: str) -> int:
        """Close every live proxied connection of one account now."""
        closers = list(self._live_connections.pop(user_id, ()))
        for close in closers:
            try:
                close()
            except Exception:
                pass
        return len(closers)

    def live_session_valid(self, request: web.Request) -> bool:
        """Re-check, for a long-lived connection, its session and account."""
        request.pop("cryostack_session_user", None)
        user = self.current_user(request)
        return user is not None

    # ============================================================
    # Background delivery and provisioning
    # ============================================================

    async def _start_background(self, app: web.Application) -> None:
        if self._background_interval_s <= 0:
            return
        mail_logger = logging.getLogger("icesee_auth.mailer")
        mail_logger.setLevel(logging.INFO)
        if not mail_logger.handlers:
            mail_logger.addHandler(logging.StreamHandler(sys.stderr))
        mail_logger.propagate = False
        self._background_task = asyncio.create_task(self._background_loop())

    async def _stop_background(self, app: web.Application) -> None:
        task, self._background_task = self._background_task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    async def _background_loop(self) -> None:
        while True:
            try:
                await self.run_background_once()
            except asyncio.CancelledError:
                raise
            except Exception as error:      # keep the loop alive
                print(f"[auth] background step failed: {type(error).__name__}",
                      file=sys.stderr, flush=True)
            await asyncio.sleep(self._background_interval_s)

    async def run_background_once(self) -> dict:
        loop = asyncio.get_running_loop()
        mail = await loop.run_in_executor(None, self._outbox.deliver_due)
        provisioned = await loop.run_in_executor(None, self.provision_due)
        return {"mail": mail, "provisioning": provisioned}

    def provision_due(self) -> dict:
        """Provision every approved account that is due (blocking)."""
        result = {"ready": 0, "retry": 0, "failed": 0}
        for user_id in self._approval.due_provisioning():
            if self._approval.claim_provisioning(user_id):
                outcome = self.provision_workspace(user_id)
                result[outcome] = result.get(outcome, 0) + 1
        return result

    def provision_workspace(self, user_id: str) -> str:
        """One attempt; ``ready``, ``retry`` (queued again) or ``failed``."""
        provisioner = self._workspace_provisioner
        if provisioner is None:
            from .provisioning import provision_owner_workspace as provisioner
        try:
            details = provisioner(user_id)
        except Exception as error:
            status = self._approval.fail_provisioning(
                user_id, f"{type(error).__name__}: {str(error)[:200]}")
            return "failed" if status == "failed" else "retry"
        self._approval.finish_provisioning(
            user_id,
            owner_key=details["owner_key"],
            allowance_bytes=details["allowance_bytes"],
            allowance_source=details["allowance_source"],
        )
        return "ready"

    def _require_api_user(
        self,
        request: web.Request,
    ) -> User:
        user = self.current_user(request)

        if user is None:
            raise web.HTTPUnauthorized(
                text="Authentication required."
            )

        return user

    async def _handle_me(self, request: web.Request) -> web.Response:
        session = self._get_or_create_session(request)
        user = self._user_for_session(session)
        account_status = None

        if user is not None and not self.user_is_active(user.id):
            account_status = self._approval.effective_status(user.id)
            user = None

        response = web.json_response(
            {
                "authenticated": user is not None,
                "account_status": (
                    account_status
                    or ("approved" if user is not None else None)
                ),
                "user": self._public_user(user),
                "session": {
                    "created_at": self._format_timestamp(
                        session.created_at
                    ),
                    "expires_at": self._format_timestamp(
                        session.expires_at
                    ),
                },
            }
        )
        self._prepare_no_cache(response)
        self._set_session_cookie(request, response, session.id)
        return response

    async def _api_update_experiment_by_job(
        self,
        request: web.Request,
    ) -> web.Response:
        user = self._require_api_user(request)

        job_id = request.match_info[
            "job_id"
        ]

        experiment = (
            self._storage.get_experiment_by_job_id(
                user_id=user.id,
                job_id=job_id,
            )
        )

        if experiment is None:
            raise web.HTTPNotFound(
                text="Experiment not found."
            )

        try:
            payload = await request.json()
        except Exception:
            raise web.HTTPBadRequest(
                text="A valid JSON body is required."
            )

        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(
                text="A JSON object is required."
            )

        from icesee_jupyter_book.core.experiment_status import (
            EXPERIMENT_STATUSES,
        )

        status = str(
            payload.get(
                "status",
                experiment.status,
            )
        ).strip().lower()

        if status not in EXPERIMENT_STATUSES:
            raise web.HTTPBadRequest(
                text="Invalid experiment status."
            )

        updated = self._apply_experiment_status(
            experiment,
            user_id=user.id,
            status=status,
            payload=payload,
        )

        if updated is None:
            raise web.HTTPNotFound(
                text="Experiment not found."
            )

        response = web.json_response(
            self._experiment_to_dict(updated)
        )

        self._prepare_no_cache(response)

        return response


    async def _account_redirect(
        self,
        request: web.Request,
    ) -> web.StreamResponse:
        raise web.HTTPFound("/account/")


    async def _account_page(
        self,
        request: web.Request,
    ) -> web.Response:
        user = self.current_user(request)

        if user is None:
            raise web.HTTPFound(
                "/auth/login?return_to=%2Faccount%2F"
            )

        source_application = (
            request.query.get("from", "")
            .strip()
            .lower()
        )

        identities = self._storage.list_user_identities(
            user_id=user.id,
        )

        response = web.Response(
            text=account_settings_page(
                user=user,
                identities=identities,
                source_application=source_application,
                google_available=self._google_provider.configured,
            ),
            content_type="text/html",
        )

        self._prepare_no_cache(response)

        return response

    async def _account_update(
        self,
        request: web.Request,
    ) -> web.Response:
        user = self.current_user(request)

        if user is None:
            raise web.HTTPFound(
                "/auth/login?return_to=%2Faccount%2F"
            )

        source_application = (
            request.query.get("from", "")
            .strip()
            .lower()
        )

        form = await request.post()

        display_name = str(
            form.get("display_name", "")
        ).strip()

        institution = str(
            form.get("institution", "")
        ).strip()

        research_role = str(
            form.get("research_role", "")
        ).strip()

        country = str(
            form.get("country", "")
        ).strip()

        default_application = str(
            form.get("default_application", "")
        ).strip()

        default_execution_mode = str(
            form.get("default_execution_mode", "")
        ).strip()

        if len(display_name) < 2:
            identities = self._storage.list_user_identities(
                user_id=user.id,
            )
            response = web.Response(
                text=account_settings_page(
                    user=user,
                    identities=identities,
                    error="Please enter a valid display name.",
                    source_application=source_application,
                    google_available=self._google_provider.configured,
                ),
                content_type="text/html",
                status=400,
            )
            self._prepare_no_cache(response)
            return response

        updated_user = self._storage.update_user_profile(
            user_id=user.id,
            display_name=display_name,
            institution=institution or None,
            research_role=research_role or None,
            country=country or None,
            default_application=default_application or None,
            default_execution_mode=(
                default_execution_mode or None
            ),
            now=self._clock(),
        )

        if updated_user is None:
            raise web.HTTPNotFound(
                text="CryoStack account not found."
            )

        identities = self._storage.list_user_identities(
                user_id=user.id,
            )

        response = web.Response(
            text=account_settings_page(
                user=updated_user,
                identities=identities,
                message="Your account settings were updated.",
                source_application=source_application,
                google_available=self._google_provider.configured,
            ),
            content_type="text/html",
        )
        self._prepare_no_cache(response)

        return response

    async def _login_page(self, request: web.Request) -> web.Response:
        return_to = safe_return_to(
            request.query.get("return_to")
        )

        session = self._get_or_create_session(request)
        user = self._user_for_session(session)

        if user is not None:
            raise web.HTTPFound(
                self._after_sign_in(user, return_to)
            )

        response = web.Response(
            text=self._render_login(return_to=return_to),
            content_type="text/html",
        )
        self._prepare_no_cache(response)
        self._set_session_cookie(request, response, session.id)
        return response

    async def _login_submit(
        self,
        request: web.Request,
    ) -> web.Response:
        form = await request.post()

        email = str(form.get("email", "")).strip().lower()
        password = str(form.get("password", ""))
        return_to = safe_return_to(
            str(form.get("return_to", ""))
        )

        session = self._get_or_create_session(request)
        now = self._clock()

        address_key = "address:" + client_address(request)

        if (
            self._login_limiter.blocked(email, now)
            or self._address_limiter.blocked(address_key, now)
        ):
            known = self._storage.get_user_by_email(email)
            self._record_access(
                event_type=access_log.LOGIN_RATE_LIMITED,
                outcome="denied",
                category="rate_limited",
                user_id=known.id if known else None,
                provider="password",
            )
            response = web.Response(
                text=self._render_login(
                    return_to=return_to,
                    email=email,
                    error=(
                        "Too many failed sign-in attempts. "
                        "Wait a few minutes and try again."
                    ),
                ),
                content_type="text/html",
                status=429,
            )
            self._prepare_no_cache(response)
            self._set_session_cookie(
                request,
                response,
                session.id,
            )
            return response

        user = self._storage.get_user_by_email(email)

        # Same scrypt cost whether or not the account exists, so response time
        # does not reveal which addresses are registered.
        valid = await _off_loop(
            verify_password,
            password,
            user.password_hash if user is not None else _dummy_password_hash(),
        )

        if user is None or not valid:
            self._login_limiter.failed(email, now)
            self._address_limiter.failed(address_key, now)
            self._record_access(
                event_type=access_log.LOGIN_FAILURE,
                outcome="failure",
                category=(
                    "unknown_account"
                    if user is None
                    else "wrong_password"
                ),
                user_id=user.id if user else None,
                provider="password",
            )
            response = web.Response(
                text=self._render_login(
                    return_to=return_to,
                    email=email,
                    error="The email or password is incorrect.",
                ),
                content_type="text/html",
                status=400,
            )
            self._prepare_no_cache(response)
            self._set_session_cookie(
                request,
                response,
                session.id,
            )
            return response

        authenticated = self._start_authenticated_session(
            session.id,
            user_id=user.id,
        )

        if authenticated is None:
            raise web.HTTPInternalServerError(
                text="Unable to update the session."
            )

        self._login_limiter.succeeded(email)
        self._record_access(
            event_type=access_log.LOGIN_SUCCESS,
            outcome="success",
            user_id=user.id,
            provider="password",
        )

        response = web.HTTPFound(
            self._after_sign_in(user, return_to)
        )
        self._set_session_cookie(
            request,
            response,
            authenticated.id,
        )
        raise response

    async def _register_page(
        self,
        request: web.Request,
    ) -> web.Response:
        return_to = safe_return_to(
            request.query.get("return_to")
        )

        session = self._get_or_create_session(request)
        user = self._user_for_session(session)

        if user is not None:
            raise web.HTTPFound(
                self._after_sign_in(user, return_to)
            )

        response = web.Response(
            text=self._render_register(return_to=return_to),
            content_type="text/html",
        )
        self._prepare_no_cache(response)
        self._set_session_cookie(request, response, session.id)
        return response

    async def _register_submit(
        self,
        request: web.Request,
    ) -> web.Response:
        form = await request.post()

        display_name = str(
            form.get("display_name", "")
        ).strip()
        email = str(form.get("email", "")).strip().lower()
        institution = str(
            form.get("institution", "")
        ).strip()
        password = str(form.get("password", ""))
        confirm_password = str(
            form.get("confirm_password", "")
        )
        return_to = safe_return_to(
            str(form.get("return_to", ""))
        )

        error = self._validate_registration(
            display_name=display_name,
            email=email,
            password=password,
            confirm_password=confirm_password,
        )

        session = self._get_or_create_session(request)

        if error:
            return self._registration_error_response(
                request=request,
                session=session,
                return_to=return_to,
                display_name=display_name,
                email=email,
                institution=institution,
                error=error,
            )

        if self._approval_required:
            return await self._register_for_review(
                request,
                session=session,
                display_name=display_name,
                email=email,
                institution=institution,
                password=password,
                return_to=return_to,
            )

        try:
            user = self._storage.create_user(
                email=email,
                display_name=display_name,
                institution=institution or None,
                password_hash=await _off_loop(hash_password, password),
                now=self._clock(),
            )
        except sqlite3.IntegrityError:
            return self._registration_error_response(
                request=request,
                session=session,
                return_to=return_to,
                display_name=display_name,
                email=email,
                institution=institution,
                error=(
                    "An account already exists for this email."
                ),
            )

        authenticated = self._start_authenticated_session(
            session.id,
            user_id=user.id,
        )

        if authenticated is None:
            raise web.HTTPInternalServerError(
                text="Unable to update the session."
            )

        self._record_access(
            event_type=access_log.REGISTER,
            outcome="success",
            user_id=user.id,
            provider="password",
        )

        response = web.HTTPFound(return_to)
        self._set_session_cookie(
            request,
            response,
            authenticated.id,
        )
        raise response

    async def _logout(self, request: web.Request) -> web.Response:
        session_id = request.cookies.get(self._cookie_name)

        if session_id:
            session = self._storage.get_session(
                session_id,
                now=self._clock(),
            )
            self._storage.delete_session(session_id)

            if session is not None and session.user_id:
                self._record_access(
                    event_type=access_log.LOGOUT,
                    outcome="success",
                    user_id=session.user_id,
                )

        if request.content_type == "application/x-www-form-urlencoded":
            # the status pages sign out with a plain form
            response = web.HTTPSeeOther("/auth/login")
        else:
            response = web.json_response(
                {
                    "ok": True,
                    "authenticated": False,
                }
            )
        self._prepare_no_cache(response)
        response.del_cookie(
            self._cookie_name,
            path="/",
        )
        if isinstance(response, web.HTTPException):
            raise response
        return response

    async def _configurations_redirect(
        self,
        request: web.Request,
    ) -> web.StreamResponse:
        raise web.HTTPFound("/configurations/")


    async def _configurations_page(
        self,
        request: web.Request,
    ) -> web.Response:
        user = self.current_user(request)

        if user is None:
            raise web.HTTPFound(
                "/auth/login?return_to=%2Fconfigurations%2F"
            )

        source_application = (
            request.query.get("from", "")
            .strip()
            .lower()
        )

        configurations = (
            self._storage.list_configurations(
                user_id=user.id,
            )
        )

        response = web.Response(
            text=configurations_page(
                user=user,
                configurations=configurations,
                message=request.query.get("message"),
                source_application=source_application,
            ),
            content_type="text/html",
        )

        self._prepare_no_cache(response)

        return response


    async def _configuration_new_page(
        self,
        request: web.Request,
    ) -> web.Response:
        user = self.current_user(request)

        if user is None:
            raise web.HTTPFound(
                "/auth/login?return_to="
                "%2Fconfigurations%2Fnew"
            )

        response = web.Response(
            text=configuration_form_page(
                title="New Configuration",
                form_action="/configurations/new",
            ),
            content_type="text/html",
        )

        self._prepare_no_cache(response)
        return response


    async def _configuration_create(
        self,
        request: web.Request,
    ) -> web.Response:
        user = self.current_user(request)

        if user is None:
            raise web.HTTPFound(
                "/auth/login?return_to="
                "%2Fconfigurations%2Fnew"
            )

        form = await request.post()

        application = str(
            form.get("application", "")
        ).strip().lower()

        name = str(
            form.get("name", "")
        ).strip()

        description = str(
            form.get("description", "")
        ).strip()

        configuration_json = str(
            form.get("configuration_json", "")
        ).strip()

        schema_version = str(
            form.get("schema_version", "1.0")
        ).strip()

        error = self._validate_configuration(
            application=application,
            name=name,
            configuration_json=configuration_json,
        )

        if error:
            return self._configuration_form_error(
                title="New Configuration",
                form_action="/configurations/new",
                error=error,
            )

        self._storage.create_configuration(
            user_id=user.id,
            application=application,
            name=name,
            description=description or None,
            configuration_json=configuration_json,
            schema_version=schema_version or "1.0",
            now=self._clock(),
        )

        raise web.HTTPFound(
            "/configurations/?message="
            "Configuration%20saved."
        )


    async def _configuration_edit_page(
        self,
        request: web.Request,
    ) -> web.Response:
        user = self.current_user(request)

        if user is None:
            raise web.HTTPFound(
                "/auth/login?return_to="
                + quote(request.path_qs, safe="")
            )

        configuration_id = request.match_info[
            "configuration_id"
        ]

        configuration = self._storage.get_configuration(
            configuration_id=configuration_id,
            user_id=user.id,
        )

        if configuration is None:
            raise web.HTTPNotFound(
                text="Saved configuration not found."
            )

        response = web.Response(
            text=configuration_form_page(
                title="Edit Configuration",
                form_action=(
                    f"/configurations/"
                    f"{configuration.id}/edit"
                ),
                configuration=configuration,
            ),
            content_type="text/html",
        )

        self._prepare_no_cache(response)
        return response


    async def _configuration_update(
        self,
        request: web.Request,
    ) -> web.Response:
        user = self.current_user(request)

        if user is None:
            raise web.HTTPFound(
                "/auth/login?return_to="
                + quote(request.path_qs, safe="")
            )

        configuration_id = request.match_info[
            "configuration_id"
        ]

        configuration = self._storage.get_configuration(
            configuration_id=configuration_id,
            user_id=user.id,
        )

        if configuration is None:
            raise web.HTTPNotFound(
                text="Saved configuration not found."
            )

        form = await request.post()

        application = str(
            form.get("application", "")
        ).strip().lower()

        name = str(
            form.get("name", "")
        ).strip()

        description = str(
            form.get("description", "")
        ).strip()

        configuration_json = str(
            form.get("configuration_json", "")
        ).strip()

        schema_version = str(
            form.get("schema_version", "1.0")
        ).strip()

        error = self._validate_configuration(
            application=application,
            name=name,
            configuration_json=configuration_json,
        )

        if error:
            response = web.Response(
                text=configuration_form_page(
                    title="Edit Configuration",
                    form_action=(
                        f"/configurations/"
                        f"{configuration.id}/edit"
                    ),
                    configuration=configuration,
                    error=error,
                ),
                content_type="text/html",
                status=400,
            )

            self._prepare_no_cache(response)
            return response

        self._storage.update_configuration(
            configuration_id=configuration.id,
            user_id=user.id,
            application=application,
            name=name,
            description=description or None,
            configuration_json=configuration_json,
            schema_version=schema_version or "1.0",
            now=self._clock(),
        )

        raise web.HTTPFound(
            "/configurations/?message="
            "Configuration%20updated."
        )


    async def _configuration_delete(
        self,
        request: web.Request,
    ) -> web.StreamResponse:
        user = self.current_user(request)

        if user is None:
            raise web.HTTPFound(
                "/auth/login?return_to=%2Fconfigurations%2F"
            )

        configuration_id = request.match_info[
            "configuration_id"
        ]

        deleted = self._storage.delete_configuration(
            configuration_id=configuration_id,
            user_id=user.id,
        )

        if not deleted:
            raise web.HTTPNotFound(
                text="Saved configuration not found."
            )

        raise web.HTTPFound(
            "/configurations/?message="
            "Configuration%20deleted."
        )


    def _configuration_form_error(
        self,
        *,
        title: str,
        form_action: str,
        error: str,
    ) -> web.Response:
        response = web.Response(
            text=configuration_form_page(
                title=title,
                form_action=form_action,
                error=error,
            ),
            content_type="text/html",
            status=400,
        )

        self._prepare_no_cache(response)
        return response


    @staticmethod
    def _validate_configuration(
        *,
        application: str,
        name: str,
        configuration_json: str,
    ) -> str | None:
        allowed_applications = {
            "cryolauncher",
            "icesee",
            "livist",
        }

        if application not in allowed_applications:
            return "Please select a valid CryoStack application."

        if len(name) < 2:
            return "Configuration name must contain at least 2 characters."

        try:
            parsed = json.loads(configuration_json)
        except json.JSONDecodeError as error:
            return (
                "Configuration JSON is invalid: "
                f"{error.msg} at line {error.lineno}."
            )

        if not isinstance(parsed, dict):
            return "Configuration JSON must contain a JSON object."

        return None

    def _get_or_create_session(
        self,
        request: web.Request,
    ) -> SessionRecord:
        now = self._clock()
        self._storage.delete_expired_sessions(now)

        session_id = request.cookies.get(self._cookie_name)

        if session_id:
            session = self._storage.get_session(
                session_id,
                now=now,
            )
            if session is not None:
                refreshed = self._storage.refresh_session(
                    session.id,
                    ttl_seconds=self._session_ttl_seconds,
                    now=now,
                )
                if refreshed is not None:
                    return refreshed

        return self._storage.create_session(
            ttl_seconds=self._session_ttl_seconds,
            now=now,
        )

    def _start_authenticated_session(
        self,
        previous_session_id: str | None,
        *,
        user_id: str,
    ) -> SessionRecord | None:
        """Issue a fresh session id at sign-in and retire the old one.

        The pre-login (anonymous) session id is never promoted, so an id
        planted in a browser before sign-in cannot become authenticated.
        """
        session = self._storage.create_session(
            ttl_seconds=self._session_ttl_seconds,
            user_id=user_id,
            now=self._clock(),
        )

        if previous_session_id and previous_session_id != session.id:
            self._storage.delete_session(previous_session_id)

        return session

    def _record_access(self, **fields) -> None:
        """Record an access event; a logging failure never blocks sign-in."""
        try:
            self._storage.record_access_event(
                now=self._clock(),
                **fields,
            )
        except Exception:
            pass

    def _oauth_callback_logged(self, handler, provider: str):
        """Record the outcome of an OAuth callback by category only."""

        async def logged(request: web.Request):
            try:
                return await handler(request)
            except web.HTTPException as outcome:
                user_id = request.get("cryostack_login_user_id")
                if outcome.status < 400 and user_id:
                    self._record_access(
                        event_type=access_log.LOGIN_SUCCESS,
                        outcome="success",
                        user_id=user_id,
                        provider=provider,
                    )
                elif outcome.status >= 400:
                    category = _OAUTH_FAILURE_CATEGORY.get(
                        outcome.status,
                        "invalid_request",
                    )
                    text = (outcome.text or "").lower()
                    if request.get("cryostack_login_failure"):
                        category = request["cryostack_login_failure"]
                    elif "invalid or expired" in text:
                        category = "expired_or_invalid_state"
                    elif "does not match" in text:
                        category = "session_mismatch"
                    elif "not yet linked" in text:
                        category = "identity_not_linked"
                    elif "email address" in text and outcome.status == 400:
                        category = "missing_email"
                    self._record_access(
                        event_type=access_log.LOGIN_FAILURE,
                        outcome="failure",
                        category=category,
                        provider=provider,
                    )
                raise

        return logged

    def current_user(
        self,
        request: web.Request,
        *,
        refresh_session: bool = False,
    ) -> User | None:
        """The signed-in user, only while their account may use CryoStack.

        Every application, API, storage, compute and Connector path asks
        this, so a pending, rejected or suspended account is treated as
        signed out everywhere. The status is read on every call: a decision
        takes effect on the account's next request.
        """
        # Long-lived responses must re-read the session after logout/reset as
        # well as checking approval. Ordinary requests retain their local cache.
        if refresh_session:
            request.pop("cryostack_session_user", None)
        user = self.session_user(request)

        if user is None or not self.user_is_active(user.id):
            return None

        return user

    def user_is_active(self, user_id: str) -> bool:
        """Whether the account may use CryoStack.

        With the gate on, only ``approved``. With it off, everyone except an
        account an administrator explicitly rejected or suspended, so turning
        the gate off again never readmits a suspended account.
        """
        record = self._approval.status(user_id)
        if record is not None and record.status in (approval.REJECTED, approval.SUSPENDED):
            return False
        if not self._approval_required:
            return True
        return record is not None and record.status == approval.APPROVED

    def session_user(
        self,
        request: web.Request,
    ) -> User | None:
        """The account behind the session cookie, whatever its status.

        Only the account status pages use this directly.
        """
        if "cryostack_session_user" in request:
            return request["cryostack_session_user"]

        session_id = request.cookies.get(
            self._cookie_name
        )

        if not session_id:
            return None

        session = self._storage.get_session(
            session_id,
            now=self._clock(),
        )

        if session is None:
            return None

        if not session.user_id:
            return None

        user = self._storage.get_user_by_id(
            session.user_id
        )
        request["cryostack_session_user"] = user
        return user


    def authenticated_user(
        self,
        request: web.Request,
    ) -> User | None:
        return self.current_user(request)


    def require_login(self, handler):
        async def protected(
            request: web.Request,
        ):
            user = self.current_user(request)

            if user is None:
                self._redirect_unapproved(request)

                return_to = request.path_qs

                login_url = (
                    "/auth/login?return_to="
                    + quote(return_to, safe="")
                )

                raise web.HTTPFound(login_url)

            request["cryostack_user"] = user

            return await handler(request)

        return protected

    def _user_for_session(
        self,
        session: SessionRecord,
    ) -> User | None:
        if not session.user_id:
            return None

        return self._storage.get_user_by_id(session.user_id)

    def _public_user(
        self,
        user: User | None,
    ) -> dict | None:

        if user is None:
            return None

        roles = self._storage.get_user_roles(
            user_id=user.id
        )

        return {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "institution": user.institution,
            "research_role": user.research_role,
            "country": user.country,

            "roles": roles,

            "control_center_access": bool(
                set(roles).intersection({
                    "developer",
                    "maintainer",
                    "admin",
                    "owner",
                })
            ),

            "preferences": {
                "default_application": (
                    user.default_application
                ),
                "default_execution_mode": (
                    user.default_execution_mode
                ),
            },
        }

    def _set_session_cookie(
        self,
        request: web.Request,
        response: web.StreamResponse,
        session_id: str,
    ) -> None:
        response.set_cookie(
            self._cookie_name,
            session_id,
            max_age=self._session_ttl_seconds,
            httponly=True,
            secure=self._request_uses_https(request),
            samesite="Lax",
            path="/",
        )

    def _request_uses_https(self, request: web.Request) -> bool:
        if self._secure_cookies is not None:
            return self._secure_cookies

        forwarded_proto = request.headers.get(
            "X-Forwarded-Proto",
            "",
        )
        if forwarded_proto:
            return (
                forwarded_proto
                .split(",", maxsplit=1)[0]
                .strip()
                .lower()
                == "https"
            )

        return request.secure

    @staticmethod
    def _prepare_no_cache(response: web.StreamResponse) -> None:
        response.headers["Cache-Control"] = "no-store"
        response.headers["Vary"] = "Cookie"

    def _render_login(
        self,
        *,
        return_to: str,
        email: str = "",
        error: str | None = None,
    ) -> str:
        register_href = (
            "/auth/register?return_to="
            + quote(return_to, safe="")
        )

        github_href = (
            "/auth/github?return_to="
            + quote(return_to, safe="")
        )

        return auth_page(
            title="Sign in",
            subtitle=(
                "Access your CryoStack applications, "
                "configurations, jobs, and HPC connections."
            ),
            form_action="/auth/login",
            return_to=return_to,
            fields=login_fields(email),
            submit_label="Sign In",
            alternate_text="New to CryoStack?",
            alternate_href=register_href,
            alternate_label="Create an account",
            error=error,
            github_href=github_href,
            google_href=self._google_href(return_to),
            after_form_html=(
                '<p class="forgot"><a href="/auth/forgot">Forgot your password?</a></p>'
                if self._outbox.config.delivers
                else ""
            ),
        )

    def _google_href(self, return_to: str) -> str | None:
        if not self._google_provider.configured:
            return None
        return "/auth/google?return_to=" + quote(return_to, safe="")

    def _render_register(
        self,
        *,
        return_to: str,
        display_name: str = "",
        email: str = "",
        institution: str = "",
        error: str | None = None,
    ) -> str:
        login_href = (
            "/auth/login?return_to="
            + quote(return_to, safe="")
        )

        github_href = (
            "/auth/github?return_to="
            + quote(return_to, safe="")
        )

        return auth_page(
            title="Create your account",
            subtitle=(
                "Create a CryoStack workspace for saved "
                "configurations, jobs, and computing resources."
            ),
            form_action="/auth/register",
            return_to=return_to,
            fields=register_fields(
                display_name=display_name,
                email=email,
                institution=institution,
            ),
            submit_label="Create Account",
            alternate_text="Already have an account?",
            alternate_href=login_href,
            alternate_label="Sign in",
            error=error,
            github_href=github_href,
            google_href=(
                self._google_href(return_to)
                if self._approval_required
                else None
            ),
            notice=(
                "New accounts are reviewed by an administrator before "
                "they can use CryoStack."
                if self._approval_required
                else None
            ),
        )

    def _registration_error_response(
        self,
        *,
        request: web.Request,
        session: SessionRecord,
        return_to: str,
        display_name: str,
        email: str,
        institution: str,
        error: str,
    ) -> web.Response:
        response = web.Response(
            text=self._render_register(
                return_to=return_to,
                display_name=display_name,
                email=email,
                institution=institution,
                error=error,
            ),
            content_type="text/html",
            status=400,
        )
        self._prepare_no_cache(response)
        self._set_session_cookie(
            request,
            response,
            session.id,
        )
        return response

    @staticmethod
    def _validate_registration(
        *,
        display_name: str,
        email: str,
        password: str,
        confirm_password: str,
    ) -> str | None:
        if len(display_name) < 2:
            return "Please enter your name."

        if (
            "@" not in email
            or email.startswith("@")
            or email.endswith("@")
            or len(email) > 254
            or any(character.isspace() for character in email)
        ):
            return "Please enter a valid email address."

        if len(password) < 8:
            return (
                "Your password must contain at least "
                "8 characters."
            )

        if password != confirm_password:
            return "The passwords do not match."

        return None

    @staticmethod
    def _format_timestamp(value: float) -> str:
        return (
            datetime
            .fromtimestamp(value, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )

    def _experiment_to_dict(self, experiment) -> dict:
        import json

        try:
            configuration = json.loads(
                experiment.configuration_snapshot_json
            )
        except Exception:
            configuration = {}

        try:
            metadata = json.loads(
                experiment.metadata_json
            )
        except Exception:
            metadata = {}

        return {
            "id": experiment.id,
            "configuration_id": experiment.configuration_id,
            "application": experiment.application,
            "name": experiment.name,
            "backend": experiment.backend,
            "status": experiment.status,
            "configuration": configuration,
            "job_id": experiment.job_id,
            "cluster": experiment.cluster,
            "working_directory": experiment.working_directory,
            "output_directory": experiment.output_directory,
            "log_path": experiment.log_path,
            "exit_code": experiment.exit_code,
            "error_message": experiment.error_message,
            "metadata": metadata,
            "created_at": self._format_timestamp(
                experiment.created_at
            ),
            "started_at": (
                self._format_timestamp(experiment.started_at)
                if experiment.started_at is not None
                else None
            ),
            "finished_at": (
                self._format_timestamp(experiment.finished_at)
                if experiment.finished_at is not None
                else None
            ),
            "updated_at": self._format_timestamp(
                experiment.updated_at
            ),
        }

    async def _api_list_experiments(
        self,
        request: web.Request,
    ) -> web.Response:
        user = self._require_api_user(request)

        experiments = self._storage.list_experiments(
            user_id=user.id,
            application=request.query.get("application"),
            status=request.query.get("status"),
        )

        response = web.json_response(
            {
                "experiments": [
                    self._experiment_to_dict(experiment)
                    for experiment in experiments
                ]
            }
        )

        self._prepare_no_cache(response)
        return response

    #: a create for a job that already has a record this recent is a re-send
    EXPERIMENT_DUPLICATE_WINDOW_SECONDS = 7 * 24 * 3600

    async def _api_create_experiment(
        self,
        request: web.Request,
    ) -> web.Response:
        user = self._require_api_user(request)

        try:
            payload = await request.json()
        except Exception:
            raise web.HTTPBadRequest(
                text="A valid JSON body is required."
            )

        application = str(
            payload.get("application", "")
        ).strip().lower()

        name = str(
            payload.get("name", "")
        ).strip()

        backend = str(
            payload.get("backend", "")
        ).strip().lower()

        configuration_id = payload.get("configuration_id")
        configuration = payload.get("configuration")

        if application not in {
            "cryolauncher",
            "icesee",
            "livist",
        }:
            raise web.HTTPBadRequest(
                text="Invalid application."
            )

        if len(name) < 2:
            raise web.HTTPBadRequest(
                text="Experiment name is required."
            )

        if not backend:
            raise web.HTTPBadRequest(
                text="Execution backend is required."
            )

        if configuration_id:
            saved = self._storage.get_configuration(
                configuration_id=str(configuration_id),
                user_id=user.id,
            )

            if saved is None:
                raise web.HTTPBadRequest(
                    text="Saved configuration not found."
                )

            configuration_snapshot_json = (
                saved.configuration_json
            )
        else:
            if not isinstance(configuration, dict):
                raise web.HTTPBadRequest(
                    text=(
                        "Provide configuration_id or a "
                        "configuration object."
                    )
                )

            configuration_snapshot_json = json.dumps(
                configuration,
                sort_keys=True,
            )

        metadata = payload.get("metadata", {})

        if not isinstance(metadata, dict):
            raise web.HTTPBadRequest(
                text="metadata must be a JSON object."
            )

        from icesee_jupyter_book.core.experiment_status import (
            EXPERIMENT_STATUSES,
        )

        status = str(
            payload.get("status", "queued")
        ).strip().lower()

        if status not in EXPERIMENT_STATUSES:
            raise web.HTTPBadRequest(
                text="Invalid experiment status."
            )

        # One record per submitted job: a repeated create for the same
        # scheduler job (a re-sent browser command) returns the record that
        # already exists instead of tracking the job twice.
        job_id = str(payload.get("job_id") or "").strip()

        if job_id:
            existing = self._storage.get_experiment_by_job_id(
                user_id=user.id,
                job_id=job_id,
            )

            if (
                existing is not None
                and existing.application == application
                and existing.backend == backend
                and (existing.cluster or "") == str(
                    payload.get("cluster") or ""
                ).strip()
                and self._clock() - existing.created_at
                < self.EXPERIMENT_DUPLICATE_WINDOW_SECONDS
            ):
                response = web.json_response(
                    self._experiment_to_dict(existing),
                    status=200,
                )

                self._prepare_no_cache(response)
                return response

        experiment = self._storage.create_experiment(
            user_id=user.id,
            configuration_id=(
                str(configuration_id)
                if configuration_id
                else None
            ),
            application=application,
            name=name,
            backend=backend,
            status=status,
            configuration_snapshot_json=(
                configuration_snapshot_json
            ),
            job_id=payload.get("job_id"),
            cluster=payload.get("cluster"),
            working_directory=payload.get(
                "working_directory"
            ),
            output_directory=payload.get(
                "output_directory"
            ),
            log_path=payload.get("log_path"),
            metadata_json=json.dumps(
                metadata,
                sort_keys=True,
            ),
            now=self._clock(),
        )

        self._storage.create_experiment_event(
            experiment_id=experiment.id,
            user_id=user.id,
            event_type="created",
            message="Experiment created.",
            metadata_json=json.dumps(
                {
                    "application": experiment.application,
                    "backend": experiment.backend,
                },
                sort_keys=True,
            ),
            now=self._clock(),
        )

        if experiment.status == "running":
            self._storage.create_experiment_event(
                experiment_id=experiment.id,
                user_id=user.id,
                event_type="running",
                message="Experiment entered running state.",
                metadata_json="{}",
                now=self._clock(),
            )

        response = web.json_response(
            self._experiment_to_dict(experiment),
            status=201,
        )

        self._prepare_no_cache(response)
        return response

    
    async def _api_get_experiment(
        self,
        request: web.Request,
    ) -> web.Response:
        user = self._require_api_user(request)

        experiment = self._storage.get_experiment(
            experiment_id=request.match_info[
                "experiment_id"
            ],
            user_id=user.id,
        )

        if experiment is None:
            raise web.HTTPNotFound(
                text="Experiment not found."
            )

        response = web.json_response(
            self._experiment_to_dict(experiment)
        )

        self._prepare_no_cache(response)
        return response


    async def _api_update_experiment(
        self,
        request: web.Request,
    ) -> web.Response:
        user = self._require_api_user(request)

        try:
            payload = await request.json()
        except Exception:
            raise web.HTTPBadRequest(
                text="A valid JSON body is required."
            )

        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(
                text="A JSON object is required."
            )

        from icesee_jupyter_book.core.experiment_status import (
            EXPERIMENT_STATUSES,
        )

        status = payload.get("status")

        if status is not None:
            status = str(status).strip().lower()

            if status not in EXPERIMENT_STATUSES:
                raise web.HTTPBadRequest(
                    text="Invalid experiment status."
                )

        metadata = payload.get("metadata")

        if metadata is not None and not isinstance(
            metadata,
            dict,
        ):
            raise web.HTTPBadRequest(
                text="metadata must be a JSON object."
            )

        existing = self._storage.get_experiment(
            experiment_id=request.match_info[
                "experiment_id"
            ],
            user_id=user.id,
        )

        if existing is None:
            raise web.HTTPNotFound(
                text="Experiment not found."
            )

        experiment = self._apply_experiment_status(
            existing,
            user_id=user.id,
            status=status,
            payload=payload,
            metadata=metadata,
        )

        if experiment is None:
            raise web.HTTPNotFound(
                text="Experiment not found."
            )

        response = web.json_response(
            self._experiment_to_dict(experiment)
        )

        self._prepare_no_cache(response)
        return response

    def _apply_experiment_status(
        self,
        experiment,
        *,
        user_id: str,
        status: str | None,
        payload: dict,
        metadata: dict | None = None,
    ):
        """
        Apply one status/field update to an experiment the caller owns.

        A record that already reached a terminal status (completed, failed,
        cancelled) is final: later updates -- a repeated poll, a late
        "running" -- leave it, its finish time and its events unchanged.
        A ``failure`` summary is reduced to its bounded, redacted form and
        kept as ``metadata["failure"]``; ``error_message`` is redacted too.
        """

        from icesee_jupyter_book.core.experiment_status import (
            TERMINAL_STATUSES,
            failure_message,
            redact_secrets,
            sanitize_failure,
        )

        if experiment.status in TERMINAL_STATUSES:
            return experiment

        previous_status = experiment.status

        failure = sanitize_failure(
            payload.get("failure")
        )

        if metadata is not None or failure is not None:
            merged = (
                dict(metadata)
                if metadata is not None
                else self._experiment_metadata(experiment)
            )

            if failure is None and "failure" in merged:
                failure = sanitize_failure(merged.pop("failure"))

            if failure is not None:
                merged["failure"] = failure

            metadata_json = json.dumps(
                merged,
                sort_keys=True,
            )
        else:
            metadata_json = None

        error_message = payload.get("error_message")

        if error_message is None and failure is not None:
            error_message = failure_message(failure)

        if error_message is not None:
            error_message = (
                redact_secrets(error_message, limit=500)
                or None
            )

        exit_code = payload.get("exit_code")

        if isinstance(exit_code, bool) or not isinstance(exit_code, int):
            exit_code = None

        updated = self._storage.update_experiment(
            experiment_id=experiment.id,
            user_id=user_id,
            status=status,
            job_id=payload.get("job_id"),
            cluster=payload.get("cluster"),
            working_directory=payload.get(
                "working_directory"
            ),
            output_directory=payload.get(
                "output_directory"
            ),
            log_path=payload.get("log_path"),
            exit_code=exit_code,
            error_message=error_message,
            metadata_json=metadata_json,
            now=self._clock(),
        )

        if (
            updated is not None
            and updated.status != previous_status
        ):
            event_metadata = {
                "previous_status": previous_status,
                "status": updated.status,
                "job_id": updated.job_id,
                "exit_code": updated.exit_code,
            }

            if failure is not None:
                for key in ("scheduler", "state", "signal", "reason"):
                    if key in failure:
                        event_metadata[key] = failure[key]

            self._storage.create_experiment_event(
                experiment_id=updated.id,
                user_id=user_id,
                event_type=updated.status,
                message=(
                    f"Experiment status changed from "
                    f"{previous_status} to {updated.status}."
                ),
                metadata_json=json.dumps(
                    event_metadata,
                    sort_keys=True,
                ),
                now=self._clock(),
            )

        return updated

    @staticmethod
    def _experiment_metadata(experiment) -> dict:
        try:
            value = json.loads(experiment.metadata_json or "{}")
        except (TypeError, ValueError):
            return {}

        return value if isinstance(value, dict) else {}


    async def _api_delete_experiment(
        self,
        request: web.Request,
    ) -> web.Response:
        user = self._require_api_user(request)

        deleted = self._storage.delete_experiment(
            experiment_id=request.match_info[
                "experiment_id"
            ],
            user_id=user.id,
        )

        if not deleted:
            raise web.HTTPNotFound(
                text="Experiment not found."
            )

        response = web.json_response(
            {
                "ok": True,
                "deleted": True,
            }
        )

        self._prepare_no_cache(response)
        return response

    async def _experiments_redirect(
        self,
        request: web.Request,
    ) -> web.StreamResponse:
        raise web.HTTPFound("/experiments/")

    async def _experiments_page(
        self,
        request: web.Request,
    ) -> web.Response:
        user = self.current_user(request)

        if user is None:
            raise web.HTTPFound(
                "/auth/login?return_to=%2Fexperiments%2F"
            )

        source_application = (
            request.query.get("from", "")
            .strip()
            .lower()
        )

        experiments = (
            self._storage.list_experiments(
                user_id=user.id,
                application=request.query.get(
                    "application"
                ),
                status=request.query.get(
                    "status"
                ),
            )
        )

        response = web.Response(
            text=experiments_page(
                user=user,
                experiments=experiments,
                source_application=source_application,
            ),
            content_type="text/html",
        )

        self._prepare_no_cache(response)

        return response

    async def _experiment_detail_page(
        self,
        request: web.Request,
    ) -> web.StreamResponse:
        user = self.current_user(request)

        if user is None:
            raise web.HTTPFound(
                "/auth/login?return_to="
                + quote(request.path_qs, safe="")
            )

        experiment = self._storage.get_experiment(
            experiment_id=request.match_info[
                "experiment_id"
            ],
            user_id=user.id,
        )

        if experiment is None:
            raise web.HTTPNotFound(
                text="Experiment not found."
            )

        events = self._storage.list_experiment_events(
            experiment_id=experiment.id,
            user_id=user.id,
        )

        source_application = (
            request.query.get("from", "")
            .strip()
            .lower()
        )

        response = web.Response(
            text=experiment_detail_page(
                user=user,
                experiment=experiment,
                events=events,
                source_application=source_application,
            ),
            content_type="text/html",
        )

        self._prepare_no_cache(response)

        return response

    async def _experiment_delete(
        self,
        request: web.Request,
    ) -> web.StreamResponse:
        user = self.current_user(request)

        if user is None:
            raise web.HTTPFound(
                "/auth/login?return_to=%2Fexperiments%2F"
            )

        experiment_id = request.match_info[
            "experiment_id"
        ]

        deleted = self._storage.delete_experiment(
            experiment_id=experiment_id,
            user_id=user.id,
        )

        if not deleted:
            raise web.HTTPNotFound(
                text="Experiment not found."
            )

        raise web.HTTPFound(
            "/experiments/"
        )
    
    async def _api_get_workspace(
        self,
        request: web.Request,
    ) -> web.Response:
        user = self._require_api_user(request)

        application = request.match_info[
            "application"
        ].strip().lower()

        workspace = self._storage.get_workspace(
            user_id=user.id,
            application=application,
        )

        if workspace is None:
            return web.json_response({
                "application": application,
                "state": None,
            })

        try:
            state = json.loads(workspace.state_json)
        except Exception:
            state = {}

        response = web.json_response({
            "id": workspace.id,
            "application": workspace.application,
            "state": state,
            "updated_at": self._format_timestamp(
                workspace.updated_at
            ),
        })

        self._prepare_no_cache(response)
        return response

    async def _api_save_workspace(
        self,
        request: web.Request,
    ) -> web.Response:
        user = self._require_api_user(request)

        application = request.match_info[
            "application"
        ].strip().lower()

        if application not in {
            "cryolauncher",
            "icesee",
            "livist",
        }:
            raise web.HTTPBadRequest(
                text="Invalid application."
            )

        try:
            payload = await request.json()
        except Exception:
            raise web.HTTPBadRequest(
                text="A valid JSON body is required."
            )

        state = payload.get("state")

        if not isinstance(state, dict):
            raise web.HTTPBadRequest(
                text="state must be a JSON object."
            )

        workspace = self._storage.save_workspace(
            user_id=user.id,
            application=application,
            state_json=json.dumps(
                state,
                sort_keys=True,
            ),
            now=self._clock(),
        )

        response = web.json_response({
            "ok": True,
            "workspace_id": workspace.id,
            "application": workspace.application,
            "updated_at": self._format_timestamp(
                workspace.updated_at
            ),
        })

        self._prepare_no_cache(response)
        return response

    def require_roles(
        self,
        *allowed_roles: str,
    ):
        allowed = {
            role.strip().lower()
            for role in allowed_roles
        }

        async def unauthorized(
            request: web.Request,
        ):
            raise web.HTTPForbidden(
                text=(
                    "You do not have access to "
                    "the CryoStack Control Center."
                )
            )

        def decorator(handler):

            async def protected(
                request: web.Request,
            ):
                user = self.current_user(
                    request
                )

                if user is None:
                    self._redirect_unapproved(request)

                    return_to = (
                        request.path_qs
                    )

                    login_url = (
                        "/auth/login?return_to="
                        + quote(
                            return_to,
                            safe="",
                        )
                    )

                    raise web.HTTPFound(
                        login_url
                    )

                roles = set(
                    self._storage
                    .get_user_roles(
                        user_id=user.id
                    )
                )

                if not roles.intersection(
                    allowed
                ):
                    self._record_access(
                        event_type=access_log.CONTROL_DENIED,
                        outcome="denied",
                        category="missing_role",
                        user_id=user.id,
                        path=request.path,
                    )
                    return await unauthorized(
                        request
                    )

                #
                # IMPORTANT:
                # Make authenticated identity available
                # to all protected handlers.
                #
                request[
                    "cryostack_user"
                ] = user

                request[
                    "cryostack_roles"
                ] = roles

                return await handler(
                    request
                )

            return protected

        return decorator