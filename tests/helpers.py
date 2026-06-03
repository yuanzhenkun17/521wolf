import asyncio

from engine.models import ActionResponse, ActionType
from engine.players import ScriptedAgent


def run(coro):
    return asyncio.run(coro)


def agents_with(default_response=None):
    response = default_response or ActionResponse(ActionType.SPEAK, text="")
    return {player_id: ScriptedAgent(default=response) for player_id in range(1, 13)}


from engine.roles import standard_roles
