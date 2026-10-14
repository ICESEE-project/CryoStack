"""Voila configuration for the two gateway-managed application servers.

The gateway (bin/icesee_app.py) puts this directory on JUPYTER_CONFIG_PATH and
passes a per-process token in CRYOSTACK_VOILA_TOKEN to its Voila children only.
Every page, kernel and websocket request must then carry
``Authorization: token <token>``, which only the gateway adds, so a local
process that connects to 127.0.0.1 directly cannot render a notebook with a
forged X-CryoStack-User-Id.

The token is removed from the environment here, before any kernel starts, so
kernels and the processes they launch never inherit it. Without a token Voila
stays closed: a random token nobody knows is used instead.
"""

import os
import secrets

c.Voila.token = (  # noqa: F821 - `c` is provided by the traitlets config loader
    os.environ.pop("CRYOSTACK_VOILA_TOKEN", "") or secrets.token_urlsafe(32)
)
# An external deployment shares the token through a file; kernels do not
# need to know where it is.
os.environ.pop("CRYOSTACK_VOILA_TOKEN_FILE", None)
