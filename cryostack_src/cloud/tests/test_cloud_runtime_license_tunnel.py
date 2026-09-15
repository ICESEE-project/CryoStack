"""cryostack_src.cloud.runtime.build_cloud_runner -- the private-service
license-tunnel block added to the ISSM branch of the generic Batch runner
script. Structural checks only (this is a bash script embedded as a Python
string); the tunnel client itself is unit/integration tested elsewhere.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.cloud.runtime import LICENSE_TUNNEL_CLIENT_FILENAME, build_cloud_runner

#: the runner invokes the STAGED FILE by path -- never
#: `python3 -m cryostack_src.cloud.license_tunnel_client`, which requires
#: the CryoLauncher web app's own package to be importable and cannot work
#: inside the scientific Batch container (the actual live-run failure this
#: staging fix resolves).
_LISTEN_INVOCATION = f'"${{WORKDIR}}/{LICENSE_TUNNEL_CLIENT_FILENAME}" listen'


def test_tunnel_block_is_conditional_on_a_plain_flag():
    script = build_cloud_runner()
    assert 'if [ "${CRYOSTACK_LICENSE_TUNNEL_REQUIRED:-0}" = "1" ]; then' in script


def test_tunnel_client_is_invoked_by_its_staged_file_path_not_as_a_module():
    """The regression for the live packaging failure: the Batch container
    is a scientific image with no CryoLauncher `cryostack_src` package
    installed, so the tunnel client must be invoked by the file path phase
    1 already staged into WORKDIR, never `-m cryostack_src...`."""
    script = build_cloud_runner()
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
    script = build_cloud_runner()
    listen_idx = script.index(_LISTEN_INVOCATION)
    fail_idx = script.index('|| fail 65 "${_lt_msg}"')
    matlab_idx = script.index("with-issm matlab")
    assert listen_idx < fail_idx < matlab_idx


def test_mlm_license_file_is_rewritten_indirectly_not_as_a_literal_assignment():
    """The existing security invariant (no literal ``MLM_LICENSE_FILE=<value>``
    assignment embedded in the script) must still hold -- the loopback
    rewrite goes through a variable so no license-shaped literal ever
    appears in the script's own source text."""
    script = build_cloud_runner()
    assert "MLM_LICENSE_FILE=" not in script
    assert '_mlm="MLM_LICENSE_FILE"' in script
    assert 'export "${_mlm}=${CRYOSTACK_LT_PORT}@127.0.0.1"' in script


def test_no_secret_or_session_literal_is_embedded():
    """The relay/session/token/purpose/endpoint values are never even
    NAMED in the runner script -- license_tunnel_client.py's `listen`
    reads all of them directly from its own process environment (see its
    _ENV_FALLBACK), so the embedded bash text carries no flags and no
    variable references for them at all; only CRYOSTACK_LT_PORT is
    referenced here, for the local MLM_LICENSE_FILE rewrite."""
    script = build_cloud_runner()
    for placeholder in ("CRYOSTACK_LT_RELAY", "CRYOSTACK_LT_SESSION",
                        "CRYOSTACK_LT_TOKEN", "CRYOSTACK_LT_PURPOSE",
                        "CRYOSTACK_LT_ENDPOINT"):
        assert placeholder not in script
    assert '"${CRYOSTACK_LT_PORT}"' not in script     # never passed as a flag
    assert "${CRYOSTACK_LT_PORT}" in script            # only in the MLM_LICENSE_FILE rewrite
    assert f"{_LISTEN_INVOCATION})" in script          # invoked with NO flags at all


def test_tunnel_block_is_only_in_the_issm_branch_not_icepack_or_smoke():
    script = build_cloud_runner()
    issm_start = script.index("issm)")
    icepack_start = script.index("icepack)")
    tunnel_idx = script.index(_LISTEN_INVOCATION)
    assert issm_start < tunnel_idx < icepack_start


def test_script_stays_within_the_container_override_command_cap():
    # Batch's hard cap on containerOverrides.command is 8192 characters --
    # this whole script becomes exactly that on every launch (see the
    # module docstring). The tunnel addition (a synchronous CLI invocation
    # doing its own connectivity check + detached serve, never a bash
    # polling loop -- see license_tunnel_client._cmd_listen) keeps real
    # headroom under that hard cap, even though it narrows the internal
    # "not just hair's-breadth" margin asserted in test_cloud_runtime.py.
    assert len(build_cloud_runner()) < 8192
