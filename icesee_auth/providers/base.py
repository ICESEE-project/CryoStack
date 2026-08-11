# ============================================================
# icesee_auth/providers/base.py
# ============================================================

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExternalIdentity:
    """
    Normalized identity returned by an external OAuth provider.

    AuthManager should work with this structure instead of
    provider-specific JSON responses.
    """

    provider: str
    subject: str

    username: str | None = None
    email: str | None = None
    display_name: str | None = None
    profile_url: str | None = None


class OAuthProvider(ABC):
    """
    Base interface implemented by CryoStack OAuth providers.

    Providers are responsible only for communication with the
    external identity service.

    They do NOT manage:
      - CryoStack sessions
      - CryoStack users
      - cookies
      - redirects
      - database identities
    """

    name: str
    display_name: str

    @property
    @abstractmethod
    def configured(self) -> bool:
        """Return True when the provider has required credentials."""

        raise NotImplementedError

    @abstractmethod
    def authorization_url(
        self,
        *,
        state: str,
        code_challenge: str,
    ) -> str:
        """
        Build the external OAuth authorization URL.
        """

        raise NotImplementedError

    @abstractmethod
    async def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str,
    ) -> str:
        """
        Exchange an authorization code for an access token.
        """

        raise NotImplementedError

    @abstractmethod
    async def fetch_identity(
        self,
        access_token: str,
    ) -> ExternalIdentity:
        """
        Retrieve and normalize the authenticated external identity.
        """

        raise NotImplementedError