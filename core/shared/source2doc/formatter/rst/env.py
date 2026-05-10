import typing as tp


class RSTFormatterEnv(tp.Protocol):
    def get_file_extension(self) -> str: ...
