"""One lossless typed task transport header, independent of display headings."""

import re

HEADER = re.compile(r"(?ms)^```countersign-task\s*\n(.*?)^```\s*$")
