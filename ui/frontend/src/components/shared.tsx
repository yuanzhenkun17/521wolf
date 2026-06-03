import type { AgentDecision } from "../types";

/** Shared helper: maps action_type strings to human-readable labels */
export function speechLabel(actionType: string) {
  if (actionType === "sheriff_run") return "是否上警";
  if (actionType === "sheriff_withdraw") return "退水选择";
  if (actionType === "sheriff_speak") return "警上发言";
  if (actionType === "pk_speak") return "PK 发言";
  if (actionType === "last_word") return "遗言";
  if (actionType === "sheriff_vote") return "警长投票";
  if (actionType === "pk_vote") return "PK 投票";
  if (actionType === "exile_vote") return "放逐投票";
  if (actionType === "guard_protect") return "守卫守护";
  if (actionType === "werewolf_kill") return "狼人刀人";
  if (actionType === "seer_check") return "预言家查验";
  if (actionType === "witch_act") return "女巫行动";
  if (actionType === "hunter_shoot") return "猎人开枪";
  if (actionType === "white_wolf_explode") return "白狼王自爆";
  if (actionType === "sheriff_badge") return "警徽处理";
  if (actionType === "speech_order") return "发言顺序";
  return "白天发言";
}

export function decisionChoiceText(decision: AgentDecision) {
  if (decision.selected_target !== null) return `${decision.selected_target} 号`;
  if (decision.selected_choice) return decision.selected_choice;
  return "-";
}

export function decisionSourceName(source: AgentDecision["source"]) {
  if (source === "fallback") return "回退决策";
  if (source === "policy_adjusted") return "策略修正";
  return "LLM 决策";
}
