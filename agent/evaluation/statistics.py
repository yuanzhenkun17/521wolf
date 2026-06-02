"""Small statistical helpers for leaderboard confidence reporting."""

from __future__ import annotations

import math
from statistics import mean, pstdev


def mean_ci95(samples: list[float]) -> tuple[float, float]:
    """Return a normal-approximation 95% CI for a bounded score sample."""
    if not samples:
        return (0.0, 0.0)
    avg = mean(samples)
    if len(samples) == 1:
        return (avg, avg)
    stderr = pstdev(samples) / math.sqrt(len(samples))
    delta = 1.96 * stderr
    return (avg - delta, avg + delta)


def wilson_ci95(successes: int, total: int) -> tuple[float, float]:
    """Wilson 95% confidence interval for a binomial rate."""
    if total <= 0:
        return (0.0, 0.0)
    z = 1.96
    p = successes / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def intervals_separate(a: tuple[float, float], b: tuple[float, float]) -> bool:
    """Conservative significance signal: CIs do not overlap."""
    return a[0] > b[1] or b[0] > a[1]
