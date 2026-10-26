"""Select only bundled instruction modules; never load repository/global skills."""

import json
from pathlib import Path

from taskrail.application import evidence
from taskrail.application.instruction_sources import fingerprint
from taskrail.core.files import atomic_json

IDENTIFIER = "id"
# Every stage reads; large inputs must not overflow the model context.
READING = "reading"

CATALOG = Path(__file__).with_name("instruction-modules.json")


def frozen_catalog(run, state):
    """Snapshot modules once and reject altered continuation instructions."""
    path = run / "00-input/modules.json"
    if not path.exists():
        if state.get("modules_sha256"):
            raise ValueError("Saved instruction modules missing; restart required")
        atomic_json(path, json.loads(CATALOG.read_text()))
    signature = fingerprint(path.read_bytes())
    if state.get("modules_sha256", signature) != signature:
        raise ValueError("Saved instruction modules changed; restart required")
    state["modules_sha256"] = signature
    return json.loads(path.read_text())


def source_suffixes(execution, state):
    """Select from validated plan paths and observed reads, not agent skill requests."""
    plan = execution[1] or {}
    paths = plan.get("files_read", []) + plan.get("proposed_change_files", [])
    paths += state.get("module_source_files", [])
    return {Path(path).suffix.lower() for path in paths}


def select(catalog, execution, state):
    """Omit irrelevant modules and resolve only declared bundled dependencies."""
    stage = execution[0]
    suffixes = source_suffixes(execution, state)
    chosen = {READING} if stage == "implementer" else {READING, "verification"}
    for module in catalog:
        if stage in module["stages"] and suffixes.intersection(module["suffixes"]):
            chosen.add(module[IDENTIFIER])
    for module in catalog:
        if module[IDENTIFIER] in chosen:
            chosen.update(module["requires"])
    return [entry for entry in catalog if entry[IDENTIFIER] in chosen]


def render(run, execution, state):
    """Disclose exact selected versions and hashes; modules grant no permissions."""
    selected = select(frozen_catalog(run, state), execution, state)
    state["instruction_modules"] = [
        {
            "id": module[IDENTIFIER],
            "version": module["version"],
            "sha256": fingerprint(module["text"].encode()),
        }
        for module in selected
    ]
    paragraphs = "\n".join(
        f"{module['id']} v{module['version']}: {module['text']}" for module in selected
    )
    return f"Instruction modules:\n{paragraphs}"


def observed_files(run):
    """Use current source reads rather than model-authored module selections."""
    from_records = evidence.load_index(run)["records"]
    return [entry["input"]["filePath"] for entry in from_records if evidence.current(entry)]
