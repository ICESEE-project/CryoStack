# ============================================================
# icesee_auth/providers/google.py
# ============================================================

"""Google OpenID Connect sign-in for CryoStack.

Authorization-code flow with PKCE (S256), a ``state`` bound to the browser
session and a per-flow ``nonce``. The ID token is verified with Google's
maintained ``google-auth`` library (signature against Google's published
keys, issuer, audience = our client id, expiry), then CryoStack checks the
nonce and that Google reports the email as verified.

Configuration (server-side only)::

    CRYOSTACK_GOOGLE_CLIENT_ID
    CRYOSTACK_GOOGLE_CLIENT_SECRET_FILE   file holding the client secret
    CRYOSTACK_GOOGLE_REDIRECT_URI         exact https://.../auth/google/callback

The redirect URI is the one registered with Google; it is never built from
the request.
"""

from __future__ import annotations

import asyncio
import hmac
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import aiohttp

from .base import (
    ExternalIdentity,
    OAuthAuthentication,
    OAuthProvider,
)

GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")


class GoogleTokenError(RuntimeError):
    """The ID token failed verification (category in ``.category``)."""

    def __init__(self, message: str, category: str = "provider_error"):
        super().__init__(message)
        self.category = category


def _verify_with_google_auth(id_token: str, audience: str) -> dict:
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token as google_id_token

    return google_id_token.verify_oauth2_token(
        id_token,
        google_requests.Request(),
        audience=audience,
        clock_skew_in_seconds=60,
    )


class GoogleProvider(OAuthProvider):
    name = "google"
    display_name = "Google"

    AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        token_verifier=None,
        token_exchanger=None,
    ) -> None:
        self.client_id = (client_id or "").strip()
        self.client_secret = (client_secret or "").strip()
        self.redirect_uri = (redirect_uri or "").strip()
        #: ``verifier(id_token, audience) -> claims``; raises on failure
        self._token_verifier = token_verifier or _verify_with_google_auth
        #: ``await exchanger(form) -> token response``; tests replace it
        self._token_exchanger = token_exchanger

    @classmethod
    def from_env(cls, env) -> "GoogleProvider":
        secret = env.get("CRYOSTACK_GOOGLE_CLIENT_SECRET", "")
        secret_file = env.get("CRYOSTACK_GOOGLE_CLIENT_SECRET_FILE", "").strip()
        if secret_file:
            try:
                secret = Path(secret_file).read_text(encoding="utf-8").strip()
            except OSError:
                secret = ""
        return cls(
            client_id=env.get("CRYOSTACK_GOOGLE_CLIENT_ID", ""),
            client_secret=secret,
            redirect_uri=env.get("CRYOSTACK_GOOGLE_REDIRECT_URI", ""),
        )

    @property
    def configured(self) -> bool:
        parts = urlsplit(self.redirect_uri)
        trusted = parts.scheme == "https" or parts.hostname in ("localhost", "127.0.0.1")
        return bool(self.client_id and self.client_secret and trusted
                    and parts.path.endswith("/auth/google/callback"))

    def authorization_url(
        self,
        *,
        state: str,
        code_challenge: str | None = None,
        nonce: str | None = None,
    ) -> str:
        if not code_challenge or not nonce:
            raise RuntimeError("Google sign-in requires PKCE and a nonce.")
        return self.AUTHORIZE_URL + "?" + urlencode({
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        })

    async def _exchange(self, form: dict) -> dict:
        if self._token_exchanger is not None:
            return await self._token_exchanger(form)
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as client:
            async with client.post(
                self.TOKEN_URL, data=form, headers={"Accept": "application/json"},
            ) as response:
                try:
                    return await response.json(content_type=None)
                except Exception:
                    raise RuntimeError("Google returned an invalid token response.")

    async def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str | None = None,
    ) -> OAuthAuthentication:
        if not code_verifier:
            raise RuntimeError("Google sign-in requires a PKCE code verifier.")
        result = await self._exchange({
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
        })
        id_token = result.get("id_token") if isinstance(result, dict) else None
        if not id_token:
            raise RuntimeError("Google did not return an ID token.")
        return OAuthAuthentication(access_token=str(id_token))

    async def verify(self, authentication: OAuthAuthentication, *, nonce: str) -> ExternalIdentity:
        """Verify the ID token and return the identity it asserts."""
        id_token = authentication.access_token
        loop = asyncio.get_running_loop()
        try:
            # google-auth fetches Google's keys with a blocking request
            claims = await loop.run_in_executor(
                None, self._token_verifier, id_token, self.client_id)
        except Exception as error:
            raise GoogleTokenError(
                "The Google sign-in token could not be verified.",
                "invalid_token") from error
        if not isinstance(claims, dict):
            raise GoogleTokenError("The Google sign-in token is invalid.", "invalid_token")
        # google-auth checks these too; checked again so a substituted
        # verifier can never weaken them
        if claims.get("iss") not in GOOGLE_ISSUERS:
            raise GoogleTokenError("Unexpected token issuer.", "invalid_token")
        audience = claims.get("aud")
        audiences = audience if isinstance(audience, list) else [audience]
        if self.client_id not in audiences:
            raise GoogleTokenError("Token is for another application.", "invalid_token")
        if len(audiences) > 1 and claims.get("azp") != self.client_id:
            raise GoogleTokenError("Token is for another application.", "invalid_token")
        token_nonce = claims.get("nonce")
        if not isinstance(token_nonce, str) or not hmac.compare_digest(token_nonce, nonce or ""):
            raise GoogleTokenError("The Google sign-in response does not match this request.",
                                   "nonce_mismatch")
        subject = str(claims.get("sub") or "").strip()
        email = str(claims.get("email") or "").strip().lower()
        if not subject:
            raise GoogleTokenError("Google did not identify the account.", "invalid_token")
        if not email or claims.get("email_verified") is not True:
            raise GoogleTokenError(
                "CryoStack needs a verified email address from Google.", "missing_email")
        return ExternalIdentity(
            provider=self.name,
            subject=subject,
            username=email,
            email=email,
            display_name=str(claims.get("name") or "").strip() or None,
            profile_url=None,
        )

    async def fetch_identity(self, authentication: OAuthAuthentication) -> ExternalIdentity:
        raise RuntimeError("Use GoogleProvider.verify(authentication, nonce=...).")
