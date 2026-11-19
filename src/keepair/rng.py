"""Injected randomness (hard rule 9).

This module is the only place allowed to import ``random``. Callers receive a
seeded generator, so the same seed always produces the same sequence.
"""

from __future__ import annotations

import random

DEMO_SEED = 20260115


def seeded_rng(seed: int) -> random.Random:
    # Not used for security purposes: this drives reproducible demo data only.
    return random.Random(seed)  # noqa: S311


def system_rng() -> random.Random:
    """Operating-system randomness for identifiers created at run time."""
    return random.SystemRandom()


# The type other modules use for an injected generator.
Rng = random.Random
