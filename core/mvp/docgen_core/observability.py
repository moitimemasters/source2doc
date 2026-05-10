try:
    import logfire

    LOGFIRE_AVAILABLE = True
except ImportError:
    LOGFIRE_AVAILABLE = False

from source2doc import get_logger
from source2doc.config import LogfireConfig


logger = get_logger(__name__)


def setup_logfire(config: LogfireConfig) -> None:
    """Setup Logfire instrumentation for Pydantic AI agents.

    This enables real-time monitoring of:
    - All messages exchanged with the model
    - Tool calls with arguments and results
    - Token usage and latency
    - Errors with full context

    Args:
        config: Logfire configuration from settings
    """
    if not config.enabled:
        logger.debug("logfire_disabled")
        # Explicitly silence logfire even when disabled. pydantic_ai auto-detects
        # the logfire package and emits a "Logfire project URL: …" banner unless
        # it has been configured. send_to_logfire=False keeps it quiet locally.
        if LOGFIRE_AVAILABLE:
            try:
                logfire.configure(send_to_logfire=False, console=False)
            except Exception as exc:
                logger.warning("logfire_disable_failed", error=str(exc))
        return

    if not LOGFIRE_AVAILABLE:
        raise ImportError("Logfire package not installed. Install with: uv add logfire")

    if not config.token:
        raise ValueError(
            "Logfire enabled but no token provided. "
            "Set LOGFIRE_TOKEN environment variable or logfire.token in config."
        )

    # Configure Logfire
    logfire.configure(
        token=config.token,
        send_to_logfire=True,
    )

    # Instrument Pydantic AI
    logfire.instrument_pydantic_ai()

    logger.info(
        "logfire_enabled",
        message="Logfire instrumentation enabled. View traces at https://logfire.pydantic.dev",
    )
