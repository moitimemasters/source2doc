from source2doc.formatter.mdx.env import MDXFormatterEnv


class MDXFormatter(MDXFormatterEnv):
    def get_file_extension(self) -> str:
        return ".mdx"
