"""Onboarding - New user setup from Aider

Adapted from aider/onboarding.py
Provides: Default model selection, API key detection, OpenRouter OAuth
"""

import os

# URLs
CLAWD_URLS = {
    "models_and_keys": "https://docs.clawd.dev/models",
    "website": "https://clawd.dev",
}


def check_openrouter_tier(api_key: str) -> bool:
    """Check if user is on OpenRouter free tier."""
    try:
        import requests
        response = requests.get(
            "https://openrouter.ai/api/v1/auth/key",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=5
        )
        response.raise_for_status()
        data = response.json()
        return data.get("data", {}).get("is_free_tier", True)
    except Exception:
        return True  # Default to free tier on error


def try_select_default_model() -> str | None:
    """Select default model based on available API keys."""
    # Check OpenRouter first
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if openrouter_key:
        is_free = check_openrouter_tier(openrouter_key)
        if is_free:
            return "openrouter/deepseek/deepseek-r1:free"
        else:
            return "openrouter/anthropic/claude-sonnet-4"

    # Check other providers
    model_key_pairs = [
        ("ANTHROPIC_API_KEY", "claude-sonnet-4-5"),
        ("DEEPSEEK_API_KEY", "deepseek/deepseek-chat"),
        ("OPENAI_API_KEY", "gpt-4o"),
        ("GEMINI_API_KEY", "gemini/gemini-2.5-pro"),
        ("OPENROUTER_API_KEY", "openrouter/deepseek/deepseek-r1:free"),
    ]

    for env_key, model_name in model_key_pairs:
        if os.environ.get(env_key):
            return model_name

    return None


def offer_openrouter_oauth(io, analytics=None) -> bool:
    """Offer OpenRouter OAuth flow if no API keys found."""
    io.tool_output("OpenRouter provides free and paid access to many LLMs.")

    if io.confirm_ask("Login to OpenRouter or create a free account?", default="y"):
        if analytics:
            analytics.event("oauth_flow_initiated", provider="openrouter")

        openrouter_key = start_oauth_flow(io)
        if openrouter_key:
            os.environ["OPENROUTER_API_KEY"] = openrouter_key
            if analytics:
                analytics.event("oauth_flow_success")
            return True

        if analytics:
            analytics.event("oauth_flow_failure")
        io.tool_error("OpenRouter authentication did not complete.")

    return False


def start_oauth_flow(io) -> str | None:
    """Start OAuth flow and return API key."""
    # Simple OAuth placeholder - actual implementation would use
    # HTTP server and browser redirect flow
    io.tool_output("Opening OpenRouter in browser...")
    io.tool_output("After login, copy your API key and paste it here.")

    # For now, just return None - full OAuth requires more setup
    return None


def select_default_model(args, io, analytics=None) -> str | None:
    """
    Select default model based on args and available API keys.

    Args:
        args: Command line args with .model attribute
        io: InputOutput instance
        analytics: Analytics instance (optional)

    Returns:
        Model name or None
    """
    if hasattr(args, 'model') and args.model:
        return args.model

    model = try_select_default_model()
    if model:
        io.tool_warning(f"Using {model} model with API key from environment.")
        if analytics:
            analytics.event("auto_model_selection", model=model)
        return model

    # No API keys - offer help
    io.tool_warning("No LLM model specified and no API keys found.")
    io.tool_output(f"See {CLAWD_URLS['models_and_keys']} for setup info.")

    return None


def detect_api_keys() -> dict:
    """Detect available API keys in environment."""
    keys = {
        "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "openai": bool(os.environ.get("OPENAI_API_KEY")),
        "deepseek": bool(os.environ.get("DEEPSEEK_API_KEY")),
        "gemini": bool(os.environ.get("GEMINI_API_KEY")),
        "openrouter": bool(os.environ.get("OPENROUTER_API_KEY")),
        "vertex": bool(os.environ.get("VERTEXAI_PROJECT")),
    }
    return {k: v for k, v in keys.items() if v}


def print_available_keys():
    """Print available API keys."""
    keys = detect_api_keys()
    if keys:
        print("Available API keys:", ", ".join(keys.keys()))
    else:
        print("No API keys detected in environment.")


__all__ = [
    "check_openrouter_tier",
    "detect_api_keys",
    "offer_openrouter_oauth",
    "print_available_keys",
    "select_default_model",
    "start_oauth_flow",
    "try_select_default_model",
]
