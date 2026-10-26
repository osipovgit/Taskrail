"""Original bytes taken over from earlier runs, so a diff shows the complete change.

A retried split task and the integration review of a split start after other runs
edited the files. Their diff must still compare against the original bytes, which the
first run that edited each file captured. The digest of every inherited preimage is
recorded, so a continuation can verify it.
"""

from countersign.application import reviewed_artifacts
from countersign.core.files import digest
from countersign.infrastructure.agent_sync import atomic_write

PREIMAGES = "preimages"
INHERITED = "inherited_preimages"


def inherit(workflow, runs, names=None):
    """Take each file's preimage from the oldest run that captured it.

    names limits the files to those already approved for this run; None takes all.
    """
    inherited = workflow.state.setdefault(INHERITED, {})
    for run in runs:
        taken = captured(run)
        wanted = taken.keys() if names is None else taken.keys() & names
        for name in sorted(wanted - inherited.keys()):
            inherited[name] = adopt(workflow.run, run, taken[name])
            workflow.state[PREIMAGES][name] = taken[name]


def captured(run):
    """The preimages a finished or stopped run recorded."""
    if not run.joinpath("run.json").is_file():
        return {}
    return reviewed_artifacts.document(run, "run.json").get(PREIMAGES, {})


def adopt(target, source, reference):
    """Copy one preimage; returns its digest, or None for a file that did not exist."""
    if not reference:
        return None
    original = reviewed_artifacts.read(source, reference)
    atomic_write(target / reference, original)
    return digest(original)
