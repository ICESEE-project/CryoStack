"""CryoStack integration of LIVIST (Living Ice Sheet Temperature).

LIVIST itself is the ``external/living-ice-sheet-temperature`` submodule and
is only read. This package runs LIVIST's own ``scripts/generate`` in an
isolated environment (``environment/build_env.sh``) as controlled background
jobs in each user's workspace, validates the products, and plans their
publication to source.coop. :func:`routes.install_livist` adds the Control
Center page ``/control/livist`` and the ``/api/livist/`` API.
"""
