"""One lossless typed task transport header, independent of display headings."""

import re

# Stored runs and existing task files from before the rename open with countersign-task;
# they are read as they are, new tasks are written with taskrail-task.
NAMES = r"(?:taskrail|countersign)-task"
HEADER = re.compile(rf"(?ms)^```{NAMES}\s*\n(.*?)^```\s*$")
FENCE = re.compile(rf"^```{NAMES}\s*$", re.MULTILINE)
