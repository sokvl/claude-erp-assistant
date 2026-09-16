import os

# app.config reads API_KEY at import time, so this must be set before any
# `app.*` import. conftest is imported before test modules, so here is early enough.
os.environ.setdefault("API_KEY", "test-key")
