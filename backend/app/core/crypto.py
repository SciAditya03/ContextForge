"""Symmetric encryption for API keys persisted server-side."""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


def _load_key() -> bytes:
    settings = get_settings()
    if settings.secret_key:
        return settings.secret_key.encode()
    key_file: Path = settings.data_dir / ".secret.key"
    if key_file.exists():
        return key_file.read_bytes().strip()
    key = Fernet.generate_key()
    fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(key)
    return key


def encrypt(value: str) -> str:
    return Fernet(_load_key()).encrypt(value.encode()).decode()


def decrypt(token: str) -> str | None:
    try:
        return Fernet(_load_key()).decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None
