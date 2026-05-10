from pathlib import Path

from jinja2 import Environment, FileSystemLoader


TEMPLATES_DIR = Path(__file__).parent / "templates"


def get_template_env(bundler_type: str) -> Environment:
    template_path = TEMPLATES_DIR / bundler_type
    return Environment(
        loader=FileSystemLoader(str(template_path)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_template(
    bundler_type: str,
    category: str,
    filename: str,
    data: dict,
) -> str:
    env = get_template_env(bundler_type)
    template_file = f"{category}/{filename}"
    template = env.get_template(template_file)
    return template.render(**data)


def load_template_file(
    bundler_type: str,
    category: str,
    filename: str,
) -> str:
    template_path = TEMPLATES_DIR / bundler_type / category / filename
    return template_path.read_text(encoding="utf-8")


def template_exists(
    bundler_type: str,
    category: str,
    filename: str,
) -> bool:
    template_path = TEMPLATES_DIR / bundler_type / category / filename
    return template_path.exists()
