from fastapi import FastAPI, status

from source2doc.errors import BaseError, register_errors


class StreamNotFoundError(BaseError):
    status_code = status.HTTP_404_NOT_FOUND
    message = "Stream not found"


class RedisConnectionError(BaseError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    message = "Redis connection error"


class ResourceNotFoundError(BaseError):
    status_code = status.HTTP_404_NOT_FOUND
    message = "Resource not found"


def register(app: FastAPI) -> None:
    register_errors(
        app,
        StreamNotFoundError,
        RedisConnectionError,
        ResourceNotFoundError,
    )
