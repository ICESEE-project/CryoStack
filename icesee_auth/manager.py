"""Session and identity management for the CryoStack web application."""

from __future__ import annotations

import os
import sqlite3
import time
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import quote

import base64
import hashlib
import secrets

from aiohttp import web

from .security import hash_password, safe_return_to, verify_password
from .storage import AuthStorage, SessionRecord, User

from .templates import (
    account_settings_page,
    auth_page,
    configuration_form_page,
    configurations_page,
    login_fields,
    register_fields,
    experiments_page,
    experiment_detail_page,
)

from .providers import (
    GitHubProvider,
    ORCIDProvider,
)

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
    ) -> None:
        if session_ttl_seconds <= 0:
            raise ValueError("session_ttl_seconds must be positive")

        default_database = (
            Path(__file__).resolve().parent.parent
            / "var"
            / "cryostack_auth.db"
        )

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
                "https://sandbox.orcid.org",
            ),
        )

    def install(self, app: web.Application) -> None:
        app.router.add_get("/api/v1/me", self._handle_me)

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
            self._github_callback,
        )

        app.router.add_get(
            "/auth/orcid",
            self._orcid_begin,
        )

        app.router.add_get(
            "/auth/orcid/callback",
            self._orcid_callback,
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

        authenticated = (
            self._storage.authenticate_session(
                flow.session_id,
                user_id=user.id,
                ttl_seconds=(
                    self._session_ttl_seconds
                ),
                now=self._clock(),
            )
        )

        if authenticated is None:
            raise web.HTTPInternalServerError(
                text="Unable to update the session."
            )

        response = web.HTTPFound(
            safe_return_to(
                flow.return_to
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

        authenticated = (
            self._storage.authenticate_session(
                flow.session_id,

                user_id=user.id,

                ttl_seconds=(
                    self._session_ttl_seconds
                ),

                now=self._clock(),
            )
        )

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
            safe_return_to(
                flow.return_to
            )
        )

        self._set_session_cookie(
            request,
            response,
            authenticated.id,
        )

        raise response

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

        response = web.json_response(
            {
                "authenticated": user is not None,
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

        status = str(
            payload.get(
                "status",
                experiment.status,
            )
        ).strip().lower()

        allowed_statuses = {
            "queued",
            "preparing",
            "running",
            "completed",
            "failed",
            "cancelled",
        }

        if status not in allowed_statuses:
            raise web.HTTPBadRequest(
                text="Invalid experiment status."
            )

        previous_status = experiment.status

        updated = self._storage.update_experiment(
            experiment_id=experiment.id,
            user_id=user.id,
            status=status,
            exit_code=payload.get("exit_code"),
            error_message=payload.get(
                "error_message"
            ),
            now=self._clock(),
        )

        if (
            updated is not None
            and updated.status != previous_status
        ):
            self._storage.create_experiment_event(
                experiment_id=updated.id,
                user_id=user.id,
                event_type=updated.status,
                message=(
                    f"Experiment status changed from "
                    f"{previous_status} to {updated.status}."
                ),
                metadata_json=json.dumps(
                    {
                        "previous_status": previous_status,
                        "status": updated.status,
                        "job_id": updated.job_id,
                        "exit_code": updated.exit_code,
                    },
                    sort_keys=True,
                ),
                now=self._clock(),
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
            raise web.HTTPFound(return_to)

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
        user = self._storage.get_user_by_email(email)

        if user is None or not verify_password(
            password,
            user.password_hash,
        ):
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

        authenticated = self._storage.authenticate_session(
            session.id,
            user_id=user.id,
            ttl_seconds=self._session_ttl_seconds,
            now=self._clock(),
        )

        if authenticated is None:
            raise web.HTTPInternalServerError(
                text="Unable to update the session."
            )

        response = web.HTTPFound(return_to)
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
            raise web.HTTPFound(return_to)

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

        try:
            user = self._storage.create_user(
                email=email,
                display_name=display_name,
                institution=institution or None,
                password_hash=hash_password(password),
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

        authenticated = self._storage.authenticate_session(
            session.id,
            user_id=user.id,
            ttl_seconds=self._session_ttl_seconds,
            now=self._clock(),
        )

        if authenticated is None:
            raise web.HTTPInternalServerError(
                text="Unable to update the session."
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
            self._storage.delete_session(session_id)

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

    def current_user(
        self,
        request: web.Request,
    ) -> User | None:
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

        return self._storage.get_user_by_id(
            session.user_id
        )


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
                    "administrator",
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
        )

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

    # @staticmethod
    def _experiment_to_dict(experiment) -> dict:
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
            status=str(
                payload.get("status", "queued")
            ),
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

        allowed_statuses = {
            "queued",
            "preparing",
            "running",
            "completed",
            "failed",
            "cancelled",
        }

        status = payload.get("status")

        if status is not None:
            status = str(status).strip().lower()

            if status not in allowed_statuses:
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

        previous_status = experiment.status
        experiment = self._storage.update_experiment(
            experiment_id=request.match_info[
                "experiment_id"
            ],
            user_id=user.id,
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
            exit_code=payload.get("exit_code"),
            error_message=payload.get(
                "error_message"
            ),
            metadata_json=(
                json.dumps(metadata, sort_keys=True)
                if metadata is not None
                else None
            ),
            now=self._clock(),
        )

        if (
            updated is not None
            and updated.status != previous_status
        ):
            self._storage.create_experiment_event(
                experiment_id=updated.id,
                user_id=user.id,
                event_type=updated.status,
                message=(
                    f"Experiment status changed from "
                    f"{previous_status} to {updated.status}."
                ),
                metadata_json=json.dumps(
                    {
                        "previous_status": previous_status,
                        "status": updated.status,
                        "job_id": updated.job_id,
                        "exit_code": updated.exit_code,
                    },
                    sort_keys=True,
                ),
                now=self._clock(),
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

        def decorator(handler):

            async def protected(
                request: web.Request,
            ):
                user = self.current_user(
                    request
                )

                if user is None:
                    return_to = request.path_qs

                    raise web.HTTPFound(
                        "/auth/login?return_to="
                        + quote(
                            return_to,
                            safe="",
                        )
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
                    raise web.HTTPForbidden(
                        text=(
                            "You do not have access "
                            "to the CryoStack "
                            "Control Center."
                        )
                    )

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