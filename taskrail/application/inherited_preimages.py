"""Original bytes taken over from earlier runs, so a diff shows the complete change.

A retried split task and the integration review of a split start after other runs
edited the files. Their diff must still compare against the original bytes, which the
first run that edited each file captured. The digest of every inherited preimage is
recorded, so a continuation can verify it.
"""

import json
import stat

from taskrail.application import reviewed_artifacts
from taskrail.core.files import atomic_json, digest
from taskrail.core.schema import require
from taskrail.infrastructure.agent_sync import atomic_write

PREIMAGES = "preimages"
INHERITED = "inherited_preimages"
BASELINE = "inherited_source_baseline"
BASELINE_HASH = "inherited_source_baseline_sha256"
SELECTED = "followup_selected"
BASELINE_FILE = "00-input/inherited-sources.json"


def inherit(workflow, runs, names=None):
    """Take each file's preimage from the oldest run that captured it.

    names limits the files to those already approved for this run; None takes all.
    """
    workflow.state.setdefault(INHERITED, {})
    workflow.state.setdefault(BASELINE, {})
    seen = set()
    for run in runs:
        inherit_run(workflow, run, names, seen)
    seal(workflow)


def seal(workflow):
    """Bind the original identities before using them for review and finalization."""
    path = workflow.run / BASELINE_FILE
    atomic_json(path, workflow.state[BASELINE])
    workflow.state[BASELINE_HASH] = digest(path.read_bytes())
    restore(workflow)


def inherit_run(workflow, run, names, seen):
    """Copy each file's earliest preimage and original source identity together."""
    if not run.joinpath("run.json").is_file():
        return
    state = reviewed_artifacts.document(run, "run.json")
    wanted = set(state.get(PREIMAGES, {})) - seen
    if names is not None:
        wanted.intersection_update(names)
    seen.update(wanted)
    if wanted:
        inherit_selected(workflow.state, state, wanted)
        source = reviewed_artifacts.document(run, "00-input/manifest.json")
        source.update(verified(run, state))
        for name in sorted(wanted):
            reference = state[PREIMAGES][name]
            workflow.state[INHERITED][name] = adopt(workflow.run, run, reference)
            workflow.state[PREIMAGES][name] = reference
            workflow.state[BASELINE][name] = source.get(name)


def inherit_selected(state, previous, wanted):
    """A retry and integration review use the same full patches as their source."""
    selected = wanted.intersection(previous.get(SELECTED, []))
    if selected:
        state[SELECTED] = sorted(selected.union(state.get(SELECTED, [])))


def restore(workflow):
    """A child retry owns the whole reviewed diff, even edits it did not repeat."""
    original = verified(workflow.run, workflow.state)
    phase = workflow.config.get("phase")
    writer = phase == "task" or workflow.state.get(SELECTED)
    if phase == "integration" or not writer:
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


def adopt(target, source, reference):
    """Copy one preimage; returns its digest, or None for a file that did not exist."""
    if not reference:
        return None
    original = reviewed_artifacts.read(source, reference)
    atomic_write(target / reference, original)
    permissions = (source / reference).stat().st_mode & stat.S_IRWXU
    (target / reference).chmod(permissions)
    return digest(original)
