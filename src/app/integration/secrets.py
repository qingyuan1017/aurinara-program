"""Versioned integration signing-secret protection."""

import base64
import hashlib
import secrets

from cryptography.fernet import Fernet


class SecretCipher:
    """Encrypt signing secrets with the environment-backed key boundary."""

    def __init__(self, configured_key: str) -> None:
        derived = base64.urlsafe_b64encode(hashlib.sha256(configured_key.encode()).digest())
        self._fernet = Fernet(derived)

    def generate(self) -> tuple[str, bytes, str]:
        """Return plaintext once, encrypted bytes, and a non-secret fingerprint."""

        plaintext = secrets.token_urlsafe(32)
        fingerprint = hashlib.sha256(plaintext.encode()).hexdigest()
        return plaintext, self._fernet.encrypt(plaintext.encode()), fingerprint

    def decrypt(self, encrypted: bytes) -> bytes:
        """Decrypt only inside the delivery worker boundary."""

        return self._fernet.decrypt(encrypted)
