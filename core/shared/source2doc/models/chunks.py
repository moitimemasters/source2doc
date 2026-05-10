from pydantic import BaseModel, Field


class FileSpan(BaseModel):
    """Reference to a specific section of a file."""

    file_path: str = Field(description="Path to the file")
    start_line: int = Field(ge=1, description="Starting line number (1-indexed)")
    end_line: int = Field(ge=1, description="Ending line number (1-indexed)")

    def __str__(self) -> str:
        return f"{self.file_path}:{self.start_line}-{self.end_line}"


class CodeChunk(BaseModel):
    """A chunk of code with metadata."""

    chunk_id: str = Field(description="Unique identifier for the chunk")
    span: FileSpan = Field(description="Location of this chunk in source")
    content: str = Field(description="The actual code content")
    language: str = Field(default="python", description="Programming language")
    metadata: dict = Field(default_factory=dict, description="Additional metadata")

    def __str__(self) -> str:
        return f"CodeChunk({self.chunk_id}, {self.span})"
