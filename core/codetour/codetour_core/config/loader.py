from pathlib import Path

import codetour_core.config.agents as agents
import codetour_core.config.app as app

from source2doc import loader


def load_config(config_path: str | Path) -> app.CodetourAppConfig:
    return loader.load_yaml_config(config_path, app.CodetourAppConfig)


def load_prompt(prompt_path: str | Path):
    return loader.load_yaml_config(prompt_path, agents.CodetourGeneratorConfig)
