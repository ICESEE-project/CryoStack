from __future__ import annotations

from .base import RemoteDriver

class ConnectorDriver(RemoteDriver):

    def submit(self, **kwargs):
        submitter = kwargs.pop("submitter")
        return submitter(**kwargs)

    def status(self, job_id, **kwargs):
        handler = kwargs.pop("handler")
        return handler(job_id=job_id, **kwargs)

    def logs(self, job_id, **kwargs):
        handler = kwargs.pop("handler")
        return handler(job_id=job_id, **kwargs)

    def terminate(self, job_id, **kwargs):
        handler = kwargs.pop("handler")
        return handler(job_id=job_id, **kwargs)
