# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : Hosted Pilot Account Guardrails
# File        : guardrails.py
#
# Description :
#     Definitions of the spending and retention guardrails configured in the
#     hosted pilot AWS account: budget, alerts, automatic spend block,
#     compute cap, S3 expiry and log retention. Definitions only -- no AWS
#     calls.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-11-15
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: MIT
#
# =============================================================================

"""
Account guardrails for the CryoStack hosted pilot.

The pilot is paid from a small fixed fund, so the account carries several
independent limits. None of them alone is a hard real-time cap:

* an AWS **budget** for the whole pilot window (one period that is meant
  not to reset during the pilot) with e-mail alerts at 50% and 80% actual
  and 100% forecast spend;
* a **budget action** that, at a dollar threshold, attaches a deny policy
  (``batch:SubmitJob`` and ``ecs:RunTask``) to the role(s) the gateway
  submits with -- new work stops, running jobs finish or hit their timeout;
* a low **maxvCpus** on the Fargate compute environment, which bounds how
  fast money can be spent while AWS billing data (hours behind) catches up;
* an S3 **lifecycle** rule that expires the gateway's result archives
  (``pilot-results/``; the model task itself has no S3 access), and short
  CloudWatch **log retention** on the pilot log group, so storage does not
  keep charging after the pilot.

This module only builds the documents. The operator tool
``deployment/pilot/setup_pilot_account.py`` shows and applies them.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

DEFAULT_BUDGET_NAME = "cryostack-pilot"
DEFAULT_BUDGET_USD = 500
#: Spend at which new submissions are blocked, as a share of the budget.
DEFAULT_BLOCK_FRACTION = Decimal("0.8")
DEFAULT_MAX_VCPUS = 8
DEFAULT_RETENTION_DAYS = 30
#: Retention of the dedicated pilot log group (``/cryostack/pilot``).
DEFAULT_LOG_RETENTION_DAYS = 14
#: Prefix of the gateway's durable result archives
#: (``control_center/services/project_results.py``). The only pilot data in S3.
DEFAULT_RESULT_PREFIX = "pilot-results/"
#: Default budget period: ONE period covering the whole pilot window.
DEFAULT_BUDGET_TIME_UNIT = "CUSTOM"
#: Longest pilot window one non-resetting annual period can cover.
MAX_PILOT_DAYS = 366
DEFAULT_ABORT_MULTIPART_DAYS = 1

SPEND_BLOCK_POLICY_NAME = "cryostack-pilot-spend-block"
BUDGET_ACTION_ROLE_NAME = "cryostack-pilot-budget-action"
BUDGET_ACTION_ROLE_POLICY_NAME = "CryoStackPilotApplySpendBlock"
LIFECYCLE_RULE_ID = "cryostack-pilot-expire"

#: AWS Budgets allows at most 10 e-mail subscribers per notification.
MAX_BUDGET_EMAILS = 10
#: Recurring periods AWS Budgets offers. There is no "one fixed amount"
#: unit; see :func:`budget_definition` for how the default avoids a reset.
BUDGET_TIME_UNITS = ("CUSTOM", "MONTHLY", "QUARTERLY", "ANNUALLY")
#: The only retention values CloudWatch Logs accepts.
LOG_RETENTION_CHOICES = (
    1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731,
    1096, 1827, 2192, 2557, 2922, 3288, 3653,
)

_EMAIL_RE = re.compile(r"\A[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,185}\.[A-Za-z]{2,24}\Z")
_ACCOUNT_ID_RE = re.compile(r"\A[0-9]{12}\Z")
_ROLE_NAME_RE = re.compile(r"\A[A-Za-z0-9+=,.@_-]{1,64}\Z")
_BUDGET_NAME_RE = re.compile(r"\A[A-Za-z0-9_.-]{1,100}\Z")


def _usd(amount, *, what: str) -> Decimal:
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{what} must be a dollar amount") from None
    if not value.is_finite() or value <= 0:
        raise ValueError(f"{what} must be greater than zero")
    return value


def usd_text(amount) -> str:
    """A dollar amount the way the Budgets API wants it: a plain decimal
    string with no exponent and no trailing zeros (``500``, ``12.5``)."""
    value = _usd(amount, what="amount")
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _account(account_id: str) -> str:
    account = (account_id or "").strip()
    if not _ACCOUNT_ID_RE.match(account):
        raise ValueError("an AWS account id is exactly 12 digits")
    return account


def _role_names(role_names) -> list[str]:
    names = [role_names] if isinstance(role_names, str) else list(role_names or [])
    names = list(dict.fromkeys(str(name).strip() for name in names))
    if not names or not all(_ROLE_NAME_RE.match(name) for name in names):
        raise ValueError("the spend block needs one or more valid IAM role NAMES (not ARNs)")
    return names


def normalize_emails(emails) -> list[str]:
    """Validated, de-duplicated alert addresses (1 to 10)."""
    found = [emails] if isinstance(emails, str) else list(emails or [])
    unique = list(dict.fromkeys(str(item).strip() for item in found if str(item).strip()))
    if not unique:
        raise ValueError("at least one alert e-mail address is required")
    if len(unique) > MAX_BUDGET_EMAILS:
        raise ValueError(f"AWS Budgets allows at most {MAX_BUDGET_EMAILS} alert addresses")
    if not all(_EMAIL_RE.match(item) for item in unique):
        raise ValueError("an alert e-mail address is not valid")
    return unique


def default_block_usd(budget_usd=DEFAULT_BUDGET_USD) -> Decimal:
    """80% of the budget -- $400 for the default $500 fund."""
    return _usd(budget_usd, what="budget") * DEFAULT_BLOCK_FRACTION


def policy_arn(account_id: str, name: str = SPEND_BLOCK_POLICY_NAME) -> str:
    return f"arn:aws:iam::{_account(account_id)}:policy/{name}"


def role_arn(account_id: str, name: str) -> str:
    return f"arn:aws:iam::{_account(account_id)}:role/{name}"


# ── budget and alerts ────────────────────────────────────────────────────────
def _epoch(value) -> int:
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return int(moment.timestamp())
    return int(value)


def pilot_period(start_month: str, end_date: str) -> tuple[int, int]:
    """``(start, end)`` epoch seconds of the pilot budget window.

    ``start_month`` is ``YYYY-MM`` (the budget starts at 00:00 UTC on the
    first of that month, the only start AWS budget periods align to);
    ``end_date`` is ``YYYY-MM-DD`` (00:00 UTC). The window must be positive
    and no longer than :data:`MAX_PILOT_DAYS` so that it fits in one annual
    period.
    """
    try:
        year, month = (int(part) for part in str(start_month).strip().split("-"))
        begin = datetime(year, month, 1, tzinfo=timezone.utc)
        finish = datetime.combine(
            date.fromisoformat(str(end_date).strip()), datetime.min.time(), timezone.utc)
    except (TypeError, ValueError):
        raise ValueError("pilot start is YYYY-MM and pilot end is YYYY-MM-DD") from None
    days = (finish - begin).days
    if not 1 <= days <= MAX_PILOT_DAYS:
        raise ValueError(
            f"the pilot window must be 1-{MAX_PILOT_DAYS} days so the budget cannot reset in it")
    return int(begin.timestamp()), int(finish.timestamp())


def budget_definition(
    *,
    limit_usd=DEFAULT_BUDGET_USD,
    name: str = DEFAULT_BUDGET_NAME,
    time_unit: str = DEFAULT_BUDGET_TIME_UNIT,
    start=None,
    end=None,
) -> dict:
    """The ``Budget`` document for ``aws budgets create-budget``: a COST
    budget of ``limit_usd`` per ``time_unit``.

    A recurring budget (MONTHLY, QUARTERLY, ANNUALLY) restarts its spend at
    zero each period, so it cannot cap a fixed $500 fund. The default is
    ``CUSTOM``: one period from ``start`` to ``end`` that never resets
    (AWS API reference, Budget.TimeUnit / TimePeriod, read 2026-11-16: "After
    the end date, AWS deletes the budget and all the associated notifications
    and subscribers"). ``start`` and ``end`` (``datetime`` or epoch seconds)
    are REQUIRED for ``CUSTOM`` and ``ANNUALLY``; see :func:`pilot_period`.

    UNVERIFIED (needs one live test): that the spend-block budget action
    attaches to a CUSTOM budget. The Action API page names no restriction by
    time unit. After ``end`` the budget and its block are gone, so the pilot
    must be closed out by then.
    """
    unit = (time_unit or "").strip().upper()
    if unit not in BUDGET_TIME_UNITS:
        raise ValueError(f"budget time unit must be one of {', '.join(BUDGET_TIME_UNITS)}")
    if not _BUDGET_NAME_RE.match(name or ""):
        raise ValueError("budget name must be 1-100 letters, digits, '_', '.' or '-'")
    budget: dict = {
        "BudgetName": name,
        "BudgetType": "COST",
        "TimeUnit": unit,
        "BudgetLimit": {"Amount": usd_text(limit_usd), "Unit": "USD"},
    }
    period: dict = {}
    if start is not None:
        period["Start"] = _epoch(start)
    if end is not None:
        period["End"] = _epoch(end)
    if "Start" in period and "End" in period and period["End"] <= period["Start"]:
        raise ValueError("the budget must end after it starts")
    if unit in ("CUSTOM", "ANNUALLY"):
        if len(period) != 2:
            raise ValueError(f"a {unit.lower()} pilot budget needs an explicit start and end")
        if period["End"] - period["Start"] > MAX_PILOT_DAYS * 86400:
            raise ValueError("a pilot budget cannot span more than one year")
    if period:
        budget["TimePeriod"] = period
    return budget


#: (notification type, percent of the budget) for the three e-mail alerts.
BUDGET_ALERTS: tuple[tuple[str, int], ...] = (
    ("ACTUAL", 50),
    ("ACTUAL", 80),
    ("FORECASTED", 100),
)


def budget_notification(kind: str, percent: int) -> dict:
    return {
        "NotificationType": kind,
        "ComparisonOperator": "GREATER_THAN",
        "Threshold": float(percent),
        "ThresholdType": "PERCENTAGE",
    }


def budget_subscribers(emails) -> list[dict]:
    return [
        {"SubscriptionType": "EMAIL", "Address": address}
        for address in normalize_emails(emails)
    ]


def budget_notifications(emails) -> list[dict]:
    """``NotificationsWithSubscribers`` for ``create-budget``: e-mail at 50%
    and 80% of ACTUAL spend and at 100% FORECASTED spend."""
    subscribers = budget_subscribers(emails)
    return [
        {
            "Notification": budget_notification(kind, percent),
            "Subscribers": [dict(item) for item in subscribers],
        }
        for kind, percent in BUDGET_ALERTS
    ]


# ── automatic spend block ────────────────────────────────────────────────────
def spend_block_policy() -> dict:
    """The deny policy the budget action attaches when the threshold is hit.

    An explicit ``Deny`` overrides every ``Allow``, so a role carrying this
    policy can no longer submit Batch jobs or start ECS tasks, whatever else
    it is allowed. It does not stop jobs that are already running, and it
    does not stop AWS Batch's own service role from starting jobs that are
    already queued; the operator disables the queue for that.
    """
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "CryoStackPilotSpendBlock",
                "Effect": "Deny",
                "Action": ["batch:SubmitJob", "ecs:RunTask"],
                "Resource": "*",
            }
        ],
    }


def budget_action_role_trust(account_id: str, budget_name: str = DEFAULT_BUDGET_NAME) -> dict:
    """Trust policy of the role AWS Budgets assumes to run the action."""
    account = _account(account_id)
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "budgets.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": account},
                    "ArnLike": {
                        "aws:SourceArn": f"arn:aws:budgets::{account}:budget/{budget_name}"
                    },
                },
            }
        ],
    }


def budget_action_role_policy(account_id: str, role_names) -> dict:
    """What the budget-action role may do: attach or detach ONLY the spend
    block policy, and only on the named role(s)."""
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ApplySpendBlockOnly",
                "Effect": "Allow",
                "Action": ["iam:AttachRolePolicy", "iam:DetachRolePolicy"],
                "Resource": [role_arn(account_id, name) for name in _role_names(role_names)],
                "Condition": {
                    "ArnEquals": {"iam:PolicyARN": policy_arn(account_id)}
                },
            }
        ],
    }


def budget_action_definition(
    *,
    account_id: str,
    role_names,
    emails,
    block_at_usd=None,
    budget_usd=DEFAULT_BUDGET_USD,
    budget_name: str = DEFAULT_BUDGET_NAME,
) -> dict:
    """The ``CreateBudgetAction`` request: when ACTUAL spend passes
    ``block_at_usd`` (default 80% of the budget, $400 of $500), attach
    :func:`spend_block_policy` to ``role_names`` automatically.

    ``role_names`` are the role(s) the gateway uses to submit pilot jobs.
    The threshold is an absolute dollar value so changing the budget limit
    later never silently moves the block.
    """
    budget = _usd(budget_usd, what="budget")
    block = default_block_usd(budget) if block_at_usd is None else _usd(
        block_at_usd, what="block threshold")
    if block > budget:
        raise ValueError("the block threshold cannot be above the budget")
    return {
        "AccountId": _account(account_id),
        "BudgetName": budget_name,
        "NotificationType": "ACTUAL",
        "ActionType": "APPLY_IAM_POLICY",
        "ActionThreshold": {
            "ActionThresholdValue": float(block),
            "ActionThresholdType": "ABSOLUTE_VALUE",
        },
        "Definition": {
            "IamActionDefinition": {
                "PolicyArn": policy_arn(account_id),
                "Roles": _role_names(role_names),
            }
        },
        "ExecutionRoleArn": role_arn(account_id, BUDGET_ACTION_ROLE_NAME),
        "ApprovalModel": "AUTOMATIC",
        "Subscribers": budget_subscribers(emails),
    }


# ── compute cap ──────────────────────────────────────────────────────────────
def max_vcpus_cap(max_vcpus: int = DEFAULT_MAX_VCPUS) -> int:
    """The ``maxvCpus`` of the pilot Fargate compute environment.

    With the default 2-vCPU job this allows four jobs at once. It is the
    guardrail that limits the RATE of spend, which matters because budget
    data lags real usage by hours.
    """
    value = int(max_vcpus)
    if not 1 <= value <= 256:
        raise ValueError("max vCPUs must be between 1 and 256")
    return value


def compute_cap_update(max_vcpus: int = DEFAULT_MAX_VCPUS) -> dict:
    """``--compute-resources`` for ``batch update-compute-environment``."""
    return {"maxvCpus": max_vcpus_cap(max_vcpus)}


# ── retention ────────────────────────────────────────────────────────────────
_PREFIX_RE = re.compile(r"\A(?:[A-Za-z0-9_-]+/)+\Z")


def lifecycle_rule(
    days: int = DEFAULT_RETENTION_DAYS,
    *,
    prefix: str = DEFAULT_RESULT_PREFIX,
    abort_multipart_days: int = DEFAULT_ABORT_MULTIPART_DAYS,
) -> dict:
    """One S3 lifecycle rule for the pilot result archives under ``prefix``:
    delete objects ``days`` after creation (and old versions, if versioning
    is on) and discard unfinished multipart uploads."""
    if int(days) < 1 or int(abort_multipart_days) < 1:
        raise ValueError("lifecycle days must be at least 1")
    if not _PREFIX_RE.match(prefix or ""):
        raise ValueError("the lifecycle prefix must be one or more 'name/' segments")
    return {
        "ID": LIFECYCLE_RULE_ID,
        "Status": "Enabled",
        "Filter": {"Prefix": prefix},
        "Expiration": {"Days": int(days)},
        "NoncurrentVersionExpiration": {"NoncurrentDays": int(days)},
        "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": int(abort_multipart_days)},
    }


def lifecycle_configuration(
    days: int = DEFAULT_RETENTION_DAYS,
    *,
    prefix: str = DEFAULT_RESULT_PREFIX,
    abort_multipart_days: int = DEFAULT_ABORT_MULTIPART_DAYS,
    existing_rules: list[dict] | None = None,
) -> dict:
    """The bucket lifecycle configuration containing the pilot rule.

    ``put-bucket-lifecycle-configuration`` REPLACES the whole configuration,
    so pass the bucket's current rules as ``existing_rules``: every rule
    with a different ``ID`` is kept unchanged and only the pilot rule is
    added or replaced.
    """
    kept = [
        rule for rule in (existing_rules or [])
        if isinstance(rule, dict) and rule.get("ID") != LIFECYCLE_RULE_ID
    ]
    return {"Rules": kept + [lifecycle_rule(
        days, prefix=prefix, abort_multipart_days=abort_multipart_days)]}


def log_retention_days(days: int = DEFAULT_LOG_RETENTION_DAYS) -> int:
    """CloudWatch Logs retention: ``days`` rounded UP to the nearest value
    the service accepts (so logs are never dropped earlier than asked)."""
    wanted = int(days)
    if wanted < 1:
        raise ValueError("log retention must be at least 1 day")
    for choice in LOG_RETENTION_CHOICES:
        if choice >= wanted:
            return choice
    return LOG_RETENTION_CHOICES[-1]
