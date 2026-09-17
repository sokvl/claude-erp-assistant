import pytest

from app.assistant import memory
from app.assistant.memory import ConversationStore


def _turn(question, answer):
    return [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]


def test_conversation_store_new_conversation_has_empty_history():
    # Arrange
    store = ConversationStore()

    # Act
    history = store.history(store.create())

    # Assert
    assert history == []


def test_conversation_store_unknown_conversation_has_no_history():
    # Arrange / Act
    history = ConversationStore().history("never-created")

    # Assert
    assert history is None


def test_conversation_store_append_turn_saves_question_and_answer():
    # Arrange
    store = ConversationStore()
    conversation_id = store.create()

    # Act
    saved = store.append_turn(conversation_id, 0, "question", "answer")

    # Assert
    assert (saved, store.history(conversation_id)) == (True, _turn("question", "answer"))


@pytest.mark.parametrize(
    ("known", "expected_length"),
    [(True, 2), (True, -1), (False, 0)],
    ids=["stale_length", "negative_length", "unknown_conversation"],
)
def test_conversation_store_append_turn_rejects_stale_or_unknown_conversation(known, expected_length):
    # Arrange
    store = ConversationStore()
    conversation_id = store.create() if known else "never-created"

    # Act
    saved = store.append_turn(conversation_id, expected_length, "question", "answer")

    # Assert
    assert (saved, store.history(conversation_id)) == (False, [] if known else None)


def test_conversation_store_turn_cap_drops_oldest_turns(monkeypatch):
    # Arrange
    monkeypatch.setattr(memory, "MAX_MESSAGES", 4)
    store = ConversationStore()
    conversation_id = store.create()

    # Act
    for number in range(3):
        store.append_turn(conversation_id, len(store.history(conversation_id)), f"q{number}", f"a{number}")

    # Assert
    assert store.history(conversation_id) == _turn("q1", "a1") + _turn("q2", "a2")


def test_conversation_store_evicts_least_recently_used_conversation(monkeypatch):
    # Arrange
    monkeypatch.setattr(memory, "MAX_CONVERSATIONS", 2)
    store = ConversationStore()
    first, second = store.create(), store.create()
    store.history(first)

    # Act
    third = store.create()

    # Assert
    assert (store.history(first), store.history(second), store.history(third)) == ([], None, [])


def test_conversation_store_history_is_a_copy():
    # Arrange
    store = ConversationStore()
    conversation_id = store.create()
    store.append_turn(conversation_id, 0, "question", "answer")

    # Act
    store.history(conversation_id).clear()

    # Assert
    assert store.history(conversation_id) == _turn("question", "answer")
