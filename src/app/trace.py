import functools
import importlib
import inspect
import itertools
import json
import logging
import logging.handlers
import os
import time
from pathlib import Path
from threading import Lock

TRACE_FILE = Path(__file__).resolve().parents[2] / "logs" / "chat_trace.log"
MAX_VALUE_CHARS = 4000

_TARGETS = [
    ("app.security", "require_api_key"),
    ("app.catalog.vocab", "get_vocabulary"),
    ("app.catalog.service", "search_catalog"),
    ("app.catalog.service", "search_products"),
    ("app.pagination", "paginate"),
    ("app.assistant.dispatch", "run_tool"),
    ("app.assistant.tools", "build_tools"),
    ("app.assistant.chat", "run_turn"),
    ("app.assistant.chat", "_stream_once"),
]
_ENTRYPOINT = ("app.assistant.chat", "run_turn")
_MEMORY_METHODS = ("create", "history", "append_turn")

_lock = Lock()
_steps = itertools.count(1)
_installed = False


def enabled() -> bool:
    return os.environ.get("CHAT_TRACE") == "1"


@functools.cache
def _logger() -> logging.Logger:
    TRACE_FILE.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("app.trace")
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    handler = logging.handlers.WatchedFileHandler(TRACE_FILE, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d %(message)s", "%H:%M:%S"))
    logger.addHandler(handler)
    return logger


def _new_block(title: str) -> None:
    global _steps
    with _lock:
        _steps = itertools.count(1)
        _logger().debug("\n%s\n%s\n%s", "=" * 100, title, "=" * 100)


def _summarize(value: object) -> str:
    try:
        text = json.dumps(value, indent=2, default=str, ensure_ascii=False)
    except TypeError:
        text = repr(value)
    if len(text) > MAX_VALUE_CHARS:
        text = text[:MAX_VALUE_CHARS] + f"\n... [{len(text) - MAX_VALUE_CHARS} more chars]"
    return "\n" + "\n".join(f"      {line}" for line in text.splitlines())


def _emit(where: str, what: str, **data: object) -> None:
    body = "".join(f"\n   {key}:{_summarize(value)}" for key, value in data.items() if value is not None)
    with _lock:
        _logger().debug("#%03d [%s] %s%s", next(_steps), where, what, body)


def _call_args(fn: object, args: tuple, kwargs: dict) -> dict:
    try:
        bound = inspect.signature(fn).bind_partial(*args, **kwargs)
        bound.apply_defaults()
        return {key: value for key, value in bound.arguments.items() if key not in ("self", "cls")}
    except TypeError:
        return {"args": list(args), "kwargs": kwargs}


def _instrument(where: str, fn: object, *, is_entrypoint: bool = False) -> object:
    label = f"{getattr(fn, '__module__', '?')}.{getattr(fn, '__qualname__', fn)}"

    if inspect.isgeneratorfunction(fn):

        @functools.wraps(fn)
        def generator_wrapper(*args: object, **kwargs: object):
            if is_entrypoint:
                _new_block(f"{label}() - new request")
            _emit(where, f"{label}() called", args=_call_args(fn, args, kwargs))
            started_at = time.perf_counter()
            generator = fn(*args, **kwargs)
            sent = None
            try:
                while True:
                    item = generator.send(sent)
                    _emit(where, f"{label}() yielded", value=item)
                    sent = yield item
            except StopIteration as stop:
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                _emit(where, f"{label}() finished in {elapsed_ms:.0f} ms", ret=stop.value)
                return stop.value
            except BaseException as exc:
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                _emit(where, f"{label}() raised {type(exc).__name__} after {elapsed_ms:.0f} ms", error=str(exc))
                raise

        return generator_wrapper

    @functools.wraps(fn)
    def wrapper(*args: object, **kwargs: object):
        _emit(where, f"{label}() called", args=_call_args(fn, args, kwargs))
        started_at = time.perf_counter()
        try:
            result = fn(*args, **kwargs)
        except BaseException as exc:
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            _emit(where, f"{label}() raised {type(exc).__name__} after {elapsed_ms:.0f} ms", error=str(exc))
            raise
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        _emit(where, f"{label}() returned in {elapsed_ms:.0f} ms", ret=result)
        return result

    return wrapper


def install() -> None:
    """Monkey-patch a curated set of functions to log every call to logs/chat_trace.log.

    Must run before `app.main` (and the routers it imports) are imported, since a
    patched module's own `from X import Y` copies a reference at that moment - see
    debug_main.py, the only intended caller.
    """
    global _installed
    if not enabled() or _installed:
        return
    _installed = True

    for module_name, attr in _TARGETS:
        module = importlib.import_module(module_name)
        original = getattr(module, attr)
        where = f"{module_name.rsplit('.', 1)[-1]}.{attr}"
        setattr(module, attr, _instrument(where, original, is_entrypoint=(module_name, attr) == _ENTRYPOINT))

    memory = importlib.import_module("app.assistant.memory")
    for name in _MEMORY_METHODS:
        original = getattr(memory.ConversationStore, name)
        setattr(memory.ConversationStore, name, _instrument("memory.ConversationStore", original))
