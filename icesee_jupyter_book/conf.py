from __future__ import annotations
from pathlib import Path
import sys

def setup(app):
    book_root = Path(__file__).resolve().parent
    utils_dir = book_root / "utils"
    if str(utils_dir) not in sys.path:
        sys.path.insert(0, str(utils_dir))

    def _run_fix(_app):
        try:
            from fix_notebook_schema import fix_all_notebooks
            fix_all_notebooks(book_root)
            print("[ICESEE book] fixed notebook schema: nbformat_minor>=5 and removed cell ids")
        except Exception as e:
            print(f"[ICESEE book] schema fix skipped: {e}")

    # Run early enough before myst-nb execution
    app.connect("builder-inited", _run_fix)
