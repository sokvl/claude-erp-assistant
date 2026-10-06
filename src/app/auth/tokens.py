import base64
import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.auth.roles import Principal, Role
from app.auth.signer import TokenSigner
from app.limits import ACCESS_TOKEN_MINUTES

ISSUER = "invoices-app"
AUDIENCE = "invoices-api"
ALGORITHM = "EdDSA"
REQUIRED_CLAIMS = ["exp", "iat", "sub", "iss", "aud"]


class InvalidToken(Exception):
    pass


def issue_access_token(principal: Principal, signer: TokenSigner, now: datetime) -> str:
    kid = signer.current_kid()
    header = {"alg": ALGORITHM, "typ": "JWT", "kid": kid}
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": principal.username,
        "role": str(principal.role),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ACCESS_TOKEN_MINUTES)).timestamp()),
        "jti": uuid4().hex,
    }
    signing_input = f"{_encode(_json(header))}.{_encode(_json(claims))}"
    return f"{signing_input}.{_encode(signer.sign(kid, signing_input.encode()))}"


def verify_access_token(token: str, keys: Mapping[str, Ed25519PublicKey]) -> Principal:
    try:
        key = keys[jwt.get_unverified_header(token).get("kid")]
        claims = jwt.decode(
            token,
            key,
            algorithms=[ALGORITHM],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": REQUIRED_CLAIMS},
        )
        return Principal(claims["sub"], Role(claims["role"]))
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise InvalidToken(str(exc)) from exc


def _json(value: dict) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode()


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
