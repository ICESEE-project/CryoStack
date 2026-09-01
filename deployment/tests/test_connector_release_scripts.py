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


# ── release_connector.sh: the shell privilege boundary ─────────────────────
import hashlib

_SS = _DEPLOYMENT / "connector_store.py"
sys.path.insert(0, str(_DEPLOYMENT))
import connector_store as cs  # noqa: E402


def _seed_store(store: Path, build_dir: Path, name: str, payload: bytes):
    art = build_dir / name
    art.write_bytes(payload)
    plat = name.replace("CryoStack-Connector-", "").rsplit(".tar", 1)[0].rsplit(".", 1)[0]
    (build_dir / (name + ".build.json")).write_text(json.dumps({
        "platform": plat, "filename": name, "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload), "built_at": "2026-09-01T00:00:00Z",
        "pairing_protocol": "v2", "connector_build_revision": "abcdef012345",
    }))
    cs.register(store, art, art.with_name(art.name + ".build.json"))


@pytest.fixture
def release_repo(tmp_path):
    root = tmp_path / "repo"
    (root / "deployment").mkdir(parents=True)
    shutil.copy(_REPO / "release_connector.sh", root / "release_connector.sh")
    for f in ("connector_store.py", "connector_manifest.py", "release_env.sh"):
        shutil.copy(_DEPLOYMENT / f, root / "deployment" / f)
    return root


@pytest.fixture
def fake_priv_bin(tmp_path):
    """A fake `sudo` that records argv, emulates root's write power over the
    test web root, then execs through; plus stub nginx/systemctl."""
    b = tmp_path / "privbin"
    b.mkdir()
    log = tmp_path / "sudo.log"
    (b / "sudo").write_text(
        "#!/bin/sh\n"
        f'printf "SUDO %s\\n" "$*" >> "{log}"\n'
        '[ "$1" = "-u" ] && shift 2\n'
        '[ "$1" = "--" ] && shift\n'
        '[ -n "$CRYOSTACK_WEB_ROOT" ] && chmod -R u+rwX "$CRYOSTACK_WEB_ROOT" 2>/dev/null\n'
        'exec "$@"\n'
    )
    (b / "nginx").write_text('#!/bin/sh\nexit 0\n')
    (b / "systemctl").write_text('#!/bin/sh\nexit 0\n')
    for f in ("sudo", "nginx", "systemctl"):
        (b / f).chmod(0o755)
    return b, log


def _seed_two_platform_store(tmp_path):
    store = tmp_path / "store"
    build_dir = tmp_path / "dist"
    build_dir.mkdir()
    _seed_store(store, build_dir, LINUX, b"linux-release-payload")
    _seed_store(store, build_dir, MAC_ARM, b"macos-release-payload")
    return store


def test_release_runs_candidate_unprivileged_and_promotes_through_sudo(
    release_repo, fake_priv_bin, tmp_path
):
    b, sudo_log = fake_priv_bin
    store = _seed_two_platform_store(tmp_path)

    web_root = tmp_path / "web"
    connectors = web_root / "downloads" / "connectors"
    connectors.mkdir(parents=True)
    (connectors / "oldjunk.txt").write_text("stale from a previous deploy")
    # a root-owned web root: the operator cannot write the parent
    os.chmod(web_root / "downloads", 0o555)

    env = {
        "PATH": f"{b}:{os.environ['PATH']}",
        "CRYOSTACK_CONNECTOR_STORE": str(store),
        "CRYOSTACK_WEB_ROOT": str(web_root),
    }
    r = _bash(f'bash "{release_repo}/release_connector.sh"', env=env)
    assert r.returncode == 0, r.stdout + r.stderr

    calls = sudo_log.read_text() if sudo_log.exists() else ""
    assert "promote" in calls, f"promotion must go through sudo:\n{calls}"
    assert "build-candidate" not in calls, "candidate build must stay unprivileged"
    assert "connector_store.py --store" not in calls, "store inspection must stay unprivileged"

    os.chmod(web_root / "downloads", 0o755)
    assert not (connectors / "oldjunk.txt").exists()          # full replace
    served = {p.name for p in connectors.iterdir()}
    assert served == {LINUX, MAC_ARM, "manifest.json", "SHA256SUMS"}
    cs.cm.verify(connectors)


def test_release_stays_unprivileged_when_the_web_root_is_writable(
    release_repo, fake_priv_bin, tmp_path
):
    b, sudo_log = fake_priv_bin
    store = _seed_two_platform_store(tmp_path)
    web_root = tmp_path / "web"
    (web_root / "downloads").mkdir(parents=True)          # owned + writable by us

    r = _bash(f'bash "{release_repo}/release_connector.sh"', env={
        "PATH": f"{b}:{os.environ['PATH']}",
        "CRYOSTACK_CONNECTOR_STORE": str(store),
        "CRYOSTACK_WEB_ROOT": str(web_root),
    })
    assert r.returncode == 0, r.stdout + r.stderr
    calls = sudo_log.read_text() if sudo_log.exists() else ""
    assert "promote" not in calls                          # no escalation needed
    cs.cm.verify(web_root / "downloads" / "connectors")


def test_print_config_reports_when_promotion_needs_root(release_repo, tmp_path):
    web = tmp_path / "web"
    (web / "downloads").mkdir(parents=True)

    def cfg(env):
        r = subprocess.run(
            ["bash", f"{release_repo}/release_connector.sh", "--print-config"],
            capture_output=True, text=True,
            env={**{k: v for k, v in os.environ.items() if k != "CRYOSTACK_CONNECTOR_STORE"}, **env},
        )
        assert r.returncode == 0, r.stdout + r.stderr
        return dict(l.split("=", 1) for l in r.stdout.splitlines() if "=" in l)

    assert cfg({"CRYOSTACK_WEB_ROOT": str(web)})["privileged_promotion"] == "no"
    os.chmod(web / "downloads", 0o555)
    assert cfg({"CRYOSTACK_WEB_ROOT": str(web)})["privileged_promotion"] == "yes"
    os.chmod(web / "downloads", 0o755)


def test_release_under_whole_script_sudo_keeps_store_off_root(release_repo):
    me = subprocess.run(["id", "-un"], capture_output=True, text=True).stdout.strip()
    real_home = subprocess.run(
        ["getent", "passwd", me], capture_output=True, text=True
    ).stdout.strip().split(":")[5]

    r = subprocess.run(
        ["bash", f"{release_repo}/release_connector.sh", "--print-config"],
        capture_output=True, text=True,
        env={**{k: v for k, v in os.environ.items() if k != "CRYOSTACK_CONNECTOR_STORE"},
             "SUDO_USER": me, "HOME": "/root"},
    )
    assert r.returncode == 0, r.stdout + r.stderr
    cfg = dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)
    assert cfg["release_owner"] == me
    assert cfg["canonical_store"] == f"{real_home}/.cryostack/connector-artifacts"
    assert "/root/.cryostack" not in r.stdout
