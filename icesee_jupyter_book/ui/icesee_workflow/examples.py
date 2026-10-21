"""Application -> example selection for the Experiment card.

ICESEE couples several examples to each forecast-model application
(core/example_registry.py discovers them from the ICESEE repository). The
user picks the application, then one of its examples. ``source`` -- the
gateway's existing example dropdown holding every example key -- stays the
single source of truth: everything that reads or sets the example (launch,
run records, Reuse configuration, Auto-config) keeps using it, and this
picker follows it both ways.
"""
from __future__ import annotations

import ipywidgets as W

from icesee_jupyter_book.core import example_registry as registry
from icesee_jupyter_book.core.example_registry import application_of, applications, canonical, examples_of

from .components import esc


class ExamplePicker:
    def __init__(self, source: W.Dropdown):
        self.source = source
        current = registry.EXAMPLES[source.value]
        self.application = W.Dropdown(options=applications(), value=application_of(current),
                                      layout=W.Layout(width="100%"))
        self.application.tooltip = "The forecast model ICESEE assimilates data into"
        self.example = W.Dropdown(options=self._options(application_of(current)), value=canonical(source.value),
                                  layout=W.Layout(width="100%"))
        self.example.tooltip = "An example ICESEE couples to this application"
        self.note = W.HTML()
        self._busy = False
        self.application.observe(self._on_application, names="value")
        self.example.observe(self._on_example, names="value")
        source.observe(self._on_source, names="value")
        self._render_note()

    @staticmethod
    def _options(application: str) -> list:
        return [(registry.EXAMPLES[k].get("example", k) + ("  (default)" if registry.EXAMPLES[k].get("default") else ""), k)
                for k in examples_of(application)]

    def _guard(self, fn):
        if self._busy:
            return
        self._busy = True
        try:
            fn()
        finally:
            self._busy = False

    def _on_application(self, change) -> None:
        def go():
            options = self._options(change["new"])
            self.example.options = options
            self.example.value = options[0][1]
            if self.source.value != options[0][1]:
                self.source.value = options[0][1]
        self._guard(go)
        self._render_note()

    def _on_example(self, change) -> None:
        def go():
            if change["new"] and self.source.value != change["new"]:
                self.source.value = change["new"]
        self._guard(go)
        self._render_note()

    def _on_source(self, change) -> None:
        """The example was set elsewhere (Reuse configuration, Auto-config)."""
        def go():
            key = canonical(change["new"])
            cfg = registry.EXAMPLES.get(key)
            if cfg is None:
                return
            app = application_of(cfg)
            if app not in self.application.options:
                self.application.options = applications()
            if self.application.value != app:
                self.application.value = app
            if key not in [v for _l, v in self.example.options]:
                self.example.options = self._options(app)
            if self.example.value != key:
                self.example.value = key
        self._guard(go)
        if canonical(change["new"]) != change["new"]:
            # a legacy key (an older run record, a saved configuration): use the example's own key
            self.source.value = canonical(change["new"])
        self._render_note()

    def _render_note(self) -> None:
        cfg = registry.EXAMPLES.get(self.example.value)
        if cfg is None:
            self.note.value = ""
            return
        app = application_of(cfg)
        n = len(examples_of(app))
        where = f' · <code>{esc(cfg["remote_rel"])}</code>' if cfg.get("remote_rel") else ""
        self.note.value = (f'<div class="icw-card-sub">{n} example{"s" if n != 1 else ""} coupled to ICESEE for '
                           f'{esc(app)}{where}</div>')
