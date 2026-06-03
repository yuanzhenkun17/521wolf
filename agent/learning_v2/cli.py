"""Command-line entry point for learning_v2 evidence generation."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from agent.infrastructure.llm import load_llm_client
from agent.learning_v2.pipeline import run_evidence_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Run learning_v2 evidence analysis for a selfplay game directory.")
    parser.add_argument("game_dir", type=Path)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--no-llm", action="store_true")
    args = parser.parse_args()

    async def _run() -> None:
        model = None if args.no_llm else load_llm_client(model_name=args.model, temperature=0.2)
        result = await run_evidence_pipeline(
            args.game_dir,
            model=model,
            output_dir=args.output_dir,
            use_llm=not args.no_llm,
        )
        print(f"learning_v2 evidence written to {result.output_dir}")
        if result.errors:
            print(f"errors: {len(result.errors)}")

    asyncio.run(_run())


if __name__ == "__main__":
    main()

