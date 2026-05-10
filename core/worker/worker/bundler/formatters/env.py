import typing as tp


class MkDocsFormatterEnv(tp.Protocol):
    def get_file_extension(self) -> str: ...


class NextraFormatterEnv(tp.Protocol):
    def get_file_extension(self) -> str: ...


class SphinxFormatterEnv(tp.Protocol):
    def get_file_extension(self) -> str: ...


class GFMFormatterEnv(tp.Protocol):
    def get_file_extension(self) -> str: ...


class YFMFormatterEnv(tp.Protocol):
    def get_file_extension(self) -> str: ...
