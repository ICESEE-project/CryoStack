"""Phase-A follow-up: deploy_web.sh must hand nginx a readable static tree.

Reproduces the live 403: the repo's web/ tree is 0770 dirs / 0660 files (the
repo's group-shared umask); `rsync -a` preserves that; the nginx worker is a
different unprivileged user -> `open() ... (13: Permission denied)`.
deploy_web.sh must re-harden the subtrees it owns to 0755 / 0644.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

_DEPLOYMENT = Path(__file__).resolve().parents[1]
_DEPLOY_WEB_DIR = _DEPLOYMENT / "deploy_web_nginx"


@pytest.fixture
def fake_bin(tmp_path):
    """sudo (exec-through), nginx (-T user, -t ok), systemctl, restorecon,
    getenforce (Disabled), and a curl that records URLs."""
    b = tmp_path / "bin"
    b.mkdir()
    curl_log = tmp_path / "curl.log"
    (b / "sudo").write_text(
        "#!/bin/sh\n"
        '[ "$1" = "-u" ] && shift 2\n'
        '[ "$1" = "--" ] && shift\n'
        'exec "$@"\n'
    )
    (b / "nginx").write_text(
        '#!/bin/sh\n'
        'case "$1" in\n'
        '  -T) echo "user nginx;" ;;\n'
        '  -t) exit 0 ;;\n'
        'esac\n'
    )
    (b / "systemctl").write_text("#!/bin/sh\nexit 0\n")
    (b / "restorecon").write_text("#!/bin/sh\nexit 0\n")
    (b / "getenforce").write_text("#!/bin/sh\necho Disabled\n")
    (b / "curl").write_text(
        "#!/bin/sh\n"
        f'for a in "$@"; do case "$a" in http*) printf "%s\\n" "$a" >> "{curl_log}" ;; esac; done\n'
        "exit 0\n"
    )
    for f in ("sudo", "nginx", "systemctl", "restorecon", "getenforce", "curl"):
        (b / f).chmod(0o755)
    return b, curl_log


@pytest.fixture
def deploy_repo(tmp_path):
    """A copy of deploy_web_nginx/ with a deliberately unreadable source tree."""
    root = tmp_path / "deploy_web_nginx"
    shutil.copytree(_DEPLOY_WEB_DIR, root)
    # simulate the repo's group-shared umask on the source assets
    for p in root.rglob("*"):
        if p.is_dir():
            p.chmod(0o770)
        else:
            p.chmod(0o660)
    root.chmod(0o755)
    (root / "deploy_web.sh").chmod(0o755)
    return root


def _mode(p: Path) -> int:
    return stat.S_IMODE(p.stat().st_mode)


def _run(deploy_repo, fake_bin, served, confd, extra_env=None):
    b, _ = fake_bin
    env = {
        **os.environ,
        "PATH": f"{b}:{os.environ['PATH']}",
        "CRYOSTACK_WEB_ROOT": str(served),
        "CRYOSTACK_NGINX_CONFD": str(confd),
        "CRYOSTACK_PUBLIC_BASE": "http://smoke.test",
    }
    env.update(extra_env or {})
    return subprocess.run(
        ["bash", str(deploy_repo / "deploy_web.sh")],
        capture_output=True, text=True, env=env,
    )


def test_deploy_hardens_the_static_tree_for_nginx(deploy_repo, fake_bin, tmp_path):
    served = tmp_path / "served"
    confd = tmp_path / "confd"
    confd.mkdir()

    r = _run(deploy_repo, fake_bin, served, confd)
    assert r.returncode == 0, r.stdout + r.stderr

    connect = served / "connect"
    index = connect / "index.html"
    js = connect / "connect.js"

    assert index.is_file() and js.is_file()
    assert _mode(served) == 0o755
    assert _mode(connect) == 0o755, oct(_mode(connect))
    assert _mode(index) == 0o644, oct(_mode(index))
    assert _mode(js) == 0o644
    # world-readable / traversable == readable by a different (nginx) user
    assert _mode(connect) & 0o001 and _mode(connect) & 0o004
    assert _mode(index) & 0o004


def test_connectors_subtree_contents_are_left_to_release_connector(deploy_repo, fake_bin, tmp_path):
    served = tmp_path / "served"
    # a pre-existing published connector release owned "by root" (0644 files)
    (served / "downloads" / "connectors").mkdir(parents=True)
    art = served / "downloads" / "connectors" / "CryoStack-Connector-linux-x86_64.tar.gz"
    art.write_bytes(b"binary")
    art.chmod(0o600)                      # deliberately not 0644
    confd = tmp_path / "confd"
    confd.mkdir()

    r = _run(deploy_repo, fake_bin, served, confd)
    assert r.returncode == 0, r.stdout + r.stderr

    assert art.read_bytes() == b"binary"          # not wiped
    assert _mode(art) == 0o600                     # deploy_web.sh did NOT touch it
    assert _mode(served / "downloads" / "connectors") == 0o755   # dir stays traversable


def test_query_strings_do_not_create_files_and_smoke_check_hits_them(deploy_repo, fake_bin, tmp_path):
    b, curl_log = fake_bin
    served = tmp_path / "served"
    confd = tmp_path / "confd"
    confd.mkdir()

    r = _run(deploy_repo, fake_bin, served, confd)
    assert r.returncode == 0, r.stdout + r.stderr

    hits = curl_log.read_text().splitlines() if curl_log.exists() else []
    assert "http://smoke.test/connect/" in hits
    assert "http://smoke.test/connect/?app=icesheets" in hits
    # a query string is never a filesystem path
    assert {"index.html", "connect.js", "package.json"} <= {
        p.name for p in (served / "connect").iterdir()
    }
    assert not any("?" in p.name for p in served.rglob("*"))


def test_skip_smoke_env_disables_the_http_check(deploy_repo, fake_bin, tmp_path):
    b, curl_log = fake_bin
    served = tmp_path / "served"
    confd = tmp_path / "confd"
    confd.mkdir()

    r = _run(deploy_repo, fake_bin, served, confd, {"CRYOSTACK_SKIP_SMOKE": "1"})
    assert r.returncode == 0, r.stdout + r.stderr
    assert not curl_log.exists() or curl_log.read_text().strip() == ""


def test_nginx_still_maps_connect_to_the_var_www_path():
    conf = (_DEPLOY_WEB_DIR / "nginx" / "icesee.conf").read_text()
    assert "alias /var/www/cryolauncher/connect/;" in conf
    assert "location /connect/" in conf


def test_static_page_has_no_connector_secrets():
    for name in ("index.html", "connect.js"):
        text = (_DEPLOY_WEB_DIR / "web" / "connect" / name).read_text()
        for secret in ("control_secret", "session_secret", "pairing_code"):
            assert secret not in text
    js = (_DEPLOY_WEB_DIR / "web" / "connect" / "connect.js").read_text()
    assert "/connector/latest" not in js          # v2: no global discovery
    assert "/connector/status/" in js             # ?session= is used for status polling
