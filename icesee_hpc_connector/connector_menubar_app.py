from __future__ import annotations

import os
import platform
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

from icesee_hpc_connector.connector_core import run_connector


APP_NAME = "CryoStack Connector"
RELAY_URL = "https://cryostack.eas.gatech.edu"
SETUP_URL = "https://cryostack.eas.gatech.edu/connect/"
LOG_FILE = Path.home() / "icesee_connector.log"

OS_NAME = platform.system().lower()
ARCH = platform.machine().lower()


def log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg.rstrip() + "\n")


def open_log_file() -> None:
    LOG_FILE.touch(exist_ok=True)
    if sys.platform == "win32":
        subprocess.Popen(["notepad.exe", str(LOG_FILE)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(LOG_FILE)])
    else:
        subprocess.Popen(["xdg-open", str(LOG_FILE)])


def _prompt_pairing_code_tk() -> str | None:
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
        root.destroy()


def connector_worker(pairing_code: str | None, set_status=None):
    if set_status:
        set_status("Status: pairing" if pairing_code else "Status: waiting to pair")
    try:
        run_connector(relay=RELAY_URL, pairing_code=pairing_code or None, poll=True)
        if set_status:
            set_status("Status: not paired")
    except Exception as e:
        log(f"[menubar] connector crashed: {type(e).__name__}: {e}")
        if set_status:
            set_status("Status: error")


if sys.platform == "darwin":
    import rumps

    class CryoStackConnectorApp(rumps.App):
        def __init__(self):
            super().__init__("CryoStack", quit_button=None)
            self.thread = None
            self.menu = [
                rumps.MenuItem("Status: not paired", callback=None),
                None,
                rumps.MenuItem("Pair with CryoStack…", callback=self.pair),
                rumps.MenuItem("Open Setup Page", callback=self.open_setup),
                rumps.MenuItem("Open Log File", callback=self.open_log),
                None,
                rumps.MenuItem("Quit", callback=self.quit_app),
            ]
            # Auto-pair only if a code was provided out-of-band.
            env_code = (os.environ.get("CRYOSTACK_PAIRING_CODE") or "").strip()
            if env_code:
                self._start(env_code)

        def set_status(self, text: str):
            self.menu["Status: not paired"].title = text

        def _start(self, code: str | None):
            if self.thread and self.thread.is_alive():
                rumps.notification(APP_NAME, "Already running", "The connector is already active.")
                return
            self.thread = threading.Thread(
                target=connector_worker, args=(code, self.set_status), daemon=True
            )
            self.thread.start()

        def pair(self, _):
            code = rumps.Window(
                message="Enter the pairing code from the CryoStack Connector Setup page:",
                title=APP_NAME,
                dimensions=(220, 24),
            ).run().text.strip()
            if code:
                self._start(code)

        def open_setup(self, _):
            webbrowser.open(SETUP_URL)

        def open_log(self, _):
            open_log_file()

        def quit_app(self, _):
            rumps.quit_application()

    def main():
        CryoStackConnectorApp().run()


else:
    import pystray
    from PIL import Image, ImageDraw

    class CryoStackConnectorTray:
        def __init__(self):
            self.thread = None
            self.status = "Status: not paired"
            self.icon = pystray.Icon("CryoStack", self.make_icon(), APP_NAME, menu=self.make_menu())

        def make_icon(self):
            img = Image.new("RGB", (64, 64), "white")
            draw = ImageDraw.Draw(img)
            draw.ellipse((8, 8, 56, 56), fill="black")
            draw.text((26, 22), "C", fill="white")
            return img

        def set_status(self, text: str):
            self.status = text
            self.icon.menu = self.make_menu()
            self.icon.update_menu()

        def make_menu(self):
            return pystray.Menu(
                pystray.MenuItem(lambda _: self.status, None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Pair with CryoStack…", self.pair),
                pystray.MenuItem("Open Setup Page", self.open_setup),
                pystray.MenuItem("Open Log File", self.open_log),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", self.quit_app),
            )

        def _start(self, code: str | None):
            if self.thread and self.thread.is_alive():
                log("[menubar] connector already running")
                return
            self.thread = threading.Thread(
                target=connector_worker, args=(code, self.set_status), daemon=True
            )
            self.thread.start()

        def pair(self, *_):
            code = _prompt_pairing_code_tk()
            if code and code.strip():
                self._start(code.strip())
            else:
                log("[menubar] pairing cancelled or no dialog available; "
                    "set CRYOSTACK_PAIRING_CODE and relaunch")

        def open_setup(self, *_):
            webbrowser.open(SETUP_URL)

        def open_log(self, *_):
            open_log_file()

        def quit_app(self, *_):
            self.icon.stop()

        def run(self):
            env_code = (os.environ.get("CRYOSTACK_PAIRING_CODE") or "").strip()
            if env_code:
                self._start(env_code)
            self.icon.run()

    def main():
        CryoStackConnectorTray().run()


if __name__ == "__main__":
    log(f"[startup] OS={OS_NAME}, ARCH={ARCH}, Python={sys.version}")
    main()
