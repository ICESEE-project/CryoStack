try:
    # `app.py`'s Flask Blueprint is not mounted or imported anywhere by the
    # running gateway (bin/icesee_app.py serves /frozen-legacies/ itself via
    # a plain aiohttp static route); Flask is therefore not a dependency of
    # the active application architecture. But `__init__.py` runs before any
    # submodule when this package is invoked as `python -m
    # icesee_jupyter_book.applications.frozen_legacies.build_antarctica` (or
    # `.build_geojson`), so an unconditional import here previously forced
    # Flask to be installed just to run those data-generator scripts, which
    # never touch `frozen_legacies_bp`. Degrade to None instead of failing
    # when Flask is absent; callers that actually need the Blueprint still
    # get the real object when Flask is installed.
    from .app import frozen_legacies_bp
except ImportError:
    frozen_legacies_bp = None

__all__ = [
    "frozen_legacies_bp",
]