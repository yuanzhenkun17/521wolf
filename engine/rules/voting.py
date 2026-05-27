from __future__ import annotations

from collections import Counter


def resolve_votes(
    votes: dict[int, int],
    sheriff_id: int | None,
    candidates: tuple[int, ...] | None = None,
    return_ties: bool = False,
) -> int | tuple[int, ...] | None:
    if not votes:
        return () if return_ties else None
    totals: dict[int, float] = {candidate: 0.0 for candidate in candidates or set(votes.values())}
    for voter, target in votes.items():
        if candidates is not None and target not in candidates:
            continue
        weight = 1.5 if voter == sheriff_id else 1.0
        totals[target] = totals.get(target, 0.0) + weight
    if not totals:
        return () if return_ties else None
    highest = max(totals.values())
    tied = tuple(sorted(candidate for candidate, total in totals.items() if total == highest))
    if len(tied) == 1:
        return tied[0]
    return tied if return_ties else None


def plurality(targets: list[int | None]) -> int | None:
    valid_targets = [target for target in targets if target is not None]
    if not valid_targets:
        return None
    counts = Counter(valid_targets)
    highest = max(counts.values())
    return min(target for target, count in counts.items() if count == highest)
