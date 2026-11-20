"""Account email: a durable, de-duplicated outbox and its delivery.

Messages are never sent inline from a request. A request writes one row to
``notification_outbox`` (in the auth database) with a ``dedupe_key``; a
second request for the same key is a no-op, so an administrator is told
about a registration once however often the applicant retries. A background
worker delivers due rows, backing off after each failure (1 min, 2, 4 ...
capped at 1 h) and marking a row ``failed`` after ``MAX_ATTEMPTS``, where
Control Center shows it with a retry button. A mail outage only delays
notices: approval never depends on delivery.

Delivery is configured entirely by environment (see the operator guide)::

    CRYOSTACK_MAIL_MODE            disabled (default) | file | smtp | resend | postmark
    CRYOSTACK_MAIL_FROM            provider-authorized sender address
    CRYOSTACK_PUBLIC_BASE_URL      https://... origin used for every link
    CRYOSTACK_SMTP_HOST / _PORT    relay host, port (587)
    CRYOSTACK_SMTP_SECURITY        starttls (default) | ssl
    CRYOSTACK_SMTP_USERNAME        optional
    CRYOSTACK_SMTP_PASSWORD_FILE   file holding the password (never the env)
    CRYOSTACK_RESEND_API_KEY_FILE  file holding a Resend API key
    CRYOSTACK_POSTMARK_SERVER_TOKEN_FILE  file holding a Postmark server token
    CRYOSTACK_MAIL_FILE_DIR        file mode: where .eml files are written
    CRYOSTACK_APPROVAL_ADMIN_EMAILS  comma-separated reviewer addresses

``disabled`` keeps every message queued and sends nothing, which is the
state to review the feature in. ``file`` writes each message to a directory
instead of sending it. Links are built from ``CRYOSTACK_PUBLIC_BASE_URL``,
never from the request's Host header.

Reviewer addresses come from the configured policy-role list and the
owner-managed registration-approver list. Delegates are used only while
their account remains approved and their bound email is confirmed; no
address is inferred. Message context that carries a one-time link is scrubbed from
the row once the message is delivered.

An outbox ``sent`` state means the transport accepted the message (or file
mode wrote it), not that it reached an inbox. Provider receipt identifiers
are logged for subsequent delivery/bounce investigation in that provider.
Selecting a provider is explicit; ambiguous failures never trigger an
automatic cross-provider resend.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import smtplib
import ssl
import stat
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path
from urllib.parse import quote, urlsplit
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from .approval import ApprovalStore, PASSWORD_RESET, VERIFY_EMAIL, decision_roles, new_id
from .registration_approvers import RegistrationApproverStore

MODES = ("disabled", "file", "smtp", "resend", "postmark")
MAX_ATTEMPTS = 10
STALE_SENDING_S = 600
SMTP_TIMEOUT_S = 20
LOGGER = logging.getLogger(__name__)
MAX_API_RESPONSE_BYTES = 65536
MAX_CREDENTIAL_BYTES = 4096

#: context keys that hold a one-time secret, removed after delivery
SECRET_CONTEXT_KEYS = ("token",)


class MailConfigError(RuntimeError):
    pass


class MailDeliveryError(RuntimeError):
    """A malformed or rejected provider response; its body is never retained."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward provider credentials or one-time links to a redirect.
        return None


def _safe_error(error: Exception) -> str:
    """Only an exception class and numeric protocol status may reach logs/DB."""
    name = type(error).__name__
    if isinstance(error, HTTPError):
        return f"{name} HTTP {int(error.code)}"
    if isinstance(error, smtplib.SMTPResponseException):
        return f"{name} SMTP {int(error.smtp_code)}"
    return name


def _read_api_credential(path: str) -> str:
    """Read a bounded, private, current-user regular file without following links."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or info.st_size > MAX_CREDENTIAL_BYTES):
            raise MailConfigError("Provider credential file must be private and owned by the service user.")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(MAX_CREDENTIAL_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(raw) > MAX_CREDENTIAL_BYTES:
        raise MailConfigError("Provider credential file is too large.")
    lines = raw.decode("utf-8").splitlines()
    credential = lines[0].strip() if len(lines) == 1 else ""
    if not credential or any(not 33 <= ord(character) <= 126 for character in credential):
        raise MailConfigError("Provider credential file must contain one nonempty token.")
    return credential


@dataclass(frozen=True)
class MailConfig:
    mode: str = "disabled"
    sender: str = ""
    base_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_security: str = "starttls"
    smtp_tls_policy: str = "verified"
    smtp_username: str = ""
    smtp_password_file: str = ""
    resend_api_key_file: str = ""
    postmark_server_token_file: str = ""
    file_dir: str = ""
    admin_emails: tuple[str, ...] = ()

    @classmethod
    def from_env(cls, env=None) -> "MailConfig":
        env = os.environ if env is None else env
        try:
            port = int(env.get("CRYOSTACK_SMTP_PORT", "587") or 587)
        except ValueError:
            port = -1
        admins = tuple(sorted({
            part.strip().lower()
            for part in env.get("CRYOSTACK_APPROVAL_ADMIN_EMAILS", "").split(",")
            if part.strip()
        }))
        return cls(
            mode=(env.get("CRYOSTACK_MAIL_MODE", "disabled") or "disabled").strip().lower(),
            sender=env.get("CRYOSTACK_MAIL_FROM", "").strip(),
            base_url=env.get("CRYOSTACK_PUBLIC_BASE_URL", "").strip().rstrip("/"),
            smtp_host=env.get("CRYOSTACK_SMTP_HOST", "").strip(),
            smtp_port=port,
            smtp_security=(env.get("CRYOSTACK_SMTP_SECURITY", "starttls") or "starttls").strip().lower(),
            smtp_tls_policy=env.get("CRYOSTACK_SMTP_TLS_POLICY", "verified").strip().lower(),
            smtp_username=env.get("CRYOSTACK_SMTP_USERNAME", "").strip(),
            smtp_password_file=env.get("CRYOSTACK_SMTP_PASSWORD_FILE", "").strip(),
            resend_api_key_file=env.get("CRYOSTACK_RESEND_API_KEY_FILE", "").strip(),
            postmark_server_token_file=env.get("CRYOSTACK_POSTMARK_SERVER_TOKEN_FILE", "").strip(),
            file_dir=env.get("CRYOSTACK_MAIL_FILE_DIR", "").strip(),
            admin_emails=admins,
        )

    @property
    def delivers(self) -> bool:
        return self.mode in ("file", "smtp", "resend", "postmark")

    def problems(self) -> list[str]:
        """Configuration errors; empty when delivery can be attempted."""
        found = []
        if self.mode not in MODES:
            return [f"CRYOSTACK_MAIL_MODE must be one of {', '.join(MODES)}."]
        if not self.delivers:
            return found
        if "@" not in self.sender:
            found.append("CRYOSTACK_MAIL_FROM must be a sender address.")
        parts = urlsplit(self.base_url)
        if parts.scheme != "https" or not parts.netloc or parts.path not in ("", "/"):
            found.append("CRYOSTACK_PUBLIC_BASE_URL must be an https:// origin.")
        if self.mode == "file" and not self.file_dir:
            found.append("CRYOSTACK_MAIL_FILE_DIR is required in file mode.")
        if self.mode == "resend" and not self.resend_api_key_file:
            found.append("CRYOSTACK_RESEND_API_KEY_FILE is required in resend mode.")
        if self.mode == "postmark" and not self.postmark_server_token_file:
            found.append("CRYOSTACK_POSTMARK_SERVER_TOKEN_FILE is required in postmark mode.")
        if self.mode == "smtp":
            if not self.smtp_host:
                found.append("CRYOSTACK_SMTP_HOST is required in smtp mode.")
            if not 0 < self.smtp_port < 65536:
                found.append("CRYOSTACK_SMTP_PORT must be a port number.")
            if self.smtp_security not in ("starttls", "ssl"):
                found.append("CRYOSTACK_SMTP_SECURITY must be starttls or ssl.")
            if self.smtp_username and not self.smtp_password_file:
                found.append("CRYOSTACK_SMTP_PASSWORD_FILE is required with a username.")
            if self.smtp_tls_policy not in ("verified", "gt-relay-exception"):
                found.append("CRYOSTACK_SMTP_TLS_POLICY must be verified or gt-relay-exception.")
            elif self.smtp_tls_policy == "gt-relay-exception" and (
                    self.smtp_host != "outbound.mail.gatech.edu" or self.smtp_port != 25
                    or self.smtp_security != "starttls" or self.smtp_username
                    or self.smtp_password_file):
                found.append("The GT TLS exception requires outbound.mail.gatech.edu:25, STARTTLS and no SMTP credentials.")
        return found

    def public(self) -> dict:
        """What Control Center may show: no password, no file contents."""
        return {
            "mode": self.mode,
            "sender": self.sender,
            "base_url": self.base_url,
            "smtp_host": self.smtp_host if self.mode == "smtp" else "",
            "smtp_tls_policy": self.smtp_tls_policy if self.mode == "smtp" else "",
            "reviewers_configured": len(self.admin_emails),
            "problems": self.problems(),
        }


# ── templates ──────────────────────────────────────────────────────────

def _link(config: MailConfig, path: str) -> str:
    return f"{config.base_url}{path}"


def render(template: str, context: dict, config: MailConfig) -> tuple[str, str]:
    """``(subject, plain-text body)`` for one outbox row."""
    name = context.get("display_name") or "there"
    if template == "verify_email":
        return (
            "Confirm your CryoStack email address",
            f"Hello {name},\n\n"
            "Please confirm this address for your new CryoStack account:\n\n"
            f"{_link(config, '/auth/verify-email?token=' + quote(context['token']))}\n\n"
            "The link works once and expires in 3 days. After you confirm, "
            "a CryoStack administrator reviews the registration; you will "
            "receive another email with the decision.\n\n"
            "If you did not register, ignore this message.\n",
        )
    if template == "registration_exists":
        return (
            "CryoStack registration attempt",
            "Someone tried to register a new CryoStack account with this "
            "address, which already has an account.\n\n"
            f"Sign in: {_link(config, '/auth/login')}\n"
            f"Forgot your password? {_link(config, '/auth/forgot')}\n\n"
            "If this was not you, no action is needed.\n",
        )
    if template == "password_reset":
        return (
            "Reset your CryoStack password",
            f"Hello {name},\n\n"
            "Use this link to choose a new CryoStack password:\n\n"
            f"{_link(config, '/auth/reset?token=' + quote(context['token']))}\n\n"
            "The link works once and expires in 1 hour. Resetting your "
            "password signs you out everywhere.\n\n"
            "If you did not ask for this, ignore this message; your password "
            "is unchanged.\n",
        )
    if template == "applicant_pending":
        return (
            "Your CryoStack registration is awaiting review",
            f"Hello {name},\n\n"
            "Thank you for registering. A CryoStack administrator will review "
            "your account; you will receive an email when it is decided. "
            "Until then you can sign in to see your status, but applications, "
            "storage and computing are not available.\n\n"
            f"Status: {_link(config, '/auth/status')}\n",
        )
    if template == "admin_review":
        return (
            "CryoStack registration needs review",
            "A new CryoStack registration is waiting for review.\n\n"
            f"Name: {context.get('applicant_name', '')}\n"
            f"Institution: {context.get('institution') or '-'}\n"
            f"Registered with: {context.get('method', '')}\n\n"
            "Review it in Control Center (sign-in required; nothing is "
            "approved from this email):\n\n"
            f"{_link(config, '/control/registrations?user=' + quote(context['user_id']))}\n",
        )
    if template == "decision":
        status = context.get("status")
        text = {
            "approved": (
                "Your CryoStack account has been approved. You can now sign "
                "in and use the applications. Your private workspace is being "
                "prepared; it is usually ready within a few minutes.\n\n"
                f"Sign in: {_link(config, '/auth/login')}\n"
            ),
            "rejected": (
                "Your CryoStack registration was not approved. If you think "
                "this is a mistake, reply to the person who invited you.\n"
            ),
            "suspended": (
                "Your CryoStack account has been suspended and you have been "
                "signed out. Your files are kept. Contact the CryoStack "
                "organizers if you have questions.\n"
            ),
        }.get(status)
        if text is None:
            raise MailConfigError("unknown decision")
        subject = {
            "approved": "Your CryoStack account is approved",
            "rejected": "Your CryoStack registration",
            "suspended": "Your CryoStack account is suspended",
        }[status]
        return subject, f"Hello {name},\n\n{text}"
    raise MailConfigError(f"unknown template {template!r}")


def build_message(row: dict, config: MailConfig) -> EmailMessage:
    context = json.loads(row["context_json"] or "{}")
    subject, body = render(row["template"], context, config)
    message = EmailMessage()
    message["From"] = config.sender
    message["To"] = row["recipient"]
    message["Subject"] = subject
    message["Date"] = formatdate(float(row["created_at"]), localtime=False)
    identity = hashlib.sha256(str(row["id"]).encode("utf-8")).hexdigest()
    domain = config.sender.rsplit("@", 1)[-1].rstrip(">")
    message["Message-ID"] = f"<{identity}@{domain}>"
    message["X-CryoStack-Outbox-ID"] = str(row["id"])
    message["Auto-Submitted"] = "auto-generated"
    message.set_content(body)
    return message


# ── outbox ─────────────────────────────────────────────────────────────

class Outbox:
    def __init__(self, storage, *, config: MailConfig | None = None,
                 clock=time.time, transport=None) -> None:
        self._storage = storage
        self._clock = clock
        self.config = config or MailConfig.from_env()
        #: ``transport(message, config)``; default by mode
        self._transport = transport
        self._blocked_state = None

    def _event(self, event: str, row: dict | None = None, *, warning=False, **fields) -> None:
        """Structured metadata only: never addresses, message content or tokens."""
        data = {"event": event,
                "provider": self.config.mode if self.config.mode in MODES else "invalid"}
        if self.config.mode == "smtp":
            data["tls_policy"] = self.config.smtp_tls_policy
        if row is not None:
            data.update(outbox_id=row["id"], template=row["template"])
        data.update(fields)
        LOGGER.log(logging.WARNING if warning else logging.INFO,
                   "cryostack_mail %s", json.dumps(data, sort_keys=True))

    def _connect(self):
        return self._storage._connect()

    def enqueue(self, *, dedupe_key: str, template: str, recipient: str,
                context: dict, user_id: str | None = None) -> bool:
        """Queue one message; ``False`` when that key was already queued."""
        now = self._clock()
        row_id = new_id()
        with self._connect() as connection:
            inserted = connection.execute(
                """
                INSERT INTO notification_outbox (
                    id, dedupe_key, template, user_id, recipient, context_json,
                    status, attempts, next_attempt_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 'queued', 0, ?, ?, ?)
                ON CONFLICT(dedupe_key) DO NOTHING
                """,
                (row_id, dedupe_key[:300], template, user_id,
                 recipient.strip().lower(), json.dumps(context, sort_keys=True),
                 now, now, now),
            ).rowcount
        if inserted:
            self._event("queued", {"id": row_id, "template": template})
        return bool(inserted)

    def reviewers(self) -> tuple[list[str], list[str]]:
        """``(authorized, refused)`` configured reviewer addresses."""
        delegates = set(RegistrationApproverStore(self._storage).authorized_emails())
        authorized, refused = list(delegates), []
        with self._connect() as connection:
            for email in self.config.admin_emails:
                row = connection.execute(
                    """
                    SELECT u.id FROM users u
                    JOIN account_status a ON a.user_id = u.id
                    WHERE u.email = ? COLLATE NOCASE AND a.status = 'approved'
                    """,
                    (email,),
                ).fetchone()
                roles = set() if row is None else {
                    r["role"] for r in connection.execute(
                        "SELECT role FROM user_roles WHERE user_id = ?", (row["id"],))
                }
                (authorized if roles & decision_roles() or email in delegates else refused).append(email)
        return sorted(set(authorized)), sorted(set(refused))

    def notify_reviewers(self, *, user, method: str) -> int:
        """Queue one review notice per authorized reviewer, once per account."""
        authorized, _refused = self.reviewers()
        queued = 0
        for email in authorized:
            queued += self.enqueue(
                dedupe_key=f"admin_review:{user.id}:{email}",
                template="admin_review",
                recipient=email,
                user_id=user.id,
                context={
                    "user_id": user.id,
                    "applicant_name": user.display_name,
                    "institution": user.institution or "",
                    "method": method,
                },
            )
        return queued

    def reactivate_reviewer_notices(self, *, user_id: str) -> int:
        """Restore cancelled backlog notices after an owner re-grants a delegate.

        This never retries token mail, decided accounts, or already accepted
        notices. The recipient must still be an active explicit delegate.
        """
        now = self._clock()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT n.id,n.template FROM notification_outbox n
                JOIN account_status applicant ON applicant.user_id = n.user_id
                WHERE n.user_id = ? AND n.template = 'admin_review' AND n.status = 'cancelled'
                  AND n.sent_at IS NULL
                  AND applicant.status = 'pending' AND applicant.email_verified_at IS NOT NULL
                  AND EXISTS (
                    SELECT 1 FROM registration_approvers r
                    JOIN users u ON u.id = r.user_id
                    JOIN account_status reviewer ON reviewer.user_id = u.id
                    WHERE r.email = n.recipient COLLATE NOCASE
                      AND u.email = r.email COLLATE NOCASE
                      AND reviewer.status = 'approved' AND reviewer.email_verified_at IS NOT NULL
                  )
                """, (user_id,),
            ).fetchall()
            for row in rows:
                connection.execute(
                    "UPDATE notification_outbox SET status='queued',attempts=0,last_error=NULL,"
                    "next_attempt_at=?,updated_at=? WHERE id=? AND status='cancelled'",
                    (now, now, row["id"]),
                )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        for row in rows:
            self._event("queued", dict(row), reason="delegate_reauthorized")
        return len(rows)

    # delivery ─────────────────────────────────────────────────────────

    def _due(self, limit: int) -> list[dict]:
        now = self._clock()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE notification_outbox SET status = 'queued', updated_at = ?
                WHERE status = 'sending' AND updated_at < ?
                """,
                (now, now - STALE_SENDING_S),
            )
            rows = connection.execute(
                """
                SELECT * FROM notification_outbox
                WHERE status = 'queued' AND next_attempt_at <= ?
                ORDER BY next_attempt_at LIMIT ?
                """,
                (now, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def _claim(self, row_id: str) -> bool:
        with self._connect() as connection:
            return bool(connection.execute(
                """
                UPDATE notification_outbox
                SET status = 'sending', attempts = attempts + 1, updated_at = ?
                WHERE id = ? AND status = 'queued'
                """,
                (self._clock(), row_id),
            ).rowcount)

    def _still_wanted(self, row: dict) -> bool:
        """Drop obsolete notices and expired, used or superseded email links."""
        if row["template"] in (VERIFY_EMAIL, PASSWORD_RESET):
            context = json.loads(row["context_json"] or "{}")
            token = context.get("token", "")
            return bool(row["user_id"] and ApprovalStore(
                self._storage, clock=self._clock).peek_token(
                    token, row["template"]) == row["user_id"])
        if row["template"] != "admin_review" or not row["user_id"]:
            return True
        with self._connect() as connection:
            found = connection.execute(
                "SELECT status FROM account_status WHERE user_id = ?",
                (row["user_id"],),
            ).fetchone()
        if found is None or found["status"] != "pending":
            return False
        authorized, _ = self.reviewers()
        return row["recipient"] in authorized

    def _finish(self, row: dict, *, status: str, error: str | None = None) -> None:
        now = self._clock()
        context = json.loads(row["context_json"] or "{}")
        if status in ("sent", "cancelled"):
            for key in SECRET_CONTEXT_KEYS:
                if key in context:
                    context[key] = "[removed]"
        attempts = int(row["attempts"]) + 1
        if status == "retry":
            status = "failed" if attempts >= MAX_ATTEMPTS else "queued"
        delay = min(60 * 2 ** max(attempts - 1, 0), 3600)
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE notification_outbox
                SET status = ?, last_error = ?, context_json = ?, updated_at = ?,
                    next_attempt_at = ?, sent_at = CASE WHEN ? = 'sent' THEN ? ELSE sent_at END
                WHERE id = ?
                """,
                (status, (error or None) and error[:300],
                 json.dumps(context, sort_keys=True), now, now + delay,
                 status, now, row["id"]),
            )

    def _send_api(self, message: EmailMessage) -> str:
        """Submit to a fixed HTTPS endpoint; success means provider acceptance."""
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                   "User-Agent": "CryoStack-account-mail/1"}
        mail_headers = {name: str(message[name])
                        for name in ("Message-ID", "Date", "Auto-Submitted")}
        if self.config.mode == "resend":
            endpoint = "https://api.resend.com/emails"
            credential_path = self.config.resend_api_key_file
            payload = {"from": str(message["From"]), "to": [str(message["To"])],
                       "subject": str(message["Subject"]), "text": message.get_content(),
                       "headers": mail_headers}
        else:
            endpoint = "https://api.postmarkapp.com/email"
            credential_path = self.config.postmark_server_token_file
            payload = {"From": str(message["From"]), "To": str(message["To"]),
                       "Subject": str(message["Subject"]), "TextBody": message.get_content(),
                       "Headers": [{"Name": name, "Value": value}
                                   for name, value in mail_headers.items()],
                       "MessageStream": "outbound", "TrackOpens": False,
                       "TrackLinks": "None"}
        credential = _read_api_credential(credential_path)
        if self.config.mode == "resend":
            headers["Authorization"] = "Bearer " + credential
            # Resend retains this key for 24 hours. Every retry uses the same
            # row identity and payload; no token or recipient enters the key.
            headers["Idempotency-Key"] = "cryostack/" + str(message["X-CryoStack-Outbox-ID"])
        else:
            headers["X-Postmark-Server-Token"] = credential
        request = Request(endpoint, data=json.dumps(payload, sort_keys=True).encode("utf-8"),
                          headers=headers, method="POST")
        opener = build_opener(HTTPSHandler(context=ssl.create_default_context()), _NoRedirect())
        with opener.open(request, timeout=SMTP_TIMEOUT_S) as response:
            if not 200 <= response.status < 300:
                raise HTTPError(endpoint, response.status, "Provider rejected submission", {}, None)
            raw = response.read(MAX_API_RESPONSE_BYTES + 1)
        if len(raw) > MAX_API_RESPONSE_BYTES:
            raise MailDeliveryError("Oversized provider response.")
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError) as error:
            raise MailDeliveryError("Invalid provider response.") from error
        if not isinstance(result, dict):
            raise MailDeliveryError("Invalid provider response.")
        if self.config.mode == "postmark" and (
                type(result.get("ErrorCode")) is not int or result["ErrorCode"] != 0):
            raise MailDeliveryError("Provider rejected submission.")
        receipt = result.get("id" if self.config.mode == "resend" else "MessageID")
        if not isinstance(receipt, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", receipt):
            raise MailDeliveryError("Provider receipt is missing or invalid.")
        return receipt

    def _send(self, message: EmailMessage) -> str | None:
        if self.config.mode == "smtp" and self.config.problems():
            raise MailConfigError("Invalid SMTP configuration.")
        if self._transport is not None:
            return self._transport(message, self.config)
        if self.config.mode in ("resend", "postmark"):
            return self._send_api(message)
        if self.config.mode == "file":
            directory = Path(self.config.file_dir)
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            name = f"{int(self._clock() * 1000)}-{new_id()[:8]}.eml"
            target = directory / name
            target.write_bytes(bytes(message))
            os.chmod(target, 0o600)
            return
        password = ""
        if self.config.smtp_password_file:
            password = Path(self.config.smtp_password_file).read_text(encoding="utf-8").strip()
        context = ssl.create_default_context()
        if self.config.smtp_tls_policy == "gt-relay-exception":
            # OIT's documented GT relay configuration, explicitly selected by
            # the operator. Scope is validated above; never fall back to plaintext.
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        if self.config.smtp_security == "ssl":
            client = smtplib.SMTP_SSL(self.config.smtp_host, self.config.smtp_port,
                                      timeout=SMTP_TIMEOUT_S, context=context)
        else:
            client = smtplib.SMTP(self.config.smtp_host, self.config.smtp_port,
                                  timeout=SMTP_TIMEOUT_S)
        with client:
            if self.config.smtp_security == "starttls":
                client.starttls(context=context)
            if self.config.smtp_username:
                client.login(self.config.smtp_username, password)
            client.send_message(message)

    def deliver_due(self, *, limit: int = 20) -> dict:
        """Send what is due (blocking: run it off the event loop)."""
        result = {"sent": 0, "retry": 0, "cancelled": 0, "skipped": 0}
        problems = self.config.problems()
        if not self.config.delivers or problems:
            blocked = (self.config.mode, tuple(problems))
            if blocked != self._blocked_state:
                self._event("blocked", warning=True,
                            reason="configuration_invalid" if problems else "delivery_disabled",
                            problem_count=len(problems))
                self._blocked_state = blocked
            return result
        self._blocked_state = None
        for row in self._due(limit):
            if not self._claim(row["id"]):
                result["skipped"] += 1
                continue
            try:
                if not self._still_wanted(row):
                    self._finish(row, status="cancelled", error="no longer needed")
                    self._event("cancelled", row, reason="no_longer_needed")
                    result["cancelled"] += 1
                    continue
                self._event("attempt", row, attempt=int(row["attempts"]) + 1)
                receipt = self._send(build_message(row, self.config))
            except Exception as error:      # every failure is retried later
                safe_error = _safe_error(error)
                self._finish(row, status="retry",
                             error=safe_error)
                self._event("retry", row, warning=True, error=safe_error,
                            attempt=int(row["attempts"]) + 1,
                            exhausted=int(row["attempts"]) + 1 >= MAX_ATTEMPTS)
                result["retry"] += 1
            else:
                self._finish(row, status="sent")
                self._event("accepted", row, receipt=receipt,
                            outcome="written_to_file" if self.config.mode == "file"
                            else "provider_accepted")
                result["sent"] += 1
        return result

    def retry(self, row_id: str) -> bool:
        now = self._clock()
        with self._connect() as connection:
            return bool(connection.execute(
                """
                UPDATE notification_outbox
                SET status = 'queued', attempts = 0, next_attempt_at = ?, updated_at = ?
                WHERE id = ? AND status = 'failed'
                """,
                (now, now, row_id),
            ).rowcount)

    def summary(self) -> dict:
        with self._connect() as connection:
            counts = {row["status"]: int(row["n"]) for row in connection.execute(
                "SELECT status, COUNT(*) AS n FROM notification_outbox GROUP BY status")}
            failed = [dict(row) for row in connection.execute(
                """
                SELECT id, template, recipient, attempts, last_error, updated_at
                FROM notification_outbox WHERE status = 'failed'
                ORDER BY updated_at DESC LIMIT 50
                """)]
        return {"counts": counts, "failed": failed}
