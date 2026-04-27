from __future__ import annotations

import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path




@dataclass
class SSHKeyInfo:
    cluster_id: str
    alias: str
    host: str
    user: str
    private_key: Path
    public_key: Path


def _safe_name(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9._-]+", "_", text)
    return text.strip("_") or "cluster"


def cluster_key_paths(cluster_id: str) -> tuple[Path, Path]:
    safe = _safe_name(cluster_id)
    priv = Path.home() / ".ssh" / f"id_ed25519_icesee_{safe}"
    pub = Path(str(priv) + ".pub")
    return priv, pub


def make_ssh_key_info(cluster_id: str, host: str, user: str, alias: str | None = None) -> SSHKeyInfo:
    priv, pub = cluster_key_paths(cluster_id)
    return SSHKeyInfo(
        cluster_id=cluster_id,
        alias=alias or _safe_name(cluster_id),
        host=host.strip(),
        user=user.strip(),
        private_key=priv,
        public_key=pub,
    )


def ensure_cluster_ssh_key(
    cluster_id: str,
    comment: str,
    passphrase: str = "",
) -> tuple[Path, Path, bool]:
    priv, pub = cluster_key_paths(cluster_id)

    if priv.exists() and pub.exists():
        return priv, pub, False

    priv.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ssh-keygen",
        "-t", "ed25519",
        "-C", comment,
        "-f", str(priv),
        "-N", passphrase,
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return priv, pub, True


def read_public_key(public_key: Path) -> str:
    if not public_key.exists():
        raise FileNotFoundError(f"Public key not found: {public_key}")
    return public_key.read_text(encoding="utf-8").strip()


def ssh_agent_running() -> bool:
    return bool(os.environ.get("SSH_AUTH_SOCK"))


def list_agent_keys() -> subprocess.CompletedProcess:
    return subprocess.run(
        ["ssh-add", "-L"],
        capture_output=True,
        text=True,
        check=False,
    )


def key_loaded_in_agent(private_key: Path) -> bool:
    r = list_agent_keys()
    if r.returncode != 0:
        return False

    pub = Path(str(private_key) + ".pub")
    if not pub.exists():
        return False

    pub_text = pub.read_text(encoding="utf-8").strip()
    pub_parts = pub_text.split()
    if len(pub_parts) < 2:
        return False

    pub_blob = pub_parts[1]
    return pub_blob in (r.stdout or "")


def add_key_to_agent(private_key: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["ssh-add", str(private_key)],
        capture_output=True,
        text=True,
        check=False,
    )


def ssh_agent_start_instructions() -> str:
    return (
        'Run this in your terminal first:\n'
        'eval "$(ssh-agent -s)"\n'
        'Then add the key with:\n'
        'ssh-add ~/.ssh/<your-private-key>'
    )


def ensure_ssh_config_entry(alias: str, host: str, user: str, private_key: Path) -> tuple[Path, bool]:
    ssh_config = Path.home() / ".ssh" / "config"
    ssh_config.parent.mkdir(parents=True, exist_ok=True)

    block = (
        f"Host {alias}\n"
        f"    HostName {host}\n"
        f"    User {user}\n"
        f"    IdentityFile {private_key}\n"
        f"    IdentitiesOnly yes\n"
        f"    AddKeysToAgent yes\n"
    )

    existing = ssh_config.read_text(encoding="utf-8") if ssh_config.exists() else ""
    if re.search(rf"(?m)^Host\s+{re.escape(alias)}\s*$", existing):
        return ssh_config, False

    with ssh_config.open("a", encoding="utf-8") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write("\n" + block)

    return ssh_config, True


def build_ssh_target(alias: str | None, host: str, user: str) -> str:
    if alias:
        return alias
    return f"{user}@{host}"


def test_ssh_login(alias: str | None, host: str, user: str, timeout: int = 10) -> subprocess.CompletedProcess:
    target = build_ssh_target(alias, host, user)
    return subprocess.run(
        [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", f"ConnectTimeout={timeout}",
            target,
            "hostname && whoami && date",
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def cluster_setup_summary(cluster_id: str, host: str, user: str, alias: str | None = None) -> dict:
    info = make_ssh_key_info(cluster_id=cluster_id, host=host, user=user, alias=alias)
    agent = list_agent_keys()
    return {
        "cluster_id": info.cluster_id,
        "alias": info.alias,
        "host": info.host,
        "user": info.user,
        "private_key_exists": info.private_key.exists(),
        "public_key_exists": info.public_key.exists(),
        "private_key": str(info.private_key),
        "public_key": str(info.public_key),
        "agent_running": ssh_agent_running(),
        "agent_has_any_keys": agent.returncode == 0 and bool((agent.stdout or "").strip()),
        "cluster_key_loaded": key_loaded_in_agent(info.private_key),
    }