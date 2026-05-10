from worker.bundler.formatters.env import GFMFormatterEnv


class GFMFormatter(GFMFormatterEnv):
    def get_file_extension(self) -> str:
        return ".md"
