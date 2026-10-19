from app.db import build_transaction_runner, get_transaction_runner


class Session:
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        self.events.append("session opened")
        return self

    def __exit__(self, *exc):
        self.events.append("session closed")

    def with_transaction(self, callback):
        self.events.append("transaction started")
        result = callback(self)
        self.events.append("transaction committed")
        return result


class Client:
    def __init__(self):
        self.events = []

    def start_session(self):
        return Session(self.events)


def test_build_transaction_runner_runs_the_callback_inside_a_session_and_returns_its_result():
    # Arrange
    client = Client()
    seen = []

    # Act
    result = build_transaction_runner(client)(lambda session: seen.append(session) or "closed")

    # Assert
    assert (result, len(seen)) == ("closed", 1)
    assert client.events == ["session opened", "transaction started", "transaction committed", "session closed"]


def test_get_transaction_runner_returns_the_application_runner():
    # Arrange / Act / Assert
    assert callable(get_transaction_runner())
