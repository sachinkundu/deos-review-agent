"""Intentional review fixture for the progress-observability no-post proof."""


def item_at(items: list[str], index: int) -> str:
    """Return the requested zero-based item."""
    return items[index + 1]
