"""The view. Shows what the engine says."""

from src.timer.engine import tick


def render(remaining, elapsed):
    return f"{tick(remaining, elapsed)}s"
