from __future__ import annotations

import asyncio
from pathlib import Path

from playeragent.decision_log import AgentDecisionRecorder
from werewolf.engine import GameEngine
from werewolf.llm_agents import create_llm_demo_agents
from werewolf.logging import next_game_log_name
from werewolf.roles import random_standard_roles


async def run_demo(log_name: str | None = None, seed: int | None = None) -> GameEngine:
    roles = random_standard_roles(seed=seed)
    decision_recorder = AgentDecisionRecorder()
    engine = GameEngine(roles, create_llm_demo_agents(roles, decision_recorder=decision_recorder))
    winner = await engine.run_until_finished(max_days=20)

    print("=== 521wolf LLM demo ===")
    print(f"seed: {seed if seed is not None else 'random'}")
    print("座位身份:")
    for player_id, role in roles.items():
        print(f"  {player_id}: {role.value}")
    print()
    print(f"胜利方: {winner.value}")

    log_dir = Path("logs")
    log_name = log_name or next_game_log_name(log_dir)
    jsonl_path = engine.logger.write_jsonl(log_dir / f"{log_name}.jsonl")
    text_path = engine.logger.write_text(log_dir / f"{log_name}.txt")
    agent_path = decision_recorder.write_jsonl(log_dir / f"{log_name}.agent.jsonl")
    print(f"结构化日志: {jsonl_path}")
    print(f"文本日志: {text_path}")
    print(f"Agent 决策日志: {agent_path}")
    return engine


def main() -> None:
    asyncio.run(run_demo())


if __name__ == "__main__":
    main()
