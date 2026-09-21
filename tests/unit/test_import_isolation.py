import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"

# app.config reads API_KEY at import time and app.db builds a MongoClient, so
# the pure modules staying clear of both is what lets this suite run with no
# environment and no database.
PURE_MODULES = [
    "app.catalog.enums",
    "app.catalog.query",
    "app.catalog.schemas",
    "app.invoices.enums",
    "app.invoices.query",
    "app.invoices.schemas",
    "app.charts.enums",
    "app.charts.schemas",
    "app.charts.render",
]


@pytest.mark.parametrize("module", PURE_MODULES, ids=PURE_MODULES)
def test_pure_module_does_not_import_db_or_config(module):
    # Arrange
    code = (
        f"import {module}, sys; "
        "assert 'app.db' not in sys.modules, 'app.db leaked'; "
        "assert 'app.config' not in sys.modules, 'app.config leaked'"
    )

    # Act: a subprocess so no earlier import in this session can mask a leak
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=SRC, capture_output=True, text=True
    )

    # Assert
    assert result.returncode == 0, result.stderr
