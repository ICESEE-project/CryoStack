from __future__ import annotations

from .base import RemoteDriver

from cryostack_src.remote.legacy.remote_runner import (
    submit_remote_example,
    remote_job_status,
    remote_tail_log,
    remote_cancel_job,
)


class SSHDriver(RemoteDriver):

    def submit(self, **kwargs):
        return submit_remote_example(**kwargs)

    def status(self, job_id, **kwargs):
        return remote_job_status(job_id=job_id, **kwargs)

    def logs(self, job_id, **kwargs):
        return remote_tail_log(job_id=job_id, **kwargs)

    def terminate(self, job_id, **kwargs):
        return remote_cancel_job(jobid=job_id, **kwargs)