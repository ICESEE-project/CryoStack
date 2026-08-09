"""Authentication support for the ICESEE web application.

Only :class:`AuthManager` is part of the package's public API.  Keeping the
integration behind that class lets the application add an identity provider
later without spreading authentication details through the route handlers.
"""

from .manager import AuthManager

__all__ = ["AuthManager"]
