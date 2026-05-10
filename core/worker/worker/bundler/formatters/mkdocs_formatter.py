from worker.bundler.formatters.env import MkDocsFormatterEnv


class MkDocsFormatter(MkDocsFormatterEnv):
    def get_file_extension(self) -> str:
        return ".md"
