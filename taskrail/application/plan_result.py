"""The planner's stage result: plan.md read by the server, plus the files it read.

The planner never lists the files it read; the observed reads inside the declared
roots are the plan's files_read. The accepted plan.md is kept beside the attempt.
"""

import shutil
from pathlib import Path

from taskrail.application import evidence_delivery, plan_file
from taskrail.core import schema

PLANNER = "planner"


def stage_result(context):
    """The validated plan result of plan.md; ValueError names its problems by label."""
    run = context["run"]
    payload = plan_file.read_plan(run, context["requirements"], context["roots"])
    payload["files_read"] = observed_sources(context)
    schema.validate(payload, schema.SCHEMAS[PLANNER])
    shutil.copyfile(plan_file.path(run), context["folder"] / plan_file.NAME)
    return payload


def observed_sources(context):
    """Current files the session read inside the declared roots, sorted."""
    records = evidence_delivery.session_records(context)
    names = {record["input"]["filePath"] for record in records}
    roots = context["roots"].values()
    return sorted(name for name in names if inside(name, roots))


def inside(name, roots):
    """A path inside one of the roots."""
    return any(Path(name).is_relative_to(root) for root in roots)
