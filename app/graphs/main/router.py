"""Root graph routing helpers."""

from __future__ import annotations

from app.graphs.shared.state import RootState


def _dispatch(state: RootState) -> str:
    """Route to the correct sub-pipeline based on run_type."""
    run_type = state.get("run_type", "play")
    if run_type == "play":
        return "play"
    if run_type in ("eval", "evaluation", "evaluation_batch"):
        return "eval"
    if run_type in ("evolve", "evolution"):
        return "evolve"
    raise ValueError(f"Unknown run_type: {run_type!r}. Expected: play, eval, or evolve.")
