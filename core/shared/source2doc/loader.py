import os
from pathlib import Path
import re

import pydantic as pyd
import yaml


def _substitute_env_vars(text: str) -> str:
    pattern = r"\$\{([^}]+)\}"
    return re.sub(pattern, lambda m: os.environ.get(m.group(1), ""), text)


def load_yaml_config[T: pyd.BaseModel](
    config_path: str | Path,
    model_class: type[T],
) -> T:
    config_path = Path(config_path)

    with open(config_path, encoding="utf-8") as f:
        content = f.read()

    content = _substitute_env_vars(content)
    config_data = yaml.safe_load(content)

    return model_class(**config_data)
