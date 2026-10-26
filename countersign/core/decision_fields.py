"""Explicit semantic decisions mapped onto canonical requirement identities."""

from countersign.core import coverage, schema

IDENTIFIER = "id"
REASONS = frozenset(("gap", "not_evaluated", "contradicted", "deferred"))


def requirement_id(name, requirements):
    """Short labels are stage-local aliases; canonical IDs never depend on labels."""
    numbered = enumerate(requirements, 1)
    aliases = {f"R{index}": entry[IDENTIFIER] for index, entry in numbered}
    aliases.update({entry[IDENTIFIER]: entry[IDENTIFIER] for entry in requirements})
    schema.require(name in aliases, f"Unknown requirement: {name}")
    return aliases[name]


def outcome(entry, requirements, claims):
    """Semantic outcomes stay explicit; routine success needs no repeated prose."""
    kind = entry["result"]
    explained = kind not in REASONS or bool(entry.get("reason"))
    schema.require(explained, f"{kind} needs a reason")
    return dict(
        id=requirement_id(entry["requirement"], requirements),
        outcome=kind,
        evidence_ids=claims.collect(entry["evidence"]),
        explanation=entry.get("reason", f"Agent assessment: {kind}."),
    )


def finding(entry, requirements, claims):
    """Every repair request identifies observed lines rather than invented file prose."""
    identifiers = claims.collect(entry["evidence"])
    schema.require(bool(identifiers), "Finding needs observed source evidence")
    first = identifiers[0]
    proof = next(claim for claim in claims.entries if claim[IDENTIFIER] == first)
    return dict(
        criterion=requirement_id(entry["requirement"], requirements),
        file=proof["path"],
        evidence="{} ({})".format(entry["problem"], ", ".join(identifiers)),
    )


def deferred(rows, requirements):
    """Runtime instructions remain the original assigned check, not a second paraphrase."""
    indexed = coverage.unique(rows, "coverage ID")
    return [
        entry["text"]
        for entry in requirements
        if indexed.get(entry[IDENTIFIER], {}).get("outcome") == "deferred"
    ]
