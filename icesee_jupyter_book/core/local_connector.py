from __future__ import annotations

import json
import platform
import urllib.request
from dataclasses import dataclass

import ipywidgets as W


ICESEE_CONNECTOR_URL = "http://127.0.0.1:8765"


@dataclass
class ConnectorCheck:
    ok: bool
    data: dict
    error: str = ""


def detect_client_os() -> str:
    """
    Detects the OS where the notebook/server Python is running.

    For local/GHUB-style deployments this is usually enough for the first MVP.
    Later, for true browser-client OS detection, we can move detection to JS.
    """
    system = platform.system().lower()

    if "darwin" in system:
        return "macos"
    if "windows" in system:
        return "windows"
    if "linux" in system:
        return "linux"

    return "unknown"


def connector_installer_url() -> str:
    os_name = detect_client_os()

    urls = {
        "macos": "https://cryolauncher.com/downloads/ICESEE-Connector-macOS.pkg",
        "windows": "https://cryolauncher.com/downloads/ICESEE-Connector-Windows.exe",
        "linux": "https://cryolauncher.com/downloads/ICESEE-Connector-Linux.AppImage",
        "unknown": "https://cryolauncher.com/downloads/",
    }

    return urls.get(os_name, urls["unknown"])


def connector_required_for_mode(mode: str) -> bool:
    """
    Connector should only be required for remote HPC mode.
    Cloud/public/local demos should not trigger it.
    """
    return str(mode).strip().lower() in {
        "remote",
        "remote_hpc",
        "ssh_slurm",
        "vpn_cluster",
        "local_relay",
    }


def check_local_connector(timeout: float = 1.5) -> ConnectorCheck:
    """
    Checks whether the ICESEE Connector is running.

    MVP behavior:
      - Connector exposes http://127.0.0.1:8765/status
      - Returns JSON:
          {
            "status": "ok",
            "version": "0.1.0"
          }
    """
    url = f"{ICESEE_CONNECTOR_URL}/status"

    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            text = response.read().decode("utf-8")
            data = json.loads(text)

        return ConnectorCheck(
            ok=True,
            data=data,
            error="",
        )

    except Exception as e:
        return ConnectorCheck(
            ok=False,
            data={},
            error=str(e),
        )


def connector_success_html(data: dict | None = None) -> str:
    data = data or {}
    version = data.get("version", "unknown")

    return f"""
    <div style="
        border:1px solid rgba(30,170,80,.25);
        background:rgba(30,170,80,.08);
        border-radius:12px;
        padding:12px;
        line-height:1.5;
        margin:8px 0;
    ">
      <b>ICESEE Connector detected.</b><br>
      Version: <b>{version}</b><br>
      Remote HPC bridge is available.
    </div>
    """


def connector_prompt_html(error: str = "") -> str:
    os_name = detect_client_os()
    installer = connector_installer_url()

    error_block = ""
    if error:
        error_block = f"""
        <div style="margin-top:8px; color:rgba(150,0,0,.85); font-size:12px;">
          Last check: {error}
        </div>
        """

    return f"""
    <div style="
        border:1px solid rgba(220,60,60,.25);
        background:rgba(220,60,60,.06);
        border-radius:12px;
        padding:14px;
        line-height:1.55;
        margin:8px 0;
    ">
      <b>ICESEE Connector is required for remote HPC runs.</b><br>
      Remote mode needs a local connector so the user's workstation can act as
      the bridge to VPN-protected clusters.
      <br><br>
      Detected OS: <b>{os_name}</b><br>
      <a href="{installer}" target="_blank"
         style="
           display:inline-block;
           margin-top:8px;
           background:#0d6efd;
           color:white;
           padding:8px 12px;
           border-radius:8px;
           text-decoration:none;
           font-weight:700;">
        Download ICESEE Connector
      </a>
      <br><br>
      After installation, turn on VPN and click <b>Retry connector check</b>.
      {error_block}
    </div>
    """


def build_connector_panel(mode_widget=None):
    """
    Reusable connector panel for both gateways.

    Returns:
      panel_box, refresh_fn

    Usage:
      connector_panel, refresh_connector = build_connector_panel(mode_dd)
      remote_box = W.VBox([connector_panel, ...])

      if mode_dd.value == "remote":
          if not refresh_connector():
              block submit
    """
    status_html = W.HTML("")
    retry_btn = W.Button(
        description="Retry connector check",
        icon="refresh",
        button_style="info",
    )

    panel = W.VBox(
        [status_html, retry_btn],
        layout=W.Layout(width="100%", gap="6px"),
    )

    def refresh(_=None) -> bool:
        mode = getattr(mode_widget, "value", "remote") if mode_widget is not None else "remote"

        if not connector_required_for_mode(mode):
            status_html.value = ""
            panel.layout.display = "none"
            return True

        panel.layout.display = ""

        result = check_local_connector()

        if result.ok:
            status_html.value = connector_success_html(result.data)
            return True

        status_html.value = connector_prompt_html(result.error)
        return False

    retry_btn.on_click(refresh)

    if mode_widget is not None:
        def _on_mode_change(change):
            if change.get("name") == "value":
                refresh()

        mode_widget.observe(_on_mode_change, names="value")

    refresh()

    return panel, refresh


def check_connector_or_prompt(mode: str, status_widget: W.HTML | None = None) -> bool:
    """
    Utility for submit buttons.

    Returns True if:
      - connector is not required, or
      - connector is running.

    Returns False if:
      - connector is required but missing.
    """
    if not connector_required_for_mode(mode):
        if status_widget is not None:
            status_widget.value = ""
        return True

    result = check_local_connector()

    if result.ok:
        if status_widget is not None:
            status_widget.value = connector_success_html(result.data)
        return True

    if status_widget is not None:
        status_widget.value = connector_prompt_html(result.error)

    return False