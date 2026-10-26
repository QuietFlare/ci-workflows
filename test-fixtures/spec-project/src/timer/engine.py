"""The timer engine. Owns the clock."""


def tick(remaining, elapsed):
    return max(0, remaining - elapsed)
