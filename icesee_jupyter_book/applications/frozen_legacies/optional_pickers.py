"""The picker implementations, which are not part of the public repository.

``pickers/`` (the headless ASTRA port and the LYRA/URSA runners) and
``Pickers/`` (the original picker tools) are distributed separately. A
deployment that holds them installs them at those paths; nothing else changes.

Without them the application still starts and serves everything that does not
need a picker. Manual picking then raises :class:`PickerUnavailable`, which the
API reports as ``503``, and automatic picking reports the picker as not
installed (see ``radar/automatic.py``).

Application code imports ASTRA names from this module, never from
``pickers.astra`` directly.
"""
from __future__ import annotations

_PICKERS = f"{__package__}.pickers"


class PickerUnavailable(RuntimeError):
    """The picker implementation is not installed on this server."""


def is_missing_picker(error: ModuleNotFoundError) -> bool:
    """True when *error* means the picker code itself is absent (as opposed to
    a dependency of an installed picker, which must still fail loudly)."""
    return error.name == _PICKERS or (error.name or "").startswith(_PICKERS + ".")


class _Missing:
    """Stand-in for an ASTRA class or function: any use raises."""

    def __init__(self, name: str):
        self._name = name

    def _raise(self, *_args, **_kwargs):
        raise PickerUnavailable("The ASTRA manual picker is not installed on this server.")

    __call__ = _raise

    def __getattr__(self, attribute):
        if attribute.startswith("__"):  # introspection (copy, inspect, ...)
            raise AttributeError(attribute)
        self._raise()

    def __repr__(self) -> str:
        return f"<{self._name}: ASTRA not installed>"


try:
    from .pickers.astra import (
        CSV_COLUMNS,
        FEATURES,
        STATE_FIELDS,
        SWEEP_RATES,
        ZOOM_WIDTH,
        AstraError,
        AstraGeometry,
        AstraSession,
        astra_csv_text,
        astra_dataframe,
        astra_trace,
        astra_window,
        get_coordinates_for_cbd,
        load_flight_coordinates,
        save_qc_image,
    )
    ASTRA_AVAILABLE = True
except ModuleNotFoundError as _error:
    if not is_missing_picker(_error):
        raise
    ASTRA_AVAILABLE = False

    class AstraError(ValueError):
        """Never raised without ASTRA; kept so ``except AstraError`` works."""

    # Only read while validating a session document, which needs ASTRA anyway.
    CSV_COLUMNS = FEATURES = STATE_FIELDS = SWEEP_RATES = ()
    ZOOM_WIDTH = 0
    AstraGeometry = _Missing("AstraGeometry")
    AstraSession = _Missing("AstraSession")
    astra_csv_text = _Missing("astra_csv_text")
    astra_dataframe = _Missing("astra_dataframe")
    astra_trace = _Missing("astra_trace")
    astra_window = _Missing("astra_window")
    get_coordinates_for_cbd = _Missing("get_coordinates_for_cbd")
    load_flight_coordinates = _Missing("load_flight_coordinates")
    save_qc_image = _Missing("save_qc_image")
