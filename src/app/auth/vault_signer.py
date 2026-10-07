import base64
import math
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

import hvac.exceptions
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.limits import MIN_SIGNING_KEY_RELOAD_SECONDS, SIGNING_KEY_CACHE_SECONDS

TRANSIT_KEY = "app-jwt"


class VaultTransitSigner:
    def __init__(
        self,
        client: Callable[[], Any],
        reconnect: Callable[[], None],
        key_name: str = TRANSIT_KEY,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._reconnect = reconnect
        self._name = key_name
        self._clock = clock
        self._lock = threading.Lock()
        self._key: dict[str, Any] | None = None
        self._loaded_at = -math.inf

    def current_kid(self) -> str:
        return f"{self._name}:v{self._read_key()['latest_version']}"

    def sign(self, kid: str, message: bytes) -> bytes:
        version = int(kid.rsplit(":v", 1)[1])
        response = self._call(
            lambda client: client.secrets.transit.sign_data(
                self._name,
                hash_input=base64.b64encode(message).decode(),
                key_version=version,
                marshaling_algorithm="jws",
            )
        )
        return _decode(response["data"]["signature"].split(":", 2)[2])

    def public_keys(self) -> Mapping[str, Ed25519PublicKey]:
        return _KeySet(self)

    def verifying_keys(self, reload: bool = False) -> dict[str, Ed25519PublicKey]:
        key = self._read_key(reload)
        return {
            f"{self._name}:v{version}": Ed25519PublicKey.from_public_bytes(base64.b64decode(entry["public_key"]))
            for version, entry in key["keys"].items()
            if int(version) >= key["min_decryption_version"]
        }

    def _read_key(self, reload: bool = False) -> dict[str, Any]:
        with self._lock:
            age = self._clock() - self._loaded_at
            if self._key is None or age >= SIGNING_KEY_CACHE_SECONDS or (reload and age >= MIN_SIGNING_KEY_RELOAD_SECONDS):
                self._key = self._call(lambda client: client.secrets.transit.read_key(self._name)["data"])
                self._loaded_at = self._clock()
            return self._key

    def _call(self, request: Callable[[Any], Any]) -> Any:
        try:
            return request(self._client())
        except hvac.exceptions.Forbidden:
            self._reconnect()
            return request(self._client())


class _KeySet(dict):
    def __init__(self, signer: VaultTransitSigner) -> None:
        super().__init__(signer.verifying_keys())
        self._signer = signer

    def __missing__(self, kid: str) -> Ed25519PublicKey:
        self.update(self._signer.verifying_keys(reload=True))
        if kid not in self:
            raise KeyError(kid)
        return self[kid]


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
