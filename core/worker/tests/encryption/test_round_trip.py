"""Worker-side encryption tests.

PMI-mapping: 6.2.4 — workers must decrypt the user-supplied LLM/Postgres/
Qdrant config from Redis using the shared Fernet key.  Mirrors the
gateway-side test but exercises the worker's re-export.
"""

import json

import pytest
from cryptography.fernet import Fernet

from worker.encryption import ConfigEncryption


def test_decrypts_payload_written_by_gateway_key() -> None:
    key = Fernet.generate_key().decode()
    cfg = {"llm": {"api_key": "sk-xyz"}, "generation": {"max_nodes": 10}}

    cipher = Fernet(key.encode())
    encrypted = cipher.encrypt(json.dumps(cfg).encode()).decode()

    enc = ConfigEncryption(key)
    assert enc.decrypt_config(encrypted) == cfg


def test_fails_on_mismatched_key() -> None:
    key1 = Fernet.generate_key().decode()
    key2 = Fernet.generate_key().decode()

    enc1 = ConfigEncryption(key1)
    enc2 = ConfigEncryption(key2)

    token = enc1.encrypt_config({"x": 1})
    with pytest.raises(Exception):
        enc2.decrypt_config(token)
