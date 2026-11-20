"""Reviewing registrations: who may decide, and what a decision does.

Control Center roles retain the configured approval policy. Owners may
explicitly delegate review of pending registrations to approved accounts
with confirmed email addresses. This grants approval/rejection permission
only, without granting platform roles; nobody decides for their own account.
An account that holds a Control Center role can be decided only by
an owner, and an owner account cannot be rejected or suspended at all
(remove the owner role first, which keeps the last-owner rule in one place).

A decision is one transaction in :meth:`ApprovalStore.decide` (status,
audit row, session deletion). Afterwards the applicant's email is queued,
live connections of a rejected or suspended account are closed, and an
approval queues the account's workspace for provisioning.
"""
from __future__ import annotations

from icesee_auth import access_log, approval
from icesee_auth.approval import DecisionError
from icesee_auth.registration_approvers import RegistrationApproverStore

APPROVE_DEFAULT_REASON = "Approved after review"


class RegistrationService:
    def __init__(self, auth, access) -> None:
        self.auth = auth
        self.access = access
        self.storage = auth.storage
        self.approvers = RegistrationApproverStore(self.storage, clock=auth._clock)

    def _policy_decider(self, actor_user_id: str) -> bool:
        return (self.auth.user_is_active(actor_user_id)
                and self.access.effective_role(user_id=actor_user_id) in approval.decision_roles())

    def can_view(self, *, actor_user_id: str) -> bool:
        return (self.auth.user_is_active(actor_user_id) and (
            self.access.can_access_control_center(user_id=actor_user_id)
            or self.approvers.is_authorized(actor_user_id)))

    def registration_only(self, actor_user_id: str) -> bool:
        return self.access.effective_role(user_id=actor_user_id) is None

    def can_decide(self, *, actor_user_id: str) -> bool:
        return self._policy_decider(actor_user_id) or self.approvers.is_authorized(actor_user_id)

    def allowed_decisions(self, *, actor_user_id: str, target_user_id: str) -> list[str]:
        """The decisions the actor may make for the target right now."""
        if actor_user_id == target_user_id or not self.can_decide(actor_user_id=actor_user_id):
            return []
        actor_role = self.access.effective_role(user_id=actor_user_id)
        target_role = self.access.effective_role(user_id=target_user_id)
        if target_role and actor_role != "owner":
            return []
        current = self.auth.approval.effective_status(target_user_id)
        allowed = [
            decision for decision, (sources, _new) in approval.DECISIONS.items()
            if current in sources
        ]
        if not self._policy_decider(actor_user_id):
            allowed = [d for d in allowed if current == approval.PENDING and d in {"approve", "reject"}]
        if target_role == "owner":
            allowed = [d for d in allowed if d not in ("reject", "suspend")]
        record = self.auth.approval.status(target_user_id)
        if (record is not None and not record.email_verified) or (
                record is None and not self._policy_decider(actor_user_id)):
            # approving waits for the applicant to confirm their address
            allowed = [d for d in allowed if d != "approve"]
        return allowed

    def _label(self, user_id: str) -> str:
        user = self.storage.get_user_by_id(user_id)
        return user.email if user is not None else user_id

    def decide(self, *, actor_user_id: str, target_user_id: str,
               decision: str, reason: str | None) -> dict:
        target = self.storage.get_user_by_id(target_user_id)
        if target is None:
            raise LookupError("User not found.")
        if decision not in approval.DECISIONS:
            raise ValueError("Unknown decision.")
        record = self.auth.approval.status(target_user_id)
        if decision == "approve" and record is not None and not record.email_verified:
            raise DecisionError("The applicant has not verified their email address yet.")
        if decision not in self.allowed_decisions(
                actor_user_id=actor_user_id, target_user_id=target_user_id):
            try:
                self.storage.record_access_event(
                    event_type=access_log.ACCOUNT_STATUS_CHANGED,
                    outcome="denied",
                    category=("self_change" if actor_user_id == target_user_id
                              else "not_permitted"),
                    user_id=target_user_id,
                    actor_user_id=actor_user_id,
                    metadata={"decision": decision},
                )
            except Exception:
                pass
            raise PermissionError("You do not have permission to make this decision.")
        reason = approval.clean_reason(reason, required=decision != "approve") \
            or APPROVE_DEFAULT_REASON
        previous, new, audit_id = self.auth.approval.decide(
            actor_user_id=actor_user_id,
            actor_label=self._label(actor_user_id),
            target_user_id=target_user_id,
            target_label=target.email,
            decision=decision,
            reason=reason,
            authorization_check=lambda: self._recheck_decision(actor_user_id, target_user_id, decision),
        )
        if new in (approval.REJECTED, approval.SUSPENDED):
            self.auth.revoke_user(target_user_id)
        self.auth.notify_decision(target, status=new, audit_id=audit_id)
        return {"previous": previous, "status": new, "audit_id": audit_id}

    def _recheck_decision(self, actor_user_id, target_user_id, decision):
        if decision not in self.allowed_decisions(
                actor_user_id=actor_user_id, target_user_id=target_user_id):
            raise PermissionError("You do not have permission to make this decision.")

    def notify_waiting_reviewers(self):
        for account in self.auth.approval.list_accounts(status=approval.PENDING):
            if account.get("email_verified_at") is not None:
                user = self.storage.get_user_by_id(account["id"])
                if user is not None:
                    self.auth.outbox.reactivate_reviewer_notices(user_id=user.id)
                    self.auth.outbox.notify_reviewers(
                        user=user, method=account.get("registration_method") or "password")

    def retry_provisioning(self, *, actor_user_id: str, target_user_id: str) -> None:
        if not self._policy_decider(actor_user_id):
            raise PermissionError("You do not have permission to retry provisioning.")
        if self.auth.approval.effective_status(target_user_id) != approval.APPROVED:
            raise DecisionError("Only approved accounts get a workspace.")
        self.auth.approval.retry_provisioning(target_user_id)

    def retry_notification(self, *, actor_user_id: str, row_id: str) -> bool:
        if not self._policy_decider(actor_user_id):
            raise PermissionError("You do not have permission to retry email.")
        return self.auth.outbox.retry(row_id)

    def approver_candidates(self, actor_user_id):
        if not self.approvers.can_manage(actor_user_id):
            return []
        with self.storage._connect() as connection:
            rows = connection.execute(
                "SELECT u.id,u.email,u.display_name,a.status,a.email_verified_at "
                "FROM users u LEFT JOIN account_status a ON a.user_id=u.id "
                "WHERE u.id != ? AND NOT EXISTS (SELECT 1 FROM registration_approvers r "
                "WHERE r.user_id=u.id AND r.email=u.email COLLATE NOCASE "
                "AND a.status='approved' AND a.email_verified_at IS NOT NULL) "
                "ORDER BY u.display_name COLLATE NOCASE,u.email", (actor_user_id,)).fetchall()
        return [{**dict(row), "eligible": row["status"] == "approved"
                 and row["email_verified_at"] is not None} for row in rows]

    def overview(self, *, actor_user_id: str, focus_user_id: str | None = None) -> dict:
        store = self.auth.approval
        outbox = self.auth.outbox
        if not self.can_view(actor_user_id=actor_user_id):
            raise PermissionError("You do not have permission to review registrations.")
        limited = self.registration_only(actor_user_id)
        manage_approvers = self.approvers.can_manage(actor_user_id)
        authorized, refused = outbox.reviewers()
        lists = {status: store.list_accounts(status=status) for status in
                 (approval.PENDING, approval.SUSPENDED, approval.REJECTED)}
        if limited:
            lists[approval.SUSPENDED] = []
            lists[approval.REJECTED] = []
        for rows in lists.values():
            for row in rows:
                row["decisions"] = self.allowed_decisions(
                    actor_user_id=actor_user_id, target_user_id=row["id"])
        failed_provisioning = []
        with self.storage._connect() as connection:
            for row in connection.execute(
                """
                SELECT p.user_id, p.status, p.attempts, p.last_error, p.updated_at,
                       u.email, u.display_name
                FROM workspace_provisioning p JOIN users u ON u.id = p.user_id
                WHERE p.status IN ('queued', 'provisioning', 'failed')
                ORDER BY p.updated_at DESC LIMIT 50
                """
            ):
                if not limited:
                    failed_provisioning.append(dict(row))
        focus = store.account(focus_user_id) if focus_user_id else None
        if limited and focus is not None and focus.get("status") != approval.PENDING:
            focus = None
        if focus is not None:
            focus["decisions"] = self.allowed_decisions(
                actor_user_id=actor_user_id, target_user_id=focus["id"])
        counts = store.counts()
        if limited:
            counts = {"pending": counts.get("pending", 0)}
        return {
            "approval_required": self.auth.approval_required,
            "focus": focus,
            "baseline": None if limited else store.baseline(),
            "counts": counts,
            "accounts": lists,
            "focus_user_id": focus_user_id,
            "provisioning": failed_provisioning,
            "mail": {} if limited else {
                **outbox.config.public(),
                "reviewers_authorized": len(authorized),
                "reviewers_refused": refused,
                **outbox.summary(),
            },
            "can_decide": self.can_decide(actor_user_id=actor_user_id),
            "can_retry": self._policy_decider(actor_user_id),
            "registration_only": limited,
            "can_manage_approvers": manage_approvers,
            "approvers": self.approvers.list_entries() if manage_approvers else [],
            "approver_candidates": self.approver_candidates(actor_user_id) if manage_approvers else [],
        }
