"""Tool definitions for werewolf game actions.

Each tool has a Pydantic args_schema so the LLM understands parameter
shapes automatically when using tool calling mode.

17 registered tools covering all game phases: day/night speech, voting, role skills.
"""

from __future__ import annotations

from typing import Any, Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field


# ===========================================================================
# Pydantic input schemas — one per tool
# ===========================================================================

class VoteInput(BaseModel):
    """Input for vote_tool."""
    target: int | None = Field(None, description="Player seat number to vote for. None to abstain.")
    reasoning: str = Field("", description="Private reasoning for this vote (not shared publicly).")


class SpeakInput(BaseModel):
    """Input for speak_tool."""
    text: str = Field(..., description="The public speech content (will be seen by all players).")
    private_reasoning: str = Field("", description="Internal reasoning that stays hidden.")


class SeerCheckInput(BaseModel):
    """Input for seer_check_tool."""
    target: int = Field(..., description="The player to inspect.")
    reasoning: str = Field("", description="Why this target was chosen.")


class WitchSaveInput(BaseModel):
    """Input for witch_save_tool."""
    target: int | None = Field(None, description="The player to save.")
    reasoning: str = Field("", description="Why save this player.")


class WitchPoisonInput(BaseModel):
    """Input for witch_poison_tool."""
    target: int = Field(..., description="The player to poison.")
    reasoning: str = Field("", description="Why poison this player.")


class HunterShootInput(BaseModel):
    """Input for hunter_shoot_tool."""
    target: int | None = Field(None, description="The player to shoot, or None to not shoot.")
    reasoning: str = Field("", description="Why shoot this player (or skip).")


class GuardProtectInput(BaseModel):
    """Input for guard_protect_tool."""
    target: int = Field(..., description="The player to protect.")
    reasoning: str = Field("", description="Why protect this player.")


class WerewolfKillInput(BaseModel):
    """Input for werewolf_kill_tool."""
    target: int = Field(..., description="The player to kill (must not be a wolf).")
    reasoning: str = Field("", description="Internal reasoning for target selection.")


class SheriffRunInput(BaseModel):
    """Input for sheriff_run_tool."""
    choice: Literal["run", "pass"] = Field("run", description="'run' to enter the election or 'pass' to skip.")


class SheriffWithdrawInput(BaseModel):
    """Input for sheriff_withdraw_tool."""
    choice: Literal["stay", "withdraw"] = Field("stay", description="'stay' to continue or 'withdraw' to drop out.")


class SheriffBadgeInput(BaseModel):
    """Input for sheriff_badge_tool."""
    choice: Literal["transfer", "destroy"] = Field(..., description="'transfer' to give the badge or 'destroy' to destroy it.")
    target: int | None = Field(None, description="Target player if transferring.")


class SpeechOrderInput(BaseModel):
    """Input for speech_order_tool."""
    choice: Literal["forward", "reverse"] = Field("forward", description="'forward' for sequential or 'reverse' for reverse order.")


class WhiteWolfExplodeInput(BaseModel):
    """Input for white_wolf_explode_tool."""
    choice: Literal["explode", "pass"] = Field("pass", description="'explode' to self-destruct, 'pass' to skip.")
    target: int | None = Field(None, description="The player to take with you if exploding.")


class PassInput(BaseModel):
    """Input for pass_tool."""
    reasoning: str = Field("", description="Why you are abstaining.")


class ClaimRoleInput(BaseModel):
    """Input for claim_role_tool."""
    role: str = Field(..., description="The role you are claiming to be.")
    reasoning: str = Field("", description="Why you are making this claim.")
    public: bool = Field(False, description="Whether to announce publicly or keep internal.")


class AccuseInput(BaseModel):
    """Input for accuse_tool."""
    target: int = Field(..., description="The player to accuse.")
    evidence: str = Field("", description="Public evidence/reason for the accusation.")
    reasoning: str = Field("", description="Private reasoning.")


class DefendInput(BaseModel):
    """Input for defend_tool."""
    text: str = Field(..., description="Public defense statement.")
    target: int | None = Field(None, description="Optional player being defended.")
    reasoning: str = Field("", description="Private reasoning.")


# ===========================================================================
# Tool definitions
# ===========================================================================

@tool(args_schema=VoteInput)
def vote_tool(target: int | None = None, reasoning: str = "") -> dict[str, Any]:
    """Vote to exile a player during the day phase. Provide a target or null to abstain."""
    return {"action": "vote", "target": target, "reasoning": reasoning}


@tool(args_schema=SpeakInput)
def speak_tool(text: str, private_reasoning: str = "") -> dict[str, Any]:
    """Give a public speech during the day phase or sheriff election."""
    return {"action": "speak", "public_text": text, "private_reasoning": private_reasoning}


@tool(args_schema=SeerCheckInput)
def seer_check_tool(target: int, reasoning: str = "") -> dict[str, Any]:
    """Seer: inspect a player's alignment at night."""
    return {"action": "seer_check", "target": target, "reasoning": reasoning}


@tool(args_schema=WitchSaveInput)
def witch_save_tool(target: int | None = None, reasoning: str = "") -> dict[str, Any]:
    """Witch: use the antidote to save a player from death."""
    return {"action": "witch_save", "target": target, "reasoning": reasoning}


@tool(args_schema=WitchPoisonInput)
def witch_poison_tool(target: int, reasoning: str = "") -> dict[str, Any]:
    """Witch: use poison to kill a player."""
    return {"action": "witch_poison", "target": target, "reasoning": reasoning}


@tool(args_schema=HunterShootInput)
def hunter_shoot_tool(target: int | None = None, reasoning: str = "") -> dict[str, Any]:
    """Hunter: shoot a player when dying."""
    return {"action": "hunter_shoot", "target": target, "reasoning": reasoning}


@tool(args_schema=GuardProtectInput)
def guard_protect_tool(target: int, reasoning: str = "") -> dict[str, Any]:
    """Guard: protect a player from being killed tonight."""
    return {"action": "guard_protect", "target": target, "reasoning": reasoning}


@tool(args_schema=WerewolfKillInput)
def werewolf_kill_tool(target: int, reasoning: str = "") -> dict[str, Any]:
    """Werewolf: kill a target player at night."""
    return {"action": "werewolf_kill", "target": target, "reasoning": reasoning}


@tool(args_schema=SheriffRunInput)
def sheriff_run_tool(choice: str = "run") -> dict[str, Any]:
    """Declare candidacy for sheriff election. 'run' to enter, 'pass' to skip."""
    return {"action": "sheriff_run", "choice": choice}


@tool(args_schema=SheriffWithdrawInput)
def sheriff_withdraw_tool(choice: str = "stay") -> dict[str, Any]:
    """Withdraw from sheriff candidacy or stay in."""
    return {"action": "sheriff_withdraw", "choice": choice}


@tool(args_schema=SheriffBadgeInput)
def sheriff_badge_tool(choice: str, target: int | None = None) -> dict[str, Any]:
    """Sheriff badge handling: transfer to a player or destroy it."""
    return {"action": "sheriff_badge", "choice": choice, "target": target}


@tool(args_schema=SpeechOrderInput)
def speech_order_tool(choice: str = "forward") -> dict[str, Any]:
    """Set the speech order for the day phase."""
    return {"action": "speech_order", "choice": choice}


@tool(args_schema=WhiteWolfExplodeInput)
def white_wolf_explode_tool(choice: str = "pass", target: int | None = None) -> dict[str, Any]:
    """White Wolf King: self-destruct and optionally take a player with you."""
    return {"action": "white_wolf_explode", "choice": choice, "target": target}


@tool(args_schema=PassInput)
def pass_tool(reasoning: str = "") -> dict[str, Any]:
    """Skip/abstain from the current action."""
    return {"action": "pass", "reasoning": reasoning}


@tool(args_schema=ClaimRoleInput)
def claim_role_tool(role: str, reasoning: str = "", public: bool = False) -> dict[str, Any]:
    """Claim a role identity (internally or publicly)."""
    return {"action": "claim_role", "role": role, "reasoning": reasoning, "public": public}


@tool(args_schema=AccuseInput)
def accuse_tool(target: int, evidence: str = "", reasoning: str = "") -> dict[str, Any]:
    """Publicly accuse a player of being suspicious."""
    return {"action": "accuse", "target": target, "evidence": evidence, "reasoning": reasoning}


@tool(args_schema=DefendInput)
def defend_tool(text: str, target: int | None = None, reasoning: str = "") -> dict[str, Any]:
    """Publicly defend yourself or another player."""
    return {"action": "defend", "target": target, "public_text": text, "reasoning": reasoning}


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

ALL_TOOLS = [
    vote_tool,
    speak_tool,
    seer_check_tool,
    witch_save_tool,
    witch_poison_tool,
    hunter_shoot_tool,
    guard_protect_tool,
    werewolf_kill_tool,
    sheriff_run_tool,
    sheriff_withdraw_tool,
    sheriff_badge_tool,
    speech_order_tool,
    white_wolf_explode_tool,
    pass_tool,
    claim_role_tool,
    accuse_tool,
    defend_tool,
]


def get_tools_for_phase(phase: str, role: str) -> list:
    """Return the subset of tools available to a role in a given phase."""
    night_tools = {
        "seer": [seer_check_tool, pass_tool],
        "werewolf": [werewolf_kill_tool, pass_tool],
        "white_wolf_king": [werewolf_kill_tool, white_wolf_explode_tool, pass_tool],
        "guard": [guard_protect_tool, pass_tool],
        "witch": [witch_save_tool, witch_poison_tool, pass_tool],
        "hunter": [pass_tool],
    }
    day_tools = [speak_tool, vote_tool, accuse_tool, defend_tool, claim_role_tool, pass_tool]

    if "night" in phase.lower():
        return night_tools.get(role.lower(), [pass_tool])
    return day_tools
