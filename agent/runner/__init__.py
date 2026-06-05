"""Game runners for battle and evolution systems."""
from agent.runner.battle_runner import BattleRunner, BattleGameConfig
from agent.runner.evolution_runner import EvolutionRunner, TrainingConfig, ABConfig
from agent.runner.shared import create_engine, create_agents_for_game
