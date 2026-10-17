"""Source and Git integrity across the attempts of one run."""

from countersign.application.git_state import git_metadata
from countersign.application.planned_paths import safe_file
from countersign.application.source_tree import snapshot
from countersign.core import control
from countersign.core.files import changed


class SourceGuard:
    """Every change between attempts must come from an approved writer or executor."""

    def __init__(self, roots):
        """Nothing is fingerprinted until a run starts or a checkpoint is restored."""
        self.roots = roots
        self.cache = {}
        self.before = None
        self.expected = {}
        self.git_before = None

    def scan(self):
        """Fingerprint current sources, reusing hashes of unchanged files."""
        return snapshot(self.roots, self.cache)

    def capture(self):
        """Fingerprint untouched sources and Git state at the start of a fresh run."""
        self.before = self.scan()
        self.adopt(dict(self.before), git_metadata(self.roots))

    def adopt(self, expected, git_before):
        """Accept fingerprints from a checkpoint or a scope-checked executor result."""
        self.expected = expected
        self.git_before = git_before

    def verify(self, message):
        """Stop when anything changed outside the workflow."""
        if self.scan() != self.expected or not self.git_unchanged():
            raise ValueError(message)

    def git_unchanged(self):
        """Git control files still match the recorded state."""
        return self.git_before is not None and git_metadata(self.roots) == self.git_before

    def accept(self, writable):
        """Check an attempt's delta, adopt it and return all files changed by the run."""
        after = self.scan()
        delta = changed(self.expected, after)
        control.check_delta(delta, writable, self.git_unchanged())
        for name in delta:
            safe_file(name, self.roots)
        self.expected = after
        return changed(self.before, after)
