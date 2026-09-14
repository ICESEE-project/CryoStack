"""Offline release/demo acceptance command (PASS 4, task 14)."""
from __future__ import annotations

from cryostack_src.acceptance import FAIL, MANUAL, PASS, main, run_all


def test_all_checks_run_and_none_crash():
    results = run_all()
    assert len(results) >= 12
    assert all(r.status in (PASS, FAIL, MANUAL) for r in results)


def test_no_hard_failures_on_this_tree():
    fails = [f"{r.name}: {r.detail}" for r in run_all() if r.status == FAIL]
    assert not fails, "\n".join(fails)


def test_the_agent_safety_invariants_pass():
    by_name = {r.name: r for r in run_all()}
    for key in ("agent: tool modules reference no prohibited symbol",
                "agent: no shipped tool takes a user_id / owner argument",
                "agent: every shipped tool is OBSERVE/PLAN and read-only",
                "agent: approve-A / mutate / execute is rejected",
                "agent: provider adapters import no vendor SDK / key / network"):
        assert by_name[key].status == PASS, by_name[key].detail


def test_live_only_checks_are_flagged_manual_not_pass():
    by_name = {r.name: r for r in run_all()}
    assert by_name["live: PACE bootstrap / Duo / real HPC run / paid AWS run"].status == MANUAL


def test_cli_exit_code_is_zero_when_no_failures(capsys):
    rc = main(["--offline"])
    out = capsys.readouterr().out
    assert "MANUAL CHECK REQUIRED" in out
    assert rc == 0


def test_cli_json_mode(capsys):
    rc = main(["--offline", "--json"])
    import json
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list) and all("status" in d for d in data)
    assert rc == 0
