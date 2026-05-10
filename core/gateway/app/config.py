from pathlib import Path

from pydantic import BaseModel, Field, SecretStr

from source2doc.config import PostgresConfig, QdrantConfig, RedisConfig, S3Config
from source2doc.loader import load_yaml_config


class Config(BaseModel):
    debug: bool = Field(default=False, description="Debug mode")
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8000, description="Server port")
    encryption_key: str = Field(..., description="Encryption key for user configs")
    admin_username: str = Field(..., description="Admin login username")
    admin_password_hash: SecretStr = Field(
        ...,
        description="Admin password bcrypt hash; generate via ./generate-admin-password.sh",
    )
    session_ttl_hours: int = Field(default=24, description="Admin session TTL in hours")
    cookie_secure: bool = Field(
        default=True,
        description="Set to false in local dev over plain HTTP so the admin cookie is sent",
    )
    cookie_domain: str | None = Field(
        default=None,
        description="Optional cookie Domain attribute; leave null for host-only cookies",
    )
    redis: RedisConfig = Field(default_factory=RedisConfig)
    postgres: PostgresConfig = Field(default_factory=PostgresConfig)
    qdrant: QdrantConfig = Field(default_factory=QdrantConfig)
    s3: S3Config = Field(default_factory=S3Config)


def get_config(config_path: str | Path = "config.yaml") -> Config:
    return load_yaml_config(config_path, Config)
