"""Recover only known plan-artifact read-before-write rejections."""


def read_before_write(outcome, run):
    """Only a rejected edit of this run's plan can request a same-session read."""
    failures = outcome.get("tool_errors", [])
    if not failures or outcome.get("status") != "TOOL_ERROR":
        return None
    if outcome.get("errors") != [failure.get("error") for failure in failures]:
        return None
    target = str(run / "plan.md")
    if not all(unread_plan(failure, target) for failure in failures):
        return None
    return (
        f"The plan edit was rejected before execution. Read {target} with the read tool "
        "in THIS session, inspect its current contents, then apply your intended plan edit "
        "and end with DONE. Earlier session or server reads do not satisfy this rule."
    )


def unread_plan(failure, target):
    """Known read-before-write messages are recoverable only for the allowed plan path."""
    message = failure.get("error", "").casefold()
    same_file = failure.get("input", {}).get("filePath") == target
    known = "must read" in message and ("before" in message or "first" in message)
    return same_file and failure.get("tool") in {"write", "edit"} and known
