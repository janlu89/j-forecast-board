# SPDX-License-Identifier: Apache-2.0
"""One background worker thread with a priority queue (implements application.JobRunner)."""

from __future__ import annotations

import itertools
import queue
import threading
import time
import traceback
from collections.abc import Callable

from ....application.ports import JobState


class ThreadJobRunner:
    def __init__(self):
        self._jobs: dict[tuple, JobState] = {}
        self._work: dict[tuple, Callable[[JobState], None]] = {}
        self._queue: queue.PriorityQueue = queue.PriorityQueue()
        self._order = itertools.count()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._loop, daemon=True, name="evaluation-worker"
            )
            self._thread.start()

    def submit(
        self, key: tuple, work: Callable[[JobState], None], priority: int, info: dict
    ) -> JobState:
        with self._lock:
            job = self._jobs.get(key)
            if job is not None and job.state == "running":
                return job
            if job is not None and job.state == "queued":
                if priority < job.priority:  # promote: the worker skips the stale entry
                    job.priority = priority
                    self._queue.put((priority, next(self._order), key))
                return job
            job = JobState(key=key, info=info, priority=priority)
            self._jobs[key] = job
            self._work[key] = work
            self._queue.put((priority, next(self._order), key))
            return job

    def get(self, key: tuple) -> JobState | None:
        with self._lock:
            return self._jobs.get(key)

    def all(self) -> list[JobState]:
        with self._lock:
            return list(self._jobs.values())

    def _loop(self) -> None:
        while True:
            _, _, key = self._queue.get()
            with self._lock:
                job, work = self._jobs[key], self._work[key]
            if job.state != "queued":  # duplicate entry left by a promotion
                self._queue.task_done()
                continue
            try:
                job.state, job.started = "running", time.time()
                work(job)
                job.state = "done"
            except Exception as error:  # report every failure on the job, keep the worker alive
                traceback.print_exc()
                job.state, job.error = "error", f"{type(error).__name__}: {error}"
            finally:
                self._queue.task_done()
