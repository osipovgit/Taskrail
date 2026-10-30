"""Prepare installable configuration completely before stopping the old service."""

import shutil
import sys
from pathlib import Path

from taskrail.deployment import settings_init


def main():
    """The final argument is a private staging directory owned by this installer."""
    prepared = Path(sys.argv.pop())
    arguments = settings_init.parsed(sys.argv[1:])
    prepared.mkdir()
    installation = settings_init.Installation(arguments.source, prepared, arguments.app)
    if (arguments.config / settings_init.SETTINGS).exists() and not arguments.fresh:
        shutil.copyfile(arguments.config / settings_init.SETTINGS, installation.target)
        environment = arguments.config / "service.env"
        if environment.exists():
            shutil.copyfile(environment, prepared / environment.name)
    else:
        options = installation.first_settings(arguments.supplied)
        if options[settings_init.AGENT_SOURCE] == str(prepared / "agents"):
            options[settings_init.AGENT_SOURCE] = str(arguments.config / "agents")
        settings_init.write_private(installation.target, options)
    if arguments.agents == "bundled":
        installation.use_bundled_agents()
    settings_init.service_environment(prepared)


if __name__ == "__main__":
    main()
