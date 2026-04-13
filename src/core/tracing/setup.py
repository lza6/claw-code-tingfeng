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

    import os

    initialized_providers: list[str] = []

    # Setup Langfuse if configured
    langfuse_public = os.environ.get("LANGFUSE_PUBLIC_KEY")
    langfuse_secret = os.environ.get("LANGFUSE_SECRET_KEY")
    if langfuse_secret and langfuse_public:
        try:
            _setup_langfuse(langfuse_public, langfuse_secret)
            initialized_providers.append("langfuse")
        except Exception as e:
            logger.error(f"Failed to initialize Langfuse tracing: {e}")
    else:
        logger.info("Langfuse credentials not provided, skipping Langfuse setup")

    # Setup Braintrust if configured
    braintrust_key = os.environ.get("BRAINTRUST_API_KEY")
    if braintrust_key:
        try:
            _setup_braintrust(braintrust_key)
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


def _setup_braintrust(api_key: str) -> None:
    """Initialize Braintrust tracing."""
    try:
        import braintrust
    except ImportError:
        logger.warning("braintrust not installed, skipping Braintrust setup")
        return

    from onyx.tracing.braintrust_tracing_processor import BraintrustTracingProcessor
    from onyx.tracing.framework import add_trace_processor
    from onyx.tracing.masking import mask_sensitive_data

    braintrust_logger = braintrust.init_logger(
        project=os.environ.get("BRAINTRUST_PROJECT", "ClawdCode"),
        api_key=api_key,
    )
    braintrust.set_masking_function(mask_sensitive_data)
    add_trace_processor(BraintrustTracingProcessor(braintrust_logger))


def _setup_langfuse(public_key: str, secret_key: str) -> None:
    """Initialize Langfuse tracing using the native Langfuse SDK."""
    import os

    try:
        from langfuse import Langfuse
    except ImportError:
        logger.warning("langfuse not installed, skipping Langfuse setup")
        return

    from onyx.tracing.framework import add_trace_processor
    from onyx.tracing.langfuse_tracing_processor import LangfuseTracingProcessor

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

    add_trace_processor(LangfuseTracingProcessor(client=client))
