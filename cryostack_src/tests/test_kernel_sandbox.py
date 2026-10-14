"""Isolation acceptance: Voila kernels in the per-user sandbox (bin/cryostack_kernel.py).

The end-to-end tests start real kernels through the gateway's kernelspec with
``CRYOSTACK_KERNEL_SANDBOX=bwrap`` next to a stand-in gateway process holding
fake secrets, and check from inside the kernel -- with
``deployment/check_kernel_isolation.py`` and direct probes -- that it cannot
reach the gateway's environment, databases, credentials, keys or other users'
workspaces, cannot write the code, and can still do its work (own workspace,
imports, MPI, restart, interrupt).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("_cryostack_kernel", _REPO / "bin" / "cryostack_kernel.py")
launcher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(launcher)

ALICE = "alice-sandbox-test-id"


def _bwrap_works() -> bool:
    bwrap = shutil.which("bwrap")
    if not bwrap:
        return False
    probe = subprocess.run([bwrap, "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin",
                            "--symlink", "usr/lib64", "/lib64", "--proc", "/proc", "--dev", "/dev",
                            "--unshare-pid", "/usr/bin/true"], capture_output=True)
    return probe.returncode == 0


needs_bwrap = pytest.mark.skipif(not _bwrap_works(), reason="unprivileged bubblewrap not available")


# ── launcher unit tests ───────────────────────────────────────────────────

def test_off_mode_starts_the_stock_kernel(monkeypatch):
    monkeypatch.setenv(launcher.MODE_ENV, "off")
    seen = {}
    monkeypatch.setattr(launcher.os, "execv", lambda path, argv: seen.update(path=path, argv=argv))
    launcher.main(["-f", "/tmp/kernel-1.json", "--HistoryManager.hist_file=:memory:"])
    assert seen["argv"] == [sys.executable, "-m", "ipykernel_launcher", "-f", "/tmp/kernel-1.json",
                            "--HistoryManager.hist_file=:memory:"]          # as nbclient passes it


@pytest.mark.parametrize("env, message", [
    ({launcher.MODE_ENV: "bwrap"}, "no CryoStack identity"),
    ({launcher.MODE_ENV: "bwrap", "HTTP_X_CRYOSTACK_USER_ID": ALICE,
      launcher.BWRAP_ENV: ""}, None),
    ({launcher.MODE_ENV: "sideways"}, "must be 'off' or 'bwrap'"),
])
def test_sandbox_fails_closed(monkeypatch, tmp_path, capsys, env, message):
    for name in (launcher.MODE_ENV, "HTTP_X_CRYOSTACK_USER_ID", launcher.BWRAP_ENV):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.setattr(launcher.os, "execv", lambda *a: pytest.fail("kernel started"))
    monkeypatch.setattr(launcher.os, "execve", lambda *a: pytest.fail("kernel started"))
    if message is None:                                  # bwrap missing
        monkeypatch.setattr(launcher.shutil, "which", lambda name: None)
        message = "bubblewrap (bwrap) is not installed"
    assert launcher.main(["-f", str(tmp_path / "k.json")]) in (1, 2)
    assert message in capsys.readouterr().err


def test_sandbox_plan_hides_the_installation_and_other_users(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    for d in ("var", "users", "bin", "icesee_jupyter_book/icesee_runs"):
        (repo / d).mkdir(parents=True)
    (repo / "icesee.log").write_text("log")
    monkeypatch.setattr(launcher, "REPO", repo)
    ws = tmp_path / "ws"
    (ws / "users" / "bob-x").mkdir(parents=True)
    conn = tmp_path / "kernel.json"
    conn.write_text("{}")
    env = {"HTTP_X_CRYOSTACK_USER_ID": ALICE, "CRYOSTACK_WORKSPACE_ROOT": str(ws),
           "CRYOSTACK_AUTH_DATABASE": "/x/auth.db", "JPY_PARENT_PID": "1",
           "AWS_SHARED_CREDENTIALS_FILE": "/home/op/.aws/credentials", "AWS_PROFILE": "p"}
    argv, child = launcher.sandbox_command(str(conn), env=env, cwd=tmp_path, bwrap="/usr/bin/bwrap",
                                           operator_home=tmp_path / "home")
    joined = " ".join(argv)
    for flag in ("--unshare-pid", "--die-with-parent", "--new-session", "--cap-drop ALL"):
        assert flag in joined
    assert f"--tmpfs {repo / 'var'}" in joined and f"--tmpfs {repo / 'users'}" in joined
    assert f"--ro-bind /dev/null {repo / 'icesee.log'}" in joined
    assert f"--tmpfs {ws / 'users'}" in joined
    owner = ws / "users" / launcher._owner_dir(ws, ALICE).name
    assert f"--bind {owner} {owner}" in joined and str(ws / "users" / "bob-x") not in joined
    assert f"--ro-bind {repo} {repo}" in joined and f"--bind {repo} " not in joined
    assert child["HOME"] == str(owner / ".cryostack" / "home")
    for name in ("CRYOSTACK_AUTH_DATABASE", "JPY_PARENT_PID", "AWS_SHARED_CREDENTIALS_FILE"):
        assert name not in child
    assert child["AWS_PROFILE"] == "p"
    assert argv[-5:] == [sys.executable, "-m", "ipykernel_launcher", "-f", str(conn.resolve())]


# ── end to end: real kernels ──────────────────────────────────────────────

@pytest.fixture
def sandboxed_kernels(tmp_path, monkeypatch):
    from jupyter_client.manager import start_new_kernel

    ws = tmp_path / "ws"
    other = ws / "users" / "bob-other-user-0000"
    other.mkdir(parents=True)
    (other / "notes.txt").write_text("bob's private notes")
    secrets_dir = tmp_path / "operator"
    (secrets_dir / ".aws").mkdir(parents=True)
    (secrets_dir / ".aws" / "credentials").write_text("[default]\naws_secret_access_key=FAKE\n")
    gateway = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"],
                               env={**os.environ, "CRYOSTACK_SESSION_SECRET": "FAKE-SESSION-SECRET",
                                    "CRYOSTACK_RELAY_CONTROL_TOKEN": "FAKE-RELAY-TOKEN",
                                    "CRYOSTACK_GITHUB_CLIENT_SECRET": "FAKE-OAUTH"})
    for name in ("PYTHONSTARTUP", "JPY_PARENT_PID"):
        monkeypatch.delenv(name, raising=False)
    # Voila hands kernels an allowlisted environment (tested elsewhere); do the same here
    for name in list(os.environ):
        if "SECRET" in name or name.endswith("_TOKEN"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("JUPYTER_PATH", str(_REPO / "bin" / "voila_config"))
    monkeypatch.setenv(launcher.MODE_ENV, "bwrap")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(ws))
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(_REPO), str(_REPO / "external")]))
    started = []

    def start(user_id: str):
        monkeypatch.setenv("HTTP_X_CRYOSTACK_USER_ID", user_id)
        km, kc = start_new_kernel(kernel_name="python3", startup_timeout=120,
                                  cwd=str(_REPO / "icesee_jupyter_book" / "icesee_jupyter_notebooks"))
        started.append(km)
        return km, kc

    yield {"start": start, "ws": ws, "other": other, "gateway": gateway.pid,
           "operator": secrets_dir}
    for km in started:
        km.shutdown_kernel(now=True)
    gateway.kill()
    gateway.wait()


def _run(kc, code: str) -> dict:
    out = []
    reply = kc.execute_interactive(code, timeout=180,
                                   output_hook=lambda m: out.append(m["content"].get("text", ""))
                                   if m["msg_type"] == "stream" else None)
    assert reply["content"]["status"] == "ok", reply["content"]
    return json.loads("".join(out).strip().splitlines()[-1])


@needs_bwrap
def test_sandboxed_kernel_passes_the_isolation_acceptance(sandboxed_kernels):
    k = sandboxed_kernels
    km, kc = k["start"](ALICE)
    own = k["ws"] / "users" / launcher._owner_dir(k["ws"], ALICE).name
    result = _run(kc, f"""
import json, os, sys
sys.path.insert(0, {str(_REPO)!r})
from deployment import check_kernel_isolation as c
r = c.check({str(_REPO)!r}, {str(Path.home())!r}, workspace_root={str(k['ws'])!r},
            own_workspace={str(own)!r}, pids=[{k['gateway']}])
probe = {{}}
probe['processes'] = sorted(int(p) for p in os.listdir('/proc') if p.isdigit())
probe['gateway_environ'] = os.path.exists('/proc/{k['gateway']}/environ')
probe['fake_operator_aws'] = os.path.exists({str(k['operator'] / '.aws' / 'credentials')!r})
probe['other_user'] = os.path.exists({str(k['other'] / 'notes.txt')!r})
probe['home'] = os.environ['HOME']
probe['auth_db_setting'] = 'CRYOSTACK_AUTH_DATABASE' in os.environ
probe['env_secrets'] = [n for n in os.environ if 'SECRET' in n or n.endswith('_TOKEN')]
try:
    open({str(_REPO / 'bin' / 'sandbox-write-test')!r}, 'w'); probe['code_write'] = 'written'
except OSError as e:
    probe['code_write'] = e.__class__.__name__
open(os.path.join({str(own)!r}, 'mine.txt'), 'w').write('ok'); probe['own_write'] = True
import numpy, h5py, ICESEE; probe['imports'] = 'ok'
print(json.dumps({{'check': r, 'probe': probe}}))
""")
    check, probe = result["check"], result["probe"]
    assert check["exposed"] == [], check
    assert check["missing_access"] == [] and check["ok"] is True and check["gateway_visible"] is False
    # bob's directory is not even listed: no other user's workspace exists in this sandbox
    assert not any(label.startswith("other user's") for label in check["exposed"] + check["denied"])
    assert len(probe["processes"]) <= 3 and probe["gateway_environ"] is False
    assert probe["fake_operator_aws"] is False and probe["other_user"] is False
    assert probe["home"] == str(own / ".cryostack" / "home")
    assert probe["auth_db_setting"] is False and probe["env_secrets"] == []
    assert probe["code_write"] in ("OSError", "PermissionError")
    assert probe["own_write"] is True and probe["imports"] == "ok"
    assert (own / "mine.txt").read_text() == "ok"                  # really the user's directory
    assert not (_REPO / "bin" / "sandbox-write-test").exists()


@needs_bwrap
def test_two_users_never_see_each_other(sandboxed_kernels):
    k = sandboxed_kernels
    _km_a, kc_a = k["start"]("alice-sandbox-test-id")
    _run(kc_a, "import os, json; open(os.path.join(os.environ['HOME'], 'alice.txt'), 'w').write('a'); "
               "print(json.dumps({}))")
    _km_b, kc_b = k["start"]("bob-sandbox-test-id")
    seen = _run(kc_b, f"import os, json; print(json.dumps(os.listdir({str(k['ws'] / 'users')!r})))")
    assert len(seen) == 1 and seen[0].startswith("bob-sandbox-test-id")


@needs_bwrap
def test_kernel_lifecycle_and_mpi_work_in_the_sandbox(sandboxed_kernels):
    km, kc = sandboxed_kernels["start"](ALICE)
    mpi = _run(kc, r"""
import json, os, subprocess, sys
p = subprocess.run([os.path.join(sys.prefix, 'bin', 'mpirun'), '--oversubscribe', '-n', '2', sys.executable,
    '-c', 'from mpi4py import MPI; c = MPI.COMM_WORLD; print(c.allreduce(c.Get_rank() + 1))'],
    capture_output=True, text=True, timeout=120)
print(json.dumps({'rc': p.returncode, 'out': p.stdout.split()}))
""")
    assert mpi == {"rc": 0, "out": ["3", "3"]}
    km.restart_kernel(now=False)
    kc.wait_for_ready(timeout=120)
    assert _run(kc, "import json; print(json.dumps({'after': 'restart'}))") == {"after": "restart"}
    msg_id = kc.execute("import time; time.sleep(60)")
    time.sleep(2)
    started = time.time()
    km.interrupt_kernel()
    while True:
        reply = kc.get_shell_msg(timeout=30)
        if reply["parent_header"].get("msg_id") == msg_id:
            break
    assert reply["content"]["ename"] == "KeyboardInterrupt" and time.time() - started < 15
    km.shutdown_kernel(now=False)
    assert not km.is_alive()


@needs_bwrap
def test_ssh_and_aws_work_with_per_user_settings_only(sandboxed_kernels, tmp_path, monkeypatch):
    aws = tmp_path / "kernel-aws"
    aws.mkdir()
    (aws / "config").write_text("[profile cryostack-kernel]\nregion = us-east-1\n")
    (aws / "credentials").write_text("[cryostack-kernel]\naws_access_key_id = AKIASANDBOXTEST\n"
                                     "aws_secret_access_key = sandbox-test-only\n")
    monkeypatch.setenv(launcher.AWS_DIR_ENV, str(aws))
    monkeypatch.setenv("AWS_PROFILE", "cryostack-kernel")
    _km, kc = sandboxed_kernels["start"](ALICE)
    result = _run(kc, r"""
import getpass, json, os, subprocess
from pathlib import Path
home = Path(os.environ['HOME'])
key = home / '.ssh' / 'cryostack' / 'id_ed25519_probe'
key.parent.mkdir(parents=True, exist_ok=True)
gen = subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key)], capture_output=True, text=True)
cfgfile = home / '.ssh' / 'config'; cfgfile.write_text('Host hpc-probe\n    HostName hpc.example.org\n    User probe\n    IdentityFile ' + str(key) + '\n'); cfgfile.chmod(0o600)
cfg = subprocess.run(['ssh', '-G', 'hpc-probe'], capture_output=True, text=True)
from cryostack_src.remote.ssh_identity import cryostack_key_paths
priv, _pub = cryostack_key_paths('ns-probe')
import boto3
creds = boto3.Session().get_credentials()
print(json.dumps({'user': getpass.getuser(), 'keygen': gen.returncode, 'key_in_home': key.is_file(),
    'ssh_hostname': [l for l in cfg.stdout.splitlines() if l.startswith('hostname ')],
    'ssh_rc': cfg.returncode, 'ssh_err': cfg.stderr[-300:], 'cryostack_keys_in_home': str(priv).startswith(str(home)),
    'aws_key': creds.access_key if creds else None, 'operator_known_hosts': os.path.exists('/home/bkyanjo3/.ssh/known_hosts')}))
""")
    assert result["keygen"] == 0 and result["key_in_home"] and result["ssh_rc"] == 0, result
    assert result["ssh_hostname"] == ["hostname hpc.example.org"]
    assert result["user"] and result["cryostack_keys_in_home"]
    assert result["aws_key"] == "AKIASANDBOXTEST"          # only the kernel's own AWS settings
    assert result["operator_known_hosts"] is False


# ── SSH key migration into the per-user homes ─────────────────────────────

def test_ssh_key_migration_copies_each_key_to_its_owner(tmp_path):
    from deployment import migrate_kernel_ssh_keys as migrate

    ssh = tmp_path / "op-ssh"
    (ssh / "cryostack").mkdir(parents=True)
    for name in ("id_ed25519_48daa81ee695409f-pace-b063e22d92c4", "id_ed25519_ffff000011112222-x-1"):
        (ssh / "cryostack" / name).write_text("PRIVATE")
        (ssh / "cryostack" / (name + ".pub")).write_text("ssh-ed25519 AAAA")
    (ssh / "known_hosts").write_text("hpc ssh-ed25519 AAAA\n")
    ws = tmp_path / "ws"
    owner = ws / "users" / "48daa81ee695409f9a63ae133bf22d42-7ec81b4cd674"
    owner.mkdir(parents=True)
    (ws / "users" / "aaaabbbbccccdddd0000-0123").mkdir()
    dry = migrate.plan(ssh, ws)
    assert [c["user_dir"] for c in dry["copies"]] == [owner.name]
    assert dry["unmatched"] == ["id_ed25519_ffff000011112222-x-1"]
    assert not (owner / ".cryostack").exists()                     # dry run writes nothing
    migrate.apply(dry, ssh)
    keys = owner / ".cryostack" / "home" / ".ssh" / "cryostack"
    assert (keys / "id_ed25519_48daa81ee695409f-pace-b063e22d92c4").stat().st_mode & 0o777 == 0o600
    assert (keys / "id_ed25519_48daa81ee695409f-pace-b063e22d92c4.pub").is_file()
    assert (keys.parent / "known_hosts").read_text() == "hpc ssh-ed25519 AAAA\n"
    assert (ssh / "cryostack" / "id_ed25519_48daa81ee695409f-pace-b063e22d92c4").is_file()   # kept
    assert not list((ws / "users" / "aaaabbbbccccdddd0000-0123").iterdir())
    migrate.apply(migrate.plan(ssh, ws), ssh)                      # idempotent
