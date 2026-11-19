"""In-program background calls.

``jobs.start`` is the one handle that works for every tool function: it starts
the call on a worker thread and returns immediately. The program keeps running;
``result`` blocks only where the value is needed. This is concurrency inside one
program, not detached work that survives it.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import CancelledError as FutureCancelled, Future, ThreadPoolExecutor
from typing import Any, Callable, Generic, TypeVar

from ._errors import AgentError

T = TypeVar("T")

# The host advertises the same limit, so one worker per concurrent call is the
# natural shape. Extra starts queue here rather than being refused.
_MAX_WORKERS = 8

_EXECUTOR = ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix="agent-job")
_JOBS: set["Job[Any]"] = set()
_JOBS_LOCK = threading.Lock()


class Job(Generic[T]):
    """One started call.

    ``result`` and ``wait`` block the calling thread until the call finishes.
    ``cancel`` refuses a job that has not started; a tool call already in flight
    cannot be interrupted by the Python side.
    """

    def __init__(self, future: Future[Any], callable_name: str) -> None:
        self._future = future
        self.name = callable_name

    def result(self, timeout: float | None = None) -> Any:
        """Return the tool result, or raise the tool error."""

        try:
            return self._future.result(timeout)
        except AgentError:
            raise
        except FutureCancelled:
            raise AgentError("canceled", "job canceled before it started")
        except Exception as error:  # defensive: worker failures are tool failures
            raise AgentError("tool_failed", str(error)) from error

    def wait(self, timeout: float | None = None) -> Any:
        """Block until the call finishes and return its result."""

        return self.result(timeout)

    def done(self) -> bool:
        return self._future.done()

    def cancel(self) -> bool:
        """Cancel a queued job. A running tool call is not interruptible."""

        return self._future.cancel()

    def exception(self, timeout: float | None = None) -> BaseException | None:
        """Return the tool error without raising it."""

        try:
            return self._future.exception(timeout)
        except Exception as error:  # defensive: worker failures are tool failures
            return error


def start(fn: Callable[..., T], *args: Any, **kwargs: Any) -> Job:
    """Start one tool call and return its handle.

    The callable is a normal SDK function::

        job = jobs.start(fs.read, "src/main.ts", limit=40)
        text = job.result().text

    The program keeps running until ``result`` is reached. The host's
    concurrency limit applies to in-flight calls; extra starts queue.
    """

    if not callable(fn):
        raise AgentError("invalid_argument", "jobs.start needs a callable")
    name = getattr(fn, "__name__", "call")
    try:
        future = _EXECUTOR.submit(fn, *args, **kwargs)
    except RuntimeError as error:
        raise AgentError("unavailable", f"job worker unavailable: {error}") from error
    job = Job(future, name)
    with _JOBS_LOCK:
        _JOBS.add(job)
    future.add_done_callback(lambda _future: _forget(job))
    return job


def gather(*jobs: Job) -> list[Any]:
    """Wait for the given jobs and return their results in order."""

    return [job.result() for job in jobs]


def wait_all(timeout: float | None = None) -> bool:
    """Wait for every started job.

    Returns ``True`` when all jobs finished before the timeout. A ``None``
    timeout waits for every job. Returns ``False`` when the timeout expires.
    """

    with _JOBS_LOCK:
        pending = list(_JOBS)
    if not pending:
        return True
    deadline = None if timeout is None else time.monotonic() + timeout
    done = True
    for job in pending:
        remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
        try:
            job.result(remaining)
            done = True
        except AgentError:
            done = True
        except TimeoutError:
            done = False
        except BaseException:
            done = True
    return done


def cancel_all() -> int:
    """Cancel every job that has not started; return the canceled count."""

    with _JOBS_LOCK:
        pending = list(_JOBS)
    return sum(1 for job in pending if job.cancel())


def _forget(job: "Job[Any]") -> None:
    with _JOBS_LOCK:
        _JOBS.discard(job)


__all__ = ["Job", "start", "gather", "wait_all", "cancel_all"]


def __dir__() -> list[str]:
    return sorted(__all__)
