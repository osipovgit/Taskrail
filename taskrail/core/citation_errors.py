"""A citation whose lines no observation of the run returned in full."""

from taskrail.core import source_lines


class MissingLines(ValueError):
    """Carries the cited path, the missing {line: current text} and the source hash."""

    def __init__(self, claim, missing, source_hash):
        """Name the claim and the windows that would supply its missing lines."""
        self.label = "Evidence {id} ({path} lines {line_start}-{line_end})".format(**claim)
        windows = source_lines.missing_feedback(missing)
        super().__init__(f"{self.label}: no matching observed read returned these lines; {windows}")
        self.path = claim["path"]
        self.missing = dict(missing)
        self.source_sha256 = source_hash
