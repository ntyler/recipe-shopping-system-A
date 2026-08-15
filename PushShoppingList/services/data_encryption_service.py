"""Authenticated encryption for durable application secrets.

Encryption keys are deliberately supplied by the environment or by an injected
test adapter.  Database rows contain the key identifier and an AES-GCM envelope,
never the key itself.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Mapping, Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


DATA_ENCRYPTION_KEY_ENV = "SHOPPING_APP_DATA_ENCRYPTION_KEY"
DATA_ENCRYPTION_KEY_ID_ENV = "SHOPPING_APP_DATA_ENCRYPTION_KEY_ID"
AES_GCM_ALGORITHM = "AES-256-GCM"


class DataEncryptionError(ValueError):
    """Raised when application secret encryption cannot be used safely."""


class SecretEncryptor(Protocol):
    """Narrow migration/runtime boundary for recoverable secrets."""

    @property
    def key_id(self) -> str: ...

    def encrypt_json(self, value: object, *, associated_data: str) -> str: ...

    def decrypt_json(self, envelope_json: str, *, associated_data: str) -> object: ...


@dataclass(frozen=True)
class EncryptedEnvelope:
    algorithm: str
    key_id: str
    nonce: str
    ciphertext: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "algorithm": self.algorithm,
                "ciphertext": self.ciphertext,
                "key_id": self.key_id,
                "nonce": self.nonce,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, value: str) -> "EncryptedEnvelope":
        try:
            payload = json.loads(str(value or ""))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise DataEncryptionError("Encrypted secret envelope is not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise DataEncryptionError("Encrypted secret envelope must be a JSON object.")
        required = ("algorithm", "key_id", "nonce", "ciphertext")
        fields = {name: str(payload.get(name) or "").strip() for name in required}
        if any(not fields[name] for name in required):
            raise DataEncryptionError("Encrypted secret envelope is missing required fields.")
        return cls(**fields)


def _decode_key(value: str) -> bytes:
    encoded = str(value or "").strip()
    if not encoded:
        raise DataEncryptionError(
            f"{DATA_ENCRYPTION_KEY_ENV} is required before recoverable secrets can be migrated."
        )
    padding = "=" * (-len(encoded) % 4)
    try:
        key = base64.urlsafe_b64decode(encoded + padding)
    except (ValueError, TypeError) as exc:
        raise DataEncryptionError(
            f"{DATA_ENCRYPTION_KEY_ENV} must be URL-safe base64."
        ) from exc
    if len(key) != 32:
        raise DataEncryptionError(
            f"{DATA_ENCRYPTION_KEY_ENV} must decode to exactly 32 bytes."
        )
    return key


def _decode_envelope_bytes(value: str, field_name: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except (ValueError, TypeError) as exc:
        raise DataEncryptionError(f"Encrypted secret {field_name} is not valid base64.") from exc


def _encode_bytes(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


class AesGcmDataEncryptor:
    """AES-256-GCM encryptor with record-bound associated data."""

    def __init__(self, key: bytes, *, key_id: str) -> None:
        if len(key) != 32:
            raise DataEncryptionError("AES-256-GCM requires a 32-byte key.")
        normalized_key_id = str(key_id or "").strip()
        if not normalized_key_id:
            raise DataEncryptionError(
                f"{DATA_ENCRYPTION_KEY_ID_ENV} is required for key rotation and auditability."
            )
        self._cipher = AESGCM(key)
        self._key_id = normalized_key_id

    @property
    def key_id(self) -> str:
        return self._key_id

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> "AesGcmDataEncryptor":
        environment = environment if environment is not None else os.environ
        return cls(
            _decode_key(environment.get(DATA_ENCRYPTION_KEY_ENV, "")),
            key_id=environment.get(DATA_ENCRYPTION_KEY_ID_ENV, ""),
        )

    def encrypt_json(self, value: object, *, associated_data: str) -> str:
        binding = str(associated_data or "").encode("utf-8")
        if not binding:
            raise DataEncryptionError("Secret encryption requires non-empty associated data.")
        plaintext = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        nonce = os.urandom(12)
        ciphertext = self._cipher.encrypt(nonce, plaintext, binding)
        return EncryptedEnvelope(
            algorithm=AES_GCM_ALGORITHM,
            key_id=self.key_id,
            nonce=_encode_bytes(nonce),
            ciphertext=_encode_bytes(ciphertext),
        ).to_json()

    def decrypt_json(self, envelope_json: str, *, associated_data: str) -> object:
        envelope = EncryptedEnvelope.from_json(envelope_json)
        if envelope.algorithm != AES_GCM_ALGORITHM:
            raise DataEncryptionError(
                f"Unsupported encrypted secret algorithm: {envelope.algorithm}."
            )
        if envelope.key_id != self.key_id:
            raise DataEncryptionError(
                f"Encrypted secret requires key id {envelope.key_id}, not {self.key_id}."
            )
        nonce = _decode_envelope_bytes(envelope.nonce, "nonce")
        ciphertext = _decode_envelope_bytes(envelope.ciphertext, "ciphertext")
        binding = str(associated_data or "").encode("utf-8")
        if not binding:
            raise DataEncryptionError("Secret decryption requires non-empty associated data.")
        try:
            plaintext = self._cipher.decrypt(nonce, ciphertext, binding)
            return json.loads(plaintext.decode("utf-8"))
        except Exception as exc:
            raise DataEncryptionError(
                "Encrypted secret could not be authenticated with this key and record binding."
            ) from exc


__all__ = [
    "AES_GCM_ALGORITHM",
    "AesGcmDataEncryptor",
    "DATA_ENCRYPTION_KEY_ENV",
    "DATA_ENCRYPTION_KEY_ID_ENV",
    "DataEncryptionError",
    "EncryptedEnvelope",
    "SecretEncryptor",
]
