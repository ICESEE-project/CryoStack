# ============================================================
# icesee_auth/providers/base.py
# ============================================================

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExternalIdentity:
    """
    Normalized identity returned by an external provider.
    """

    provider: str
    subject: str

    username: str | None = None
    email: str | None = None
    display_name: str | None = None
    profile_url: str | None = None


@dataclass(frozen=True, slots=True)
class OAuthAuthentication:
    """
    Result of a successful provider OAuth exchange.

    Some providers, such as ORCID, return identity information
    during the token exchange itself. Others, such as GitHub,
    require a subsequent profile request.
    """

    access_token: str
    identity: ExternalIdentity | None = None


class OAuthProvider(ABC):
    name: str
    display_name: str

    @property
    @abstractmethod
    def configured(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def authorization_url(
        self,
        *,
        state: str,
        code_challenge: str | None = None,
    ) -> str:
        raise NotImplementedError

    @abstractmethod
    async def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str | None = None,
    ) -> OAuthAuthentication:
        raise NotImplementedError

    @abstractmethod
    async def fetch_identity(
        self,
        authentication: OAuthAuthentication,
    ) -> ExternalIdentity:
        raise NotImplementedError