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

    def authenticated_user(self, request: web.Request):
        session_id = request.cookies.get(self._cookie_name)

        if not session_id:
            return None

        session = self._sessions.get(session_id)

        if session is None:
            return None

        if session.user is None:
            return None

        return session.user

    def require_login(self, handler):

        async def wrapped(request):

            user = self.authenticated_user(request)

            if user is None:
                raise web.HTTPFound(
                    "/login?next=" + request.path_qs
                )

            request["user"] = user

            return await handler(request)

        return wrapped

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

        response = web.Response(
            text=account_settings_page(user=user),
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
            response = web.Response(
                text=account_settings_page(
                    user=user,
                    error="Please enter a valid display name.",
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

        response = web.Response(
            text=account_settings_page(
                user=updated_user,
                message="Your account settings were updated.",
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

        configurations = self._storage.list_configurations(
            user_id=user.id,
        )

        response = web.Response(
            text=configurations_page(
                user=user,
                configurations=configurations,
                message=request.query.get("message"),
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

    def current_user(self, request: web.Request) -> User | None:
        """Return the authenticated user for the current request."""

        session_id = request.cookies.get(self._cookie_name)

        if not session_id:
            return None

        session = self._storage.get_session(
            session_id,
            now=self._clock(),
        )

        if session is None or not session.user_id:
            return None

        return self._storage.get_user_by_id(session.user_id)


    def require_login(self, handler):
        """Protect an aiohttp route while preserving its destination."""

        async def protected(request: web.Request) -> web.StreamResponse:
            user = self.current_user(request)

            if user is None:
                return_to = safe_return_to(
                    request.path_qs,
                    default="/index.html",
                )

                login_url = (
                    "/auth/login?return_to="
                    + quote(return_to, safe="")
                )

                raise web.HTTPFound(login_url)

            request["cryostack_user"] = user
            return await handler(request)

        return protected

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

    def current_user(self, request: web.Request) -> User | None:
        """Return the authenticated user associated with this request."""

        session_id = request.cookies.get(self._cookie_name)

        if not session_id:
            return None

        session = self._storage.get_session(
            session_id,
            now=self._clock(),
        )

        if session is None or not session.user_id:
            return None

        return self._storage.get_user_by_id(session.user_id)


    def require_login(self, handler):
        """Wrap an aiohttp route so only authenticated users can access it."""

        async def protected(
            request: web.Request,
        ) -> web.StreamResponse:
            user = self.current_user(request)

            if user is None:
                return_to = safe_return_to(
                    request.path_qs,
                    default="/index.html",
                )

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

    @staticmethod
    def _public_user(user: User | None) -> dict | None:
        if user is None:
            return None

        return {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "institution": user.institution,
            "research_role": user.research_role,
            "country": user.country,
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
