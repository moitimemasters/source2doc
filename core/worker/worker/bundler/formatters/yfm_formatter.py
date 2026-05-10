from worker.bundler.formatters.env import YFMFormatterEnv


class YFMFormatter(YFMFormatterEnv):
    def get_file_extension(self) -> str:
        return ".md"
