"""Redis / RQ helpers. Long work never runs inside an HTTP request."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from redis import Redis
from rq import Queue

from app.config import get_settings

QUEUE_PROCESS = "process"  # long project pipelines
QUEUE_RENDER = "render"  # single-clip re-renders and exports (short, keep responsive)


@lru_cache
def get_redis() -> Redis:  # type: ignore[type-arg]
    return Redis.from_url(get_settings().redis_url)


def get_queue(name: str) -> Queue:
    return Queue(name, connection=get_redis(), default_timeout=get_settings().job_timeout_seconds)


def enqueue(queue: str, func: str, *args: Any, job_id: str | None = None) -> str:
    job = get_queue(queue).enqueue(func, *args, job_id=job_id, failure_ttl=7 * 24 * 3600)
    return str(job.id)


def cancel_job(job_id: str | None) -> None:
    if not job_id:
        return
    from rq.command import send_stop_job_command
    from rq.exceptions import InvalidJobOperation, NoSuchJobError
    from rq.job import Job

    try:
        job = Job.fetch(job_id, connection=get_redis())
        if job.get_status() == "started":
            send_stop_job_command(get_redis(), job_id)
        else:
            job.cancel()
    except (NoSuchJobError, InvalidJobOperation):
        pass
