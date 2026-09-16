"""cryostack_src.cloud.runtime -- the private-service license-tunnel logic
for the ISSM branch of the generic Batch runner.

The tunnel setup + MATLAB invocation live in their own STAGED FILE
(issm_cloud_runner_script(), staged as ISSM_CLOUD_RUNNER_FILENAME), never
embedded in the generic runner's own command text -- see
BATCH_CONTAINER_OVERRIDE_LIMIT and test_cloud_runtime.py's real
Container-Overrides regression test. This file tests that staged script's
content directly; a separate, small set of tests below confirms the
generic runner's ``issm)`` case is only a thin, fixed-size invocation of
it. The tunnel client itself is unit/integration tested elsewhere.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.cloud.runtime import (
    ISSM_CLOUD_RUNNER_FILENAME,
    LICENSE_TUNNEL_CLIENT_FILENAME,
    build_cloud_runner,
    issm_cloud_runner_extra_files,
    issm_cloud_runner_script,
)

#: the ISSM branch script invokes the STAGED FILE by path -- never
#: `python3 -m cryostack_src.cloud.license_tunnel_client`, which requires
#: the CryoLauncher web app's own package to be importable and cannot work
#: inside the scientific Batch container (the actual live-run failure this
#: staging fix resolves).
_LISTEN_INVOCATION = f'"${{WORKDIR}}/{LICENSE_TUNNEL_CLIENT_FILENAME}" listen'


def test_tunnel_block_is_conditional_on_a_plain_flag():
    script = issm_cloud_runner_script()
    assert 'if [ "${CRYOSTACK_LICENSE_TUNNEL_REQUIRED:-0}" = "1" ]; then' in script


def test_tunnel_client_is_invoked_by_its_staged_file_path_not_as_a_module():
    """The regression for the live packaging failure: the Batch container
    is a scientific image with no CryoLauncher `cryostack_src` package
    installed, so the tunnel client must be invoked by the file path phase
    1 already staged into WORKDIR, never `-m cryostack_src...`."""
    script = issm_cloud_runner_script()
    assert _LISTEN_INVOCATION in script
    # the ACTUAL invocation line, not any explanatory comment about it
    invoke_line = next(
        line for line in script.splitlines() if _LISTEN_INVOCATION in line)
    assert "-m" not in invoke_line
    assert "import cryostack_src" not in script


def test_connectivity_is_verified_and_can_abort_before_matlab_starts():
    """``listen`` performs its own connectivity check before ever binding
    the local port (see license_tunnel_client._cmd_listen) -- a nonzero
    exit here means MATLAB must never start."""
    script = issm_cloud_runner_script()
    listen_idx = script.index(_LISTEN_INVOCATION)
    fail_idx = script.index('|| fail 65 "${_lt_msg}"')
    matlab_idx = script.index("with-issm matlab")
    assert listen_idx < fail_idx < matlab_idx


def test_mlm_license_file_is_rewritten_indirectly_not_as_a_literal_assignment():
    """The existing security invariant (no literal ``MLM_LICENSE_FILE=<value>``
    assignment embedded in the script) must still hold -- the loopback
    rewrite goes through a variable so no license-shaped literal ever
    appears in the script's own source text."""
    script = issm_cloud_runner_script()
    assert "MLM_LICENSE_FILE=" not in script
    assert '_mlm="MLM_LICENSE_FILE"' in script
    assert 'export "${_mlm}=${CRYOSTACK_LT_PORT}@127.0.0.1"' in script


def test_no_secret_or_session_literal_is_embedded():
    """The relay/session/token/purpose/endpoint values are never even
    NAMED in the staged script -- license_tunnel_client.py's `listen`
    reads all of them directly from its own process environment (see its
    _ENV_FALLBACK), so the embedded bash text carries no flags and no
    variable references for them at all; only CRYOSTACK_LT_PORT is
    referenced here, for the local MLM_LICENSE_FILE rewrite."""
    script = issm_cloud_runner_script()
    for placeholder in ("CRYOSTACK_LT_RELAY", "CRYOSTACK_LT_SESSION",
                        "CRYOSTACK_LT_TOKEN", "CRYOSTACK_LT_PURPOSE",
                        "CRYOSTACK_LT_ENDPOINT"):
        assert placeholder not in script
    assert '"${CRYOSTACK_LT_PORT}"' not in script     # never passed as a flag
    assert "${CRYOSTACK_LT_PORT}" in script            # only in the MLM_LICENSE_FILE rewrite
    assert f"{_LISTEN_INVOCATION})" in script          # invoked with NO flags at all


# ── optional second hop: the FlexNet vendor daemon ───────────────────────
def test_vendor_tunnel_is_conditional_on_its_own_port_env_var():
    script = issm_cloud_runner_script()
    assert 'if [ -n "${CRYOSTACK_LT_VENDOR_PORT:-}" ]; then' in script


def test_vendor_tunnel_reuses_the_listen_client_with_explicit_endpoint_and_port():
    script = issm_cloud_runner_script()
    assert (
        f'"${{WORKDIR}}/{LICENSE_TUNNEL_CLIENT_FILENAME}" listen \\\n'
        '      --endpoint vendor --port "${CRYOSTACK_LT_VENDOR_PORT}"'
    ) in script


def test_vendor_tunnel_runs_after_primary_and_before_matlab():
    script = issm_cloud_runner_script()
    primary_idx = script.index(_LISTEN_INVOCATION)
    vendor_idx = script.index("--endpoint vendor")
    matlab_idx = script.index("with-issm matlab")
    assert primary_idx < vendor_idx < matlab_idx


def test_vendor_tunnel_failure_aborts_before_matlab_starts():
    script = issm_cloud_runner_script()
    vendor_idx = script.index("--endpoint vendor")
    fail_idx = script.index('|| fail 65 "${_lt_msg2}"')
    matlab_idx = script.index("with-issm matlab")
    assert vendor_idx < fail_idx < matlab_idx


def test_vendor_tunnel_never_repeats_relay_session_or_token_flags():
    """Relay/session/token/purpose stay implicit (this process's own
    environment, unchanged from the primary tunnel) -- only the endpoint
    and port differ for the vendor hop, so only those are given as flags."""
    script = issm_cloud_runner_script()
    for placeholder in ("--relay", "--session", "--token", "--purpose"):
        assert placeholder not in script


# ── the staged file is small on its own too (belt and suspenders) ──────
def test_issm_branch_script_stays_comfortably_small_on_its_own():
    # Not subject to the 8192 container-overrides cap at all (it is
    # synced as an ordinary S3 object, never embedded in the job's
    # command) -- but a runaway size here would still be a bug smell.
    assert len(issm_cloud_runner_script()) < 4096


def test_issm_cloud_runner_extra_files_stages_exactly_the_branch_script():
    files = issm_cloud_runner_extra_files()
    assert set(files) == {ISSM_CLOUD_RUNNER_FILENAME}
    assert files[ISSM_CLOUD_RUNNER_FILENAME] == issm_cloud_runner_script()


# ── the generic runner: only a thin, fixed-size staged-file invocation ──
def test_generic_runner_issm_branch_is_a_thin_staged_file_invocation():
    """The regression for THIS fix: the generic runner's ``issm)`` case
    must never grow back into an inline tunnel/MATLAB block -- it only
    hands WORKDIR/RUN_TARGET to the staged ISSM branch script and
    captures its exit code."""
    script = build_cloud_runner()
    issm_start = script.index("  issm)")
    icepack_start = script.index("  icepack)")
    issm_block = script[issm_start:icepack_start]
    assert f'bash "${{WORKDIR}}/{ISSM_CLOUD_RUNNER_FILENAME}"' in issm_block
    assert "rc=$?" in issm_block
    # none of the tunnel/MATLAB logic itself leaked back into the inline block
    for leaked in ("CRYOSTACK_LICENSE_TUNNEL_REQUIRED", "CRYOSTACK_LT_PORT",
                   "MLM_LICENSE_FILE", "with-issm matlab", "--endpoint vendor",
                   LICENSE_TUNNEL_CLIENT_FILENAME):
        assert leaked not in issm_block
    # a generous, fixed ceiling -- this block must stay small regardless of
    # how the staged ISSM script itself grows in the future.
    assert len(issm_block) < 400


def test_generic_runner_only_names_the_issm_branch_filename_once():
    script = build_cloud_runner()
    assert script.count(ISSM_CLOUD_RUNNER_FILENAME) == 1


def test_script_stays_within_the_container_override_command_cap():
    # Batch's hard cap on containerOverrides.command is 8192 characters --
    # this whole script becomes exactly that on every launch (see the
    # module docstring).
    assert len(build_cloud_runner()) < 8192
