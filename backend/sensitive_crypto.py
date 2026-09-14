"""Application-level encryption for sensitive family data."""
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


KEY_PATH = Path(os.environ.get("FAMILY_SECRETS_KEY_PATH", "/app/config/family-secrets.key"))
PREFIX = "enc:v1:"


def _cipher(path: Path = KEY_PATH) -> Fernet:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(descriptor, "wb") as key_file:
            key_file.write(Fernet.generate_key())
    os.chmod(path, 0o600)
    return Fernet(path.read_bytes().strip())


def is_encrypted(value: str | None) -> bool:
    return bool(value and value.startswith(PREFIX))


def encrypt_text(value: str | None, path: Path = KEY_PATH) -> str | None:
    if value is None:
        return None
    if is_encrypted(value):
        return value
    token = _cipher(path).encrypt(value.encode("utf-8")).decode("ascii")
    return PREFIX + token


def decrypt_text(value: str | None, path: Path = KEY_PATH) -> str | None:
    if not value:
        return None
    if not is_encrypted(value):
        return value
    try:
        return _cipher(path).decrypt(value[len(PREFIX):].encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError):
        return None


def encrypt_age(age: int | None, path: Path = KEY_PATH) -> str | None:
    return encrypt_text(None if age is None else str(age), path)


def decrypt_age(value: str | None, path: Path = KEY_PATH) -> int | None:
    try:
        plain = decrypt_text(value, path)
        return int(plain) if plain is not None else None
    except ValueError:
        return None
