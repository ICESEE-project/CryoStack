# ============================================================
# icesee_auth/providers/github.py
# ============================================================

from __future__ import annotations

from urllib.parse import urlencode

import aiohttp

from .base import (
    ExternalIdentity,
    OAuthAuthentication,
    OAuthProvider,
)


class GitHubProvider(OAuthProvider):
    """
    GitHub OAuth provider for CryoStack.
    """

    name = "github"
    display_name = "GitHub"

    AUTHORIZE_URL = (
        "https://github.com/login/oauth/authorize"
    )

    TOKEN_URL = (
        "https://github.com/login/oauth/access_token"
    )

    USER_URL = (
        "https://api.github.com/user"
    )

    EMAILS_URL = (
        "https://api.github.com/user/emails"
    )

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
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

    @property
    def configured(self) -> bool:
        return bool(
            self.client_id
            and self.client_secret
            and self.redirect_uri
        )

    def authorization_url(
        self,
        *,
        state: str,
        code_challenge: str | None = None,
    ) -> str:

        if not code_challenge:
            raise RuntimeError(
                "GitHub authentication requires PKCE."
            )

        query = urlencode(
            {
                "client_id": self.client_id,

                "redirect_uri": (
                    self.redirect_uri
                ),

                "scope": (
                    "read:user user:email"
                ),

                "state": state,

                "code_challenge": (
                    code_challenge
                ),

                "code_challenge_method": (
                    "S256"
                ),
            }
        )

        return (
            self.AUTHORIZE_URL
            + "?"
            + query
        )

    async def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str | None = None,
    ) -> OAuthAuthentication:

        if not code_verifier:
            raise RuntimeError(
                "GitHub authentication requires "
                "a PKCE code verifier."
            )

        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": self.redirect_uri,
            "code_verifier": code_verifier,
        }

        headers = {
            "Accept": "application/json",
        }

        async with aiohttp.ClientSession() as client:
            async with client.post(
                self.TOKEN_URL,
                data=payload,
                headers=headers,
            ) as response:
                try:
                    result = await response.json()
                except Exception:
                    text = await response.text()

                    raise RuntimeError(
                        "GitHub token endpoint returned "
                        f"an invalid response: {text}"
                    )

        access_token = result.get("access_token")

        if not access_token:
            error = (
                result.get("error_description")
                or result.get("error")
                or "GitHub did not return an access token."
            )

            raise RuntimeError(str(error))

        return OAuthAuthentication(
            access_token=str(access_token),
        )

    async def fetch_identity(
        self,
        authentication: OAuthAuthentication,
    ) -> ExternalIdentity:

        access_token = authentication.access_token

        if not access_token:
            raise RuntimeError(
                "GitHub authentication did not "
                "contain an access token."
            )

        headers = {
            "Accept": (
                "application/vnd.github+json"
            ),

            "Authorization": (
                f"Bearer {access_token}"
            ),

            "X-GitHub-Api-Version": (
                "2022-11-28"
            ),

            "User-Agent": (
                "CryoStack"
            ),
        }

        async with aiohttp.ClientSession() as client:

            async with client.get(
                self.USER_URL,
                headers=headers,
            ) as response:

                if response.status != 200:
                    text = await response.text()

                    raise RuntimeError(
                        "Unable to retrieve GitHub "
                        "identity. "
                        f"HTTP {response.status}: "
                        f"{text}"
                    )

                profile = await response.json()

            async with client.get(
                self.EMAILS_URL,
                headers=headers,
            ) as response:

                if response.status == 200:
                    emails = await response.json()
                else:
                    emails = []

        github_id = str(
            profile.get("id", "")
        ).strip()

        if not github_id:
            raise RuntimeError(
                "GitHub did not return a valid "
                "user identifier."
            )

        username = str(
            profile.get("login", "")
        ).strip() or None

        display_name = str(
            profile.get("name", "")
        ).strip() or username

        profile_url = str(
            profile.get("html_url", "")
        ).strip() or None

        email = self._verified_email(
            profile,
            emails,
        )

        return ExternalIdentity(
            provider=self.name,
            subject=github_id,
            username=username,
            email=email,
            display_name=display_name,
            profile_url=profile_url,
        )

    @staticmethod
    def _verified_email(
        profile: dict,
        emails: list[dict],
    ) -> str | None:

        # ----------------------------------------------------
        # Prefer primary + verified
        # ----------------------------------------------------

        for item in emails:

            if (
                item.get("primary") is True
                and item.get("verified") is True
                and item.get("email")
            ):

                return str(
                    item["email"]
                ).strip().lower()

        # ----------------------------------------------------
        # Otherwise use any verified email
        # ----------------------------------------------------

        for item in emails:

            if (
                item.get("verified") is True
                and item.get("email")
            ):

                return str(
                    item["email"]
                ).strip().lower()

        # ----------------------------------------------------
        # GitHub profile.email can be public but we should
        # avoid using it unless verification information is
        # available from /user/emails.
        # ----------------------------------------------------

        return None