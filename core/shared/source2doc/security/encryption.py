import binascii
import json
import os

from cryptography.fernet import Fernet, InvalidToken


class ConfigEncryption:
    """Fernet-based config envelope used to keep user-supplied LLM credentials
    out of plaintext in Redis.

    Gateway components encrypt user config via :meth:`encrypt_config` before
    SETEX-ing it in Redis; workers read that key and pass the value to
    :meth:`decrypt_config`.
    """

    def __init__(self, encryption_key: str | None = None) -> None:
        if not encryption_key:
            encryption_key = os.getenv("ENCRYPTION_KEY")
            if not encryption_key:
                raise ValueError("Encryption key is required")

        # Round-trip a known plaintext through the cipher at init time so a
        # malformed Fernet key fails loudly here instead of silently producing
        # InvalidToken on the first decrypt path (which historically only
        # surfaced minutes into a generation when a worker tried to read a
        # Redis-stored config).
        try:
            cipher = Fernet(encryption_key.encode())
            cipher.decrypt(cipher.encrypt(b"validation"))
        except (ValueError, binascii.Error, InvalidToken) as exc:
            raise ValueError(
                "Encryption key is not a valid Fernet key (must be 32 url-safe "
                "base64-encoded bytes). Run ./generate-encryption-key.sh to mint one."
            ) from exc

        self.cipher = cipher

    def encrypt_config(self, config: dict) -> str:
        return self.cipher.encrypt(json.dumps(config).encode()).decode()

    def decrypt_config(self, encrypted: str) -> dict:
        return json.loads(self.cipher.decrypt(encrypted.encode()).decode())
