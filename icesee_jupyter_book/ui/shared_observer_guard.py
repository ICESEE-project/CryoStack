"""A tiny, reusable observer-suppression / coalesced-refresh primitive.

Programmatic ``widget.value = ...`` assignments each fire the widget's
observers synchronously. A resource switch or a settings restore does a dozen
of these in a row, so every observer (summary rebuild, connector status,
persistence) runs a dozen times instead of once.

``UIRefreshCoordinator`` gives the gateways one shared way to say "I am about
to make a batch of programmatic changes -- observers, hold your expensive work
until I'm done, then do it once":

    coord = UIRefreshCoordinator(on_settle=update_summary)

    slurm_ntasks.observe(coord.guard(update_summary), names="value")

    with coord.batch():
        _apply_resource_facts()
        _apply_user_settings()
        panel.apply_profile(profile)
    # update_summary runs exactly once here, if anything asked for it

It is deliberately minimal: no threads, no async, reentrant, and a no-op when
not batching so existing call sites are unaffected.
"""
from __future__ import annotations

import contextlib
from collections.abc import Callable


class UIRefreshCoordinator:
    def __init__(self, on_settle: Callable[[], None] | None = None) -> None:
        self._depth = 0
        self._pending = False
        self._on_settle = on_settle or (lambda: None)

    @property
    def suppressed(self) -> bool:
        """True while a ``batch()`` is active -- guarded observers no-op."""
        return self._depth > 0

    @contextlib.contextmanager
    def batch(self):
        """Suppress guarded observers for the duration of the block, then run
        the settle callback once if any guarded observer requested a refresh."""
        self._depth += 1
        try:
            yield
        finally:
            self._depth -= 1
            if self._depth == 0 and self._pending:
                self._pending = False
                self._on_settle()

    def request_refresh(self) -> None:
        """Ask for one settle. Deferred to the end of the batch if batching,
        otherwise runs immediately."""
        if self.suppressed:
            self._pending = True
        else:
            self._on_settle()

    def guard(self, fn: Callable) -> Callable:
        """Wrap an observer so it is skipped while a batch is active. The
        coordinator records that a refresh is wanted, so the batch's settle
        callback still fires once at the end."""
        def wrapped(change=None):
            if self.suppressed:
                self._pending = True
                return None
            return fn(change)

        return wrapped

    def run_guarded(self, fn: Callable, *args, **kwargs):
        """Call ``fn`` only when not batching (for imperative call sites, e.g.
        'refresh the connector session' inside a visibility handler)."""
        if self.suppressed:
            return None
        return fn(*args, **kwargs)
