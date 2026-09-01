"""Lightweight, opt-in performance instrumentation.

Enabled only when ``CRYOSTACK_PERF`` is set to a truthy value (``1``, ``true``,
``yes``, ``on``). When disabled every helper is a near-zero-cost no-op, so calls
can stay in production code paths.

    from cryostack_src import perf

    with perf.span("gateway total"):
        with perf.span("workspace hydrate"):
            ...
        with perf.span("example discovery"):
            ...

Output (stderr)::

    [perf] workspace hydrate         0.081 s
    [perf] example discovery         0.312 s
    [perf] gateway total             2.184 s

Only static labels are ever logged -- never a value, path, credential, or any
user data. Nested spans are indented by depth.
"""
from __future__ import annotations

import contextlib
import os
import sys
import threading
import time

_TRUTHY = {"1", "true", "yes", "on"}


def enabled() -> bool:
    """Whether perf instrumentation should emit output (re-read each call so
    tests can toggle ``CRYOSTACK_PERF`` at runtime)."""
    return os.environ.get("CRYOSTACK_PERF", "").strip().lower() in _TRUTHY


_state = threading.local()


def _depth() -> int:
    return getattr(_state, "depth", 0)


def _emit(label: str, seconds: float, depth: int) -> None:
    indent = "  " * depth
    sys.stderr.write(f"[perf] {indent}{label:<28} {seconds:7.3f} s\n")
    sys.stderr.flush()


@contextlib.contextmanager
def span(label: str):
    """Time the wrapped block and log ``[perf] <label> <seconds>`` on exit.

    A no-op (aside from the ``yield``) when instrumentation is disabled.
    """
    if not enabled():
        yield
        return
    depth = _depth()
    _state.depth = depth + 1
    start = time.perf_counter()
    try:
        yield
    finally:
        _state.depth = depth
        _emit(label, time.perf_counter() - start, depth)


def mark(label: str, seconds: float) -> None:
    """Record a pre-measured duration (for work that cannot be wrapped in a
    ``with`` block)."""
    if enabled():
        _emit(label, seconds, _depth())


@contextlib.contextmanager
def timed(sink: dict, key: str):
    """Accumulate elapsed seconds into ``sink[key]`` regardless of whether
    output is enabled -- for tests and benchmarks that assert on timings."""
    start = time.perf_counter()
    try:
        yield
    finally:
        sink[key] = sink.get(key, 0.0) + (time.perf_counter() - start)
