"""Fernet config envelope round-trip tests.

PMI-mapping: 6.2.4 (Запуск задачи генерации документации) — verifies that
the gateway/worker shared encryption helper actually produces ciphertext
that round-trips back into the original config dict, and refuses operation
without a key.
"""

import pytest
from cryptography.fernet import Fernet, InvalidToken

from source2doc.security.encryption import ConfigEncryption


@pytest.fixture
def key() -> str:
    return Fernet.generate_key().decode()


def test_round_trip_preserves_config(key: str) -> None:
    enc = ConfigEncryption(key)
    payload = {
        "llm": {"provider": "openai", "api_key": "sk-secret"},
        "embeddings": {"model": "text-embedding-3-small"},
        "generation": {"max_nodes": 10},
    }

    token = enc.encrypt_config(payload)
    decoded = enc.decrypt_config(token)

    assert decoded == payload


def test_ciphertext_does_not_leak_plaintext(key: str) -> None:
    enc = ConfigEncryption(key)
    token = enc.encrypt_config({"api_key": "sk-leak-me"})
    assert "sk-leak-me" not in token


def test_decrypt_with_wrong_key_raises() -> None:
    enc1 = ConfigEncryption(Fernet.generate_key().decode())
    enc2 = ConfigEncryption(Fernet.generate_key().decode())

    token = enc1.encrypt_config({"x": 1})
    with pytest.raises(InvalidToken):
        enc2.decrypt_config(token)


def test_missing_key_raises_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    with pytest.raises(ValueError, match="Encryption key is required"):
        ConfigEncryption(None)


def test_falls_back_to_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    env_key = Fernet.generate_key().decode()
    monkeypatch.setenv("ENCRYPTION_KEY", env_key)

    enc = ConfigEncryption(None)
    token = enc.encrypt_config({"hello": "world"})
    assert enc.decrypt_config(token) == {"hello": "world"}
