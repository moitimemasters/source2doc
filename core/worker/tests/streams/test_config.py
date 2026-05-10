import pytest

from source2doc.config import RedisConfig

from worker.config import GatewayWorkerConfig


def test_worker_id_reads_from_env_var(monkeypatch):
    monkeypatch.setenv("WORKER_ID", "container-hostname-abc123")
    config = GatewayWorkerConfig(encryption_key="dGVzdGtleXRlc3RrZXl0ZXN0a2V5dGVzdGs=")
    assert config.worker_id == "container-hostname-abc123"


def test_worker_id_falls_back_to_default_when_env_not_set(monkeypatch):
    monkeypatch.delenv("WORKER_ID", raising=False)
    config = GatewayWorkerConfig(encryption_key="dGVzdGtleXRlc3RrZXl0ZXN0a2V5dGVzdGs=")
    assert config.worker_id == "worker-1"


def test_redis_config_default_max_retries():
    cfg = RedisConfig()
    assert cfg.max_retries == 3


def test_redis_config_custom_max_retries():
    cfg = RedisConfig(max_retries=5)
    assert cfg.max_retries == 5


def test_redis_config_max_retries_must_be_positive():
    with pytest.raises(Exception):
        RedisConfig(max_retries=0)
