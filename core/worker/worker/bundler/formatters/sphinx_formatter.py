from worker.bundler.formatters.env import SphinxFormatterEnv


class SphinxFormatter(SphinxFormatterEnv):
    def get_file_extension(self) -> str:
        return ".rst"
