from __future__ import annotations

from .drivers.ssh import SSHDriver
from .drivers.connector import ConnectorDriver


class RemoteManager:

    def __init__(self, mode="ssh"):

        mode = mode.lower()

        if mode == "connector":

            self.driver = ConnectorDriver()

        else:

            self.driver = SSHDriver()

    def submit(self, **kwargs):
        return self.driver.submit(**kwargs)

    def status(self, job_id, **kwargs):
        return self.driver.status(job_id, **kwargs)

    def logs(self, job_id, **kwargs):
        return self.driver.logs(job_id, **kwargs)

    def terminate(self, job_id, **kwargs):
        return self.driver.terminate(job_id, **kwargs)