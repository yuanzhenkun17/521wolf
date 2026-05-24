import asyncio

from werewolf.models import ActionResponse, ActionType
from werewolf.players import ScriptedAgent
from werewolf.roles import standard_roles as standard_game_roles


def run(coro):
    return asyncio.run(coro)


def standard_roles():
    return standard_game_roles()


def agents_with(default_response=None):
    response = default_response or ActionResponse(ActionType.SPEAK, text="")
    return {player_id: ScriptedAgent(default=response) for player_id in range(1, 13)}
