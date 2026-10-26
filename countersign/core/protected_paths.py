"""Files a model never reads or edits: environment files, credentials and keys.

An entry such as `*.pem` or `.git/config` protects that name at a root and below any
directory. `.env` files are always protected; the `protected_paths` setting replaces
the other defaults. Only `*` and `?` are wildcards, as in opencode permission rules.
"""

import re
from fnmatch import fnmatchcase

from countersign.core.schema import require

KEY = "protected_paths"
ENVIRONMENT = (".env", ".env.*")
DEFAULTS = (
    ".git/config",
    "*.pem",
    "*.key",
    "id_rsa*",
    "id_ed25519*",
    ".vault_pass*",
    "*vault-password*",
    ".npmrc",
    ".pypirc",
    ".netrc",
)
MAX_ENTRIES = 100
DOTS = frozenset((".", ".."))
ENTRY = re.compile(r"[\w.*?@+=,~-]+(?:/[\w.*?@+=,~-]+)*")
INVALID = "settings.protected_paths must list relative path patterns using only * and ?"


def configured(options):
    """The validated setting, or the defaults when it is absent."""
    entries = options.get(KEY, list(DEFAULTS))
    require(isinstance(entries, list) and len(entries) <= MAX_ENTRIES, INVALID)
    require(all(map(valid, entries)), INVALID)
    return list(dict.fromkeys(entries))


def valid(entry):
    """A relative pattern of plain names, `*` and `?`, without `.` or `..` parts."""
    if not isinstance(entry, str) or ENTRY.fullmatch(entry) is None:
        return False
    return not DOTS.intersection(entry.split("/"))


def resumed(current, frozen):
    """A resumed run keeps its frozen entries and gains newly configured ones."""
    return list(dict.fromkeys([*frozen, *current]))


def read_patterns(entries):
    """Absolute and base-relative patterns for every entry, `.env` first."""
    names = (*ENVIRONMENT, *entries)
    return (*(f"*/{name}" for name in names), *names)


DEFAULT_PATTERNS = read_patterns(DEFAULTS)


def patterns(config):
    """The read patterns of a run configuration; defaults for a partial one."""
    return read_patterns(config.get(KEY, DEFAULTS))


def matches(path, protected):
    """True when an absolute path or a `/relative` name is protected."""
    return any(fnmatchcase(str(path), pattern) for pattern in protected)
