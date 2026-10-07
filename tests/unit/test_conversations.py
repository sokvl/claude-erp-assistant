from datetime import UTC, datetime, timedelta

import pytest
from memory_collection import MemoryCollection

from app.assistant import conversations
from app.assistant.conversations import ConversationStore
from app.assistant.profiles import AssistantName
from app.limits import CONVERSATION_TTL_DAYS, MAX_CONVERSATION_TITLE_LENGTH

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def _turn(question, answer):
    return [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]


@pytest.fixture
def collection():
    return MemoryCollection()


@pytest.fixture
def store(collection):
    return ConversationStore(collection, AssistantName.ANALYST)


def _append(store, conversation_id, question, answer, chart_ids=(), now=NOW):
    turns = store.history(conversation_id, "anna").turns
    return store.append_turn(conversation_id, turns, question, answer, list(chart_ids), now)


def test_create_stores_an_empty_conversation_titled_by_the_first_question(store, collection):
    # Arrange / Act
    conversation_id = store.create("anna", "  Top customers in Q1?  ", NOW)

    # Assert
    stored = collection.documents[conversation_id]
    assert (stored["username"], stored["assistant"], stored["title"], stored["turns"]) == (
        "anna", "analyst", "Top customers in Q1?", 0,
    )
    assert stored["expiresAt"] == NOW + timedelta(days=CONVERSATION_TTL_DAYS)
    assert store.history(conversation_id, "anna").messages == []


def test_create_long_question_is_cut_to_the_title_limit(store, collection):
    # Arrange / Act
    conversation_id = store.create("anna", "x" * (MAX_CONVERSATION_TITLE_LENGTH + 10), NOW)

    # Assert
    assert len(collection.documents[conversation_id]["title"]) == MAX_CONVERSATION_TITLE_LENGTH


# A conversation id travels in the request body, so knowing one is not enough: another
# user's id, or one opened with the other assistant, reads as unknown (404).
@pytest.mark.parametrize(
    ("owner", "assistant"),
    [("piotr", AssistantName.ANALYST), ("anna", AssistantName.ADVISOR)],
    ids=["other_owner", "other_assistant"],
)
def test_history_of_a_conversation_the_caller_cannot_use_is_none(store, collection, owner, assistant):
    # Arrange
    conversation_id = store.create("anna", "question", NOW)

    # Act
    history = ConversationStore(collection, assistant).history(conversation_id, owner)

    # Assert
    assert history is None


def test_append_turn_stores_chart_ids_but_history_sends_only_role_and_content(store, collection):
    # Arrange
    conversation_id = store.create("anna", "question", NOW)

    # Act
    saved = _append(store, conversation_id, "question", "answer", ["chart-1"])

    # Assert
    assert saved is True
    assert collection.documents[conversation_id]["messages"][1]["chartIds"] == ["chart-1"]
    assert store.history(conversation_id, "anna").messages == _turn("question", "answer")


def test_append_turn_moves_the_expiry_with_the_last_message(store, collection):
    # Arrange
    conversation_id = store.create("anna", "question", NOW)
    later = NOW + timedelta(days=10)

    # Act
    _append(store, conversation_id, "question", "answer", now=later)

    # Assert
    stored = collection.documents[conversation_id]
    assert (stored["lastMessageAt"], stored["expiresAt"]) == (later, later + timedelta(days=CONVERSATION_TTL_DAYS))


# Two tabs answering the same conversation: the second save sees a turn count that
# moved on and is refused, so its answer cannot silently overwrite the first.
@pytest.mark.parametrize("expected_turns", [1, -1], ids=["stale_count", "negative_count"])
def test_append_turn_with_a_stale_turn_count_is_refused(store, collection, expected_turns):
    # Arrange
    conversation_id = store.create("anna", "question", NOW)

    # Act
    saved = store.append_turn(conversation_id, expected_turns, "question", "answer", [], NOW)

    # Assert
    assert (saved, collection.documents[conversation_id]["turns"]) == (False, 0)


def test_append_turn_unknown_conversation_is_refused(store):
    # Arrange / Act
    saved = store.append_turn("never-created", 0, "question", "answer", [], NOW)

    # Assert
    assert saved is False


def test_long_conversation_keeps_the_stored_cap_and_sends_the_model_only_recent_turns(monkeypatch, store, collection):
    # Arrange
    monkeypatch.setattr(conversations, "STORED_MESSAGES", 6)
    monkeypatch.setattr(conversations, "MODEL_MESSAGES", 4)
    conversation_id = store.create("anna", "q0", NOW)

    # Act
    for number in range(4):
        _append(store, conversation_id, f"q{number}", f"a{number}")

    # Assert
    stored = collection.documents[conversation_id]
    assert (stored["turns"], [message["content"] for message in stored["messages"]]) == (
        4, ["q1", "a1", "q2", "a2", "q3", "a3"],
    )
    assert store.history(conversation_id, "anna") == conversations.History(4, _turn("q2", "a2") + _turn("q3", "a3"))
