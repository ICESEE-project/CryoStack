#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import time
from urllib.parse import quote
from pathlib import Path


REPO_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(REPO_ROOT),
    )


from control_center import (
    install_control_center,
)

from aiohttp import ClientSession, WSMsgType, WSServerHandshakeError, web

from cryostack_src import perf
from cryostack_src.service_warmup import (
    ManagedVoilaService,
    ServiceState,
    warm_up_all,
)

#: wall-clock at process start -- perf reports "seconds since the process
#: started" for the web shell and each application backend.
_PROCESS_EPOCH = time.time()

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from icesee_auth import AuthManager

from control_center.services.access import (
    AccessService,
)

from icesee_jupyter_book.applications.frozen_legacies.server import (
    frozen_legacies_root,
    install_frozen_legacies,
)
from icesee_jupyter_book.applications.livist.routes import install_livist
from icesee_jupyter_book.core.connector_relay_auth import OWNER_GRANT_HEADER, owner_grant
from icesee_auth.kernel_access import (
    KERNEL_WORKSPACE_STATE_PATH,
    WORKSPACE_GRANT_HEADER,
    grant_matches,
    workspace_grant,
)
from icesee_jupyter_book.developer_docs_access import (
    developer_docs_middleware,
    filter_livist_html,
    is_privileged,
    private_docs_response,
    require_developer_docs,
    restricted_livist_doc,
)


HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def book_root() -> Path:
    return repo_root() / "icesee_jupyter_book" / "_build" / "html"

def livist_root() -> Path:
    return (
        repo_root()
        / "external"
        / "living-ice-sheet-temperature"
        / "frontend"
        / "dist"
    )

def livist_docs_root() -> Path:
    return (
        repo_root()
        / "external"
        / "living-ice-sheet-temperature"
        / "site"
    )

def maintainer_guide_source() -> Path:
    return (
        repo_root()
        / "icesee_jupyter_book"
        / "docs"
        / "maintainer_guide.md"
    )


# Minimal page shell for the role-protected Maintainer Guide. It reuses the
# published CryoStack stylesheet (/_static/icesee.css) — no page-specific
# visual system — and the same responsive .cryostack-docs-page rules that the
# public documentation pages use.
_MAINTAINER_SHELL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Maintainer Guide — CryoStack</title>
<link rel="stylesheet" href="/_static/icesee.css">
<style>
  body {{ margin: 0; background: #f8fafc; }}
  .cryostack-maintainer-shell {{
    max-width: 960px;
    margin: 0 auto;
    padding: 32px 22px 64px;
  }}
  .cryostack-maintainer-shell .cryostack-section-label {{ margin-bottom: 10px; }}
</style>
</head>
<body>
<main class="cryostack-docs-page cryostack-maintainer-shell">
  <div class="cryostack-section-label">CryoStack Operations</div>
  {body}
</main>
</body>
</html>
"""


async def maintainer_guide_redirect(request: web.Request) -> web.StreamResponse:
    raise web.HTTPFound("/docs/maintainer/")


async def maintainer_guide_page(request: web.Request) -> web.StreamResponse:
    src = maintainer_guide_source()
    if not src.exists():
        raise web.HTTPNotFound(text="Maintainer Guide source is not present.")

    from markdown_it import MarkdownIt

    md = (
        MarkdownIt("commonmark", {"html": False, "linkify": True})
        .enable("table")
        .enable("strikethrough")
    )
    body = md.render(src.read_text(encoding="utf-8"))
    return web.Response(
        text=_MAINTAINER_SHELL.format(body=body),
        content_type="text/html",
    )


# --- application warm-up holding page ------------------------------------
# Shown (instead of a raw 502 / connection-refused) when an application is
# reached before its Voila backend has finished starting. Reuses the canonical
# CryoStack mark and the published stylesheet -- no page-specific visual system.
def _cryostack_mark_uri() -> str:
    try:
        from icesee_jupyter_book.ui.shared_application_header import _mark_data_uri
        return _mark_data_uri()
    except Exception:
        return ""


_WARMING_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{app} is starting — CryoStack</title>
{refresh}
<link rel="stylesheet" href="/_static/icesee.css">
<style>
  body {{ margin: 0; background: #f8fafc; }}
  .cryostack-warmup {{
    max-width: 460px; margin: 12vh auto 0; padding: 34px 26px;
    text-align: center;
    border: 1px solid rgba(15,23,42,.08); border-radius: 16px; background: #fff;
    box-shadow: 0 8px 24px rgba(15,23,42,.05);
    font-family: system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
  }}
  .cryostack-warmup img, .cryostack-warmup .mark {{
    width: 52px; height: 52px; object-fit: contain; margin-bottom: 14px;
  }}
  .cryostack-warmup .brand {{
    color: rgba(15,23,42,.55); font-size: 12px; font-weight: 700;
    letter-spacing: .08em; text-transform: uppercase;
  }}
  .cryostack-warmup h1 {{ margin: 6px 0 10px; font-size: 20px; color: #111827; }}
  .cryostack-warmup p {{ color: rgba(15,23,42,.62); font-size: 14px; line-height: 1.55; }}
  .cryostack-warmup .status {{
    display: inline-flex; align-items: center; gap: 8px; margin-top: 14px;
    padding: 6px 13px; border-radius: 999px; font-size: 13px; font-weight: 700;
    background: rgba(37,99,235,.10); color: #1d4ed8;
  }}
  .cryostack-warmup .status.failed {{ background: rgba(220,38,38,.12); color: #b91c1c; }}
  .cryostack-warmup .dot {{ font-size: 11px; }}
  .cryostack-warmup a.retry {{
    display: inline-block; margin-top: 16px; padding: 8px 16px; border-radius: 9px;
    background: #2563eb; color: #fff; font-weight: 700; text-decoration: none; font-size: 13px;
  }}
  .cryostack-warmup .diag {{
    margin-top: 14px; font-size: 12px; color: rgba(15,23,42,.5);
    word-break: break-word; text-align: left;
  }}
  @media (max-width: 430px) {{ .cryostack-warmup {{ margin-top: 8vh; padding: 26px 18px; }} }}
</style>
</head>
<body>
<main class="cryostack-warmup">
  {mark}
  <div class="brand">CryoStack</div>
  <h1>{heading}</h1>
  <p>{message}</p>
  <div class="status{status_class}"><span class="dot">●</span>{status_label}</div>
  {extra}
</main>
</body>
</html>
"""


def _warming_page(app_label: str, state: "ServiceState", *, error: str = "") -> web.Response:
    uri = _cryostack_mark_uri()
    mark = (
        f'<img src="{uri}" alt="CryoStack" />' if uri
        else '<div class="mark" style="font-size:38px;line-height:52px;color:#1d4ed8;">❄</div>'
    )
    if state is ServiceState.FAILED:
        return web.Response(
            status=503,
            content_type="text/html",
            text=_WARMING_PAGE.format(
                app=app_label, refresh="", mark=mark,
                heading=f"{app_label} could not start",
                message="The interactive application backend did not come up. "
                        "An operator can check the service logs.",
                status_class=" failed", status_label="Failed",
                extra=(
                    '<a class="retry" href="?warmup_retry=1">Retry</a>'
                    + (f'<div class="diag">{error}</div>' if error else "")
                ),
            ),
        )
    return web.Response(
        status=503,
        headers={"Retry-After": "3"},
        content_type="text/html",
        text=_WARMING_PAGE.format(
            app=app_label,
            refresh='<meta http-equiv="refresh" content="3">',
            mark=mark,
            heading=f"{app_label} is starting",
            message="Preparing the interactive application… This page will "
                    "continue automatically.",
            status_class="", status_label="Starting",
            extra="",
        ),
    )


def run_center_nb() -> Path:
    return repo_root() / "icesee_jupyter_book" / "icesee_jupyter_notebooks" / "run_center_voila.ipynb"


def icesheets_nb() -> Path:
    return repo_root() / "icesee_jupyter_book" / "icesee_jupyter_notebooks" / "icesheets_voila.ipynb"


def wait_for_port(host: str, port: int, timeout: float = 30.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.25)
    return False


async def root_redirect(request: web.Request) -> web.StreamResponse:
    raise web.HTTPFound("/index.html")

async def livist_redirect(request: web.Request) -> web.StreamResponse:
    raise web.HTTPFound("/livist/")

async def livist_docs_redirect(
    request: web.Request,
) -> web.StreamResponse:
    raise web.HTTPFound("/livist/docs/")

async def livist_index(request: web.Request) -> web.StreamResponse:
    index_file = livist_root() / "index.html"

    if not index_file.exists():
        raise web.HTTPNotFound(
            text=(
                "LIVIST frontend has not been built. "
                "Run `yarn build` in "
                "external/living-ice-sheet-temperature/frontend."
            )
        )

    return web.FileResponse(index_file)

async def livist_docs_redirect(request: web.Request) -> web.StreamResponse:
    raise web.HTTPFound("/livist/docs/")


async def livist_docs_index(request: web.Request) -> web.StreamResponse:
    index_file = livist_docs_root() / "index.html"

    if not index_file.exists():
        raise web.HTTPNotFound(
            text=(
                "LIVIST documentation has not been built. "
                "Run `uv run zensical build` in "
                "external/living-ice-sheet-temperature."
            )
        )

    if is_privileged(request.app["auth"], request):
        return private_docs_response(web.FileResponse(index_file))
    return private_docs_response(web.Response(
        text=filter_livist_html(index_file.read_text(encoding="utf-8")),
        content_type="text/html"))

async def livist_docs_page(request: web.Request) -> web.StreamResponse:
    tail = request.match_info.get("tail", "").strip("/")

    docs_root = livist_docs_root().resolve()
    requested_path = (docs_root / tail).resolve()

    # Prevent paths such as ../../ from escaping the docs directory.
    if docs_root not in requested_path.parents and requested_path != docs_root:
        raise web.HTTPForbidden(text="Invalid documentation path.")

    if requested_path.is_dir():
        requested_path = requested_path / "index.html"

    if not requested_path.exists() or not requested_path.is_file():
        raise web.HTTPNotFound(text="LIVIST documentation page not found.")

    auth = request.app["auth"]
    if restricted_livist_doc(tail) and not is_privileged(auth, request):
        if auth.current_user(request) is None:
            raise web.HTTPFound("/auth/login?return_to="
                                + quote(request.path_qs, safe=""))
        raise web.HTTPForbidden(
            text="Developer documentation requires owner-controlled access.")
    if requested_path.suffix.lower() in {".html", ".htm"} and not is_privileged(auth, request):
        return private_docs_response(web.Response(
            text=filter_livist_html(requested_path.read_text(encoding="utf-8")),
            content_type="text/html"))
    return private_docs_response(web.FileResponse(requested_path))

class ManagedProcess:
    def __init__(self, command: list[str], cwd: Path, env: dict[str, str] | None = None):
        self.command = command
        self.cwd = cwd
        self.env = env
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        if self.proc and self.proc.poll() is None:
            return
        self.proc = subprocess.Popen(
            self.command,
            cwd=str(self.cwd),
            env=self.env,
            stdout=sys.stdout,
            stderr=sys.stderr,
            preexec_fn=os.setsid,
        )

    def stop(self) -> None:
        if not self.proc or self.proc.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            self.proc.wait(timeout=10)
        except Exception:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
            except Exception:
                pass


# Voila kernels inherit the Voila server's environment, so the server gets an
# explicit allowlist rather than the gateway's environment (OAuth client
# secrets, the relay deployment token, operator session variables). The
# per-user identity and relay grant reach a kernel as request headers instead.
VOILA_ENV_ALLOWLIST = frozenset({
    # process basics
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LANGUAGE", "TZ", "TMPDIR",
    "HOSTNAME", "XDG_RUNTIME_DIR", "XDG_DATA_HOME", "XDG_CONFIG_HOME",
    "XDG_CACHE_HOME", "XDG_DATA_DIRS",
    # Python, conda and Jupyter runtime
    "PYTHONPATH", "PYTHONNOUSERSITE", "PYTHONUNBUFFERED", "LD_LIBRARY_PATH",
    "CONDA_PREFIX", "CONDA_DEFAULT_ENV", "CONDA_EXE", "CONDA_PYTHON_EXE",
    "MAMBA_EXE", "MAMBA_ROOT_PREFIX",
    "JUPYTER_CONFIG_PATH", "JUPYTER_CONFIG_DIR", "JUPYTER_PATH", "JUPYTER_DATA_DIR",
    "JUPYTER_RUNTIME_DIR", "JUPYTER_PLATFORM_DIRS", "IPYTHONDIR",
    "MPLBACKEND", "MPLCONFIGDIR",
    # outbound HTTPS (relay, AWS, model downloads)
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
    # CryoStack application settings (no credentials)
    "CRYOSTACK_AGENT_PANEL", "CRYOSTACK_PERF", "CRYOSTACK_WORKSPACE_ROOT",
    "CRYOSTACK_AUTH_DATABASE", "CRYOSTACK_AWS_PRINCIPAL_ARN", "CRYOSTACK_GATEWAY_INTERNAL_URL",
    "CRYOSTACK_KERNEL_SANDBOX", "CRYOSTACK_KERNEL_BWRAP", "CRYOSTACK_KERNEL_RO_PATHS",
    "CRYOSTACK_KERNEL_AWS_DIR", "CRYOSTACK_KERNEL_HIDE",
    "CRYOSTACK_CF_TEMPLATE_URL", "CRYOSTACK_CLOUD_POLL_SECONDS",
    "CRYOSTACK_CLOUD_OPERATOR_USER_IDS",
    # Cloud: the named AWS profile and region select the CryoStack principal
    # for hosted runs and AssumeRole; static keys are never forwarded.
    "AWS_PROFILE", "AWS_REGION", "AWS_DEFAULT_REGION", "AWS_CONFIG_FILE",
    "AWS_SHARED_CREDENTIALS_FILE",
    # scientific models
    "ICEPACK_ROOT", "ISSM_DIR", "ICESEE_GHUB_ROOT", "OMP_NUM_THREADS",
    "PROJ_DATA", "PROJ_LIB", "GDAL_DATA",
    "APPTAINER_CACHEDIR", "APPTAINER_TMPDIR", "APPTAINER_BINDPATH",
    "SINGULARITY_CACHEDIR", "SINGULARITY_TMPDIR", "SINGULARITY_BINDPATH",
})
VOILA_ENV_PREFIXES = ("LC_", "ICESEE_", "ICEPACK_", "ISSM_", "PETSC_", "FIREDRAKE_", "OMPI_")
# A name that looks like a credential never passes, even under an allowed prefix.
_VOILA_ENV_SECRET_MARKERS = ("SECRET", "TOKEN", "PASSWORD", "PASSWD", "CREDENTIAL",
                             "PRIVATE", "ACCESS_KEY", "API_KEY")


def _voila_env_allowed(name: str) -> bool:
    upper = name.upper()
    if any(marker in upper for marker in _VOILA_ENV_SECRET_MARKERS):
        return name == "AWS_SHARED_CREDENTIALS_FILE"
    return name in VOILA_ENV_ALLOWLIST or name.startswith(VOILA_ENV_PREFIXES)


def voila_environment(token: str, source: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for a gateway-managed Voila server.

    Only allowlisted variables are copied from the gateway (``source``,
    default ``os.environ``). The token travels only in the child's environment
    (never argv, which any local account can read with ps);
    bin/voila_config/voila.py moves it into Voila's configuration and removes
    it before kernels start.
    """
    source = os.environ if source is None else source
    env = {name: value for name, value in source.items() if _voila_env_allowed(name)}
    env["CRYOSTACK_VOILA_TOKEN"] = token
    config_dir = str(Path(__file__).resolve().parent / "voila_config")
    existing = env.get("JUPYTER_CONFIG_PATH")
    env["JUPYTER_CONFIG_PATH"] = os.pathsep.join([config_dir, existing] if existing else [config_dir])
    # kernels/python3 there starts kernels through bin/cryostack_kernel.py
    # (per-user sandbox when CRYOSTACK_KERNEL_SANDBOX=bwrap)
    existing = env.get("JUPYTER_PATH")
    env["JUPYTER_PATH"] = os.pathsep.join([config_dir, existing] if existing else [config_dir])
    return env


#: ``managed`` (default): the gateway starts its two Voila servers as
#: children. ``external``: they run under their own service account
#: (``bin/icesee_app.py voila <app>``, started by the deployment) and the
#: gateway only proxies to them; both sides read the Voila token from
#: ``CRYOSTACK_VOILA_TOKEN_FILE``.
VOILA_MODE_ENV = "CRYOSTACK_VOILA_MODE"
VOILA_TOKEN_FILE_ENV = "CRYOSTACK_VOILA_TOKEN_FILE"


def configured_port(env_name: str, default: int) -> int:
    """Return a validated TCP port from the environment.

    Production keeps its historical ports by default; isolated staging
    deployments can select a different port set on the same host.
    """
    raw = (os.environ.get(env_name) or str(default)).strip()
    try:
        port = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{env_name} must be an integer TCP port, not {raw!r}") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError(f"{env_name} must be between 1 and 65535, not {port}")
    return port


def voila_mode() -> str:
    mode = (os.environ.get(VOILA_MODE_ENV) or "managed").strip().lower()
    if mode not in ("managed", "external"):
        raise RuntimeError(f"{VOILA_MODE_ENV} must be 'managed' or 'external', not {mode!r}")
    return mode


def read_voila_token_file(path: str | None = None) -> str:
    """The shared Voila token of an external deployment.

    The file must belong to this account or be shared through a group, never
    readable by others, and hold one non-trivial token."""
    raw = path if path is not None else os.environ.get(VOILA_TOKEN_FILE_ENV, "")
    if not raw.strip():
        raise RuntimeError(f"{VOILA_TOKEN_FILE_ENV} is required when {VOILA_MODE_ENV}=external")
    token_path = Path(raw.strip()).expanduser()
    st = token_path.stat()
    if st.st_mode & 0o007:
        raise RuntimeError(f"{token_path} is readable or writable by other accounts (chmod o-rwx)")
    token = token_path.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise RuntimeError(f"{token_path} does not hold a token of at least 32 characters")
    return token


#: (notebook, port, base URL) of the two application servers
VOILA_APPS = {
    "icesee": (
        run_center_nb,
        configured_port("CRYOSTACK_RUN_CENTER_PORT", 8866),
        "/icesee-gui/",
    ),
    "icesheets": (
        icesheets_nb,
        configured_port("CRYOSTACK_ICESHEETS_PORT", 8870),
        "/icesheets/",
    ),
}


def voila_command(app_name: str, python: str | None = None) -> list[str]:
    notebook, port, base_url = VOILA_APPS[app_name]
    return [
        python or sys.executable,
        "-m",
        "voila",
        str(notebook()),
        "--no-browser",
        "--Voila.ip=127.0.0.1",
        f"--port={port}",
        f"--Voila.base_url={base_url}",
        # Surface the proxy-verified CryoStack identity into the kernel
        # environment (HTTP_X_CRYOSTACK_USER_ID) so Workspace history is
        # isolated per authenticated user. preheat_kernel stays disabled
        # (default) so each render's kernel sees its own request headers.
        "--VoilaConfiguration.http_header_envs=X-CryoStack-User-Id",
        "--VoilaConfiguration.http_header_envs=X-CryoStack-User-Name",
        # The user's connector-relay grant (never the deployment token) and
        # workspace grant (never the gateway key).
        f"--VoilaConfiguration.http_header_envs={OWNER_GRANT_HEADER}",
        f"--VoilaConfiguration.http_header_envs={WORKSPACE_GRANT_HEADER}",
    ]


class ExternalVoilaProcess:
    """A Voila server another account supervises: nothing to start or stop."""

    proc = None

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class ICESEEState:
    def __init__(self) -> None:
        root = repo_root()
        self.voila_mode = voila_mode()

        # Shared secret between the gateway and its Voila servers: Voila only
        # serves requests that carry it, and only the proxy adds it.
        if self.voila_mode == "external":
            self.voila_token = read_voila_token_file()
        else:
            self.voila_token = secrets.token_urlsafe(32)
        # Key of the per-user workspace grants; never leaves this process.
        self.kernel_grant_key = secrets.token_bytes(32)

        self.run_center_port = VOILA_APPS["icesee"][1]
        self.icesheets_port = VOILA_APPS["icesheets"][1]

        if self.voila_mode == "external":
            _run_center_proc = ExternalVoilaProcess()
            _icesheets_proc = ExternalVoilaProcess()
        else:
            _run_center_proc = ManagedProcess(voila_command("icesee"), root,
                                              voila_environment(self.voila_token))
            _icesheets_proc = ManagedProcess(voila_command("icesheets"), root,
                                             voila_environment(self.voila_token))

        self.run_center = ManagedVoilaService(
            name="icesee", process=_run_center_proc,
            port=self.run_center_port, origin_epoch=_PROCESS_EPOCH,
        )
        self.icesheets = ManagedVoilaService(
            name="icesheets", process=_icesheets_proc,
            port=self.icesheets_port, origin_epoch=_PROCESS_EPOCH,
        )

        self.client: ClientSession | None = None
        self._warmup_task: asyncio.Task | None = None
        # (port, kernel id) pairs Voila reported as gone; see proxy_ws
        self.ended_kernels: dict[tuple[int, str], None] = {}

    def start_mode(self) -> str:
        mode = os.environ.get("CRYOSTACK_APP_START_MODE", "background").strip().lower()
        return mode if mode in ("background", "lazy") else "background"

    async def startup(self, app: web.Application) -> None:
        # Fail fast on a broken deploy -- but this is all cheap `.exists()`.
        if not book_root().joinpath("index.html").exists():
            raise RuntimeError(f"Missing built book at {book_root() / 'index.html'}")
        if not run_center_nb().exists():
            raise RuntimeError(f"Missing notebook {run_center_nb()}")
        if not icesheets_nb().exists():
            raise RuntimeError(f"Missing notebook {icesheets_nb()}")

        self.client = ClientSession()

        # The web shell (home, docs, auth, Control Center, /connect/, static
        # assets) is now serviceable. The two application Voila servers warm up
        # in the background so a user reading the homepage does not wait on
        # them; by the time they click an application it is usually ready.
        if self.start_mode() == "background":
            self._warmup_task = asyncio.create_task(
                warm_up_all(
                    [self.icesheets, self.run_center],
                    origin_label="aiohttp ready",
                    origin_seconds=time.time() - _PROCESS_EPOCH,
                )
            )
        else:  # lazy: first request to an application triggers its warm-up
            perf.mark("aiohttp ready", time.time() - _PROCESS_EPOCH)

    async def cleanup(self, app: web.Application) -> None:
        if self._warmup_task and not self._warmup_task.done():
            self._warmup_task.cancel()
            try:
                await self._warmup_task
            except (asyncio.CancelledError, Exception):
                pass
        if self.client:
            await self.client.close()
        self.run_center.stop()
        self.icesheets.stop()


# Voila's own login cookie (``username-127-0-0-1-<port>``) would let anyone
# holding it talk to Voila directly without the gateway token, so it never
# leaves the proxy in either direction.
VOILA_LOGIN_COOKIE_PREFIX = "username-"


def _without_voila_login_cookies(cookie_header: str) -> str:
    kept = [
        part.strip()
        for part in cookie_header.split(";")
        if part.strip() and not part.strip().startswith(VOILA_LOGIN_COOKIE_PREFIX)
    ]
    return "; ".join(kept)


def build_upstream_headers(
    request: web.Request,
    upstream_port: int,
) -> dict[str, str]:
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in HOP_BY_HOP
        and k.lower()
        not in {
            "host",
            "origin",
            "authorization",
            "cookie",
            "x-cryostack-user-id",
            "x-cryostack-user-email",
            "x-cryostack-user-name",
            OWNER_GRANT_HEADER.lower(),
            WORKSPACE_GRANT_HEADER.lower(),
        }
    }

    cookies = _without_voila_login_cookies(request.headers.get("Cookie", ""))
    if cookies:
        headers["Cookie"] = cookies

    # Only the gateway knows the Voila token; a client-supplied Authorization
    # header is dropped above and replaced here.
    state = request.app.get("state") if request.app is not None else None
    token = getattr(state, "voila_token", None)
    if token:
        headers["Authorization"] = f"token {token}"

    headers["Host"] = f"127.0.0.1:{upstream_port}"
    headers["Origin"] = f"http://127.0.0.1:{upstream_port}"

    headers["X-Forwarded-Proto"] = "http"
    headers["X-Forwarded-Host"] = request.host
    headers["X-Forwarded-For"] = (
        request.remote or "127.0.0.1"
    )

    # ---------------------------------------------------------
    # Trusted CryoStack identity
    # ---------------------------------------------------------
    user = request.get("cryostack_user")

    if user is not None:
        headers["X-CryoStack-User-Id"] = user.id
        headers["X-CryoStack-User-Email"] = user.email
        headers["X-CryoStack-User-Name"] = (
            user.display_name
        )
        grant = owner_grant(user.id)
        if grant:
            headers[OWNER_GRANT_HEADER] = grant
        key = getattr(state, "kernel_grant_key", None)
        workspace = workspace_grant(user.id, key) if key else None
        if workspace:
            headers[WORKSPACE_GRANT_HEADER] = workspace

    return headers

async def proxy_http(request: web.Request, upstream_port: int) -> web.StreamResponse:
    state: ICESEEState = request.app["state"]
    assert state.client is not None

    upstream_url = f"http://127.0.0.1:{upstream_port}{request.rel_url}"
    headers = build_upstream_headers(request, upstream_port)
    body = await request.read()

    async with state.client.request(
        request.method,
        upstream_url,
        headers=headers,
        data=body if body else None,
        allow_redirects=False,
    ) as resp:
        out = web.StreamResponse(status=resp.status, reason=resp.reason)
        for k, v in resp.headers.items():
            if k.lower() in HOP_BY_HOP:
                continue
            if k.lower() == "set-cookie" and v.lstrip().startswith(VOILA_LOGIN_COOKIE_PREFIX):
                continue
            out.headers.add(k, v)

        await out.prepare(request)
        async for chunk in resp.content.iter_chunked(65536):
            await out.write(chunk)
        await out.write_eof()
        return out


_KERNEL_CHANNELS = re.compile(r"/api/kernels/([0-9a-f-]{36})/channels$")
_ENDED_KERNELS_MAX = 1024


async def proxy_ws(request: web.Request, upstream_port: int) -> web.WebSocketResponse:
    state: ICESEEState = request.app["state"]
    assert state.client is not None

    upstream_url = f"http://127.0.0.1:{upstream_port}{request.rel_url}"
    headers = build_upstream_headers(request, upstream_port)

    # A tab left open across a restart keeps reconnecting to its old kernel.
    # Kernel ids are never reused, so once Voila says one is gone, answer
    # here instead of asking Voila (which logs a long traceback each time).
    kernel = _KERNEL_CHANNELS.search(request.path)
    ended = (upstream_port, kernel.group(1)) if kernel else None
    if ended in state.ended_kernels:
        return web.Response(status=404, text="Kernel does not exist")
    try:
        upstream_ws = await state.client.ws_connect(upstream_url, headers=headers)
    except WSServerHandshakeError as exc:
        if exc.status == 404 and ended:
            state.ended_kernels[ended] = None
            if len(state.ended_kernels) > _ENDED_KERNELS_MAX:
                del state.ended_kernels[next(iter(state.ended_kernels))]
        return web.Response(status=exc.status or 502, text="Upstream refused the connection")

    browser_ws = web.WebSocketResponse()
    await browser_ws.prepare(request)

    async with upstream_ws:

        async def browser_to_upstream() -> None:
            async for msg in browser_ws:
                if msg.type == WSMsgType.TEXT:
                    await upstream_ws.send_str(msg.data)
                elif msg.type == WSMsgType.BINARY:
                    await upstream_ws.send_bytes(msg.data)
                elif msg.type == WSMsgType.CLOSE:
                    await upstream_ws.close()

        async def upstream_to_browser() -> None:
            async for msg in upstream_ws:
                if msg.type == WSMsgType.TEXT:
                    await browser_ws.send_str(msg.data)
                elif msg.type == WSMsgType.BINARY:
                    await browser_ws.send_bytes(msg.data)
                elif msg.type == WSMsgType.CLOSE:
                    await browser_ws.close()

        await asyncio.gather(browser_to_upstream(), upstream_to_browser())

    return browser_ws


async def proxy_dispatch(request: web.Request, upstream_port: int) -> web.StreamResponse:
    upgrade = request.headers.get("Upgrade", "").lower()
    connection = request.headers.get("Connection", "").lower()
    if upgrade == "websocket" or "upgrade" in connection:
        return await proxy_ws(request, upstream_port)
    return await proxy_http(request, upstream_port)


async def _proxy_application(
    request: web.Request, service: "ManagedVoilaService", app_label: str
) -> web.StreamResponse:
    """Proxy to a Voila application, showing a themed 'starting' page (never a
    raw 502 / connection-refused) while its backend warms up."""
    if request.query.get("warmup_retry"):
        service.request_retry()

    state = service.ensure_started()
    if state is not ServiceState.READY:
        # A websocket handshake cannot render an HTML holding page -- ask the
        # browser to retry the whole page instead.
        upgrade = request.headers.get("Upgrade", "").lower()
        if upgrade == "websocket":
            return web.Response(status=503, headers={"Retry-After": "2"},
                                text=f"{app_label} backend is starting")
        return _warming_page(app_label, state, error=service.error)

    return await proxy_dispatch(request, service.port)


async def proxy_run_center(request: web.Request) -> web.StreamResponse:
    state: ICESEEState = request.app["state"]
    return await _proxy_application(request, state.run_center, "ICESEE")


async def proxy_icesheets(request: web.Request) -> web.StreamResponse:
    state: ICESEEState = request.app["state"]
    return await _proxy_application(request, state.icesheets, "CryoLauncher")


_LOOPBACK = {"127.0.0.1", "::1"}


async def kernel_workspace_state(request: web.Request) -> web.Response:
    """A Voila kernel's read of its own user's saved workspace state.

    Loopback only and never through nginx (which sets X-Forwarded-For /
    X-Real-IP); the caller proves the user with the grant the proxy gave
    that user's kernel. Unknown callers get 404, a wrong grant 403."""
    if request.remote not in _LOOPBACK or "X-Forwarded-For" in request.headers \
            or "X-Real-IP" in request.headers:
        raise web.HTTPNotFound()
    state = request.app["state"]
    user_id = (request.headers.get("X-CryoStack-User-Id") or "").strip()
    if not grant_matches(user_id, request.headers.get(WORKSPACE_GRANT_HEADER),
                         state.kernel_grant_key):
        raise web.HTTPForbidden(text="invalid workspace grant")
    application = (request.query.get("application") or "").strip().lower()
    if application not in ("cryolauncher", "icesee"):
        raise web.HTTPBadRequest(text="unknown application")
    workspace = request.app["auth"].storage.get_workspace(user_id=user_id, application=application)
    try:
        saved = json.loads(workspace.state_json) if workspace is not None else {}
    except (TypeError, ValueError):
        saved = {}
    return web.json_response({"state": saved if isinstance(saved, dict) else {}},
                             headers={"Cache-Control": "no-store"})


def check_storage_layout() -> list[dict]:
    """Pin every persistent store's location for this process and its children
    and refuse to start when durable storage is required but not in place
    (``cryostack_src.storage_layout``); otherwise report what is not durable."""
    from cryostack_src import storage_layout

    storage_layout.export_environment()
    report = storage_layout.enforce()        # raises with CRYOSTACK_REQUIRE_DURABLE_STORAGE=1
    for entry in report:
        for problem in entry["problems"]:
            print(f"[storage] {entry['store']} ({entry['path']}): {problem}",
                  file=sys.stderr, flush=True)
    return report


def make_app() -> web.Application:
    check_storage_layout()
    app = web.Application()
    state = ICESEEState()
    app["state"] = state

    app.on_startup.append(state.startup)
    app.on_cleanup.append(state.cleanup)

    auth = AuthManager()
    auth.install(app)
    app["auth"] = auth
    app.router.add_get(KERNEL_WORKSPACE_STATE_PATH, kernel_workspace_state)

    # Developer Guide pages: owners only (403 for
    # other users); their links are removed from everyone else's pages.
    app.middlewares.append(
        developer_docs_middleware(
            auth,
            book_root(),
            html_pages={
                "/frozen-legacies/": lambda: frozen_legacies_root() / "index.html",
            },
        )
    )

    #
    # Control Center access/roles
    #
    access_service = AccessService(
        auth.storage,
    )

    app["access_service"] = access_service

    install_control_center(
        app,
        auth=auth,
    )

    protected_run_center = auth.require_login(
        proxy_run_center
    )

    protected_icesheets = auth.require_login(
        proxy_icesheets
    )

    # ICESEE application
    app.router.add_route(
        "*",
        "/icesee-gui",
        protected_run_center,
    )

    app.router.add_route(
        "*",
        "/icesee-gui/{tail:.*}",
        protected_run_center,
    )

    # CryoLauncher application
    app.router.add_route(
        "*",
        "/icesheets",
        protected_icesheets,
    )

    app.router.add_route(
        "*",
        "/icesheets/{tail:.*}",
        protected_icesheets,
    )

    app.router.add_get("/livist/docs", livist_docs_redirect)
    app.router.add_get("/livist/docs/", livist_docs_index)

    app.router.add_get("/livist/docs/{tail:.*}", livist_docs_page)

    app.router.add_get("/livist", livist_redirect)
    app.router.add_get("/livist/", livist_index)

    app.router.add_static(
        "/livist/",
        path=str(livist_root()),
        show_index=False,
    )

    # ---------------------------------------------------------
    # FrozenLegacies application
    # ---------------------------------------------------------

    # Authenticated like CryoLauncher and ICESEE: the page, its assets and
    # its data are all served behind auth.require_login.
    install_frozen_legacies(
        app,
        auth=auth,
    )

    # LIVIST generation jobs, validation and publication requests
    # (/control/livist, /api/livist/); /livist/ itself stays static above.
    install_livist(app, auth=auth)

    # Owner-controlled Maintainer / Operations Guide. Owners may delegate
    # access to a maintainer or admin; both role and capability are checked at
    # every request. The source is deliberately excluded from the public build.
    maintainer_access = lambda handler: require_developer_docs(auth, handler)
    app.router.add_get("/docs/maintainer", maintainer_guide_redirect)
    app.router.add_get(
        "/docs/maintainer/",
        maintainer_access(maintainer_guide_page),
    )

    app.router.add_get("/", root_redirect)
    app.router.add_static("/", path=str(book_root()), show_index=True)

    return app


def run_voila(app_name: str) -> None:
    """``icesee_app.py voila <icesee|icesheets>``: run one application Voila
    server in the foreground, as whatever account starts it, with the same
    command line and environment allowlist the managed mode uses and the
    token from CRYOSTACK_VOILA_TOKEN_FILE."""
    if app_name not in VOILA_APPS:
        raise SystemExit(f"usage: icesee_app.py voila {{{'|'.join(VOILA_APPS)}}}")
    env = voila_environment(read_voila_token_file())
    os.chdir(repo_root())
    command = voila_command(app_name)
    os.execve(command[0], command, env)


if __name__ == "__main__":
    if sys.argv[1:2] == ["voila"]:
        run_voila(sys.argv[2] if len(sys.argv) > 2 else "")
    # Bare-metal production keeps its existing behavior (loopback-only;
    # nginx reverse-proxies to it on the same host) as the default. A
    # container needs to bind the interface Docker's -p port-publishing
    # actually reaches (the container's eth0, not its loopback) -- set
    # CRYOSTACK_HOST=0.0.0.0 for that case rather than changing the
    # production default.
    host = os.environ.get("CRYOSTACK_HOST", "127.0.0.1")
    web.run_app(
        make_app(),
        host=host,
        port=configured_port("CRYOSTACK_PORT", 8080),
    )
