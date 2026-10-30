"""Original bytes taken over from earlier runs, so a diff shows the complete change.

A retried split task and the integration review of a split start after other runs
edited the files. Their diff must still compare against the original bytes, which the
first run that edited each file captured. The digest of every inherited preimage is
recorded, so a continuation can verify it.
"""

import json

from taskrail.application import reviewed_artifacts
from taskrail.core.files import atomic_json, digest
from taskrail.core.schema import require
from taskrail.infrastructure.agent_sync import atomic_write

PREIMAGES = "preimages"
INHERITED = "inherited_preimages"
BASELINE = "inherited_source_baseline"
BASELINE_HASH = "inherited_source_baseline_sha256"
BASELINE_FILE = "00-input/inherited-sources.json"


def inherit(workflow, runs, names=None):
    """Take each file's preimage from the oldest run that captured it.

    names limits the files to those already approved for this run; None takes all.
    """
    workflow.state.setdefault(INHERITED, {})
    workflow.state.setdefault(BASELINE, {})
    for run in runs:
        inherit_run(workflow, run, names)
    path = workflow.run / BASELINE_FILE
    atomic_json(path, workflow.state[BASELINE])
    workflow.state[BASELINE_HASH] = digest(path.read_bytes())
    restore(workflow)


def inherit_run(workflow, run, names):
    """Copy each file's first preimage and original source identity together."""
    inherited = workflow.state[INHERITED]
    taken = captured(run)
    wanted = taken.keys() if names is None else taken.keys() & names
    source = original_sources(run) if taken else {}
    for name in sorted(wanted - inherited.keys()):
        inherited[name] = adopt(workflow.run, run, taken[name])
        workflow.state[PREIMAGES][name] = taken[name]
        workflow.state[BASELINE][name] = source.get(name)


def original_sources(run):
    """The earliest recorded modes and content identities, including a chain of retries."""
    source = reviewed_artifacts.document(run, "00-input/manifest.json")
    state = reviewed_artifacts.document(run, "run.json")
    source.update(verified(run, state))
    return source


def restore(workflow):
    """A child retry owns the whole reviewed diff, even edits it did not repeat."""
    original = verified(workflow.run, workflow.state)
    if workflow.config.get("phase") != "task":
        return
    for name, signature in original.items():
        if signature is None:
            workflow.guard.before.pop(name, None)
        else:
            workflow.guard.before[name] = signature


def verified(run, state):
    """Only unchanged frozen source identities can authorize staging across attempts."""
    if BASELINE not in state:
        return {}
    path = run / BASELINE_FILE
    require(path.is_file() and not path.is_symlink(), "Missing inherited source identities")
    stored = path.read_bytes()
    require(digest(stored) == state.get(BASELINE_HASH), "Inherited source identities changed")
    require(json.loads(stored) == state[BASELINE], "Inherited source baseline changed")
    return state[BASELINE]


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
