from source2doc.formatter.rst.env import RSTFormatterEnv


class RSTFormatter(RSTFormatterEnv):
    def get_file_extension(self) -> str:
        return ".rst"
