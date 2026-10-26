"""The context window of each model and the headroom kept free in every session.

`model_context_tokens` is one window for every model, or an object mapping
`provider/model` names to their windows with an optional `default` for the rest.
`context_reserve_tokens` is the headroom kept for responses and tool output.
"""

from taskrail.core.schema import require

MODEL_CONTEXT = "model_context_tokens"
CONTEXT_RESERVE = "context_reserve_tokens"
DEFAULT = "default"
DEFAULT_CONTEXT = 94208
DEFAULT_RESERVE = 8192
RESERVE_ERROR = "context_reserve_tokens must be positive and below every model_context_tokens"


def settings(options):
    """The configured windows and reserve, validated; a single window stays a number."""
    reserve = int(options.get(CONTEXT_RESERVE, DEFAULT_RESERVE))
    windows = parsed(options.get(MODEL_CONTEXT, DEFAULT_CONTEXT))
    sizes = windows.values() if isinstance(windows, dict) else [windows]
    require(all(0 < reserve < size for size in sizes), RESERVE_ERROR)
    return {MODEL_CONTEXT: windows, CONTEXT_RESERVE: reserve}


def parsed(configured):
    """One window as a number, or windows by model name."""
    if not isinstance(configured, dict):
        return int(configured)
    require(bool(configured), "model_context_tokens must name at least one model")
    return {str(name): int(size) for name, size in configured.items()}


def window(config, model):
    """The window of one model; the default for a model that is not listed."""
    windows = settings(config)[MODEL_CONTEXT]
    if not isinstance(windows, dict):
        return windows
    return windows.get(model or DEFAULT, windows.get(DEFAULT, DEFAULT_CONTEXT))


def capacity(config, model=None):
    """Input capacity of a model's session, keeping the configured reserve free."""
    return window(config, model) - settings(config)[CONTEXT_RESERVE]


def role_capacity(config, role):
    """Input capacity of the session of a role, by the model configured for it."""
    return capacity(config, config.get("models", {}).get(role))
