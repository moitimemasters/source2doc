from pydantic import BaseModel


class LogEntry(BaseModel):
    id: str
    level: str
    event: str
    timestamp: str
    logger: str
    extras: str | None = None


class LogsResponse(BaseModel):
    generation_id: str
    entries: list[LogEntry]
