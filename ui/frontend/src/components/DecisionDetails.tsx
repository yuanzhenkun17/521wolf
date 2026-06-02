import { ChevronRight } from "lucide-react";
import { Badge } from "./ui/badge";
import { GoTDetails } from "./GoTDetails";
import type { GoTData } from "./GoTGraph";
import { roleName } from "../presentation";
import { speechLabel, decisionChoiceText, decisionSourceName } from "./shared";
import type { AgentDecision, ArchiveMap } from "../types";

export function DecisionDetails({
  decisions,
  compact = false,
  archiveMap,
}: {
  decisions: AgentDecision[];
  compact?: boolean;
  archiveMap?: ArchiveMap;
}) {
  if (decisions.length === 0) return null;
  return (
    <details className={compact ? "group mt-2 text-xs" : "group mt-4 rounded-md border border-border bg-muted/30 p-3 text-sm"}>
      <summary className="flex cursor-pointer list-none items-center gap-1.5 font-medium text-muted-foreground marker:hidden">
        <ChevronRight className="h-3.5 w-3.5 transition-transform group-open:rotate-90" />
        决策过程
        {decisions.length > 1 ? <span className="text-xs font-normal">({decisions.length})</span> : null}
      </summary>
      <div className={compact ? "mt-2 space-y-2" : "mt-3 space-y-3"}>
        {decisions.map((decision) => (
          <DecisionBody key={decision.decision_id ?? decision.index} decision={decision} archiveEntry={archiveEntryForDecision(decision, archiveMap)} />
        ))}
      </div>
    </details>
  );
}

function archiveEntryForDecision(decision: AgentDecision, archiveMap?: ArchiveMap) {
  if (!archiveMap) return undefined;
  if (decision.decision_id) {
    const byId = archiveMap.get(decision.decision_id);
    if (byId) return byId;
  }
  return archiveMap.get(decision.index);
}

function DecisionBody({
  decision,
  archiveEntry,
}: {
  decision: AgentDecision;
  archiveEntry?: Record<string, unknown>;
}) {
  const ac = archiveEntry;
  const totCandidates = (ac?.tot_candidates as Array<Record<string, unknown>> | undefined) ?? [];
  const totJudgeReason = (ac?.tot_judge_reason as string | undefined) ?? "";
  const promptMessages = (ac?.prompt_messages as Array<Record<string, unknown>> | undefined) ?? [];
  const selectedSkills = (ac?.selected_skills as string[] | undefined) ?? [];
  const memoryContext = ac?.memory_context as Record<string, unknown> | undefined;
  const beliefContext = ac?.belief_context as Record<string, unknown> | undefined;
  const gotData = (ac?.got_data as GoTData | undefined) ?? (ac?.got_result as GoTData | undefined);
  const reasoningPromptMessages =
    decision.source === "got"
      ? ((ac?.got_prompt_messages as Array<Record<string, unknown>> | undefined) ?? [])
      : ((ac?.tot_prompt_messages as Array<Record<string, unknown>> | undefined) ?? []);
  const reasoningRawOutput =
    decision.source === "got"
      ? String(ac?.got_raw_output ?? "")
      : decision.source === "tot"
        ? String(ac?.tot_raw_output ?? "")
        : "";
  return (
    <details className="group rounded-md border border-border bg-card p-3">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 marker:hidden">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">{decision.player_id ?? "-"} 号</Badge>
          <Badge variant="secondary">{roleName(decision.role)}</Badge>
          <span className="text-xs text-muted-foreground">{speechLabel(decision.action_type)}</span>
          <span className="text-xs text-muted-foreground">{decisionSourceName(decision.source)}</span>
          {decision.confidence > 0 ? (
            <span className="text-xs text-muted-foreground">置信度: {(decision.confidence * 100).toFixed(0)}%</span>
          ) : null}
          {decision.selected_skill ? (
            <Badge variant="secondary" className="text-xs">{decision.selected_skill}</Badge>
          ) : null}
        </div>
        <ChevronRight className="h-3.5 w-3.5 shrink-0 transition-transform group-open:rotate-90" />
      </summary>
      <div className="mt-3 space-y-3">
        <p className="whitespace-pre-wrap text-sm leading-6">{decision.private_reasoning}</p>
        <div className="grid gap-2 text-xs sm:grid-cols-2">
          <DecisionMeta label="选择" value={decisionChoiceText(decision)} />
          <DecisionMeta label="候选" value={decision.candidates.length > 0 ? decision.candidates.join("、") : "-"} />
          <DecisionMeta label="备选" value={decision.alternatives.length > 0 ? decision.alternatives.join("、") : "-"} />
          <DecisionMeta label="置信度" value={decision.confidence > 0 ? `${(decision.confidence * 100).toFixed(0)}%` : "-"} />
          <DecisionMeta label="记忆事件" value={decision.memory_summary.length > 0 ? decision.memory_summary.slice(-2).join("；") : "-"} />
          <DecisionMeta label="记忆引用" value={decision.memory_refs.length > 0 ? decision.memory_refs.join("、") : "-"} />
        </div>
        {decision.confidence > 0 ? (
          <div className="h-1.5 rounded-full bg-muted overflow-hidden">
            <div className={`h-full rounded-full ${decision.confidence > 0.7 ? "bg-emerald-500" : decision.confidence > 0.4 ? "bg-amber-500" : "bg-red-500"}`} style={{ width: `${decision.confidence * 100}%` }}></div>
          </div>
        ) : null}
        {decision.rejected_reasons.length > 0 ? (
          <div className="text-xs text-muted-foreground">排除理由：{decision.rejected_reasons.join("；")}</div>
        ) : null}
        {decision.policy_adjustments.length > 0 ? (
          <div className="rounded-sm border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">
            <span className="font-medium">策略修正：</span>
            {decision.policy_adjustments.join("；")}
          </div>
        ) : null}
        {decision.errors.length > 0 ? (
          <div className="rounded-sm border border-red-200 bg-red-50 p-2 text-xs text-red-800">
            <span className="font-medium">错误：</span>
            {decision.errors.join("；")}
          </div>
        ) : null}
        <DecisionExpandedSections
          decision={decision}
          totCandidates={totCandidates}
          totJudgeReason={totJudgeReason}
          promptMessages={promptMessages}
          selectedSkills={selectedSkills}
          memoryContext={memoryContext}
          beliefContext={beliefContext}
          gotData={gotData}
          reasoningPromptMessages={reasoningPromptMessages}
          reasoningRawOutput={reasoningRawOutput}
        />
      </div>
    </details>
  );
}

function DecisionExpandedSections({
  decision,
  totCandidates,
  totJudgeReason,
  promptMessages,
  selectedSkills,
  memoryContext,
  beliefContext,
  gotData,
  reasoningPromptMessages,
  reasoningRawOutput,
}: {
  decision: AgentDecision;
  totCandidates: Array<Record<string, unknown>>;
  totJudgeReason: string;
  promptMessages: Array<Record<string, unknown>>;
  selectedSkills: string[];
  memoryContext?: Record<string, unknown>;
  beliefContext?: Record<string, unknown>;
  gotData?: GoTData;
  reasoningPromptMessages: Array<Record<string, unknown>>;
  reasoningRawOutput: string;
}) {
  const hasBelief = beliefContext && Object.keys(beliefContext).length > 0;
  const hasRaw = decision.raw_output.length > 0;
  const hasToT = totCandidates.length > 0;
  const hasPrompt = promptMessages.length > 0;
  const hasMemory = memoryContext && Object.keys(memoryContext).length > 0;
  const hasSkill = selectedSkills.length > 0 && !decision.selected_skill;
  const hasGoT = gotData && gotData.hypotheses?.length > 0;
  const hasReasoningPrompt = reasoningPromptMessages.length > 0;
  const hasReasoningRaw = reasoningRawOutput.length > 0;
  const hasAny = hasBelief || hasRaw || hasToT || hasPrompt || hasMemory || hasSkill || hasGoT || hasReasoningPrompt || hasReasoningRaw;
  if (!hasAny) return null;
  return (
    <div className="space-y-2">
      {hasToT ? (
        <details className="group rounded-sm border border-purple-200 bg-purple-50 p-2">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 text-xs font-medium text-purple-800 marker:hidden">
            <ChevronRight className="h-3 w-3 transition-transform group-open:rotate-90" />
            ToT 候选方案 ({totCandidates.length})
          </summary>
          <div className="mt-2 space-y-2">
            {totCandidates.map((cand, idx) => (
              <div key={idx} className="rounded-sm border border-purple-100 bg-white p-2 text-xs">
                <div className="font-medium text-purple-900">方案 {idx + 1}</div>
                {cand.action ? <div className="mt-1">行动: {String(cand.action)}</div> : null}
                {cand.public_text ? <div className="mt-1">发言: {String(cand.public_text)}</div> : null}
                {cand.private_reasoning ? <div className="mt-1">推理: {String(cand.private_reasoning)}</div> : null}
                {cand.expected_gain ? <div className="mt-1">预期收益: {String(cand.expected_gain)}</div> : null}
                {cand.risk ? <div className="mt-1">风险: {String(cand.risk)}</div> : null}
                {cand.judge_reason ? <div className="mt-1 text-amber-700">裁决: {String(cand.judge_reason)}</div> : null}
              </div>
            ))}
            {totJudgeReason ? (
              <div className="rounded-sm border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">
                <span className="font-medium">Judge 裁决：</span>{totJudgeReason}
              </div>
            ) : null}
          </div>
        </details>
      ) : null}

      {hasGoT && gotData ? <GoTDetails data={gotData} /> : null}

      {hasReasoningPrompt ? (
        <PromptBlock
          title={decision.source === "got" ? "GoT Prompt" : "ToT Prompt"}
          messages={reasoningPromptMessages}
        />
      ) : null}

      {hasReasoningRaw ? (
        <RawBlock title={decision.source === "got" ? "GoT Raw Output" : "ToT Raw Output"} value={reasoningRawOutput} />
      ) : null}

      {hasSkill ? (
        <details className="group rounded-sm border border-border p-2">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 text-xs font-medium text-muted-foreground marker:hidden">
            <ChevronRight className="h-3 w-3 transition-transform group-open:rotate-90" />
            注入 Skills
          </summary>
          <div className="mt-2 flex flex-wrap gap-1">
            {selectedSkills.map((sk) => (
              <Badge key={sk} variant="secondary" className="text-xs">{sk}</Badge>
            ))}
          </div>
        </details>
      ) : null}

      {hasMemory ? (
        <details className="group rounded-sm border border-border p-2">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 text-xs font-medium text-muted-foreground marker:hidden">
            <ChevronRight className="h-3 w-3 transition-transform group-open:rotate-90" />
            记忆上下文
          </summary>
          <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-xs text-muted-foreground">
            {JSON.stringify(memoryContext, null, 2)}
          </pre>
        </details>
      ) : null}

      {hasBelief ? (
        <details className="group rounded-sm border border-border p-2">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 text-xs font-medium text-muted-foreground marker:hidden">
            <ChevronRight className="h-3 w-3 transition-transform group-open:rotate-90" />
            Belief 快照
          </summary>
          <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-xs text-muted-foreground">
            {JSON.stringify(beliefContext, null, 2)}
          </pre>
        </details>
      ) : null}

      {hasPrompt ? (
        <PromptBlock title="Prompt" messages={promptMessages} />
      ) : null}

      {hasRaw ? (
        <RawBlock title="Raw Output" value={decision.raw_output} />
      ) : null}
    </div>
  );
}

function PromptBlock({ title, messages }: { title: string; messages: Array<Record<string, unknown>> }) {
  return (
    <details className="group rounded-sm border border-border p-2">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 text-xs font-medium text-muted-foreground marker:hidden">
        <ChevronRight className="h-3 w-3 transition-transform group-open:rotate-90" />
        {title} ({messages.length} 条)
      </summary>
      <div className="mt-2 space-y-2">
        {messages.map((msg, idx) => (
          <div key={idx} className="rounded-sm border border-border bg-card p-2 text-xs">
            <Badge variant="outline" className="mb-1">{(msg.role as string) ?? "unknown"}</Badge>
            <pre className="mt-1 overflow-x-auto whitespace-pre-wrap text-muted-foreground">
              {typeof msg.content === "string" ? msg.content.slice(0, 500) : JSON.stringify(msg.content, null, 2).slice(0, 500)}
              {(typeof msg.content === "string" ? msg.content.length > 500 : false) ? "...": ""}
            </pre>
          </div>
        ))}
      </div>
    </details>
  );
}

function RawBlock({ title, value }: { title: string; value: string }) {
  return (
    <details className="group rounded-sm border border-border p-2">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 text-xs font-medium text-muted-foreground marker:hidden">
        <ChevronRight className="h-3 w-3 transition-transform group-open:rotate-90" />
        {title}
      </summary>
      <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-xs text-muted-foreground">
        {value}
      </pre>
    </details>
  );
}

function DecisionMeta({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-sm bg-muted/40 px-2 py-1">
      <span className="font-medium">{label}：</span>
      <span className="break-words text-muted-foreground">{value}</span>
    </div>
  );
}
