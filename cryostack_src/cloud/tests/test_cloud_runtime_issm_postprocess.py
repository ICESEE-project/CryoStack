"""cryostack_src.cloud.runtime.issm_postprocess_extra_files -- the fix for
the live Cloud/Fargate failure: "RUN cannot execute the file
'/tmp/cryostack/run/postprocess_icesee.m'".

Root cause: the PRRTE hardware-thread fix let ISSM's solver actually
complete on Fargate, reaching the runner's unconditional
``run('${WORKDIR}/postprocess_icesee.m')`` MATLAB invocation
(cryostack_src/cloud/runtime.py's ``_ISSM_CLOUD_RUNNER``) for the first
time -- and that file had never been staged for Cloud. Remote
(cryostack_src/models/submission.py) always writes it over SSH using
``cryostack_src.models.issm.postprocess.build_postprocess()`` before its
own, equally unconditional, ``run('.../postprocess_icesee.m')`` -- so
Remote's postprocessing has always worked and needed no change.
``issm_postprocess_extra_files()`` stages the SAME generator's output as
an ordinary file (the SAME mechanism ``icepack_postprocess_extra_files``
already uses), wired into the gateway's ISSM cloud extra_files
composition (see test_cloud_gateway_wiring.py for the end-to-end proof
against the actual wired submission path).
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.cloud.runtime import (
    build_cloud_runner,
    issm_cloud_runner_extra_files,
    issm_postprocess_extra_files,
    license_tunnel_client_extra_files,
)


def test_issm_postprocess_extra_files_stages_exactly_one_file():
    files = issm_postprocess_extra_files()
    assert set(files) == {"postprocess_icesee.m"}


def test_issm_postprocess_content_is_byte_identical_to_remotes_generator():
    """The exact SAME function Remote calls right before its own SSH
    write -- not reimplemented, not merely similar content."""
    from cryostack_src.models.issm.postprocess import build_postprocess

    assert issm_postprocess_extra_files()["postprocess_icesee.m"] == build_postprocess()


def test_issm_postprocess_is_the_real_thing_not_a_stub():
    content = issm_postprocess_extra_files()["postprocess_icesee.m"]
    assert len(content) > 200
    assert "function" in content or "outdir" in content


def test_issm_postprocess_never_leaks_into_the_generic_inline_runner():
    """The 8192-char Container Overrides budget must be completely
    unaffected -- this is staged as an ordinary file, never embedded in
    the runner's own command text."""
    generic = build_cloud_runner()
    postprocess_text = issm_postprocess_extra_files()["postprocess_icesee.m"]
    assert postprocess_text not in generic


def test_issm_cloud_extra_files_composition_stages_all_three_helpers():
    """The exact merge the gateway performs for every ISSM cloud
    submission (icesee_jupyter_book/ui/icesheets_gateway.py's
    ``_issm_cloud_license_tunnel_files``) -- license tunnel client +
    staged ISSM runner script + postprocess, all three, every time."""
    merged = {
        **license_tunnel_client_extra_files(),
        **issm_cloud_runner_extra_files(),
        **issm_postprocess_extra_files(),
    }
    assert "postprocess_icesee.m" in merged
    from cryostack_src.cloud.runtime import (
        ISSM_CLOUD_RUNNER_FILENAME,
        LICENSE_TUNNEL_CLIENT_FILENAME,
    )
    assert LICENSE_TUNNEL_CLIENT_FILENAME in merged
    assert ISSM_CLOUD_RUNNER_FILENAME in merged


def test_runner_invocation_of_postprocess_is_unconditional_matching_remotes_own_contract():
    """Remote's own MATLAB invocation (cryostack_src/models/submission.py)
    is ALSO unconditional -- it never checks whether the file exists
    before calling `run(...)` on it, because Remote always writes it
    first. Cloud's runner keeps its own unconditional invocation
    unchanged (this fix is staging-only); the two together now form the
    same "always staged, therefore safe to invoke unconditionally"
    contract Remote has always relied on."""
    from cryostack_src.cloud.runtime import issm_cloud_runner_script

    script = issm_cloud_runner_script()
    assert "run('${WORKDIR}/postprocess_icesee.m')" in script
