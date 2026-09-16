import pytest
from fastapi import HTTPException

from app.config import API_KEY
from app.security import require_api_key


def test_require_api_key_valid_key_returns_none():
    # Arrange / Act
    result = require_api_key(API_KEY)

    # Assert
    assert result is None


@pytest.mark.parametrize(
    "key",
    ["", "wrong", API_KEY + "x", API_KEY[:-1], "ü", "ü" * len(API_KEY), "\x00"],
    ids=["empty", "wrong", "too_long", "truncated", "non_ascii", "non_ascii_same_length", "null_byte"],
)
def test_require_api_key_invalid_key_raises_401_with_challenge(key):
    # Arrange / Act
    with pytest.raises(HTTPException) as raised:
        require_api_key(key)

    # Assert
    assert (raised.value.status_code, raised.value.headers) == (401, {"WWW-Authenticate": "APIKey"})
