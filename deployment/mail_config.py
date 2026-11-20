"""Load private mail configuration without executing the configuration as code."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import stat
import sys

ALLOWED = frozenset({
    "CRYOSTACK_MAIL_MODE", "CRYOSTACK_MAIL_FROM", "CRYOSTACK_PUBLIC_BASE_URL",
    "CRYOSTACK_SMTP_HOST", "CRYOSTACK_SMTP_PORT", "CRYOSTACK_SMTP_SECURITY",
    "CRYOSTACK_SMTP_TLS_POLICY",
    "CRYOSTACK_SMTP_USERNAME", "CRYOSTACK_SMTP_PASSWORD_FILE",
    "CRYOSTACK_RESEND_API_KEY_FILE", "CRYOSTACK_POSTMARK_SERVER_TOKEN_FILE",
    "CRYOSTACK_MAIL_FILE_DIR",
})


def exports(path: Path) -> str:
    # O_NOFOLLOW also protects the check/read against a symlink replacement.
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, encoding="utf-8") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("mail configuration must be a regular file")
        if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
            raise ValueError("mail configuration must be owned by the service user and mode 0600")
        raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError("mail configuration is too large")
        settings = json.loads(raw)
    if not isinstance(settings, dict) or settings.keys() - ALLOWED:
        raise ValueError("mail configuration contains unsupported settings")
    if any(not isinstance(value, str) or "\0" in value for value in settings.values()):
        raise ValueError("mail configuration values must be strings without NUL characters")
    return "\n".join(f"export {key}={shlex.quote(value)}" for key, value in sorted(settings.items()))


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2:
            raise ValueError("usage: mail_config.py /path/to/private/mail.json")
        print(exports(Path(sys.argv[1])))
    except (OSError, ValueError) as error:
        # Never echo values from a malformed configuration.
        print(f"[CryoStack] Cannot load private mail configuration ({type(error).__name__}).", file=sys.stderr)
        sys.exit(1)
