# ============================================================
# icesee_auth/providers/orcid.py
# ============================================================

from __future__ import annotations

from urllib.parse import urlencode

import aiohttp

from .base import (
    ExternalIdentity,
    OAuthAuthentication,
    OAuthProvider,
)


class ORCIDProvider(OAuthProvider):
    """
    ORCID OAuth provider.

    Default configuration targets the ORCID sandbox so the
    CryoStack integration can be tested before production use.
    """

    name = "orcid"
    display_name = "ORCID"

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        base_url: str = "https://sandbox.orcid.org",
    ) -> None:

        self.client_id = (
            client_id or ""
        ).strip()

        self.client_secret = (
            client_secret or ""
        ).strip()

        self.redirect_uri = (
            redirect_uri or ""
        ).strip()

        self.base_url = (
            base_url or "https://sandbox.orcid.org"
        ).rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(
            self.client_id
            and self.client_secret
            and self.redirect_uri
        )

    @property
    def authorize_url(self) -> str:
        return (
            self.base_url
            + "/oauth/authorize"
        )

    @property
    def token_url(self) -> str:
        return (
            self.base_url
            + "/oauth/token"
        )

    def authorization_url(
        self,
        *,
        state: str,
        code_challenge: str | None = None,
    ) -> str:

        # ORCID's documented authorization-code flow does not
        # require PKCE parameters, so code_challenge is ignored.

        query = urlencode(
            {
                "client_id": self.client_id,
                "response_type": "code",
                "scope": "/authenticate",
                "redirect_uri": self.redirect_uri,
                "state": state,
            }
        )

        return (
            self.authorize_url
            + "?"
            + query
        )

    async def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str | None = None,
    ) -> OAuthAuthentication:

        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
        }

        headers = {
            "Accept": "application/json",
            "Content-Type": (
                "application/x-www-form-urlencoded"
            ),
        }

        async with aiohttp.ClientSession() as client:
            async with client.post(
                self.token_url,
                data=payload,
                headers=headers,
            ) as response:

                try:
                    result = await response.json()
                except Exception:
                    text = await response.text()

                    raise RuntimeError(
                        "ORCID token endpoint returned "
                        f"an invalid response: {text}"
                    )

                if response.status >= 400:
                    message = (
                        result.get("error_description")
                        or result.get("error")
                        or (
                            "ORCID token exchange failed "
                            f"with HTTP {response.status}."
                        )
                    )

                    raise RuntimeError(
                        str(message)
                    )

        access_token = result.get(
            "access_token"
        )

        orcid_id = str(
            result.get("orcid", "")
        ).strip()

        if not access_token:
            raise RuntimeError(
                "ORCID did not return an access token."
            )

        if not orcid_id:
            raise RuntimeError(
                "ORCID did not return an authenticated "
                "ORCID iD."
            )

        display_name = str(
            result.get("name", "")
        ).strip() or None

        identity = ExternalIdentity(
            provider=self.name,
            subject=orcid_id,
            username=orcid_id,
            email=None,
            display_name=display_name,
            profile_url=(
                f"{self.base_url}/{orcid_id}"
            ),
        )

        return OAuthAuthentication(
            access_token=str(access_token),
            identity=identity,
        )

    async def fetch_identity(
        self,
        authentication: OAuthAuthentication,
    ) -> ExternalIdentity:

        if authentication.identity is None:
            raise RuntimeError(
                "ORCID authentication did not "
                "contain an identity."
            )

        return authentication.identity