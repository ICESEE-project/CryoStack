"""CryoStack Connector -- menu-bar / tray application.

macOS threading contract (the fix for "Application Not Responding"):

    Cocoa main thread  -- menu, pairing dialog, status timer, notifications
    background worker   -- HTTP pairing, WebSocket connect/reconnect, SSH

The GUI never touches the network and the worker never touches AppKit. Status
flows one way: a main-thread ``rumps.Timer`` polls
``ConnectorController.status_label()``. There is no second GUI event loop on
macOS (tkinter is used for the pairing prompt on Linux/Windows only).
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from icesee_hpc_connector.connector_controller import ConnectorController
from icesee_hpc_connector.single_instance import SingleInstance

APP_NAME = "CryoStack Connector"
RELAY_URL = "https://cryostack.eas.gatech.edu"
SETUP_URL = "https://cryostack.eas.gatech.edu/connect/"
LOG_FILE = Path.home() / "icesee_connector.log"

OS_NAME = platform.system().lower()
ARCH = platform.machine().lower()


def log(msg: str) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(msg.rstrip() + "\n")
    except Exception:
        pass


def _asset(name: str) -> str | None:
    """Resolve a bundled branding asset (works from source and from a
    PyInstaller bundle)."""
    roots = [Path(__file__).resolve().parent / "assets"]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass) / "assets")
        roots.append(Path(meipass) / "icesee_hpc_connector" / "assets")
    for r in roots:
        p = r / name
        if p.is_file():
            return str(p)
    return None


def open_log_file() -> None:
    LOG_FILE.touch(exist_ok=True)
    opener = {"win32": ["notepad.exe"], "darwin": ["open"]}.get(sys.platform, ["xdg-open"])
    try:
        subprocess.Popen([*opener, str(LOG_FILE)])
    except Exception:
        pass


def _prompt_pairing_code_tk() -> str | None:
    """Linux/Windows pairing prompt. Not used on macOS."""
    try:
        import tkinter as tk
        from tkinter import simpledialog
    except Exception:
        return None
    root = tk.Tk()
    root.withdraw()
    try:
        return simpledialog.askstring(
            APP_NAME,
            "Enter the pairing code from the CryoStack Connector Setup page:",
        )
    finally:
        try:
            root.destroy()
        except Exception:
            pass


# ===========================================================================
# macOS -- rumps
# ===========================================================================
if sys.platform == "darwin":
    import rumps

    class CryoStackConnectorApp(rumps.App):
        def __init__(self, controller: ConnectorController):
            # The menu-bar title stays "CryoStack" text; the CryoStack mark is
            # the .app / Dock icon (set at build time via --icon), which avoids
            # the monochrome-template constraint on menu-bar images.
            super().__init__("CryoStack", quit_button=None)
            self.controller = controller
            self._status_item = rumps.MenuItem(controller.status_label(), callback=None)
            self.menu = [
                self._status_item,
                None,
                rumps.MenuItem("Pair with CryoStack…", callback=self.pair),
                rumps.MenuItem("Open Setup Page", callback=self.open_setup),
                rumps.MenuItem("Open Log File", callback=self.open_log),
                None,
                rumps.MenuItem("Quit", callback=self.quit_app),
            ]
            # Poll worker state on the MAIN thread -- never mutate menu items
            # from the worker.
            self._timer = rumps.Timer(self._tick, 1.5)
            self._timer.start()

            env_code = (os.environ.get("CRYOSTACK_PAIRING_CODE") or "").strip()
            if env_code:
                self.controller.start(env_code)

        def _tick(self, _timer):
            self._status_item.title = self.controller.status_label()

        def pair(self, _):
            self.controller.emit("pairing-dialog-open")
            resp = rumps.Window(
                message="Enter the pairing code from the CryoStack Connector Setup page:",
                title=APP_NAME,
                ok="Pair",
                cancel="Cancel",
                dimensions=(240, 24),
            ).run()
            code = (resp.text or "").strip()
            if resp.clicked and code:
                if not self.controller.start(code):
                    rumps.notification(APP_NAME, "Already running",
                                       "The connector is already paired/active.")
            else:
                self.controller.emit("pairing-dialog-cancelled")

        def open_setup(self, _):
            webbrowser.open(SETUP_URL)

        def open_log(self, _):
            open_log_file()

        def quit_app(self, _):
            self.controller.emit("app-shutdown")
            self.controller.stop()
            rumps.quit_application()

    def _run_gui(controller: ConnectorController) -> None:
        app = CryoStackConnectorApp(controller)
        controller.emit("menu-loop-started")
        app.run()


# ===========================================================================
# Linux / Windows -- pystray
# ===========================================================================
else:
    import pystray

    def _tray_image():
        from PIL import Image, ImageDraw

        path = _asset("cryostack-connector-512.png")
        if path:
            try:
                return Image.open(path)
            except Exception:
                pass
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((6, 6, 58, 58), fill=(13, 110, 253, 255))
        d.text((24, 20), "C", fill="white")
        return img

    class CryoStackConnectorTray:
        def __init__(self, controller: ConnectorController):
            self.controller = controller
            self._poller: threading.Thread | None = None
            self._poll_stop = threading.Event()
            self.icon = pystray.Icon("CryoStack", _tray_image(), APP_NAME, menu=self._menu())

        def _menu(self):
            return pystray.Menu(
                pystray.MenuItem(lambda _i: self.controller.status_label(), None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Pair with CryoStack…", self._pair),
                pystray.MenuItem("Open Setup Page", lambda *_: webbrowser.open(SETUP_URL)),
                pystray.MenuItem("Open Log File", lambda *_: open_log_file()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", self._quit),
            )

        def _pair(self, *_):
            self.controller.emit("pairing-dialog-open")
            code = _prompt_pairing_code_tk()
            if code and code.strip():
                self.controller.start(code.strip())
            else:
                self.controller.emit("pairing-dialog-cancelled")
                log("[menubar] pairing cancelled or no dialog; set CRYOSTACK_PAIRING_CODE and relaunch")

        def _quit(self, *_):
            self.controller.emit("app-shutdown")
            self._poll_stop.set()
            self.controller.stop()
            self.icon.stop()

        def _poll(self):
            # pystray.Icon.update_menu() is safe to call from another thread.
            last = None
            while not self._poll_stop.wait(1.5):
                cur = self.controller.status_label()
                if cur != last:
                    last = cur
                    try:
                        self.icon.update_menu()
                    except Exception:
                        pass

        def run(self):
            env_code = (os.environ.get("CRYOSTACK_PAIRING_CODE") or "").strip()
            if env_code:
                self.controller.start(env_code)
            self._poller = threading.Thread(target=self._poll, name="cryostack-tray-poll", daemon=True)
            self._poller.start()
            self.controller.emit("menu-loop-started")
            self.icon.run()

    def _run_gui(controller: ConnectorController) -> None:
        CryoStackConnectorTray(controller).run()


# ===========================================================================
def main() -> None:
    log(f"[startup] OS={OS_NAME}, ARCH={ARCH}, Python={sys.version.split()[0]}")

    controller = ConnectorController(RELAY_URL, log=log)
    controller.emit("app-start")

    lock = SingleInstance()
    if not lock.acquire():
        controller.emit("single-instance-blocked")
        msg = "CryoStack Connector is already running (check the menu bar / system tray)."
        log("[menubar] " + msg)
        if sys.platform == "darwin":
            try:
                import rumps
                rumps.alert(title=APP_NAME, message=msg)
            except Exception:
                pass
        return

    try:
        _run_gui(controller)
    finally:
        controller.stop()
        lock.release()
        controller.emit("app-shutdown")


if __name__ == "__main__":
    main()
