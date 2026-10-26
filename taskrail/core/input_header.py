"""One lossless typed task transport header, independent of display headings."""

import re

NAME = r"taskrail-task"
HEADER = re.compile(rf"(?ms)^```{NAME}\s*\n(.*?)^```\s*$")
FENCE = re.compile(rf"^```{NAME}\s*$", re.MULTILINE)
