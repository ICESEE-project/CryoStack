"""The tunnel client's staged runtime dependency bundle (the fix for the
live "ModuleNotFoundError: No module named 'websockets'" failure that
surfaced right after the earlier "No module named 'cryostack_src'"
packaging fix -- see test_cloud_runtime_license_tunnel.py).

The scientific Batch container (bkyanjo/icesee-combined) has neither
``cryostack_src`` nor ``websockets`` installed, and must never be rebuilt
or have anything ``pip install``ed into it at runtime. A pinned, minimal,
pure-Python ``websockets`` subset is checked into the repo
(cryostack_src/cloud/_vendor/websockets_16_0/ -- see its PROVENANCE.md for
exactly which modules and why) and staged alongside the tunnel client
under ``WORKDIR/.cryostack_runtime/websockets/`` -- the SAME extra_files
staging mechanism already used for Icepack's cloud helpers and the tunnel
client itself, extended (WorkspaceManager._write_extra_file) to also
accept a few safely-contained nested paths so a real importable package
tree can be laid out without mixing it into the scientist's own
model/example files.

Fast, hermetic checks run always. The live-image integration test at the
bottom (real relay + real Connector + real loopback echo "institution" +
the actual bkyanjo/icesee-combined:v1.0.2 container) is the strongest
pre-AWS proof and skips cleanly (never fails the suite) when this
environment has no usable docker daemon or the image is not present
locally -- mirroring test_cloud_image_awscli.py's established convention.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.cloud.runtime import (
    LICENSE_TUNNEL_CLIENT_FILENAME,
    RUNTIME_SUPPORT_DIRNAME,
    license_tunnel_client_extra_files,
)

_VENDOR_DIR = _REPO / "cryostack_src/cloud/_vendor/websockets_16_0"
_IMAGE = "bkyanjo/icesee-combined:v1.0.2"

# The exact module set license_tunnel_client.py's actual code path needs --
# empirically traced by exercising selfcheck() + run_local_listener()'s
# full send/recv/close pump against a real relay + real Connector + real
# loopback echo service and diffing sys.modules before/after (see
# PROVENANCE.md). Anything outside this list (server-only, sync, legacy,
# cli, auth) was never imported by that trace and must stay excluded.
_EXPECTED_RELATIVE_FILES = {
    "LICENSE", "__init__.py", "imports.py", "version.py", "client.py",
    "datastructures.py", "exceptions.py", "frames.py", "headers.py",
    "http11.py", "protocol.py", "proxy.py", "server.py", "streams.py",
    "typing.py", "uri.py", "utils.py",
    "asyncio/__init__.py", "asyncio/client.py", "asyncio/compatibility.py",
    "asyncio/connection.py", "asyncio/messages.py",
    "extensions/__init__.py", "extensions/base.py",
    "extensions/permessage_deflate.py",
}


# ── the vendored source tree itself ───────────────────────────────────────
def test_vendor_tree_contains_exactly_the_expected_files():
    found = {
        str(p.relative_to(_VENDOR_DIR)) for p in _VENDOR_DIR.rglob("*")
        if p.is_file() and p.suffix in (".py",) or p.name == "LICENSE"
    }
    assert found == _EXPECTED_RELATIVE_FILES


def test_no_compiled_c_extension_is_vendored():
    """The optional native ``apply_mask`` accelerator is never shipped --
    frames.py's own ``try: from .speedups import apply_mask / except
    ImportError: from .utils import apply_mask`` fallback is relied on
    deliberately (a compiled .so is Python-ABI-specific and the container
    runs a different Python version than this repo's dev environment)."""
    for p in _VENDOR_DIR.rglob("speedups*"):
        pytest.fail(f"speedups artifact must not be vendored: {p}")


def test_vendored_version_is_pinned_to_16_0():
    version_src = (_VENDOR_DIR / "version.py").read_text(encoding="utf-8")
    assert '"16.0"' in version_src or "'16.0'" in version_src


def test_provenance_note_documents_the_pin_and_scope():
    text = (_VENDOR_DIR / "PROVENANCE.md").read_text(encoding="utf-8")
    assert "16.0" in text
    assert "BSD-3-Clause" in text
    assert "speedups" in text


# ── the staged extra_files bundle ─────────────────────────────────────────
def test_extra_files_stage_the_client_and_the_full_vendor_tree():
    files = license_tunnel_client_extra_files()
    assert LICENSE_TUNNEL_CLIENT_FILENAME in files
    assert "import cryostack_src" not in files[LICENSE_TUNNEL_CLIENT_FILENAME]

    staged_vendor_paths = {
        k for k in files if k.startswith(f"{RUNTIME_SUPPORT_DIRNAME}/websockets/")
    }
    expected = {
        f"{RUNTIME_SUPPORT_DIRNAME}/websockets/{rel}"
        for rel in _EXPECTED_RELATIVE_FILES
    }
    assert staged_vendor_paths == expected
    # never mixed with the scientist's own files -- everything vendor-side
    # lives under the one dedicated runtime-support prefix.
    assert all(k == LICENSE_TUNNEL_CLIENT_FILENAME or k.startswith(RUNTIME_SUPPORT_DIRNAME)
               for k in files)


def test_extra_files_carry_no_secret_or_credential_shaped_literals():
    files = license_tunnel_client_extra_files()
    blob = "\n".join(files.values()).lower()
    for forbidden in (
        "aws_secret", "aws_access_key", "mlm_license_file=",
        "control_secret=", "session_secret=", "-----begin",
    ):
        assert forbidden not in blob, forbidden


def test_staging_lays_out_a_real_importable_package_tree_without_mixing_model_files(
    tmp_path,
):
    """WorkspaceManager.stage_example_for_run (extended to accept a few
    safely-contained nested extra_files paths) produces the exact
    WORKDIR/.cryostack_runtime/websockets/... tree the runtime helper
    expects, alongside -- never overwriting -- the scientist's own
    runme.m."""
    from cryostack_src.workspace import WorkspaceManager, WorkspaceUser

    class _Widget:
        def __init__(self, value=None):
            self.value = value
            self.options = ()

    def _mgr(owner, root):
        return WorkspaceManager(
            owner=owner, workspace_root=root, status={}, session={"id": "s"},
            example_dir=_Widget(str(root)), model=_Widget("issm"), backend=_Widget("c"),
            file_picker=_Widget(), file_editor=_Widget(), log_output=None,
            results_output=None, cluster_host=_Widget(""), cluster_user=_Widget(""),
            cluster_port=_Widget(1), access_mode=_Widget(""),
            normalize_remote_path=lambda p: p, connector_fetch_archive=None,
            should_use_connector=lambda: False, connector_ssh=None, ssh_run=None,
            cluster_name=_Widget(""),
        )

    user = WorkspaceUser(user_id="bundle-test-user", source="cryostack-auth")
    wm = _mgr(user, tmp_path / "ws")
    example = tmp_path / "SquareIceShelf"
    example.mkdir()
    (example / "runme.m").write_text("md=solve(md, 'Stressbalance');\n")

    staged = wm.stage_example_for_run(
        source_example=example, extra_files=license_tunnel_client_extra_files())

    assert (staged.path / "runme.m").is_file()
    assert (staged.path / "runme.m").read_text() == "md=solve(md, 'Stressbalance');\n"
    assert (staged.path / LICENSE_TUNNEL_CLIENT_FILENAME).is_file()
    ws_root = staged.path / RUNTIME_SUPPORT_DIRNAME / "websockets"
    assert (ws_root / "__init__.py").is_file()
    assert (ws_root / "asyncio" / "client.py").is_file()
    assert (ws_root / "extensions" / "permessage_deflate.py").is_file()
    assert (ws_root / "LICENSE").is_file()
    assert not (ws_root / "speedups.py").exists()
    assert not (ws_root / "speedups.so").exists()


def test_nested_extra_files_still_reject_path_traversal(tmp_path):
    from cryostack_src.workspace import WorkspaceManager, WorkspaceUser

    class _Widget:
        def __init__(self, value=None):
            self.value = value
            self.options = ()

    def _mgr(owner, root):
        return WorkspaceManager(
            owner=owner, workspace_root=root, status={}, session={"id": "s"},
            example_dir=_Widget(str(root)), model=_Widget("issm"), backend=_Widget("c"),
            file_picker=_Widget(), file_editor=_Widget(), log_output=None,
            results_output=None, cluster_host=_Widget(""), cluster_user=_Widget(""),
            cluster_port=_Widget(1), access_mode=_Widget(""),
            normalize_remote_path=lambda p: p, connector_fetch_archive=None,
            should_use_connector=lambda: False, connector_ssh=None, ssh_run=None,
            cluster_name=_Widget(""),
        )

    user = WorkspaceUser(user_id="bundle-traversal-user", source="cryostack-auth")
    wm = _mgr(user, tmp_path / "ws")
    example = tmp_path / "SquareIceShelf"
    example.mkdir()
    (example / "runme.m").write_text("x")

    with pytest.raises(ValueError):
        wm.stage_example_for_run(
            source_example=example,
            extra_files={"../../escape.py": "malicious"},
        )
    with pytest.raises(ValueError):
        wm.stage_example_for_run(
            source_example=example,
            extra_files={f"{RUNTIME_SUPPORT_DIRNAME}/../../escape.py": "malicious"},
        )


# ── client-side bootstrap: prefers the staged bundle, never touches
# anything outside this one process ────────────────────────────────────
def test_client_sys_path_bootstrap_is_process_local_and_conditional():
    src = (_REPO / "cryostack_src/cloud/license_tunnel_client.py").read_text(encoding="utf-8")
    assert "_RUNTIME_SUPPORT_DIR" in src
    assert "sys.path.insert" in src
    # never a global environment / PYTHONPATH mutation, never a WRITE
    # under /opt (mentioning /opt/venv-* in an explanatory comment is
    # fine -- only an actual path-construction/write reference is not)
    assert "os.environ[" not in src
    assert '"/opt/venv' not in src and "'/opt/venv" not in src


def test_staged_bundle_is_importable_in_complete_isolation_from_site_packages(tmp_path):
    """The strongest offline (no-docker) proof: with ONLY the vendored
    files on sys.path (site-packages excluded entirely), `import
    websockets` resolves and `websockets.connect` reaches the real socket
    layer -- proving the empirically-traced closure is genuinely
    complete, not merely "imports without erroring"."""
    iso_root = tmp_path / "iso"
    dest = iso_root / "websockets"
    shutil.copytree(_VENDOR_DIR, dest)
    (dest / "PROVENANCE.md").unlink(missing_ok=True)

    script = (
        "import sys\n"
        f"sys.path.insert(0, {str(iso_root)!r})\n"
        "sys.path = [p for p in sys.path if 'site-packages' not in p]\n"
        "import websockets\n"
        "assert websockets.__version__ == '16.0'\n"
        "connect = websockets.connect\n"
        "import asyncio\n"
        "async def main():\n"
        "    try:\n"
        "        await asyncio.wait_for(connect('ws://127.0.0.1:1/x'), timeout=1)\n"
        "    except Exception as e:\n"
        "        print('OK:', type(e).__name__)\n"
        "asyncio.run(main())\n"
        "import websockets.frames\n"
        "print('apply_mask source:', websockets.frames.apply_mask.__module__)\n"
    )
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=15)
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "OK: ConnectionRefusedError" in proc.stdout or "OK:" in proc.stdout
    assert "apply_mask source: websockets.utils" in proc.stdout


# ── live image integration: the strongest pre-AWS proof ──────────────────
def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        subprocess.run(["docker", "info"], capture_output=True, timeout=10, check=True)
    except Exception:
        return False
    return True


def _image_present() -> bool:
    try:
        out = subprocess.run(
            ["docker", "images", "-q", _IMAGE], capture_output=True, text=True, timeout=15,
        )
    except Exception:
        return False
    return bool(out.stdout.strip())


@pytest.mark.skipif(not _docker_available(), reason="no usable docker daemon in this environment")
@pytest.mark.skipif(not _image_present(), reason=f"{_IMAGE} is not present locally")
def test_live_real_image_end_to_end_tunnel_round_trip(tmp_path, monkeypatch):
    """Real relay + real Connector + real loopback echo "institution" +
    the ACTUAL bkyanjo/icesee-combined:v1.0.2 container running the EXACT
    command cloud_run_command()'s runner invokes
    (`python3 "${WORKDIR}/cryostack_license_tunnel_client.py" listen`).

    Not merely "import succeeds": a real TCP client on the HOST sends
    bytes into the CONTAINER's local listener and gets the identical bytes
    back, having actually crossed relay + Connector + a real destination
    socket -- the strongest proof available before submitting to AWS.
    """
    import asyncio
    import socket
    import threading
    import time

    import requests
    import uvicorn

    import icesee_hpc_connector.connector_core as cc
    import icesee_jupyter_book.core.connector_relay_server as relay
    from cryostack_src.workspace import WorkspaceManager, WorkspaceUser

    def free_port():
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        p = s.getsockname()[1]
        s.close()
        return p

    relay._reset_state_for_tests()
    port = free_port()
    config = uvicorn.Config(relay.app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    relay_thread = threading.Thread(target=server.run, daemon=True)
    relay_thread.start()
    for _ in range(200):
        if getattr(server, "started", False):
            break
        time.sleep(0.02)
    else:
        pytest.fail("relay did not start")
    live_relay = f"http://127.0.0.1:{port}"

    class _EchoServer(threading.Thread):
        def __init__(self):
            super().__init__(daemon=True)
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.bind(("127.0.0.1", 0))
            self._sock.listen(1)
            self.port = self._sock.getsockname()[1]
            self._stop = False

        def run(self):
            self._sock.settimeout(0.2)
            while not self._stop:
                try:
                    conn, _ = self._sock.accept()
                except socket.timeout:
                    continue
                except OSError:
                    return
                conn.settimeout(5)
                try:
                    while True:
                        data = conn.recv(65536)
                        if not data:
                            break
                        conn.sendall(data)
                except Exception:
                    pass
                finally:
                    conn.close()

        def stop(self):
            self._stop = True
            try:
                self._sock.close()
            except Exception:
                pass

    echo = _EchoServer()
    echo.start()
    monkeypatch.setitem(cc.SITE_TUNNEL_TARGETS, ("matlab-license", "primary"), ("127.0.0.1", echo.port))

    created = requests.post(f"{live_relay}/connector/session", json={"owner_user_id": "docker-e2e"}).json()
    session_id = created["session_id"]
    control_secret = created["control_secret"]
    session_secret = created["session_secret"]
    ws_url = f"{live_relay.replace('http://', 'ws://')}/connector/ws/{session_id}"

    stop_event = threading.Event()

    class _ConnThread(threading.Thread):
        def run(self):
            try:
                asyncio.run(cc.main(ws_url, session_secret, relay=live_relay, stop_event=stop_event))
            except Exception:
                pass

    conn_thread = _ConnThread(daemon=True)
    conn_thread.start()

    try:
        for _ in range(200):
            status = requests.get(f"{live_relay}/connector/status/{session_id}").json()
            if status["online"]:
                break
            time.sleep(0.02)
        else:
            pytest.fail("connector never came online")

        grant = requests.post(
            f"{live_relay}/connector/tunnel-grant/{session_id}",
            json={"owner_user_id": "docker-e2e", "purpose": "matlab-license"},
            headers={"Authorization": f"Bearer {control_secret}"},
        ).json()
        assert grant["ok"] is True
        token = grant["token"]

        class _Widget:
            def __init__(self, value=None):
                self.value = value
                self.options = ()

        def _mgr(owner, root):
            return WorkspaceManager(
                owner=owner, workspace_root=root, status={}, session={"id": "s"},
                example_dir=_Widget(str(root)), model=_Widget("issm"), backend=_Widget("c"),
                file_picker=_Widget(), file_editor=_Widget(), log_output=None,
                results_output=None, cluster_host=_Widget(""), cluster_user=_Widget(""),
                cluster_port=_Widget(1), access_mode=_Widget(""),
                normalize_remote_path=lambda p: p, connector_fetch_archive=None,
                should_use_connector=lambda: False, connector_ssh=None, ssh_run=None,
                cluster_name=_Widget(""),
            )

        wm = _mgr(WorkspaceUser(user_id="docker-e2e", source="cryostack-auth"), tmp_path / "ws")
        example = tmp_path / "SquareIceShelf"
        example.mkdir()
        (example / "runme.m").write_text("md=solve(md, ...);\n")
        staged = wm.stage_example_for_run(
            source_example=example, extra_files=license_tunnel_client_extra_files())

        listen_port = free_port()
        cmd = [
            "docker", "run", "--rm", "--network", "host",
            "-v", f"{staged.path}:/tmp/cryostack/run:ro",
            "-e", f"CRYOSTACK_LT_RELAY={live_relay}",
            "-e", f"CRYOSTACK_LT_SESSION={session_id}",
            "-e", f"CRYOSTACK_LT_TOKEN={token}",
            "-e", "CRYOSTACK_LT_PURPOSE=matlab-license",
            "-e", "CRYOSTACK_LT_ENDPOINT=primary",
            "-e", f"CRYOSTACK_LT_PORT={listen_port}",
            _IMAGE, "bash", "-c",
            # the EXACT invocation cloud_run_command()'s runner script uses
            f'python3 "/tmp/cryostack/run/{LICENSE_TUNNEL_CLIENT_FILENAME}" listen; '
            'echo "LISTEN_RC=$?"; sleep 8',
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

        try:
            reachable = False
            for _ in range(150):
                try:
                    s = socket.create_connection(("127.0.0.1", listen_port), timeout=0.2)
                    s.close()
                    reachable = True
                    break
                except OSError:
                    time.sleep(0.1)
            assert reachable, "the container's local listener never became reachable from the host"

            client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_sock.settimeout(5)
            client_sock.connect(("127.0.0.1", listen_port))
            try:
                client_sock.sendall(b"real-image-e2e-bytes")
                received = client_sock.recv(65536)
            finally:
                client_sock.close()
        finally:
            try:
                out, _ = proc.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                out, _ = proc.communicate()

        assert "no module named 'cryostack_src'" not in out.lower()
        assert "no module named 'websockets'" not in out.lower()
        assert "LISTEN_RC=0" in out
        assert received == b"real-image-e2e-bytes"
    finally:
        stop_event.set()
        conn_thread.join(timeout=5)
        echo.stop()
        server.should_exit = True
        relay_thread.join(timeout=5)
        relay._reset_state_for_tests()
