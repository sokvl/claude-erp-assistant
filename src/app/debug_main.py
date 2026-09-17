"""Local-only debug entry point: `CHAT_TRACE=1 uvicorn app.debug_main:app --reload`.

Never used in production - `app.main` is the real entry point and has no
knowledge of this module. Tracing is installed here, before `app.main` (and
the routers it imports) are loaded, so every patched function is in place
before any request can reach it.
"""

from app.trace import install

install()

from app.main import app  # noqa: E402
