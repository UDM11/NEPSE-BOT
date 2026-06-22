"""Credential encryption and secure storage utilities."""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from core.config import PROJECT_ROOT, get_settings
from core.exceptions import ConfigurationError


class CredentialManager:
    """Encrypt and decrypt sensitive credentials using Fernet."""

    def __init__(self, key: str | bytes | None = None):
        settings = get_settings()
        raw_key = key or settings.credential_encryption_key.get_secret_value()
        if not raw_key:
            # Derive deterministic dev key from secret_key (not for production)
            secret = settings.secret_key.get_secret_value()
            raw_key = base64.urlsafe_b64encode(
                hashlib.sha256(secret.encode()).digest()
            )
        elif isinstance(raw_key, str):
            raw_key = raw_key.encode()
        self._fernet = Fernet(raw_key)

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken as exc:
            raise ConfigurationError("Failed to decrypt credential") from exc

    def store_credentials(self, credentials: dict[str, str], path: Path | None = None) -> Path:
        """Store encrypted credentials to file."""
        store_path = path or PROJECT_ROOT / "config" / ".credentials.enc"
        store_path.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for key, value in credentials.items():
            lines.append(f"{key}={self.encrypt(value)}")
        store_path.write_text("\n".join(lines), encoding="utf-8")
        # Restrict file permissions on Unix
        if os.name != "nt":
            os.chmod(store_path, 0o600)
        return store_path

    def load_credentials(self, path: Path | None = None) -> dict[str, str]:
        """Load and decrypt credentials from file."""
        store_path = path or PROJECT_ROOT / "config" / ".credentials.enc"
        if not store_path.exists():
            return {}
        result = {}
        for line in store_path.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, encrypted = line.split("=", 1)
                result[key.strip()] = self.decrypt(encrypted.strip())
        return result
