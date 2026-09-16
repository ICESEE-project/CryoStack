# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : Private-service license tunnel (cloud-side client)
# File        : license_tunnel_client.py
#
# Description :
#     Runs INSIDE the AWS Batch/Fargate task. Opens a local TCP listener
#     (e.g. 127.0.0.1:1711) and, for each connection MATLAB makes to it,
#     opens a tunnel through the CryoStack Connector relay to the paired
#     Connector, which alone resolves the (purpose, endpoint) pair against
#     its own trusted, site-supplied allow-list and dials the real private
#     service. This process never learns, chooses, or is told the real
#     host/port -- it only ever presents a short-lived, purpose-scoped
#     tunnel token to the relay.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-09-15
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""Cloud-side (Fargate task) half of the private-service tunnel.

Mirrors the byte-framing already used by the relay and the Connector
(icesee_jupyter_book/core/connector_relay_server.py,
icesee_hpc_connector/connector_core.py): one WebSocket per local TCP
connection, a JSON ``tunnel-open`` handshake, then raw binary frames both
ways until either side closes. Requires the ``websockets`` package --
never installed in the scientific Batch container, so when this file is
staged as a standalone runtime helper a pinned, minimal copy of it is
staged alongside it and preferred via a process-local sys.path addition
(see the top of this module and
cryostack_src.cloud.runtime.license_tunnel_client_extra_files).

This process is intentionally dumb: it never knows the real destination
host/port (only the Connector's trusted allow-list does), and it never
retries past a first, fast connectivity check -- ``selfcheck()`` -- so a
misconfigured or unreachable path is reported BEFORE MATLAB is started,
never discovered only when MATLAB itself times out.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

# The scientific Batch container does not have the `websockets` package
# installed (nor any reason to). When this file is staged as a standalone
# runtime helper (see cryostack_src.cloud.runtime.
# license_tunnel_client_extra_files), a pinned, self-contained copy of it
# is staged alongside it under a dedicated runtime-support directory --
# never mixed with the scientist's own model/example files -- and
# preferred here via a sys.path addition SCOPED TO THIS PROCESS ONLY
# (never a global environment/PYTHONPATH change, never touching any
# /opt/venv-*). Local/dev invocation (where `websockets` is already
# installed normally, and this directory does not exist) is unaffected.
_RUNTIME_SUPPORT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), ".cryostack_runtime")
if os.path.isdir(_RUNTIME_SUPPORT_DIR) and _RUNTIME_SUPPORT_DIR not in sys.path:
    sys.path.insert(0, _RUNTIME_SUPPORT_DIR)

TUNNEL_PURPOSE_MATLAB_LICENSE = "matlab-license"

#: bounded so a stalled relay/connector cannot hang task startup forever.
DEFAULT_CONNECT_TIMEOUT_SECONDS = 20
#: chunk size for the socket<->websocket byte pump.
READ_CHUNK_SIZE = 65536


def _relay_ws_url(relay_url: str, session_id: str) -> str:
    base = relay_url.rstrip("/").replace("http://", "ws://").replace("https://", "wss://")
    return f"{base}/connector/tunnel/{session_id}"


async def selfcheck(
    *, relay_url: str, session_id: str, token: str, purpose: str, endpoint: str,
    timeout: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
) -> tuple[bool, str]:
    """A single, throwaway tunnel-open/close round trip -- confirms the
    relay is reachable, the token/purpose/endpoint are accepted, AND the
    paired Connector could reach the real private service, all before any
    real (MATLAB) connection is attempted. Never raises; always returns
    ``(ok, message)`` with ``message`` safe to show a scientist (see
    :func:`scientist_facing_connectivity_error`)."""
    import websockets

    url = _relay_ws_url(relay_url, session_id)
    try:
        ws = await asyncio.wait_for(
            websockets.connect(url, open_timeout=timeout, close_timeout=5),
            timeout=timeout + 5,
        )
    except Exception:
        return False, "relay_unreachable"

    try:
        await ws.send(json.dumps({
            "type": "tunnel-open", "token": token, "purpose": purpose, "endpoint": endpoint,
        }))
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        ack = json.loads(raw)
    except Exception:
        return False, "relay_no_response"
    finally:
        try:
            await ws.close()
        except Exception:
            pass

    if not ack.get("ok"):
        return False, "connector_refused"
    return True, ""


#: machine-readable selfcheck failure -> the ONE thing a scientist needs to
#: know, in plain language. Never AWS/relay/IAM/Connector jargon -- kept
#: separate from `selfcheck`'s own return code so the wording lives in one
#: place and can be reused by the runner wrapper / Run Log without every
#: caller re-deriving it.
_SCIENTIST_MESSAGES = {
    "relay_unreachable": (
        "Could not configure the MATLAB license for this run. The "
        "institutional connection needed to reach your license service is "
        "not available right now. Try again, or contact your administrator."
    ),
    "relay_no_response": (
        "Could not configure the MATLAB license for this run. The "
        "institutional connection did not respond in time. Try again."
    ),
    "connector_refused": (
        "Could not configure the MATLAB license for this run. Your "
        "institutional connection could not reach the license service. "
        "Confirm your Connector is running and try again."
    ),
}


def scientist_facing_connectivity_error(code: str) -> str:
    return _SCIENTIST_MESSAGES.get(code, _SCIENTIST_MESSAGES["relay_unreachable"])


async def _pump_socket_to_ws(reader: asyncio.StreamReader, ws) -> None:
    try:
        while True:
            chunk = await reader.read(READ_CHUNK_SIZE)
            if not chunk:
                break
            await ws.send(chunk)
    except Exception:
        pass


async def _pump_ws_to_socket(ws, writer: asyncio.StreamWriter) -> None:
    try:
        async for raw in ws:
            if not isinstance(raw, bytes):
                continue
            writer.write(raw)
            await writer.drain()
    except Exception:
        pass


async def _serve_one_connection(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, *,
    relay_url: str, session_id: str, token: str, purpose: str, endpoint: str,
    timeout: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
) -> None:
    """One local (MATLAB-side) TCP connection <-> one relay tunnel, for as
    long as either side keeps it open."""
    import websockets

    url = _relay_ws_url(relay_url, session_id)
    try:
        ws = await asyncio.wait_for(
            websockets.connect(url, open_timeout=timeout, close_timeout=5),
            timeout=timeout + 5,
        )
    except Exception:
        writer.close()
        return

    try:
        await ws.send(json.dumps({
            "type": "tunnel-open", "token": token, "purpose": purpose, "endpoint": endpoint,
        }))
        ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
        if not ack.get("ok"):
            writer.close()
            await ws.close()
            return
    except Exception:
        writer.close()
        try:
            await ws.close()
        except Exception:
            pass
        return

    to_ws = asyncio.create_task(_pump_socket_to_ws(reader, ws))
    to_socket = asyncio.create_task(_pump_ws_to_socket(ws, writer))
    try:
        await asyncio.wait({to_ws, to_socket}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        to_ws.cancel()
        to_socket.cancel()
        try:
            await ws.close()
        except Exception:
            pass
        try:
            writer.close()
        except Exception:
            pass


async def run_local_listener(
    *, listen_host: str, listen_port: int, relay_url: str, session_id: str,
    token: str, purpose: str, endpoint: str, ready_callback=None,
) -> None:
    """Serve ``listen_host:listen_port`` forever, bridging each connection
    through its own relay tunnel. ``ready_callback`` fires once the local
    port is actually bound -- used by the runner wrapper to know when it is
    safe to start MATLAB."""

    async def handle(reader, writer):
        await _serve_one_connection(
            reader, writer, relay_url=relay_url, session_id=session_id,
            token=token, purpose=purpose, endpoint=endpoint,
        )

    server = await asyncio.start_server(handle, listen_host, listen_port)
    if ready_callback is not None:
        ready_callback()
    async with server:
        await server.serve_forever()


def _write_status(path: str | None, message: str) -> None:
    """Plain text (never JSON) -- the runner wrapper's bash simply ``cat``s
    this straight into its scientist-facing failure message."""
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(message)
    except OSError:
        pass


#: env var each CLI argument falls back to when not given as a flag. This
#: is what lets the Batch runner wrapper invoke this CLI with NO flags at
#: all (see cryostack_src.cloud.runtime.build_cloud_runner): the container
#: already carries these as plain (non-secret-store) environment
#: variables from the job submission, so re-stating them as ``--flag
#: "${VAR}"`` in the embedded bash text -- which IS size-constrained,
#: capped at 8192 chars total -- would be pure duplication. Flags still
#: exist and still take priority, for direct/manual/test invocation.
_ENV_FALLBACK = {
    "relay_url": "CRYOSTACK_LT_RELAY",
    "session_id": "CRYOSTACK_LT_SESSION",
    "token": "CRYOSTACK_LT_TOKEN",
    "purpose": "CRYOSTACK_LT_PURPOSE",
    "endpoint": "CRYOSTACK_LT_ENDPOINT",
}
_ENV_FALLBACK_PORT = {"listen_port": "CRYOSTACK_LT_PORT"}


def _resolve_from_env(args, names: dict[str, str]) -> list[str]:
    """Fill any of ``names`` left unset (``None``/empty) on ``args`` from
    its matching environment variable. Returns the env var names still
    missing afterward (a caller error, never guessed at)."""
    missing = []
    for attr, env_name in names.items():
        if getattr(args, attr, None) in (None, ""):
            value = os.environ.get(env_name)
            if value:
                setattr(args, attr, int(value) if attr == "listen_port" else value)
        if getattr(args, attr, None) in (None, ""):
            missing.append(env_name)
    return missing


def _common_args(parser: argparse.ArgumentParser) -> None:
    # All optional -- see _ENV_FALLBACK. Short flag names anyway, for the
    # rare direct/manual invocation.
    parser.add_argument("--relay", dest="relay_url", default=None)
    parser.add_argument("--session", dest="session_id", default=None)
    parser.add_argument("--token", default=None)
    parser.add_argument("--purpose", default=None)
    parser.add_argument("--endpoint", default=None)
    parser.add_argument("--status", dest="status_file", default=None)
    parser.add_argument("--timeout", type=float, default=DEFAULT_CONNECT_TIMEOUT_SECONDS)


def _cmd_selfcheck(args) -> int:
    """A single, fast, throwaway tunnel-open/close round trip -- exposed as
    its own subcommand for diagnostics/testing. The Batch runner wrapper
    itself uses ``listen``, which already performs this same check before
    binding the local port -- see :func:`_cmd_listen`."""
    missing = _resolve_from_env(args, _ENV_FALLBACK)
    if missing:
        print(f"[license-tunnel][ERROR] missing: {', '.join(missing)}", file=sys.stderr)
        return 2
    ok, code = asyncio.run(selfcheck(
        relay_url=args.relay_url, session_id=args.session_id, token=args.token,
        purpose=args.purpose, endpoint=args.endpoint, timeout=args.timeout,
    ))
    if not ok:
        message = scientist_facing_connectivity_error(code)
        _write_status(args.status_file, message)
        print(f"[license-tunnel][ERROR] {message}", file=sys.stderr)
        return 1
    _write_status(args.status_file, "OK")
    return 0


def _wait_for_local_port(host: str, port: int, timeout: float) -> bool:
    import socket
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            if s.connect_ex((host, port)) == 0:
                return True
        time.sleep(0.1)
    return False


def _cmd_serve(args) -> int:
    """Bind and serve the local listener forever -- no connectivity check
    (the ``listen`` command below already did one before spawning this).
    Meant to run detached; the container's own lifecycle (the run ending)
    is what stops it."""
    missing = _resolve_from_env(args, _ENV_FALLBACK)
    missing += _resolve_from_env(args, _ENV_FALLBACK_PORT)
    if missing:
        print(f"[license-tunnel][ERROR] missing: {', '.join(missing)}", file=sys.stderr)
        return 2

    def _on_ready():
        print(f"[license-tunnel] listening on {args.listen_host}:{args.listen_port}")

    try:
        asyncio.run(run_local_listener(
            listen_host=args.listen_host, listen_port=args.listen_port,
            relay_url=args.relay_url, session_id=args.session_id, token=args.token,
            purpose=args.purpose, endpoint=args.endpoint, ready_callback=_on_ready,
        ))
    except KeyboardInterrupt:
        pass
    return 0


def _cmd_listen(args) -> int:
    """Verify connectivity (fast, foreground), then detach a ``serve``
    child that keeps running after this process exits, and wait for it to
    actually bind the local port -- all synchronously, so the Batch runner
    wrapper's bash needs no ``&``, no status file, and no polling loop: it
    just checks THIS command's own exit code. On failure, the
    scientist-facing message is on stdout for bash to capture directly.
    The detached child inherits this process's environment, so it needs
    no arguments repeated to it either.
    """
    missing = _resolve_from_env(args, _ENV_FALLBACK)
    missing += _resolve_from_env(args, _ENV_FALLBACK_PORT)
    if missing:
        print(f"missing: {', '.join(missing)}")
        return 2

    ok, code = asyncio.run(selfcheck(
        relay_url=args.relay_url, session_id=args.session_id, token=args.token,
        purpose=args.purpose, endpoint=args.endpoint, timeout=args.timeout,
    ))
    if not ok:
        print(scientist_facing_connectivity_error(code))
        return 1

    import subprocess

    # Explicitly re-assert what THIS process resolved (whether from a flag
    # or an env var) into the child's environment, rather than relying on
    # ambient inheritance alone -- correct regardless of how `listen`
    # itself was invoked, while remaining a no-op duplicate set in the
    # real Batch runner case (these already ARE env vars there).
    child_env = {
        **os.environ,
        "CRYOSTACK_LT_RELAY": args.relay_url,
        "CRYOSTACK_LT_SESSION": args.session_id,
        "CRYOSTACK_LT_TOKEN": args.token,
        "CRYOSTACK_LT_PURPOSE": args.purpose,
        "CRYOSTACK_LT_ENDPOINT": args.endpoint,
        "CRYOSTACK_LT_PORT": str(args.listen_port),
    }
    try:
        # Re-exec THIS SAME FILE by path, never ``-m cryostack_src...`` --
        # inside a Batch container this module is staged as a standalone
        # file alongside the run's other inputs (it does not import, and
        # must never require, the CryoLauncher web app's own package to be
        # installed there). ``__file__`` resolves correctly whether this
        # process itself was started as ``-m cryostack_src.cloud.
        # license_tunnel_client`` (local/dev) or as a plain staged script
        # (the real Batch runner case) -- see cryostack_src.cloud.runtime.
        subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), "serve"],
            start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=child_env,
        )
    except Exception:  # noqa: BLE001 -- never a raw traceback for a scientist
        print(scientist_facing_connectivity_error("relay_no_response"))
        return 1

    if not _wait_for_local_port(args.listen_host, args.listen_port, args.timeout):
        print(scientist_facing_connectivity_error("relay_no_response"))
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_selfcheck = sub.add_parser("selfcheck")
    _common_args(p_selfcheck)
    p_selfcheck.set_defaults(func=_cmd_selfcheck)

    p_serve = sub.add_parser("serve")
    _common_args(p_serve)
    p_serve.add_argument("--host", dest="listen_host", default="127.0.0.1")
    p_serve.add_argument("--port", dest="listen_port", type=int, default=None)
    p_serve.set_defaults(func=_cmd_serve)

    p_listen = sub.add_parser("listen")
    _common_args(p_listen)
    p_listen.add_argument("--host", dest="listen_host", default="127.0.0.1")
    p_listen.add_argument("--port", dest="listen_port", type=int, default=None)
    p_listen.set_defaults(func=_cmd_listen)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    raise SystemExit(main())
