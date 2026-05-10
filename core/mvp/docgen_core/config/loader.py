from pathlib import Path

from source2doc import load_yaml_config
from source2doc.config import AppConfig

from docgen_core.config.agents import AgentConfig


def load_config(config_path: str | Path) -> AppConfig:
    return load_yaml_config(config_path, AppConfig)


def load_prompt(prompt_path: str | Path) -> AgentConfig:
    return load_yaml_config(prompt_path, AgentConfig)
