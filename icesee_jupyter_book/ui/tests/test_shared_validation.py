"""B4: shared pre-submit validation helpers."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from icesee_jupyter_book.ui.shared_validation import (
    validate_memory,
    validate_remote_identity,
    validate_slurm_resources,
    validate_wall_time,
)


@pytest.mark.parametrize("good", ["05:00", "12:00:00", "1-00:00:00", "0-01:30:00", "00:30"])
def test_wall_time_accepts_the_three_documented_forms(good):
    assert validate_wall_time(good) is None


@pytest.mark.parametrize("bad", ["", "5h", "1:2:3:4", "90:00:00", "12:99", "abc"])
def test_wall_time_rejects_garbage(bad):
    assert validate_wall_time(bad) is not None


def test_wall_time_rejects_zero():
    assert validate_wall_time("00:00") is not None


@pytest.mark.parametrize("good", ["512M", "4G", "16GB", "1T", "2Gi", "", "256000"])
def test_memory_accepts_common_forms(good):
    assert validate_memory(good) is None


@pytest.mark.parametrize("bad", ["lots", "4 gigs", "-2G", "G", "0G"])
def test_memory_rejects_garbage(bad):
    assert validate_memory(bad) is not None


def test_slurm_resources_valid_request_has_no_messages():
    assert validate_slurm_resources(
        nodes=2, tasks=24, tasks_per_node=12, wall_time="04:00:00", memory="64G"
    ) == []


def test_slurm_resources_flags_each_floor():
    msgs = validate_slurm_resources(
        nodes=0, tasks=0, tasks_per_node=0, wall_time="01:00:00", memory="4G"
    )
    assert len(msgs) == 3


def test_tasks_per_node_cannot_exceed_tasks():
    msgs = validate_slurm_resources(
        nodes=1, tasks=4, tasks_per_node=8, wall_time="01:00:00", memory="4G"
    )
    assert any("cannot exceed" in m.lower() for m in msgs)


def test_account_required_only_when_flagged():
    common = dict(nodes=1, tasks=1, tasks_per_node=1, wall_time="01:00:00", memory="4G")
    assert validate_slurm_resources(account="", account_required=False, **common) == []
    msgs = validate_slurm_resources(account="", account_required=True, **common)
    assert msgs == ["Account is required for this resource."]
    assert validate_slurm_resources(account="gts-x", account_required=True, **common) == []


def test_messages_are_short_and_actionable():
    for m in validate_slurm_resources(
        nodes=0, tasks=2, tasks_per_node=5, wall_time="nope", memory="lots"
    ):
        assert len(m) < 80
        assert m[0].isupper() and m.endswith(".")


def test_remote_identity_requires_username_and_directory():
    assert validate_remote_identity(hpc_username="", remote_directory="") == [
        "HPC username is required for Remote execution.",
        "Remote working directory is required for Remote execution.",
    ]
    assert validate_remote_identity(hpc_username="alice", remote_directory="/scratch/alice") == []
