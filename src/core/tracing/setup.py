"""Unified tracing setup for all providers (Braintrust, Langfuse, etc.)."""

import logging
import os

logger = logging.getLogger(__name__)

_initialized = False


def setup_tracing() -> list[str]:
    """Initialize all configured tracing providers.

    Returns a list of provider names that were successfully initialized.
    Uses add_trace_processor() to ADD processors rather than replacing them,
    allowing multiple providers to receive trace events simultaneously.

    This function is idempotent - calling it multiple times will only
    initialize providers once.
    """
    global _initialized
    if _initialized:
        logger.debug("Tracing already initialized, skipping")
        return []

    initialized_providers: list[str] = []

    # Setup Langfuse if configured
    langfuse_public = os.environ.get("LANGFUSE_PUBLIC_KEY")
    langfuse_secret = os.environ.get("LANGFUSE_SECRET_KEY")
    if langfuse_secret and langfuse_public:
        try:
            if _setup_langfuse(langfuse_public, langfuse_secret):
                initialized_providers.append("langfuse")
        except Exception as e:
            logger.error(f"Failed to initialize Langfuse tracing: {e}")
    else:
        logger.info("Langfuse credentials not provided, skipping Langfuse setup")

    # Setup Braintrust if configured
    braintrust_key = os.environ.get("BRAINTRUST_API_KEY")
    if braintrust_key:
        try:
            if _setup_braintrust(braintrust_key):
                initialized_providers.append("braintrust")
        except Exception as e:
            logger.error(f"Failed to initialize Braintrust tracing: {e}")
    else:
        logger.info("Braintrust API key not provided, skipping Braintrust setup")

    _initialized = True

    if initialized_providers:
        logger.info(f"Tracing initialized with providers: {', '.join(initialized_providers)}")
    else:
        logger.info("No tracing providers configured")

    return initialized_providers


def _setup_braintrust(api_key: str) -> bool:
    """Initialize Braintrust tracing.

    NOTE: 本项目只移植了 tracing framework 与 Langfuse processor，
    Braintrust processor 未移植。此前这里绝对导入 `onyx.tracing.*`，
    一旦安装了 braintrust 就会 ImportError。现在明确跳过并留下日志，
    不再伪装成"已初始化"。
    """
    try:
        import braintrust  # noqa: F401
    except ImportError:
        logger.warning("braintrust not installed, skipping Braintrust setup")
        return False

    logger.warning(
        "Braintrust processor is not ported in this repository; "
        "BRAINTRUST_API_KEY is set but tracing will stay disabled. "
        "Use Langfuse (LANGFUSE_*) or OpenTelemetry instead."
    )
    return False


def _setup_langfuse(public_key: str, secret_key: str) -> bool:
    """Initialize Langfuse tracing using the native Langfuse SDK."""
    try:
        from langfuse import Langfuse
    except ImportError:
        logger.warning("langfuse not installed, skipping Langfuse setup")
        return False

    from .framework import get_trace_provider
    from .langfuse_tracing_processor import LangfuseTracingProcessor

    # Set LANGFUSE_HOST env var if configured (Langfuse SDK reads this automatically)
    langfuse_host = os.environ.get("LANGFUSE_HOST")
    if langfuse_host:
        os.environ["LANGFUSE_HOST"] = langfuse_host

    # Initialize Langfuse client with credentials
    client = Langfuse(
        public_key=public_key,
        secret_key=secret_key,
        host=langfuse_host,
    )

    get_trace_provider().register_processor(LangfuseTracingProcessor(client=client))
    return True
