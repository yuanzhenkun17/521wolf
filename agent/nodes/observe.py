from __future__ import annotations

from langfuse import observe

from agent.runtime.context import AgentContext


@observe(name="observe_node")
def observe_node(ctx: AgentContext) -> AgentContext:
    """Extract structured information from ActionRequest and Observation.

    Only uses information provided by the rules layer — never fabricates
    hidden information (e.g. teammates, seer checks the player shouldn't see).
    """
    request = ctx.request
    observation = request.observation

    ctx.observation_summary = {
        "day": observation.day,
        "phase": request.phase.value,
        "action_type": request.action_type.value,
        "alive_players": list(observation.alive_players),
        "dead_players": list(observation.dead_players),
        "sheriff_id": observation.sheriff_id,
        "known_roles": {
            str(pid): role.value for pid, role in observation.known_roles.items()
        },
        "seer_checks": {
            str(pid): team.value for pid, team in observation.seer_checks.items()
        },
        "candidates": list(request.candidates),
        "metadata": dict(request.metadata),
    }
    return ctx
