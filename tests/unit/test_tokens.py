import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.auth.roles import Principal, Role
from app.auth.signer import LocalSigner
from app.auth.tokens import AUDIENCE, ISSUER, InvalidToken, issue_access_token, verify_access_token
from app.limits import ACCESS_TOKEN_MINUTES

MANAGER = Principal("anna", Role.MANAGER)


def _claims(token):
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def _forge(signer, claims, kid="local:v1"):
    key = signer._key
    return jwt.encode(claims, key, algorithm="EdDSA", headers={"kid": kid})


def _valid_claims(**overrides):
    now = datetime.now(UTC)
    return {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "anna",
        "role": "manager",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
    } | overrides


def test_issue_access_token_round_trips_to_the_same_principal():
    # Arrange
    signer = LocalSigner()

    # Act
    token = issue_access_token(MANAGER, signer, datetime.now(UTC))

    # Assert
    assert verify_access_token(token, signer.public_keys()) == MANAGER


def test_issue_access_token_expires_after_the_access_window():
    # Arrange
    now = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)

    # Act
    claims = _claims(issue_access_token(MANAGER, LocalSigner(), now))

    # Assert
    assert claims["exp"] - claims["iat"] == ACCESS_TOKEN_MINUTES * 60
    assert (claims["iss"], claims["aud"], claims["sub"], claims["role"]) == (ISSUER, AUDIENCE, "anna", "manager")


# After a key rotation the old key still verifies the tokens it signed, so nobody is
# logged out; the old kid is dropped from the key set only once its tokens expired.
def test_verify_access_token_signed_by_a_previous_key_still_in_the_set_verifies():
    # Arrange
    old, new = LocalSigner(kid="vault:v1"), LocalSigner(kid="vault:v2")
    token = issue_access_token(MANAGER, old, datetime.now(UTC))

    # Act
    principal = verify_access_token(token, {**old.public_keys(), **new.public_keys()})

    # Assert
    assert principal == MANAGER


def _alg_none(signer):
    header = base64.urlsafe_b64encode(b'{"alg":"none","kid":"local:v1"}').rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps(_valid_claims()).encode()).rstrip(b"=").decode()
    return f"{header}.{body}."


def _hs256_with_public_key(signer):
    public = signer.public_keys()["local:v1"].public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    header = _segment(json.dumps({"alg": "HS256", "kid": "local:v1"}).encode())
    signing_input = f"{header}.{_segment(json.dumps(_valid_claims()).encode())}"
    signature = hmac.new(public, signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_segment(signature)}"


def _segment(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _tampered(signer):
    header, _, signature = _forge(signer, _valid_claims()).split(".")
    body = base64.urlsafe_b64encode(json.dumps(_valid_claims(role="admin")).encode()).rstrip(b"=").decode()
    return f"{header}.{body}.{signature}"


@pytest.mark.parametrize(
    "make_token",
    [
        lambda s: _forge(s, _valid_claims(exp=int((datetime.now(UTC) - timedelta(minutes=1)).timestamp()))),
        lambda s: _forge(s, _valid_claims(aud="another-api")),
        lambda s: _forge(s, _valid_claims(iss="someone-else")),
        lambda s: _forge(s, _valid_claims(), kid="vault:v9"),
        lambda s: _forge(s, {key: value for key, value in _valid_claims().items() if key != "exp"}),
        lambda s: _forge(s, _valid_claims(role="owner")),
        lambda s: _forge(s, {key: value for key, value in _valid_claims().items() if key != "role"}),
        lambda s: jwt.encode(_valid_claims(), Ed25519PrivateKey.generate(), algorithm="EdDSA", headers={"kid": "local:v1"}),
        _alg_none,
        _hs256_with_public_key,
        _tampered,
        lambda s: "not-a-token",
    ],
    ids=["expired", "wrong_audience", "wrong_issuer", "unknown_kid", "no_expiry", "unknown_role",
         "no_role", "foreign_key", "alg_none", "hs256_with_public_key", "tampered_payload", "garbage"],
)
def test_verify_access_token_rejected_token_raises_invalid_token(make_token):
    # Arrange
    signer = LocalSigner()
    token = make_token(signer)

    # Act / Assert
    with pytest.raises(InvalidToken):
        verify_access_token(token, signer.public_keys())


def test_local_signer_other_kid_raises_value_error():
    # Arrange
    signer = LocalSigner(kid="local:v1")

    # Act / Assert
    with pytest.raises(ValueError, match="Unknown signing key"):
        signer.sign("local:v2", b"message")
