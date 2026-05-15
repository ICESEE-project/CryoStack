from __future__ import annotations

import threading
import webbrowser
from pathlib import Path

import rumps

from icesee_hpc_connector.connector_core import run_connector


LOG_FILE = Path.home() / "icesee_connector.log"


class ICESEEConnectorApp(rumps.App):
    def __init__(self):
        super().__init__("ICESEE", quit_button=None)
        self.thread = None
        self.running = False

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

    def connector_worker(self):
        self.running = True
        self.menu["Status: stopped"].title = "Status: running"
        try:
            run_connector(
                relay="https://cryolauncher.com",
                session=None,
                ws_url=None,
                poll=True,
            )
        except Exception as e:
            with open(LOG_FILE, "a") as f:
                f.write(f"[menubar] connector crashed: {type(e).__name__}: {e}\n")
            self.menu["Status: stopped"].title = "Status: error"

    def start_connector(self, _):
        if self.thread and self.thread.is_alive():
            rumps.notification(
                "ICESEE Connector",
                "Already running",
                "The connector is already active.",
            )
            return

        self.thread = threading.Thread(target=self.connector_worker, daemon=True)
        self.thread.start()

        rumps.notification(
            "ICESEE Connector",
            "Started",
            "Waiting for an ICESEE connector session.",
        )

    def open_setup(self, _):
        webbrowser.open("https://cryolauncher.com/connect/")

    def open_log(self, _):
        LOG_FILE.touch(exist_ok=True)
        webbrowser.open(f"file://{LOG_FILE}")

    def quit_app(self, _):
        rumps.quit_application()


if __name__ == "__main__":
    ICESEEConnectorApp().run()