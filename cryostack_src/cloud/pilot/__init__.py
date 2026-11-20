# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : Hosted Pilot
# File        : __init__.py
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: MIT
#
# =============================================================================

"""Hosted pilot: invited participants run in one project-owned AWS account.

Participant identity, isolation, per-participant provisioning and account
guardrails are exported here. The gateway service modules of this package are
imported directly by their own callers.
"""

from .guardrails import (
    budget_action_definition,
    budget_definition,
    budget_notifications,
    compute_cap_update,
    lifecycle_configuration,
    log_retention_days,
    max_vcpus_cap,
    spend_block_policy,
)
from .identity import (
    PilotIdentityError,
    participant_key,
    participant_secret_name,
)
from .isolation import (
    PILOT_EXECUTION_ROLE_NAME,
    PilotScopeError,
    assert_no_task_role,
    assert_secret_scope,
    gateway_base_role_policy,
    licensed_pilot_job_definition,
    participant_secrets_block,
    pilot_execution_role_policy,
    pilot_execution_role_trust,
    pilot_job_definition,
)
from .provision import (
    PilotJobDefinition,
    PilotParticipantRemoval,
    PilotProvisionError,
    ensure_participant_secret,
    ensure_pilot_job_definition,
    remove_participant_resources,
    remove_reservation_resources,
)

# The per-participant job role, its S3 policy / session policy and
# ``ensure_participant_resources`` are LEGACY (they give the model task an AWS
# identity) and are deliberately not exported; see ``isolation.py``.
__all__ = [
    "PILOT_EXECUTION_ROLE_NAME",
    "PilotIdentityError",
    "PilotJobDefinition",
    "PilotParticipantRemoval",
    "PilotProvisionError",
    "PilotScopeError",
    "assert_no_task_role",
    "assert_secret_scope",
    "budget_action_definition",
    "budget_definition",
    "budget_notifications",
    "compute_cap_update",
    "ensure_participant_secret",
    "ensure_pilot_job_definition",
    "gateway_base_role_policy",
    "licensed_pilot_job_definition",
    "lifecycle_configuration",
    "log_retention_days",
    "max_vcpus_cap",
    "participant_key",
    "participant_secret_name",
    "participant_secrets_block",
    "pilot_execution_role_policy",
    "pilot_execution_role_trust",
    "pilot_job_definition",
    "remove_participant_resources",
    "remove_reservation_resources",
    "spend_block_policy",
]
