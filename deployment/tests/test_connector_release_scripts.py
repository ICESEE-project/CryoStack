"""Phase-A hardening: release-owner identity + remote store resolution.

Two real-host defects:
  1. `publish_connector_artifact.sh` expanded the default store with the
     *builder's* $HOME (/Users/... on a Mac) and passed that literal to the
     Linux release host.
  2. `sudo bash release_connector.sh` resolved the canonical store from
     /root/.cryostack instead of the release owner's home.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

_DEPLOYMENT = Path(__file__).resolve().parents[1]
_REPO = _DEPLOYMENT.parent

LINUX = "CryoStack-Connector-linux-x86_64.tar.gz"
MAC_ARM = "CryoStack-Connector-macos-arm64.dmg"


def _bash(script: str, env: dict | None = None) -> subprocess.CompletedProcess:
    full = dict(os.environ)
    full.pop("SUDO_USER", None)
    if env:
        full.update(env)
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=full)


# ── release_env.sh: the store owner is never root-under-sudo ──────────────
RELEASE_ENV = _DEPLOYMENT / "release_env.sh"
ME = subprocess.run(["id", "-un"], capture_output=True, text=True).stdout.strip()
MY_HOME = subprocess.run(
    ["getent", "passwd", ME], capture_output=True, text=True
).stdout.strip().split(":")[5]


def test_release_home_ignores_root_home_under_sudo():
    r = _bash(f'source "{RELEASE_ENV}"; cryostack_release_home',
              env={"SUDO_USER": ME, "HOME": "/root"})
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == MY_HOME
    assert r.stdout.strip() != "/root"


def test_release_owner_is_sudo_user_when_set():
    r = _bash(f'source "{RELEASE_ENV}"; cryostack_release_owner',
              env={"SUDO_USER": ME, "HOME": "/root"})
    assert r.stdout.strip() == ME


def test_release_home_honours_custom_home_without_sudo():
    r = _bash(f'source "{RELEASE_ENV}"; cryostack_release_home',
              env={"HOME": "/tmp/some/custom/home"})
    assert r.stdout.strip() == "/tmp/some/custom/home"


def test_release_owner_falls_back_to_current_user():
    r = _bash(f'source "{RELEASE_ENV}"; cryostack_release_owner')
    assert r.stdout.strip() == ME


# ── publish_connector_artifact.sh: no builder-$HOME leak across ssh ──────
@pytest.fixture
def fake_repo(tmp_path):
    """A minimal repo tree with the publish script + a fake artifact."""
    root = tmp_path / "repo"
    (root / "deployment").mkdir(parents=True)
    (root / "dist" / "packages").mkdir(parents=True)
    shutil.copy(_REPO / "publish_connector_artifact.sh", root / "publish_connector_artifact.sh")
    shutil.copy(_DEPLOYMENT / "connector_store.py", root / "deployment" / "connector_store.py")
    shutil.copy(_DEPLOYMENT / "connector_manifest.py", root / "deployment" / "connector_manifest.py")

    art = root / "dist" / "packages" / MAC_ARM
    art.write_bytes(b"fake-dmg-payload")
    (root / "dist" / "packages" / (MAC_ARM + ".build.json")).write_text(json.dumps({
        "platform": "macos-arm64", "filename": MAC_ARM,
        "sha256": "0" * 64, "size_bytes": 16, "built_at": "2026-09-01T00:00:00Z",
        "pairing_protocol": "v2", "connector_build_revision": "abc123abc123",
    }))
    return root


@pytest.fixture
def fake_bin(tmp_path):
    """Fake ssh/scp that record their argv to a file."""
    b = tmp_path / "bin"
    b.mkdir()
    rec = tmp_path / "calls.log"
    (b / "ssh").write_text(
        "#!/bin/sh\n"
        f'printf "SSH %s\\n" "$*" >> "{rec}"\n'
        'case "$*" in *"mktemp -d"*) echo /tmp/fake-remote-tmp ;; esac\n'
    )
    (b / "scp").write_text("#!/bin/sh\n" f'printf "SCP %s\\n" "$*" >> "{rec}"\n')
    for f in ("ssh", "scp"):
        (b / f).chmod(0o755)
    return b, rec


def _run_publish(fake_repo, fake_bin, extra_env):
    b, rec = fake_bin
    env = {
        "PATH": f"{b}:{os.environ['PATH']}",
        "HOME": "/Users/alice",  # a Mac builder home
        "CRYOSTACK_RELEASE_HOST": "release.example.edu",
        "CRYOSTACK_RELEASE_USER": "deployer",
        **extra_env,
    }
    r = _bash(f'bash "{fake_repo}/publish_connector_artifact.sh"', env=env)
    return r, (rec.read_text() if rec.exists() else "")


def test_publish_remote_never_leaks_builder_home(fake_repo, fake_bin):
    r, calls = _run_publish(fake_repo, fake_bin, {})
    assert r.returncode == 0, r.stderr + r.stdout
    ssh_lines = [ln for ln in calls.splitlines() if ln.startswith("SSH ")]
    register = [ln for ln in ssh_lines if "register" in ln]
    assert register, calls
    joined = "\n".join(ssh_lines)
    assert "/Users/alice" not in joined              # builder home never crosses
    assert "--store" not in joined                   # remote resolves its own default


def test_publish_remote_forwards_only_an_explicit_store(fake_repo, fake_bin):
    r, calls = _run_publish(fake_repo, fake_bin, {"CRYOSTACK_RELEASE_STORE": "/srv/cryostack/store"})
    assert r.returncode == 0, r.stderr + r.stdout
    register = [ln for ln in calls.splitlines() if ln.startswith("SSH ") and "register" in ln]
    assert register
    assert "--store /srv/cryostack/store" in register[0]
    assert "/Users/alice" not in "\n".join(calls.splitlines())
