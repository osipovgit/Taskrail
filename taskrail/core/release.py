"""Runtime contents and build identity shared by source, wheel and installed release."""

import hashlib
from pathlib import Path

SHORT_DIGEST = 12

PACKAGES = (
    ".",
    "application",
    "core",
    "deployment",
    "executor",
    "git",
    "infrastructure",
    "interactions",
    "observability",
    "web",
)
RESOURCES = (
    "settings.json",
    "agents/understanding.md",
    "agents/planner.md",
    "agents/implementer.md",
    "agents/reviewer.md",
    "application/policy.md",
    "application/instruction-modules.json",
    "core/prompt-texts.json",
    "core/result-schemas.json",
)
WEB_ASSETS = (
    "dashboard.html",
    "dashboard.css",
    "dashboard.js",
    "theme.js",
    "favicon.svg",
    "modules/analytics.js",
    "modules/app.js",
    "modules/dom.js",
    "modules/epic.js",
    "modules/graph.js",
    "modules/monitor.js",
    "modules/stages.js",
    "modules/state.js",
    "modules/task.js",
)


def modules(package, directories):
    """Python modules directly inside known packages, including each package initializer."""
    for directory in directories:
        folder = package / directory
        yield folder / "__init__.py"
        yield from (path for path in folder.glob("*.py") if path.stem.isidentifier())


def regular(paths):
    """Refuse missing, redirected and non-regular members before publishing a release."""
    for path in sorted(set(paths)):
        if path != path.resolve() or not path.is_file():
            raise ValueError(f"Release requires a regular file: {path}")
        yield path


def runtime_files(package):
    """Public runtime modules and data in stable package-relative path order."""
    assets = (package / "web/static" / name for name in WEB_ASSETS)
    resources = (package / name for name in RESOURCES)
    return regular((*modules(package, PACKAGES), *resources, *assets))


def fingerprint(package):
    """Hash the names and contents of the files shared by the source and release."""
    signature = hashlib.sha256()
    for path in runtime_files(package):
        signature.update(path.relative_to(package).as_posix().encode())
        signature.update(b"\0")
        signature.update(hashlib.sha256(path.read_bytes()).digest())
    return signature.hexdigest()


RELEASE_ID = fingerprint(Path(__file__).resolve().parents[1])
BUILD = RELEASE_ID[:SHORT_DIGEST]
VERSION = f"build-{BUILD}"
PACKAGE_VERSION = f"0+build{BUILD}"
