from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    status: str = "ok"


class MeResponse(BaseModel):
    authenticated: bool
    expires_at: str | None = None
