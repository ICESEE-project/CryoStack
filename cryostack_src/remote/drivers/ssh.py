from __future__ import annotations

from .base import RemoteDriver

from icesee_jupyter_book.core.remote_runner import (
    remote_job_status,
    remote_tail_log,
    remote_cancel_job,
)


class SSHDriver(RemoteDriver):

    def submit(self, **kwargs):
        submitter = kwargs.pop("submitter")
        return submitter(**kwargs)

    def status(self, job_id, **kwargs):
        return remote_job_status(jobid=job_id, **kwargs)

    def logs(self, job_id, **kwargs):
        return remote_tail_log(jobid=job_id, **kwargs)

    def terminate(self, job_id, **kwargs):
        return remote_cancel_job(jobid=job_id, **kwargs)
