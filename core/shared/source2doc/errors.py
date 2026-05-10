import typing as tp

import fastapi
import pydantic as pyd

from source2doc.logging import get_logger


_logger = get_logger(__name__)


class ErrorResponse(pyd.BaseModel):
    error: str
    detail: str | None = None
    context: dict[str, tp.Any] | None = None


class BaseError(Exception):
    status_code: int = fastapi.status.HTTP_500_INTERNAL_SERVER_ERROR
    message: str = "Internal server error"
    expose_detail: bool = True

    def __init__(self, **context: tp.Any) -> None:
        self.context = context
        super().__init__(self.message)


class TransientError(Exception):
    def __init__(self, message: str = "Transient error", **context: tp.Any) -> None:
        self.error_context = context
        super().__init__(message)


class LLMTransientError(TransientError): ...


class LLMTimeoutError(Exception):
    """Raised when an LLM HTTP call exhausts its retry budget on timeout.

    Carries enough metadata for the dispatch loop to emit a structured
    ``step.failed`` / ``generation.failed`` event with ``reason=llm_timeout``
    so the UI can render a model-specific banner instead of the generic
    "internal error" message.
    """

    def __init__(
        self,
        *,
        model: str,
        elapsed_s: float,
        last_attempt_n: int,
        cause: BaseException | None = None,
    ) -> None:
        self.model = model
        self.elapsed_s = elapsed_s
        self.last_attempt_n = last_attempt_n
        self.__cause__ = cause
        super().__init__(
            f"LLM call timed out after {last_attempt_n} attempts "
            f"({elapsed_s:.1f}s total) on model {model!r}"
        )


class EmbeddingTransientError(TransientError): ...


class VectorStoreTransientError(TransientError): ...


class StorageTransientError(TransientError): ...


def register_errors(app: fastapi.FastAPI, *error_classes: type[BaseError]) -> None:
    @app.exception_handler(BaseError)
    async def base_error_handler(
        request: fastapi.Request,
        exc: BaseError,
    ) -> fastapi.responses.JSONResponse:
        _logger.exception(
            "request_failed",
            path=str(request.url.path),
            method=request.method,
            error=exc.message,
            context=exc.context,
        )
        return fastapi.responses.JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                error=exc.message,
                detail=exc.message if exc.expose_detail else None,
            ).model_dump(exclude_none=True),
        )

    @app.exception_handler(Exception)
    async def generic_error_handler(
        request: fastapi.Request,
        exc: Exception,
    ) -> fastapi.responses.JSONResponse:
        _logger.exception(
            "request_failed_unhandled",
            path=str(request.url.path),
            method=request.method,
            error_type=type(exc).__name__,
        )
        return fastapi.responses.JSONResponse(
            status_code=fastapi.status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=ErrorResponse(
                error="Internal server error",
            ).model_dump(exclude_none=True),
        )
