"""The sections of policy.md that apply to one stage.

policy.md is divided by `## ` headings: `All stages`, or a comma-separated list of the
stages a section applies to. Each stage reads only its own sections.
"""

import re

HEADING = "## Effective policy"
SECTION = re.compile(r"(?m)^## (.+)\n")
EVERY_STAGE = "All stages"


def for_stage(policy, stage):
    """The policy sections that apply to one stage, under one heading."""
    # After the preamble, the split alternates heading titles and section bodies.
    parts = iter(SECTION.split(policy)[1:])
    pairs = zip(parts, parts, strict=True)
    sections = [body.strip() for title, body in pairs if applies(title, stage)]
    return "\n\n".join([HEADING, *sections])


def applies(title, stage):
    """A section for every stage, or one that names this stage."""
    stages = {name.strip() for name in title.split(",")}
    return title == EVERY_STAGE or stage in stages
