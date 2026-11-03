"""RQ worker entrypoint: ``python -m app.worker [queues...]``."""

from __future__ import annotations

import logging
import sys

from rq import Worker

from app.queue import QUEUE_PROCESS, QUEUE_RENDER, get_redis


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpx2", "huggingface_hub", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    queues = sys.argv[1:] or [QUEUE_RENDER, QUEUE_PROCESS]
    Worker(queues, connection=get_redis()).work(with_scheduler=False)


if __name__ == "__main__":
    main()
