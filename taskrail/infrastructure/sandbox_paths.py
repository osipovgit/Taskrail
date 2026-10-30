"""Explicit runtime components that may cross the sandbox's empty home boundary."""

from pathlib import Path

from taskrail.infrastructure import sandbox_secrets

TOOLCHAINS = (
    ".local/bin",
    ".local/lib",
    ".local/share/pipx/venvs",
    ".local/share/uv/tools",
    ".local/share/uv/python",
    ".local/share/virtualenvs",
    ".pyenv/versions",
    ".pyenv/shims",
    ".pyenv/bin",
    ".pyenv/libexec",
    ".pyenv/plugins",
    ".pyenv/version",
    ".conda/envs",
    ".conda/pkgs",
    ".nvm/versions",
    ".volta/bin",
    ".volta/tools",
    ".fnm/node-versions",
    ".local/share/fnm/node-versions",
    ".bun/bin",
    ".bun/install/cache",
    ".deno/bin",
    ".cargo/bin",
    ".cargo/registry",
    ".cargo/git",
    ".rustup/toolchains",
    ".rustup/settings.toml",
    ".sdkman/candidates",
    ".jdks",
    ".m2/repository",
    ".gradle/caches",
    ".gradle/wrapper/dists",
    ".ivy2/cache",
    ".sbt/boot",
    ".asdf/installs",
    ".asdf/shims",
    ".asdf/bin",
    ".asdf/lib",
    ".asdf/libexec",
    ".asdf/plugins",
    ".tool-versions",
    ".rbenv/versions",
    ".rbenv/shims",
    ".rbenv/bin",
    ".rbenv/libexec",
    ".rbenv/plugins",
    ".rbenv/version",
    ".gem/ruby",
    ".gem/specs",
    ".tfenv/versions",
    ".ansible/collections",
    ".ansible/roles",
)
COMPONENTS = ("bin", "lib", "lib64", "share", "pyvenv.cfg")
PRIVATE = ("/tmp", "/var/tmp", "/run")


def home():
    """Expose runtime code and version selectors, never unrelated manager configuration."""
    return existing(Path.home() / name for name in TOOLCHAINS)


def installation(program):
    """A private executable gets its runtime components, never its whole prefix."""
    path = Path(program)
    if not path.is_absolute() or not any(
        path.is_relative_to(root) for root in (Path.home(), *map(Path, PRIVATE))
    ):
        return []
    if path.parent.name != "bin":
        return existing((path,))
    prefix = path.parent.parent
    if Path.home().is_relative_to(prefix):
        return existing((path,))
    if prefix == Path.home() / ".local":
        return existing((path.parent, prefix / "lib"))
    return existing(prefix / name for name in COMPONENTS)


def existing(paths):
    """Refuse credential-shaped symlink aliases as well as literal credential paths."""
    return [path for path in paths if path.exists() and not sandbox_secrets.private(path)]
