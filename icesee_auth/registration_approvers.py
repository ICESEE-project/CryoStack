"""Owner-chosen registration reviewers, without granting platform roles."""
from __future__ import annotations

import time

from . import access_log
from .approval import clean_reason

AUDIT_ACTION = "registration_approver_changed"


class RegistrationApproverStore:
    def __init__(self, storage, *, clock=time.time):
        self.storage = storage
        self._clock = clock

    @staticmethod
    def _require_owner(connection, actor_user_id):
        actor = connection.execute(
            "SELECT u.email FROM users u JOIN account_status a ON a.user_id = u.id "
            "WHERE u.id = ? AND a.status = 'approved' AND a.email_verified_at IS NOT NULL "
            "AND EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id = u.id AND r.role = 'owner')",
            (actor_user_id,),
        ).fetchone()
        if actor is None:
            raise PermissionError("Only an approved owner can manage registration approvers.")
        return actor["email"]

    def can_manage(self, actor_user_id):
        with self.storage._connect() as connection:
            try:
                self._require_owner(connection, actor_user_id)
            except PermissionError:
                return False
        return True

    def is_authorized(self, user_id):
        with self.storage._connect() as connection:
            return connection.execute(
                "SELECT 1 FROM registration_approvers r JOIN users u ON u.id = r.user_id "
                "JOIN account_status a ON a.user_id = u.id "
                "WHERE u.id = ? AND u.email = r.email COLLATE NOCASE "
                "AND a.status = 'approved' AND a.email_verified_at IS NOT NULL",
                (user_id,),
            ).fetchone() is not None

    def authorized_emails(self):
        with self.storage._connect() as connection:
            return [row["email"] for row in connection.execute(
                "SELECT r.email FROM registration_approvers r JOIN users u ON u.id = r.user_id "
                "JOIN account_status a ON a.user_id = u.id "
                "WHERE u.email = r.email COLLATE NOCASE AND a.status = 'approved' "
                "AND a.email_verified_at IS NOT NULL ORDER BY r.email")]

    def list_entries(self):
        with self.storage._connect() as connection:
            rows = connection.execute(
                "SELECT r.user_id,r.email,r.granted_at,r.granted_by,u.display_name,"
                "CASE WHEN u.email = r.email COLLATE NOCASE AND a.status = 'approved' "
                "AND a.email_verified_at IS NOT NULL THEN 1 ELSE 0 END AS active "
                "FROM registration_approvers r JOIN users u ON u.id = r.user_id "
                "LEFT JOIN account_status a ON a.user_id = u.id ORDER BY r.email",
            ).fetchall()
        return [{**dict(row), "active": bool(row["active"])} for row in rows]

    def grant(self, *, actor_user_id, email, reason=""):
        email = str(email).strip().lower()
        if "@" not in email or len(email) > 254 or any(c.isspace() for c in email):
            raise ValueError("Enter the email address of an existing CryoStack account.")
        reason = clean_reason(reason, required=False) or "Registration approver added by owner"
        connection = self.storage._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            actor_label = self._require_owner(connection, actor_user_id)
            target = connection.execute(
                "SELECT u.id,u.email,a.status,a.email_verified_at FROM users u "
                "LEFT JOIN account_status a ON a.user_id = u.id WHERE u.email = ? COLLATE NOCASE",
                (email,),
            ).fetchone()
            if target is None:
                raise LookupError("That address has no CryoStack account. Ask them to sign up first.")
            if target["status"] != "approved" or target["email_verified_at"] is None:
                raise ValueError("The account must be approved and its email confirmed first.")
            previous = connection.execute(
                "SELECT email FROM registration_approvers WHERE user_id = ?", (target["id"],),
            ).fetchone()
            if previous is not None and previous["email"].lower() == email:
                connection.rollback()
                return False
            now = self._clock()
            connection.execute(
                "INSERT INTO registration_approvers(user_id,email,granted_at,granted_by) "
                "VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
                "email=excluded.email,granted_at=excluded.granted_at,granted_by=excluded.granted_by",
                (target["id"], email, now, actor_user_id),
            )
            access_log.record_audit(
                connection, actor_user_id=actor_user_id, actor_label=actor_label,
                target_user_id=target["id"], target_label=email, action=AUDIT_ACTION,
                previous_value="enabled" if previous else "disabled", new_value="enabled",
                reason=reason, metadata={"email": email, "scope": "registration_review"}, now=now,
            )
            connection.commit()
            return True
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def revoke(self, *, actor_user_id, target_user_id, reason=""):
        reason = clean_reason(reason, required=False) or "Registration approver removed by owner"
        connection = self.storage._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            actor_label = self._require_owner(connection, actor_user_id)
            previous = connection.execute(
                "SELECT email FROM registration_approvers WHERE user_id = ?", (target_user_id,),
            ).fetchone()
            if previous is None:
                connection.rollback()
                return False
            connection.execute("DELETE FROM registration_approvers WHERE user_id = ?", (target_user_id,))
            access_log.record_audit(
                connection, actor_user_id=actor_user_id, actor_label=actor_label,
                target_user_id=target_user_id, target_label=previous["email"], action=AUDIT_ACTION,
                previous_value="enabled", new_value="disabled", reason=reason,
                metadata={"email": previous["email"], "scope": "registration_review"}, now=self._clock(),
            )
            connection.commit()
            return True
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
