import copy
import logging
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from anthropic.types import Message
from pymongo.errors import ServerSelectionTimeoutError

from app.assistant import chat
from app.assistant.chat import (
    MAX_MODEL_CALLS,
    MODEL,
    TOOL_FAILURE_MESSAGE,
    Answer,
    ChatError,
    TextDelta,
    ToolCall,
    run_turn,
)
from app.assistant.dispatch import ToolInputError

REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
TOOL_OUTPUT = '{"items":[]}'


def _message(stop_reason, *content, stop_details=None):
    return Message.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": MODEL,
            "content": list(content),
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "stop_details": stop_details,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
    )


def _text(text):
    return {"type": "text", "text": text}


def _tool_use(block_id="toolu_1", name="search_products"):
    return {"type": "tool_use", "id": block_id, "name": name, "input": {}}


def _status_error(cls, status, error_type):
    return cls(
        "boom",
        response=httpx2.Response(status, request=REQUEST),
        body={"type": "error", "error": {"type": error_type, "message": "boom"}},
    )


def _mid_stream(error_type):
    return _status_error(anthropic.APIStatusError, 200, error_type)


class FakeStream:
    def __init__(self, texts=(), final=None, fail_after=None, open_error=None):
        self.texts = list(texts)
        self.final = final
        self.fail_after = fail_after
        self.open_error = open_error

    def __enter__(self):
        if self.open_error:
            raise self.open_error
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        for text in self.texts:
            yield SimpleNamespace(type="text", text=text)
        if self.fail_after:
            raise self.fail_after

    def get_final_message(self):
        return self.final


class FakeClient:
    def __init__(self, *streams):
        self._streams = iter(streams)
        self.requests = []

    @property
    def messages(self):
        return self

    def stream(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        return next(self._streams)


def _answer(text="Hi"):
    return FakeStream([text], _message("end_turn", _text(text)))


def _tool_round(*blocks):
    return FakeStream([], _message("tool_use", *(blocks or (_tool_use(),))))


def _run(client, history=()):
    return list(run_turn(client, None, [], list(history), "question"))


def _fail_tool(monkeypatch, error):
    def failing_run_tool(db, name, tool_input):
        raise error

    monkeypatch.setattr(chat, "run_tool", failing_run_tool)


@pytest.fixture(autouse=True)
def sleeps(monkeypatch):
    recorded = []
    monkeypatch.setattr(chat.time, "sleep", recorded.append)
    return recorded


@pytest.fixture(autouse=True)
def tool_runs(monkeypatch):
    calls = []

    def fake_run_tool(db, name, tool_input):
        calls.append(name)
        return TOOL_OUTPUT

    monkeypatch.setattr(chat, "run_tool", fake_run_tool)
    return calls


@pytest.mark.parametrize(
    ("streams", "expected"),
    [
        (lambda: [_answer("Hi")], [TextDelta("Hi"), Answer("Hi", truncated=False)]),
        (
            lambda: [FakeStream(["Hi"], _message("max_tokens", _text("Hi")))],
            [TextDelta("Hi"), Answer("Hi", truncated=True)],
        ),
        (
            lambda: [_tool_round(), _answer("Hi")],
            [ToolCall("search_products"), TextDelta("Hi"), Answer("Hi", truncated=False)],
        ),
        (
            lambda: [
                FakeStream(["Checking."], _message("tool_use", _text("Checking."), _tool_use())),
                _answer("Done"),
            ],
            [
                TextDelta("Checking."),
                ToolCall("search_products"),
                TextDelta("\n\n"),
                TextDelta("Done"),
                Answer("Checking.\n\nDone", truncated=False),
            ],
        ),
    ],
    ids=["plain_answer", "truncated_answer", "tool_then_answer", "text_before_and_after_tool"],
)
def test_run_turn_successful_turn_yields_expected_events(streams, expected):
    # Arrange
    client = FakeClient(*streams())

    # Act
    events = _run(client)

    # Assert
    assert events == expected


@pytest.mark.parametrize(
    "error",
    [
        lambda: _mid_stream("overloaded_error"),
        lambda: _mid_stream("api_error"),
        lambda: _mid_stream("rate_limit_error"),
        lambda: httpx2.RemoteProtocolError("peer closed connection"),
        lambda: httpx2.ReadTimeout("read timed out"),
        lambda: httpx2.ReadError("connection reset"),
    ],
    ids=["overloaded", "api_error", "rate_limit", "remote_protocol", "read_timeout", "read_error"],
)
def test_run_turn_mid_stream_failure_before_any_text_retries_and_succeeds(error):
    # Arrange
    client = FakeClient(FakeStream(fail_after=error()), _answer("Hi"))

    # Act
    events = _run(client)

    # Assert
    assert (events, len(client.requests)) == ([TextDelta("Hi"), Answer("Hi", truncated=False)], 2)


@pytest.mark.parametrize(
    ("streams", "code", "model_calls"),
    [
        (lambda: [FakeStream(fail_after=_mid_stream("overloaded_error")) for _ in range(3)], "assistant_busy", 3),
        (lambda: [FakeStream(fail_after=httpx2.ReadTimeout("x")) for _ in range(3)], "interrupted", 3),
        (lambda: [FakeStream(["partial"], fail_after=_mid_stream("overloaded_error"))], "assistant_busy", 1),
        (lambda: [FakeStream(["partial"], fail_after=httpx2.RemoteProtocolError("x"))], "interrupted", 1),
        (lambda: [FakeStream(fail_after=_mid_stream("invalid_request_error"))], "assistant_unavailable", 1),
        (
            lambda: [FakeStream(open_error=_status_error(anthropic.RateLimitError, 429, "rate_limit_error"))],
            "assistant_busy",
            1,
        ),
        (
            lambda: [FakeStream(open_error=_status_error(anthropic.OverloadedError, 529, "overloaded_error"))],
            "assistant_busy",
            1,
        ),
        (
            lambda: [FakeStream(open_error=_status_error(anthropic.InternalServerError, 500, "api_error"))],
            "assistant_busy",
            1,
        ),
        (lambda: [FakeStream(open_error=anthropic.APIConnectionError(request=REQUEST))], "assistant_busy", 1),
        (lambda: [FakeStream(open_error=anthropic.APITimeoutError(request=REQUEST))], "assistant_busy", 1),
        (
            lambda: [FakeStream(open_error=_status_error(anthropic.BadRequestError, 400, "invalid_request_error"))],
            "assistant_unavailable",
            1,
        ),
        (
            lambda: [FakeStream(open_error=_status_error(anthropic.AuthenticationError, 401, "authentication_error"))],
            "assistant_unavailable",
            1,
        ),
        (
            lambda: [FakeStream(open_error=_status_error(anthropic.NotFoundError, 404, "not_found_error"))],
            "assistant_unavailable",
            1,
        ),
        (
            lambda: [
                FakeStream(
                    final=_message(
                        "refusal", stop_details={"type": "refusal", "category": "cyber", "explanation": "no"}
                    )
                )
            ],
            "refused",
            1,
        ),
        (lambda: [FakeStream(final=_message("refusal"))], "refused", 1),
        (lambda: [FakeStream(final=_message(None, _tool_use()))], "interrupted", 1),
        (lambda: [FakeStream(final=_message("max_tokens", _tool_use()))], "interrupted", 1),
        (lambda: [FakeStream(final=_message("end_turn"))], "empty_answer", 1),
        (lambda: [FakeStream(final=_message("end_turn", _text("   ")))], "empty_answer", 1),
        (lambda: [FakeStream(final=_message("pause_turn"))], "assistant_unavailable", 1),
        (lambda: [FakeStream(final=_message("end_turn", _tool_use()))], "assistant_unavailable", 1),
        (lambda: [_tool_round() for _ in range(MAX_MODEL_CALLS)], "too_many_steps", MAX_MODEL_CALLS),
    ],
    ids=[
        "mid_stream_overloaded_retries_exhausted",
        "mid_stream_drop_retries_exhausted",
        "mid_stream_overloaded_after_text",
        "mid_stream_drop_after_text",
        "mid_stream_non_retryable",
        "open_rate_limit",
        "open_overloaded",
        "open_server_error",
        "open_connection_error",
        "open_timeout",
        "open_bad_request",
        "open_authentication",
        "open_not_found",
        "refusal_with_details",
        "refusal_without_details",
        "stream_closed_without_stop_reason",
        "max_tokens_with_truncated_tool_use",
        "end_turn_without_text",
        "end_turn_whitespace_only",
        "unexpected_pause_turn",
        "end_turn_with_tool_use",
        "tool_loop_never_ends",
    ],
)
def test_run_turn_failure_raises_chat_error(streams, code, model_calls):
    # Arrange
    client = FakeClient(*streams())

    # Act
    with pytest.raises(ChatError) as raised:
        _run(client)

    # Assert
    assert (raised.value.code, len(client.requests)) == (code, model_calls)


def test_run_turn_truncated_tool_use_is_never_executed(tool_runs):
    # Arrange
    client = FakeClient(FakeStream(final=_message("max_tokens", _tool_use())))

    # Act
    with pytest.raises(ChatError):
        _run(client)

    # Assert
    assert tool_runs == []


def test_run_turn_retries_back_off_exponentially_with_jitter(sleeps):
    # Arrange
    client = FakeClient(
        FakeStream(fail_after=_mid_stream("overloaded_error")),
        FakeStream(fail_after=_mid_stream("overloaded_error")),
        _answer(),
    )

    # Act
    _run(client)

    # Assert
    assert len(sleeps) == 2 and 0.375 <= sleeps[0] <= 0.5 and 0.75 <= sleeps[1] <= 1.0


@pytest.mark.parametrize(
    "stream",
    [
        lambda: FakeStream(open_error=_status_error(anthropic.OverloadedError, 529, "overloaded_error")),
        lambda: FakeStream(["partial"], fail_after=_mid_stream("overloaded_error")),
        lambda: FakeStream(fail_after=_mid_stream("invalid_request_error")),
    ],
    ids=["already_retried_by_sdk", "text_already_shown", "not_retryable"],
)
def test_run_turn_failure_that_is_not_retried_never_sleeps(sleeps, stream):
    # Arrange
    client = FakeClient(stream())

    # Act
    with pytest.raises(ChatError):
        _run(client)

    # Assert
    assert sleeps == []


def test_run_turn_database_error_in_tool_stops_without_another_model_call(monkeypatch):
    # Arrange
    _fail_tool(monkeypatch, ServerSelectionTimeoutError("connection refused"))
    client = FakeClient(_tool_round(), _answer())

    # Act
    with pytest.raises(ChatError) as raised:
        _run(client)

    # Assert
    assert (raised.value.code, len(client.requests)) == ("database_unavailable", 1)


@pytest.mark.parametrize(
    ("error", "expected_content"),
    [
        (ToolInputError("page_size: Input should be less than or equal to 25"),
         "page_size: Input should be less than or equal to 25"),
        (KeyError("bug"), TOOL_FAILURE_MESSAGE),
        (TypeError("bug"), TOOL_FAILURE_MESSAGE),
    ],
    ids=["invalid_input", "unexpected_key_error", "unexpected_type_error"],
)
def test_run_turn_tool_failure_returns_is_error_result_to_claude(monkeypatch, error, expected_content):
    # Arrange
    _fail_tool(monkeypatch, error)
    client = FakeClient(_tool_round(), _answer())

    # Act
    _run(client)

    # Assert
    assert client.requests[1]["messages"][-1]["content"] == [
        {"type": "tool_result", "tool_use_id": "toolu_1", "content": expected_content, "is_error": True}
    ]


def test_run_turn_successful_tool_sends_result_without_error_flag():
    # Arrange
    client = FakeClient(_tool_round(), _answer())

    # Act
    _run(client)

    # Assert
    assert client.requests[1]["messages"][-1]["content"] == [
        {"type": "tool_result", "tool_use_id": "toolu_1", "content": TOOL_OUTPUT}
    ]


def test_run_turn_parallel_tool_calls_are_answered_in_one_message():
    # Arrange
    client = FakeClient(
        _tool_round(_tool_use("toolu_1", "search_products"), _tool_use("toolu_2", "get_product_facets")),
        _answer(),
    )

    # Act
    _run(client)

    # Assert
    assistant, user = client.requests[1]["messages"][-2:]
    assert (
        assistant["role"],
        [block["id"] for block in assistant["content"]],
        user["role"],
        [result["tool_use_id"] for result in user["content"]],
    ) == ("assistant", ["toolu_1", "toolu_2"], "user", ["toolu_1", "toolu_2"])


def test_run_turn_does_not_mutate_history():
    # Arrange
    history = [{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "reply"}]
    snapshot = copy.deepcopy(history)
    client = FakeClient(_tool_round(), _answer())

    # Act
    list(run_turn(client, None, [], history, "question"))

    # Assert
    assert history == snapshot


def test_run_turn_request_pins_model_and_cache_breakpoints():
    # Arrange
    client = FakeClient(_answer())

    # Act
    _run(client, history=[{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "reply"}])

    # Assert
    request = client.requests[0]
    assert (
        request["model"],
        request["system"][0]["cache_control"],
        request["cache_control"],
        request["messages"][-1],
        "thinking" in request,
    ) == (MODEL, {"type": "ephemeral"}, {"type": "ephemeral"}, {"role": "user", "content": "question"}, False)


def test_run_turn_refusal_is_logged_with_its_category(caplog):
    # Arrange
    client = FakeClient(
        FakeStream(final=_message("refusal", stop_details={"type": "refusal", "category": "cyber", "explanation": "no"}))
    )

    # Act
    with caplog.at_level(logging.WARNING, logger=chat.__name__), pytest.raises(ChatError):
        _run(client)

    # Assert
    assert "category=cyber" in caplog.text


def _run_traced(client, steps):
    try:
        list(run_turn(client, None, [], [], "question", steps=steps))
    except ChatError:
        pass


@pytest.mark.parametrize(
    ("streams", "tool_error", "expected"),
    [
        (
            lambda: [_tool_round(), _answer()],
            None,
            [("model.call", "ok"), ("tool search_products", "ok"), ("model.call", "ok")],
        ),
        (
            lambda: [FakeStream(fail_after=_mid_stream("overloaded_error")), _answer()],
            None,
            [("model.call", "retry"), ("model.call", "ok")],
        ),
        (
            lambda: [_tool_round(), _answer()],
            ToolInputError("page_size: too big"),
            [("model.call", "ok"), ("tool search_products", "is_error"), ("model.call", "ok")],
        ),
        (
            lambda: [_tool_round(), _answer()],
            KeyError("bug"),
            [("model.call", "ok"), ("tool search_products", "is_error"), ("model.call", "ok")],
        ),
        (
            lambda: [_tool_round()],
            ServerSelectionTimeoutError("down"),
            [("model.call", "ok"), ("tool search_products", "FAIL")],
        ),
        (
            lambda: [FakeStream(open_error=_status_error(anthropic.OverloadedError, 529, "overloaded_error"))],
            None,
            [("model.call", "FAIL")],
        ),
        (
            lambda: [FakeStream(fail_after=_mid_stream("invalid_request_error"))],
            None,
            [("model.call", "FAIL")],
        ),
    ],
    ids=["tool_turn", "retried_stream", "tool_input_error", "tool_bug", "database_down",
         "open_overloaded", "mid_stream_rejected"],
)
def test_run_turn_trace_records_each_step_with_its_status(monkeypatch, streams, tool_error, expected):
    # Arrange
    if tool_error is not None:
        _fail_tool(monkeypatch, tool_error)
    steps = []

    # Act
    _run_traced(FakeClient(*streams()), steps)

    # Assert
    assert [(step.name, step.status) for step in steps] == expected


@pytest.mark.parametrize(
    ("streams", "outcome"),
    [
        (lambda: [_answer()], "done"),
        (lambda: [FakeStream(open_error=anthropic.APIConnectionError(request=REQUEST))], "assistant_busy"),
        (lambda: [FakeStream(final=_message("refusal"))], "refused"),
    ],
    ids=["done", "busy", "refused"],
)
def test_run_turn_logs_one_trace_record_with_steps_and_outcome(caplog, streams, outcome):
    # Arrange
    steps = []

    # Act
    with caplog.at_level(logging.INFO, logger=chat.__name__):
        _run_traced(FakeClient(*streams()), steps)

    # Assert
    records = [record for record in caplog.records if hasattr(record, "run_id")]
    assert [(record.outcome, record.trace) for record in records] == [(outcome, steps)]


def test_run_turn_trace_text_localizes_the_failing_step(caplog):
    # Arrange
    client = FakeClient(FakeStream(open_error=_status_error(anthropic.OverloadedError, 529, "overloaded_error")))

    # Act
    with caplog.at_level(logging.INFO, logger=chat.__name__):
        _run_traced(client, [])

    # Assert
    trace = next(record.getMessage() for record in caplog.records if hasattr(record, "run_id"))
    assert "model.call" in trace and "FAIL" in trace and "outcome: assistant_busy" in trace


def test_run_turn_model_call_step_carries_token_usage():
    # Arrange
    steps = []

    # Act
    _run_traced(FakeClient(_answer()), steps)

    # Assert
    assert steps[0].usage == {
        "input_tokens": 1,
        "output_tokens": 1,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
