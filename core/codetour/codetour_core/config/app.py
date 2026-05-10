import pydantic
import pydantic_settings

from source2doc import config


class CodetourAppConfig(pydantic_settings.BaseSettings):
    model_config = pydantic_settings.SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    llm: config.LLMConfig
    qdrant: config.QdrantConfig
    postgres: config.PostgresConfig
    logging: config.LoggingConfig = pydantic.Field(default_factory=config.LoggingConfig)
