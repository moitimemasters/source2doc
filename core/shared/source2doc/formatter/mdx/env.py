from pathlib import Path
import typing as tp


class MDXFormatterEnv(tp.Protocol):
    def get_file_extension(self) -> str: ...
