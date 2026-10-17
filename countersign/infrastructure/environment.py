"""Keep host secrets away from model-driven processes; only named exceptions pass."""

import os

SECRET_NAMES = frozenset(
    (
        "TOKEN",
        "KEY",
        "SECRET",
        "PASSWORD",
        "PAT",
        "CREDENTIAL",
        "CREDENTIALS",
        "SSH_AUTH_SOCK",
        "SSH_ASKPASS",
        "GIT_ASKPASS",
        "GIT_SSH_COMMAND",
    )
)
SECRET_SUFFIXES = ("_TOKEN", "_KEY", "_SECRET", "_PASSWORD", "_PAT", "_CREDENTIAL", "_CREDENTIALS")
FILE_SUFFIX = "_FILE"
# Provider credentials opencode may read from the environment; settings can add more.
PROVIDER_NAMES = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_GENERATIVE_AI_API_KEY",
    "GROQ_API_KEY",
    "MISTRAL_API_KEY",
    "DEEPSEEK_API_KEY",
    "XAI_API_KEY",
    "AZURE_API_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
)
ALLOW_ERROR = "settings.agent_env_allow must list environment variable names"


def filtered(allow=()):
    """Drop secret-shaped variables unless their exact name is allowed."""
    secrets = set(filter(secret, os.environ)) - set(allow)
    return {name: text for name, text in os.environ.items() if name not in secrets}


def secret(name):
    upper = name.upper()
    stem = upper.removesuffix(FILE_SUFFIX)
    return stem in SECRET_NAMES or stem.endswith(SECRET_SUFFIXES)


def agent_allowlist(configured):
    """Provider names plus the settings' additions; local commands get none of them."""
    if not isinstance(configured, list):
        raise ValueError(ALLOW_ERROR)
    if not all(isinstance(name, str) for name in configured):
        raise ValueError(ALLOW_ERROR)
    return (*PROVIDER_NAMES, *configured)
