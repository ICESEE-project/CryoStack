from .base import (
    ExternalIdentity,
    OAuthAuthentication,
    OAuthProvider,
)

from .github import GitHubProvider
from .orcid import ORCIDProvider


__all__ = [
    "ExternalIdentity",
    "OAuthAuthentication",
    "OAuthProvider",
    "GitHubProvider",
    "ORCIDProvider",
]