from __future__ import annotations

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


def connector_worker(set_status=None):
    if set_status:
        set_status("Status: running")

    try:
        run_connector(
            relay=RELAY_URL,
            session=None,
            ws_url=None,
            poll=True,
        )
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
                rumps.MenuItem("Status: stopped", callback=None),
                None,
                rumps.MenuItem("Start Connector", callback=self.start_connector),
                rumps.MenuItem("Open Setup Page", callback=self.open_setup),
                rumps.MenuItem("Open Log File", callback=self.open_log),
                None,
                rumps.MenuItem("Quit", callback=self.quit_app),
            ]

            self.start_connector(None)

        def set_status(self, text: str):
            self.menu["Status: stopped"].title = text

        def start_connector(self, _):
            if self.thread and self.thread.is_alive():
                rumps.notification(APP_NAME, "Already running", "The connector is already active.")
                return

            self.thread = threading.Thread(
                target=connector_worker,
                args=(self.set_status,),
                daemon=True,
            )
            self.thread.start()

            rumps.notification(APP_NAME, "Started", "Waiting for a CryoStack connector session.")

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
            self.status = "Status: stopped"
            self.icon = pystray.Icon(
                "CryoStack",
                self.make_icon(),
                APP_NAME,
                menu=self.make_menu(),
            )

        def make_icon(self):
            img = Image.new("RGB", (64, 64), "white")
            draw = ImageDraw.Draw(img)
            draw.ellipse((8, 8, 56, 56), fill="black")
            draw.text((20, 22), "I", fill="white")
            return img

        def set_status(self, text: str):
            self.status = text
            self.icon.menu = self.make_menu()
            self.icon.update_menu()

        def make_menu(self):
            return pystray.Menu(
                pystray.MenuItem(lambda _: self.status, None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Start Connector", self.start_connector),
                pystray.MenuItem("Open Setup Page", self.open_setup),
                pystray.MenuItem("Open Log File", self.open_log),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", self.quit_app),
            )

        def start_connector(self, *_):
            if self.thread and self.thread.is_alive():
                log("[menubar] connector already running")
                return

            self.thread = threading.Thread(
                target=connector_worker,
                args=(self.set_status,),
                daemon=True,
            )
            self.thread.start()

        def open_setup(self, *_):
            webbrowser.open(SETUP_URL)

        def open_log(self, *_):
            open_log_file()

        def quit_app(self, *_):
            self.icon.stop()

        def run(self):
            self.start_connector()
            self.icon.run()

    def main():
        CryoStackConnectorTray().run()


if __name__ == "__main__":
    log(f"[startup] OS={OS_NAME}, ARCH={ARCH}, Python={sys.version}")
    main()