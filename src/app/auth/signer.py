from collections.abc import Mapping
from typing import Protocol

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


class TokenSigner(Protocol):
    def current_kid(self) -> str: ...

    def sign(self, kid: str, message: bytes) -> bytes: ...

    def public_keys(self) -> Mapping[str, Ed25519PublicKey]: ...


class LocalSigner:
    def __init__(self, private_key: Ed25519PrivateKey | None = None, kid: str = "local:v1") -> None:
        self._key = private_key or Ed25519PrivateKey.generate()
        self._kid = kid

    def current_kid(self) -> str:
        return self._kid

    def sign(self, kid: str, message: bytes) -> bytes:
        if kid != self._kid:
            raise ValueError(f"Unknown signing key {kid!r}")
        return self._key.sign(message)

    def public_keys(self) -> Mapping[str, Ed25519PublicKey]:
        return {self._kid: self._key.public_key()}
