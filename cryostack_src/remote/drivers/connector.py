from __future__ import annotations

from .base import RemoteDriver

from cryostack_src.remote.legacy.remote_runner import (
    submit_remote_example_via_connector,
    connector_job_status,
    connector_tail_log,
    connector_cancel_job,
)


class ConnectorDriver(RemoteDriver):

    def submit(self, **kwargs):
        return submit_remote_example_via_connector(**kwargs)

    def status(self, job_id, **kwargs):
        return connector_job_status(job_id=job_id, **kwargs)

    def logs(self, job_id, **kwargs):
        return connector_tail_log(job_id=job_id, **kwargs)

    def terminate(self, job_id, **kwargs):
        return connector_cancel_job(jobid=job_id, **kwargs)