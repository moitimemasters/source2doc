from worker.bundler.formatters.env import NextraFormatterEnv


class NextraFormatter(NextraFormatterEnv):
    def get_file_extension(self) -> str:
        return ".mdx"
