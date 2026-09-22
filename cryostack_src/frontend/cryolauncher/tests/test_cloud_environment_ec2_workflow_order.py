# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Frontend
# Component   : Cloud Environment -- compute-mode workflow ordering
# File        : test_cloud_environment_ec2_workflow_order.py
#
# Author(s)   :
#     Brian Kyanjo
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: MIT
#
# =============================================================================

"""Live EC2 validation surfaced two workflow gaps in the Cloud Environment
panel:

1. The panel let a user reach Prepare cloud before ever seeing the Advanced
   compute-mode settings (Fargate/EC2, and EC2's Capacity/Accelerator/
   Network/Execution), so a real Prepare could run against a config the
   user had not actually finished choosing.
2. Nothing reset a successful Prepare's "Ready" state when the user changed
   the compute mode or an EC2 Advanced option afterwards, so the panel could
   show Review & Launch for a configuration that was never provisioned.

This file is layout/wiring-only: it does not touch AWS semantics.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[4]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.frontend.cryolauncher.cloud_environment import (
    build_cloud_environment_card,
    set_cloud_status,
)


def _contains(node, target) -> bool:
    if node is target:
        return True
    children = getattr(node, "children", None)
    if children:
        return any(_contains(c, target) for c in children)
    return False


def _index_containing(children, target) -> int:
    return next(i for i, c in enumerate(children) if _contains(c, target))


# -- workflow ordering ---------------------------------------------------
def test_advanced_compute_settings_precede_prepare_cloud_in_layout():
    """Connect account -> choose Fargate/EC2 (+ Advanced if EC2) -> Prepare
    cloud -> Review & Launch. The Advanced accordion (which holds
    compute_mode and every EC2 sub-option) must appear before the Prepare
    cloud button in the panel's top-to-bottom layout."""
    card = build_cloud_environment_card()
    body = card.container.children[0]

    advanced_idx = _index_containing(body.children, card.advanced)
    prepare_idx = _index_containing(body.children, card.prepare_button)
    assert advanced_idx < prepare_idx


def test_advanced_precedes_run_estimate_and_review_panel():
    card = build_cloud_environment_card()
    body = card.container.children[0]

    advanced_idx = _index_containing(body.children, card.advanced)
    estimate_idx = _index_containing(body.children, card.run_estimate_section)
    review_idx = _index_containing(body.children, card.review_panel)
    assert advanced_idx < estimate_idx < review_idx or advanced_idx < review_idx
    assert advanced_idx < estimate_idx


def test_fargate_remains_the_default_and_needs_no_advanced_interaction():
    """Keeping Fargate the simple/default path: a user who never opens
    Advanced still has a fully valid, ready-to-Prepare configuration."""
    card = build_cloud_environment_card()
    assert card.compute_mode.value == "fargate"
    assert card.advanced.selected_index is None    # collapsed by default


# -- prepared-state invalidation -----------------------------------------
def _mark_prepared(card) -> None:
    """Simulate the panel state right after a successful Prepare cloud."""
    set_cloud_status(card.compute_status, state="done", label="Ready")
    card.run_estimate_section.layout.display = "flex"
    card.review_panel.layout.display = "flex"


def _assert_invalidated(card) -> None:
    assert "not prepared" in card.compute_status.value.lower()
    assert card.run_estimate_section.layout.display == "none"
    assert card.review_panel.layout.display == "none"


def test_switching_fargate_to_ec2_invalidates_previously_prepared_state():
    card = build_cloud_environment_card()
    _mark_prepared(card)

    card.compute_mode.value = "ec2"

    _assert_invalidated(card)


def test_changing_ec2_capacity_invalidates_prepared_state():
    card = build_cloud_environment_card(aws_batch_compute="ec2")
    _mark_prepared(card)

    card.ec2_capacity.value = "spot"

    _assert_invalidated(card)


def test_changing_ec2_accelerator_invalidates_prepared_state():
    card = build_cloud_environment_card(aws_batch_compute="ec2")
    _mark_prepared(card)

    card.ec2_accelerator.value = "gpu"

    _assert_invalidated(card)


def test_changing_ec2_network_invalidates_prepared_state():
    card = build_cloud_environment_card(aws_batch_compute="ec2")
    _mark_prepared(card)

    card.ec2_network.value = "custom"

    _assert_invalidated(card)


def test_changing_ec2_execution_topology_invalidates_prepared_state():
    card = build_cloud_environment_card(aws_batch_compute="ec2")
    _mark_prepared(card)

    card.ec2_topology.value = "multi_node"

    _assert_invalidated(card)


def test_storage_and_registry_rows_are_not_touched_by_a_compute_change():
    """Only the Batch compute environment depends on Fargate vs. EC2 --
    S3 (Storage) and ECR (Containers) are compute-mode independent and must
    not be reset just because the compute mode changed."""
    card = build_cloud_environment_card()
    set_cloud_status(card.storage_status, state="done", label="Ready")
    set_cloud_status(card.registry_status, state="done", label="Ready")
    _mark_prepared(card)

    card.compute_mode.value = "ec2"

    assert "ready" in card.storage_status.value.lower()
    assert "ready" in card.registry_status.value.lower()


def test_invalidation_is_a_noop_before_any_prepare_has_run():
    """No crash / no spurious state change when the widgets are touched
    before Prepare cloud has ever run once."""
    card = build_cloud_environment_card()
    assert "not prepared" in card.compute_status.value.lower()

    card.compute_mode.value = "ec2"
    card.ec2_capacity.value = "spot"

    assert "not prepared" in card.compute_status.value.lower()
    assert card.run_estimate_section.layout.display == "none"
