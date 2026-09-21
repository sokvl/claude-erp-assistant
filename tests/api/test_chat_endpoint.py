import json

import pytest
from fastapi.testclient import TestClient

from app.assistant.chat import ERROR_MESSAGES, Answer, ChartRef, ChatError, TextDelta, ToolCall, TraceStep
from app.assistant import memory
from app.assistant.memory import ConversationStore
from app.assistant.profiles import AssistantName
from app.assistant.usage import USAGE_COLLECTION
from app.config import API_KEY
from app.db import get_database
from app.main import app
from app.routers import chat as chat_router
from app.routers.chat import assistant_client, chat_store, chat_tools

AUTH = {"X-API-Key": API_KEY}
MODEL_CALL_USAGE = {"input_tokens": 1200, "output_tokens": 80, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}


class UsageCollection:
    def __init__(self):
        self.documents = []

    def insert_one(self, document):
        self.documents.append(document)


class ConflictingStore(ConversationStore):
    def append_turn(self, *args, **kwargs):
        return False


def _scripted_turn(*items, seen_history=None, seen_turns=None, seen_conversations=None):
    def fake_run_turn(client, db, profile, tools, history, user_text, steps, conversation_id=None):
        if seen_conversations is not None:
            seen_conversations.append(conversation_id)
        if seen_history is not None:
            seen_history.append(list(history))
        if seen_turns is not None:
            seen_turns.append((profile.name, [tool["name"] for tool in tools]))
        steps.append(TraceStep("model.call", "ok", 5, "stop=end_turn", MODEL_CALL_USAGE))
        for item in items:
            if isinstance(item, BaseException):
                raise item
            yield item

    return fake_run_turn


def _events(response):
    events = []
    for block in response.text.strip().split("\n\n"):
        lines = [line for line in block.split("\n") if line and not line.startswith(":")]
        if not lines:
            continue
        name = next(line.removeprefix("event: ") for line in lines if line.startswith("event: "))
        data = json.loads(next(line.removeprefix("data: ") for line in lines if line.startswith("data: ")))
        events.append((name, data))
    return events


@pytest.fixture
def usage():
    return UsageCollection()


@pytest.fixture
def store(usage):
    fresh = ConversationStore()
    app.dependency_overrides[get_database] = lambda: {USAGE_COLLECTION: usage}
    app.dependency_overrides[chat_store] = lambda: fresh
    app.dependency_overrides[assistant_client] = lambda: object()
    app.dependency_overrides[chat_tools] = lambda: []
    yield fresh
    app.dependency_overrides.clear()


@pytest.fixture
def client(store):
    return TestClient(app)


def test_chat_successful_turn_streams_events_in_order(client, monkeypatch):
    # Arrange
    monkeypatch.setattr(
        chat_router,
        "run_turn",
        _scripted_turn(ToolCall("search_products"), TextDelta("Hi"), Answer("Hi", truncated=False)),
    )

    # Act
    events = _events(client.post("/chat", json={"message": "question"}, headers=AUTH))

    # Assert
    assert [name for name, _ in events] == ["conversation", "tool", "text", "done"]


def test_chat_successful_turn_saves_only_question_and_answer(client, store, monkeypatch):
    # Arrange
    monkeypatch.setattr(
        chat_router,
        "run_turn",
        _scripted_turn(ToolCall("search_products"), TextDelta("Hi"), Answer("Hi", truncated=False)),
    )

    # Act
    events = _events(client.post("/chat", json={"message": "question"}, headers=AUTH))

    # Assert
    assert store.history(events[0][1]["conversation_id"]) == [
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "Hi"},
    ]


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (ChatError("assistant_busy"), "assistant_busy"),
        (ValueError("Unable to parse tool parameter JSON from model"), "unexpected_error"),
    ],
    ids=["chat_error", "unexpected_sdk_error"],
)
def test_chat_failed_turn_ends_with_error_event(client, monkeypatch, failure, code):
    # Arrange
    monkeypatch.setattr(chat_router, "run_turn", _scripted_turn(TextDelta("partial"), failure))

    # Act
    events = _events(client.post("/chat", json={"message": "question"}, headers=AUTH))

    # Assert
    assert events[-1] == ("error", {"code": code, "message": ERROR_MESSAGES[code]})


@pytest.mark.parametrize(
    "failure",
    [ChatError("assistant_busy"), KeyError("bug")],
    ids=["chat_error", "unexpected_bug"],
)
def test_chat_failed_turn_does_not_save_history(client, store, monkeypatch, failure):
    # Arrange
    monkeypatch.setattr(chat_router, "run_turn", _scripted_turn(TextDelta("partial"), failure))

    # Act
    events = _events(client.post("/chat", json={"message": "question"}, headers=AUTH))

    # Assert
    assert store.history(events[0][1]["conversation_id"]) == []


def test_chat_history_changed_during_turn_reports_conflict(client, monkeypatch):
    # Arrange
    app.dependency_overrides[chat_store] = lambda: ConflictingStore()
    monkeypatch.setattr(chat_router, "run_turn", _scripted_turn(Answer("Hi", truncated=False)))

    # Act
    events = _events(client.post("/chat", json={"message": "question"}, headers=AUTH))

    # Assert
    assert events[-1] == ("error", {"code": "conflict", "message": ERROR_MESSAGES["conflict"]})


@pytest.mark.parametrize(
    ("items", "outcome"),
    [
        ((Answer("Hi", truncated=False),), "done"),
        ((TextDelta("partial"), ChatError("assistant_busy")), "assistant_busy"),
        ((TextDelta("partial"), KeyError("bug")), "unexpected_error"),
    ],
    ids=["answered", "chat_error", "unexpected_bug"],
)
def test_chat_any_turn_records_token_usage_with_outcome(client, usage, monkeypatch, items, outcome):
    # Arrange
    monkeypatch.setattr(chat_router, "run_turn", _scripted_turn(*items))

    # Act
    events = _events(client.post("/chat", json={"message": "question"}, headers=AUTH))

    # Assert
    [document] = usage.documents
    assert (document["conversationId"], document["outcome"], document["modelCalls"], document["tokens"]) == (
        events[0][1]["conversation_id"], outcome, 1, MODEL_CALL_USAGE,
    )


def test_chat_existing_conversation_passes_saved_history_to_turn(client, monkeypatch):
    # Arrange
    monkeypatch.setattr(chat_router, "run_turn", _scripted_turn(Answer("first answer", truncated=False)))
    first = _events(client.post("/chat", json={"message": "first question"}, headers=AUTH))
    conversation_id = first[0][1]["conversation_id"]
    seen_history = []
    monkeypatch.setattr(
        chat_router, "run_turn", _scripted_turn(Answer("second answer", truncated=False), seen_history=seen_history)
    )

    # Act
    client.post("/chat", json={"message": "follow-up", "conversation_id": conversation_id}, headers=AUTH)

    # Assert
    assert seen_history == [[
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer"},
    ]]


@pytest.mark.parametrize(
    ("headers", "body", "status"),
    [
        (AUTH, {"message": ""}, 422),
        (AUTH, {"message": "x" * 4001}, 422),
        (AUTH, {"message": "question", "extra": 1}, 422),
        (AUTH, {}, 422),
        (AUTH, {"message": "question", "conversation_id": "unknown"}, 404),
        (AUTH, {"message": "question", "assistant": "oracle"}, 422),
    ],
    ids=["empty_message", "message_too_long",
         "unknown_field", "missing_message", "unknown_conversation", "unknown_assistant"],
)
def test_chat_invalid_request_is_rejected_before_streaming(client, monkeypatch, headers, body, status):
    # Arrange
    monkeypatch.setattr(chat_router, "run_turn", _scripted_turn(Answer("never", truncated=False)))

    # Act
    response = client.post("/chat", json=body, headers=headers)

    # Assert
    assert response.status_code == status


def test_chat_without_anthropic_credentials_returns_503(client, monkeypatch):
    # Arrange
    app.dependency_overrides.pop(assistant_client)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)

    # Act
    response = client.post("/chat", json={"message": "question"}, headers=AUTH)

    # Assert
    assert response.status_code == 503


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"message": "question"}, (AssistantName.ADVISOR, ["get_product_facets", "search_products"])),
        ({"message": "question", "assistant": "analyst"}, (AssistantName.ANALYST, ["analyze_invoices", "chart_invoices", "list_invoices"])),
    ],
    ids=["default_is_advisor", "analyst"],
)
def test_chat_turn_runs_with_the_selected_assistants_profile_and_tools(client, monkeypatch, body, expected):
    # Arrange
    app.dependency_overrides.pop(chat_tools)
    seen_turns = []
    monkeypatch.setattr(chat_router, "run_turn", _scripted_turn(Answer("Hi", truncated=False), seen_turns=seen_turns))

    # Act
    client.post("/chat", json=body, headers=AUTH)

    # Assert
    assert seen_turns == [expected]


def test_chat_analyst_turn_records_usage_under_the_analyst(client, usage, monkeypatch):
    # Arrange
    monkeypatch.setattr(chat_router, "run_turn", _scripted_turn(Answer("Hi", truncated=False)))

    # Act
    client.post("/chat", json={"message": "question", "assistant": "analyst"}, headers=AUTH)

    # Assert
    [document] = usage.documents
    assert (document["assistant"], document["model"]) == ("analyst", "claude-sonnet-5")


def test_chat_conversation_of_the_other_assistant_is_unknown(client, monkeypatch):
    # Arrange: real per-assistant stores, so advisor history can never reach the analyst's context or vice versa
    app.dependency_overrides.pop(chat_store)
    monkeypatch.setattr(memory, "stores", {assistant: ConversationStore() for assistant in AssistantName})
    monkeypatch.setattr(chat_router, "run_turn", _scripted_turn(Answer("Hi", truncated=False)))
    advisor_events = _events(client.post("/chat", json={"message": "question"}, headers=AUTH))
    conversation_id = advisor_events[0][1]["conversation_id"]

    # Act
    response = client.post(
        "/chat",
        json={"message": "follow-up", "conversation_id": conversation_id, "assistant": "analyst"},
        headers=AUTH,
    )

    # Assert
    assert response.status_code == 404


# The page needs the id to fetch the image with the API key; the chart itself is
# never written to conversation memory, only the question and the answer text.
def test_chat_turn_with_a_chart_streams_its_id_and_keeps_it_out_of_memory(client, store, monkeypatch):
    # Arrange
    monkeypatch.setattr(
        chat_router,
        "run_turn",
        _scripted_turn(
            ToolCall("chart_invoices"),
            ChartRef("chart-1"),
            TextDelta("Revenue rose."),
            Answer("Revenue rose.", truncated=False),
        ),
    )

    # Act
    events = _events(client.post("/chat", json={"message": "trend", "assistant": "analyst"}, headers=AUTH))

    # Assert
    assert [name for name, _ in events] == ["conversation", "tool", "chart", "text", "done"]
    assert dict(events)["chart"] == {"chart_id": "chart-1"}
    assert store.history(events[0][1]["conversation_id"]) == [
        {"role": "user", "content": "trend"},
        {"role": "assistant", "content": "Revenue rose."},
    ]


def test_chat_turn_passes_the_conversation_id_to_the_agent_loop(client, monkeypatch):
    # Arrange
    seen = []
    monkeypatch.setattr(
        chat_router,
        "run_turn",
        _scripted_turn(Answer("Hi", truncated=False), seen_conversations=seen),
    )

    # Act
    events = _events(client.post("/chat", json={"message": "question"}, headers=AUTH))

    # Assert
    assert seen == [events[0][1]["conversation_id"]]
