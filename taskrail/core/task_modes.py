"""User-selectable modes and their stored task header flags."""

from types import MappingProxyType

FLAGS = MappingProxyType(
    {
        "develop": (),
        "discussion": ("read_only",),
        "plan": ("design", "read_only"),
        "split": ("decompose",),
    }
)


def selected(metadata):
    """Plan and Discussion both set read_only. The design flag distinguishes them."""
    if metadata.get("decompose"):
        return "split"
    if metadata.get("design"):
        return "plan"
    return "discussion" if metadata.get("read_only") else "develop"
